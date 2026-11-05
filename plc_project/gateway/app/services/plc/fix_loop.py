"""Compile-error fix loop: rule autofix + structured LLM self-heal with CircuitBreaker.

Integrates plc_engine.writeback_heal (docs/plc_chat_v3_0.html Tab 5):
- Structured CompileErrorItem parsing from compiler feedback.
- AvailableStructDefinition candidate field pool extraction to prevent LLM hallucinations.
- Slot-constrained self-heal requests and CircuitBreaker loop protection.
- Up to 3 rounds of iterative compile-heal-verify.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from plc_engine.canvas_model import (
    CanvasState,
    apply_canvas_patch,
    generate_canvas_autofix_patch,
)
from plc_engine.contracts import (
    AvailableStructDefinition,
    CompileErrorItem,
    PatchedSlotDelta,
    SelfHealRequest,
    to_dict,
)
from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_heal import (
    CIRCUIT_THRESHOLD,
    DEFAULT_MAX_RETRIES,
    STOP_CIRCUIT_BREAKER,
    STOP_CLEAN,
    STOP_MAX_RETRIES,
    STOP_NO_PROGRESS,
    STOP_REPAIR_REJECTED,
    CircuitBreaker,
    HealCircuitOpen,
    HealOutcome,
    apply_slot_patch,
    build_self_heal_request,
    heal_loop,
)


def parse_attributions_to_compile_errors(
    attributions: Sequence[dict[str, Any]],
) -> list[CompileErrorItem]:
    """Parse compiler attribution dicts into structured CompileErrorItems."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    errors: list[CompileErrorItem] = []

    for att in attributions:
        if not isinstance(att, dict):
            continue
        msg = str(att.get("message") or "").strip()
        detail = str(att.get("detail") or "").strip()
        full_text = f"{msg} {detail}".strip()

        # 1. Block name resolution
        target_type = str(att.get("target_type") or "")
        target_id = str(att.get("target_id") or "").strip()
        block_name = ""
        if target_type == "block" and target_id:
            block_name = target_id
        else:
            blk_match = re.search(
                r"块\s*\[?([A-Za-z0-9_]+)\]?|Block\s*['\"]([A-Za-z0-9_]+)['\"]",
                full_text,
                re.IGNORECASE,
            )
            if blk_match:
                block_name = blk_match.group(1) or blk_match.group(2) or ""
            elif target_id:
                block_name = target_id

        # 2. Line or network locator
        locator = ""
        ln_match = re.search(
            r"(?:行|line|L)\s*0*(\d+)",
            full_text,
            re.IGNORECASE,
        )
        if ln_match:
            locator = f"Line {ln_match.group(1)}"
        elif target_type == "network" and target_id:
            locator = f"Network {target_id}"

        # 3. Clean description (strip boilerplates and line prefixes so normalize_error_text groups them)
        desc = detail or msg
        desc = re.sub(r"^博[图途](?:生成失败|编译报错)[：:]\s*(?:块\s*\[[^\]]+\]\s*)?", "", desc).strip()
        desc = re.sub(r"^(?:行|line|L)\s*0*\d+[:：\s]*", "", desc, flags=re.IGNORECASE).strip()
        if not desc:
            desc = msg or "Unknown compilation error"

        errors.append(
            CompileErrorItem(
                block_name=block_name,
                network_or_line=locator,
                tia_description=desc,
                block_path="",
                timestamp=stamp,
            )
        )
    return errors


