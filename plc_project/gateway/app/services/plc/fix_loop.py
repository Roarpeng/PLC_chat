"""Compile-error fix loop: rule autofix + optional LLM ops, re-compile up to N rounds."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from plc_engine.canvas_model import (
    CanvasState,
    apply_canvas_patch,
    generate_canvas_autofix_patch,
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
    """Return {ok, rounds:[{attributions, ops, result}], canvas}."""
    from gateway.app.services.plc.chat_ops import build_chat_ops
    from gateway.app.services.plc.compile_jobs import default_compile_runner

    runner = compile_runner or default_compile_runner
    rounds: list[dict[str, Any]] = []
    current = canvas
    last_msgs = _msg_set(attributions)

    for round_i in range(1, max_rounds + 1):
        rule_ops = generate_canvas_autofix_patch(current, attributions)
        ops = list(rule_ops)
        source = "rules"
        if use_llm and attributions:
            prompt = _fix_prompt(attributions, current)
            built = build_chat_ops(prompt, current, use_llm=True)
            if built.get("ops"):
                ops = built["ops"]
                source = built.get("source") or "llm"
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

        current = apply_canvas_patch(deepcopy(current), ops)
        current.append_revision(ops, source="fix", message=f"fix round {round_i}")
        # Run a lightweight in-process compile job id for stage updates (optional)
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
            return {"ok": True, "rounds": rounds, "canvas": current.to_dict()}
        msgs = _msg_set(attributions)
        if msgs and msgs == last_msgs:
            rounds[-1]["stopped"] = "unchanged_errors"
            break
        last_msgs = msgs

    return {
        "ok": False,
        "rounds": rounds,
        "canvas": current.to_dict(),
        "attributions": attributions,
    }


def _msg_set(attributions: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(str(a.get("message") or "") for a in attributions)


def _fix_prompt(attributions: list[dict[str, Any]], canvas: CanvasState) -> str:
    lines = ["根据以下博途编译错误生成 canvas ops 修复（仅输出必要修改）："]
    for a in attributions[:20]:
        lines.append(f"- [{a.get('target_type')}:{a.get('target_id')}] {a.get('message')}")
    # include offending block SCL snippets
    for a in attributions[:5]:
        if a.get("target_type") == "block":
            b = canvas.blocks.get(str(a.get("target_id")))
            if b:
                lines.append(f"\n块 {b.name} SCL:\n{b.get_full_scl()[:2000]}")
    return "\n".join(lines)
