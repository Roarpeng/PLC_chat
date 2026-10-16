"""LAD/FBD/GRAPH → SCL migration middleware (Openness has no native LAD→SCL)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from plc_engine.canvas_model import CanvasBlock, CanvasState
from plc_engine.scl_precheck import precheck_block


def _extract_begin_body(full_scl: str) -> str:
    lines = full_scl.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().upper() == "BEGIN"), None)
    if start is None:
        return full_scl.strip()
    end = next(
        (i for i in range(len(lines) - 1, start, -1) if lines[i].strip().upper().startswith("END_")),
        None,
    )
    return "\n".join(lines[start + 1 : end if end is not None else None]).strip()


def validate_migration(
    original: CanvasBlock,
    scl_text: str,
) -> list[str]:
    """Return list of blocking issues (empty = ok to write)."""
    issues: list[str] = []
    upper = scl_text.upper()
    if "TODO" in upper or "(* EMPTY NETWORK *)" in upper or "图形网络" in scl_text:
        issues.append("转换结果含 TODO / 占位网络")
    # Interface / number preserved by construction when we only replace body+language;
    # still verify header mentions the same name.
    if f'"{original.name}"' not in scl_text and original.name not in scl_text:
        issues.append(f"转换结果未保留块名 {original.name}")
    findings = precheck_block(original.name, scl_text, {v.name for v in original.interface})
    for f in findings:
        if f.get("severity") == "error":
            issues.append(str(f.get("message")))
    return issues


def migrate_block_to_scl(
    canvas: CanvasState,
    block_name: str,
    *,
    ir_block: Any | None = None,
) -> dict[str, Any]:
    """Convert one canvas block language to SCL.

    Prefer ``ir_block`` (SimaticML IR) + ``translate_block_to_scl`` when available;
    otherwise use existing ``scl_body`` / network texts as already-translated content.
    """
    block = canvas.blocks.get(block_name)
    if block is None:
        return {"ok": False, "error": f"block not found: {block_name}"}

    lang = (block.language or "").upper()
    if lang in {"SCL", "STL"} and (block.scl_body or "").strip():
        return {
            "ok": True,
            "skipped": True,
            "message": f"{block_name} 已是 {lang}，无需迁移",
            "ops": [],
        }

    full_scl = ""
    if ir_block is not None:
        from agents.plc.tia.scl import translate_block_to_scl

        try:
            full_scl = translate_block_to_scl(ir_block) or ""
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"translate_block_to_scl failed: {exc}"}
    else:
        # Fallback: stitch networks already holding translator output
        full_scl = block.get_full_scl()

    issues = validate_migration(block, full_scl)
    if issues:
        return {"ok": False, "error": "migration validation failed", "issues": issues, "scl": full_scl}

    body = _extract_begin_body(full_scl) if block.block_type.upper() in {"FB", "FC", "OB"} else full_scl
    ops = [
        {
            "op": "update_block",
            "name": block_name,
            "patch": {
                "language": "SCL",
                "scl_body": body,
            },
        }
    ]
    # Keep network texts as documentation mirrors of body segments when present
    return {
        "ok": True,
        "ops": ops,
        "scl": full_scl,
        "message": f"已将 {block_name}（{lang or 'LAD'}）迁移为 SCL",
        "interface": [asdict(v) for v in block.interface],
        "number": block.number,
    }


def migrate_canvas_graphic_blocks(canvas: CanvasState) -> dict[str, Any]:
    """Propose ops for all non-SCL graphic blocks on the canvas."""
    all_ops: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for name, block in list(canvas.blocks.items()):
        if (block.language or "").upper() in {"SCL", "STL", "DB"}:
            continue
        if block.block_type.upper() in {"DB", "UDT"}:
            continue
        report = migrate_block_to_scl(canvas, name)
        reports.append({"block": name, **report})
        if report.get("ok") and report.get("ops"):
            all_ops.extend(report["ops"])
    return {
        "ok": all(r.get("ok") for r in reports) if reports else True,
        "ops": all_ops,
        "reports": reports,
    }