def match_available_struct_definition(
    canvas: CanvasState,
    errors: Sequence[CompileErrorItem],
) -> AvailableStructDefinition:
    """Find referenced UDT / struct from compilation errors and extract candidate field whitelist.

    Guards against LLM hallucinating non-existent field names (Tab 5 §2).
    """
    if not canvas or not canvas.blocks:
        return AvailableStructDefinition()

    error_texts = [f"{e.block_name} {e.tia_description}" for e in errors]
    combined_err = " ".join(error_texts)

    # 1. Search for explicit UDT name in error messages
    udt_matches = re.findall(
        r"(?:类型|type)\s*['\"‘“]?([A-Za-z0-9_]+)['\"’”]?\s*(?:中未定义|中定义|not defined|component)",
        combined_err,
        re.IGNORECASE,
    )
    if not udt_matches:
        udt_matches = re.findall(r"['\"](UDT_[A-Za-z0-9_]+)['\"]|\b(UDT_[A-Za-z0-9_]+)\b", combined_err)
        udt_matches = [m[0] or m[1] for m in udt_matches if (m[0] or m[1])]

    matched_udt_name = ""
    for candidate in udt_matches:
        for blk_name in canvas.blocks:
            if blk_name.casefold() == candidate.casefold():
                matched_udt_name = blk_name
                break
        if matched_udt_name:
            break

    # 2. If not found in text, inspect offending block's interface for UDT references
    if not matched_udt_name and errors:
        first_blk = canvas.blocks.get(errors[0].block_name)
        if first_blk and first_blk.interface:
            for v in first_blk.interface:
                dt = getattr(v, "data_type", "")
                for blk_name, blk in canvas.blocks.items():
                    if getattr(blk, "block_type", "").upper() == "UDT" and blk_name.casefold() == dt.strip('"').casefold():
                        matched_udt_name = blk_name
                        break
                if matched_udt_name:
                    break

    # 3. If still not found, check if there is an exact single UDT on canvas
    if not matched_udt_name:
        all_udts = [b for b in canvas.blocks.values() if getattr(b, "block_type", "").upper() == "UDT"]
        if len(all_udts) == 1:
            matched_udt_name = all_udts[0].name

    if not matched_udt_name:
        return AvailableStructDefinition()

    udt_block = canvas.blocks[matched_udt_name]
    fields: list[str] = []

    # Extract field names from interface
    if udt_block.interface:
        for v in udt_block.interface:
            if v.name and v.name not in fields:
                fields.append(v.name)

    # Extract field names from SCL text if interface is empty
    if not fields:
        scl_text = udt_block.get_full_scl() if hasattr(udt_block, "get_full_scl") else udt_block.scl_body
        struct_match = re.search(r"STRUCT\s+(.*?)\s+END_STRUCT", scl_text, re.DOTALL | re.IGNORECASE)
        if struct_match:
            inner = struct_match.group(1)
            for line in inner.splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:", line)
                if m and m.group(1) not in fields:
                    fields.append(m.group(1))

    return AvailableStructDefinition(type_name=matched_udt_name, fields=fields)


def run_writeback_heal(
    blocks: Sequence[BlockArtifact],
    initial_errors: Sequence[CompileErrorItem],
    repair_fn: Callable[[SelfHealRequest], PatchedSlotDelta | None],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    seeds: Iterable[str] | None = None,
    cache: Mapping[str, str] | None = None,
    struct_definition: AvailableStructDefinition | None = None,
) -> HealOutcome:
    """Direct facade to plc_engine.writeback_heal.heal_loop."""
    return heal_loop(
        blocks,
        initial_errors,
        repair_fn,
        max_retries=max_retries,
        seeds=seeds,
        cache=cache,
        struct_definition=struct_definition,
    )


