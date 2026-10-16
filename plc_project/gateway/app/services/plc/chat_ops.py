"""Natural-language → typed canvas ops (LLM + rule fallback)."""

from __future__ import annotations

import json
import re
from typing import Any

from plc_engine.canvas_model import CanvasState

ALLOWED_OPS = {
    "add_block",
    "update_block",
    "update_block_scl",
    "remove_block",
    "add_network",
    "update_network",
    "add_variable",
    "remove_variable",
    "add_hmi_widget",
    "update_hmi_widget",
    "remove_hmi_widget",
    "add_screen",
    "add_tag",
    "clear_errors",
}


def validate_ops(canvas: CanvasState, ops: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Filter/validate ops against whitelist and canvas references."""
    cleaned: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, op_item in enumerate(ops):
        if not isinstance(op_item, dict):
            errors.append(f"op[{i}] not an object")
            continue
        op = str(op_item.get("op") or "")
        if op not in ALLOWED_OPS:
            errors.append(f"op[{i}] unsupported: {op}")
            continue
        if op in {"update_block", "update_block_scl", "remove_block", "add_network", "update_network", "add_variable"}:
            name = op_item.get("name") or op_item.get("block")
            if op != "add_block" and name and name not in canvas.blocks and op.startswith("update"):
                # update_block_scl / update_block require existing block
                if op in {"update_block", "update_block_scl", "update_network", "add_network", "add_variable"}:
                    if name not in canvas.blocks:
                        errors.append(f"op[{i}] unknown block: {name}")
                        continue
        if op in {"update_hmi_widget", "remove_hmi_widget"}:
            wid = op_item.get("id")
            if wid and wid not in canvas.hmi_widgets:
                errors.append(f"op[{i}] unknown hmi widget: {wid}")
                continue
        cleaned.append(op_item)
    return cleaned, errors


def build_ops_from_rules(prompt: str, canvas: CanvasState) -> list[dict[str, Any]]:
    text = (prompt or "").strip()
    low = text.lower()
    ops: list[dict[str, Any]] = []

    # Emergency stop / alarm button
    if any(k in text for k in ("急停", "紧急停止", "e-stop", "estop", "alarm")):
        ops.append(
            {
                "op": "add_variable",
                "block": next(iter(canvas.blocks), "MainDB"),
                "variable": {
                    "name": "EmergencyStop",
                    "data_type": "Bool",
                    "section": "VAR",
                    "comment": "急停",
                },
            }
        )
        ops.append(
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": "btn_estop",
                    "widget_type": "button",
                    "title": "急停",
                    "x": 50,
                    "y": 220,
                    "width": 120,
                    "height": 50,
                    "plc_tag": f"{next(iter(canvas.blocks), 'MainDB')}.EmergencyStop",
                    "data_type": "Bool",
                    "properties": {"color": "rose"},
                    "supported": True,
                },
            }
        )

    # Add FB from description
    m = re.search(r"(?:新建|添加|创建)\s*(?:一个)?\s*(?:FB|功能块)\s*[「\"']?([A-Za-z_][A-Za-z0-9_]*)", text)
    if m:
        name = m.group(1)
        if name not in canvas.blocks:
            ops.append(
                {
                    "op": "add_block",
                    "block": {
                        "name": name,
                        "block_type": "FB",
                        "language": "SCL",
                        "number": max((b.number for b in canvas.blocks.values()), default=0) + 1,
                        "comment": text[:80],
                        "interface": [
                            {"name": "Enable", "data_type": "Bool", "section": "VAR_INPUT"},
                            {"name": "Done", "data_type": "Bool", "section": "VAR_OUTPUT"},
                        ],
                        "scl_body": "IF #Enable THEN\n    #Done := TRUE;\nELSE\n    #Done := FALSE;\nEND_IF;",
                        "networks": [],
                    },
                }
            )

    # Add HMI button bound to tag
    m2 = re.search(
        r"(?:添加|新建)\s*(?:一个)?\s*(?:按钮|button).{0,20}?(?:绑定|绑定到|bind)?\s*[「\"']?([A-Za-z_][A-Za-z0-9_\.]*)",
        text,
        flags=re.I,
    )
    if m2:
        tag = m2.group(1)
        wid = f"btn_{tag.replace('.', '_')}"
        ops.append(
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": wid,
                    "widget_type": "button",
                    "title": tag,
                    "x": 80,
                    "y": 80,
                    "width": 120,
                    "height": 48,
                    "plc_tag": tag if "." in tag else tag,
                    "data_type": "Bool",
                    "supported": True,
                },
            }
        )

    # Indicator for pump / cooling
    if any(k in text for k in ("指示灯", "indicator", "冷却", "水泵", "泵运行")):
        blk = next(iter(canvas.blocks), "MainDB")
        ops.append(
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": "lamp_status",
                    "widget_type": "indicator",
                    "title": "状态指示",
                    "x": 220,
                    "y": 80,
                    "width": 80,
                    "height": 80,
                    "plc_tag": f"{blk}.MotorRunning" if blk in canvas.blocks else "",
                    "data_type": "Bool",
                    "properties": {"shape": "circle", "color": "green"},
                    "supported": True,
                },
            }
        )

    # Migrate hint: if user asks to convert LAD
    if any(k in low for k in ("转成 scl", "转为 scl", "migrate", "迁移为 scl", "改成 scl")):
        # Caller should use lad_migrate separately; emit no destructive ops here.
        pass

    return ops


def _llm_ops(prompt: str, canvas: CanvasState, context: dict[str, Any]) -> list[dict[str, Any]]:
    from gateway.app.services.plc.llm_explain import call_chat_completions, llm_settings

    settings = llm_settings()
    if settings is None:
        return []

    # Compact context
    block_summaries = []
    for name, b in list(canvas.blocks.items())[:40]:
        block_summaries.append(
            {
                "name": name,
                "type": b.block_type,
                "language": b.language,
                "vars": [v.name for v in b.interface[:20]],
            }
        )
    widgets = [
        {"id": w.id, "type": w.widget_type, "plc_tag": w.plc_tag, "title": w.title}
        for w in list(canvas.hmi_widgets.values())[:40]
    ]
    system = (
        "You are a PLC/HMI editor that outputs ONLY a JSON array of canvas ops. "
        f"Allowed op names: {sorted(ALLOWED_OPS)}. "
        "For block body changes prefer update_block_scl with full SCL statements between BEGIN/END. "
        "Do not invent block names that are not in context unless op is add_block. "
        "Reply with raw JSON array, no markdown."
    )
    user = json.dumps(
        {
            "request": prompt,
            "selected": context,
            "blocks": block_summaries,
            "hmi_widgets": widgets,
            "tags": list(canvas.tags.keys())[:80],
        },
        ensure_ascii=False,
    )
    raw = call_chat_completions(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        settings,
    )
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # try extract array
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict) and "ops" in data:
        data = data["ops"]
    return data if isinstance(data, list) else []


def build_chat_ops(
    prompt: str,
    canvas: CanvasState,
    *,
    context: dict[str, Any] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Build validated ops from natural language."""
    ctx = context or {}
    ops: list[dict[str, Any]] = []
    source = "rules"
    if use_llm:
        try:
            ops = _llm_ops(prompt, canvas, ctx)
            if ops:
                source = "llm"
        except Exception:  # noqa: BLE001
            ops = []
    if not ops:
        ops = build_ops_from_rules(prompt, canvas)
        source = "rules"
    cleaned, errors = validate_ops(canvas, ops)
    # One LLM retry on validation errors
    if errors and source == "llm" and use_llm:
        try:
            retry_prompt = prompt + "\n\nPrevious ops invalid: " + "; ".join(errors)
            ops2 = _llm_ops(retry_prompt, canvas, ctx)
            cleaned2, errors2 = validate_ops(canvas, ops2)
            if cleaned2:
                cleaned, errors = cleaned2, errors2
                source = "llm_retry"
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": len(cleaned) > 0 and not errors,
        "ops": cleaned,
        "errors": errors,
        "source": source,
        "preview": _preview_ops(canvas, cleaned),
    }


def _preview_ops(canvas: CanvasState, ops: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for op in ops:
        name = op.get("op", "")
        if name == "add_block":
            out.append({"kind": "block+", "summary": f"新增块 {(op.get('block') or {}).get('name')}"})
        elif name in {"update_block", "update_block_scl"}:
            out.append({"kind": "block~", "summary": f"修改块 {op.get('name')} SCL"})
        elif name == "add_hmi_widget":
            w = op.get("widget") or {}
            out.append({"kind": "hmi+", "summary": f"新增控件 {w.get('title') or w.get('id')}"})
        elif name == "update_hmi_widget":
            out.append({"kind": "hmi~", "summary": f"修改控件 {op.get('id')}"})
        elif name == "add_variable":
            v = op.get("variable") or {}
            out.append({"kind": "var+", "summary": f"{op.get('block')}.{v.get('name')}"})
        else:
            out.append({"kind": name, "summary": json.dumps(op, ensure_ascii=False)[:120]})
    return out