def run_fix_loop(
    canvas: CanvasState,
    attributions: list[dict[str, Any]],
    *,
    project_path: str,
    plc_name: str = "",
    max_rounds: int = 3,
    use_llm: bool = True,
    auto: bool = True,
    compile_runner=None,
) -> dict[str, Any]:
    """Compile-error fix loop with structured self-healing and CircuitBreaker protection.

    Return {
        ok: bool,
        rounds: list[dict],
        canvas: dict,
        attributions: list[dict],
        requests: list[dict],
        struct_definition: dict,
        circuit_breaker: bool,
        stopped: str,
    }.
    """
    from gateway.app.services.plc.chat_ops import build_chat_ops
    from gateway.app.services.plc.compile_jobs import default_compile_runner

    runner = compile_runner or default_compile_runner
    rounds: list[dict[str, Any]] = []
    current = canvas
    last_msgs = _msg_set(attributions)

    breaker = CircuitBreaker(threshold=CIRCUIT_THRESHOLD)
    error_items = parse_attributions_to_compile_errors(attributions)
    struct_def = match_available_struct_definition(current, error_items)
    heal_requests: list[SelfHealRequest] = []
    stop_reason: str = STOP_CLEAN if not error_items else ""

    for round_i in range(1, max_rounds + 1):
        # 1. CircuitBreaker protection: detect continuous repeated errors early
        if error_items:
            try:
                breaker.update(error_items)
            except HealCircuitOpen as exc:
                rounds.append(
                    {
                        "round": round_i,
                        "ops": [],
                        "source": "circuit_breaker",
                        "stopped": STOP_CIRCUIT_BREAKER,
                        "circuit_breaker": True,
                        "message": str(exc),
                        "attributions": attributions,
                    }
                )
                return {
                    "ok": False,
                    "stopped": STOP_CIRCUIT_BREAKER,
                    "stop_reason": STOP_CIRCUIT_BREAKER,
                    "circuit_breaker": True,
                    "circuit_breaker_alert": str(exc),
                    "rounds": rounds,
                    "canvas": current.to_dict(),
                    "attributions": attributions,
                    "requests": [to_dict(r) for r in heal_requests],
                    "struct_definition": to_dict(struct_def),
                }

        # 2. Try deterministic rule-based autofix first
        rule_ops = generate_canvas_autofix_patch(current, attributions)
        ops = list(rule_ops)
        source = "rules"

        # 3. If rules yield no ops and LLM is enabled, use structured self-heal request
        if not ops and use_llm and attributions:
            station_id = error_items[0].block_name if error_items else ""
            req = build_self_heal_request(
                error_items,
                attempt=round_i,
                max_retries=max_rounds,
                struct_definition=struct_def,
                station_id=station_id,
            )
            heal_requests.append(req)

            # Enhanced prompt includes whitelist instruction + block context
            prompt = _build_enhanced_heal_prompt(req, current)
            built = build_chat_ops(prompt, current, use_llm=True)
            if built.get("ops"):
                candidate_ops = built["ops"]
                # Validate that candidate ops do not introduce hallucinated fields outside struct whitelist
                ops = _filter_ops_against_whitelist(candidate_ops, struct_def)
                source = built.get("source") or "llm_self_heal"

        if not ops:
            rounds.append(
                {
                    "round": round_i,
                    "ops": [],
                    "source": source,
                    "stopped": "no_ops",
                    "attributions": attributions,
                }
            )
            stop_reason = STOP_REPAIR_REJECTED
            break

        if not auto:
            rounds.append(
                {
                    "round": round_i,
                    "ops": ops,
                    "source": source,
                    "needs_confirm": True,
                    "attributions": attributions,
                }
            )
            break

        # 4. Apply patch and commit revision
        current = apply_canvas_patch(deepcopy(current), ops)
        current.append_revision(ops, source="fix", message=f"fix round {round_i}")

        # 5. Incremental compilation verification
        job_id = f"fix-{round_i}"
        result = runner(
            job_id,
            current.to_dict(),
            project_path=project_path,
            plc_name=plc_name,
            compile_plc=True,
            compile_hmi=bool(current.hmi_devices),
            save_on_success=False,
            reset_work=False,
        )
        attributions = result.get("attributions") or []
        error_items = parse_attributions_to_compile_errors(attributions)
        current = CanvasState.from_dict(result.get("canvas") or current.to_dict())
        rounds.append(
            {
                "round": round_i,
                "ops": ops,
                "source": source,
                "result_ok": bool(result.get("ok")),
                "attributions": attributions,
                "error": result.get("error"),
            }
        )

        if result.get("ok"):
            return {
                "ok": True,
                "rounds": rounds,
                "canvas": current.to_dict(),
                "attributions": [],
                "stop_reason": STOP_CLEAN,
                "circuit_breaker": False,
                "requests": [to_dict(r) for r in heal_requests],
                "struct_definition": to_dict(struct_def),
            }

        msgs = _msg_set(attributions)
        if msgs and msgs == last_msgs:
            rounds[-1]["stopped"] = STOP_NO_PROGRESS
            stop_reason = STOP_NO_PROGRESS
            break
        last_msgs = msgs

        if round_i == max_rounds:
            rounds[-1]["stopped"] = STOP_MAX_RETRIES
            stop_reason = STOP_MAX_RETRIES

    return {
        "ok": False,
        "rounds": rounds,
        "canvas": current.to_dict(),
        "attributions": attributions,
        "requests": [to_dict(r) for r in heal_requests],
        "struct_definition": to_dict(struct_def),
        "circuit_breaker": False,
        "stop_reason": stop_reason or STOP_MAX_RETRIES,
    }


def _error_fingerprint(errors: Sequence[CompileErrorItem]) -> frozenset[tuple[str, str, str]]:
    """错误集合指纹，用于 no_progress 判定（包含块名、行号及描述）。"""
    return frozenset(
        (
            e.block_name.strip().casefold(),
            (e.network_or_line or "").strip(),
            e.tia_description.strip().casefold(),
        )
        for e in errors
    )


def _msg_set(attributions: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(str(a.get("message") or "") + str(a.get("detail") or "") for a in attributions)



def _build_enhanced_heal_prompt(req: SelfHealRequest, canvas: CanvasState) -> str:
    """Build prompt that combines structured SelfHealRequest instruction and offending SCL."""
    lines = [req.instruction, "\n【当前受影响的代码槽位与上下文】:"]
    for err in req.compiler_errors[:5]:
        blk = canvas.blocks.get(err.block_name)
        if blk:
            scl = blk.get_full_scl() if hasattr(blk, "get_full_scl") else blk.scl_body
            lines.append(f"\n--- 块 {blk.name} (定位: {err.network_or_line}) ---")
            lines.append(scl[:2500])
    return "\n".join(lines)


def _filter_ops_against_whitelist(
    ops: list[dict[str, Any]], struct_def: AvailableStructDefinition
) -> list[dict[str, Any]]:
    """Reject or filter ops that attempt to introduce invalid fields outside the struct whitelist."""
    if not struct_def or not struct_def.fields:
        return ops

    allowed = set(struct_def.fields)
    filtered: list[dict[str, Any]] = []

    for op in ops:
        op_name = op.get("op", "")
        # If adding a variable typed with this struct, or adding a field
        if op_name == "add_variable":
            v = op.get("variable") or {}
            # If op specifically adds member to struct
            if op.get("block") == struct_def.type_name and v.get("name") not in allowed:
                continue
        filtered.append(op)

    return filtered or ops
