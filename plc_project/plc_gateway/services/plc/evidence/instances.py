"""Lookup and evidence-gated descriptions of KG instances."""

from __future__ import annotations

from typing import Any

from gateway.app.services.plc.chat_intents import _normalize_fb_type_name

from .blocks import _block_assoc_lines
from .cards import _describe_block_function

__all__ = [
    "_lookup_instance_entity",
    "_describe_instance_from_kg",
]


def _lookup_instance_entity(job: dict[str, Any], query: str) -> dict[str, Any] | None:
    """Resolve multi-instance / external DB name from KG (not job.blocks).

    Returns evidence-only dict:
      name, parents, type_block, uses_callers, instance_of, variables, kg_block, evidence[]
    """
    q = (query or "").strip().strip("@").strip()
    if not q:
        return None
    kg = job.get("knowledge_graph") or {}
    nodes = list(kg.get("nodes") or [])
    edges = list(kg.get("edges") or [])
    ql = q.lower()

    variables: list[dict[str, Any]] = []
    for n in nodes:
        if n.get("type") != "Variable":
            continue
        props = n.get("props") if isinstance(n.get("props"), dict) else {}
        vname = str(props.get("name") or "")
        if vname.lower() != ql:
            continue
        # id: Variable::Parent::Name  or  Variable::Parent::Section::Name
        parts = str(n.get("id") or "").split("::")
        parent = parts[1] if len(parts) >= 3 else ""
        variables.append(
            {
                "id": n.get("id"),
                "name": vname,
                "parent": parent,
                "section": props.get("section"),
                "data_type": props.get("data_type"),
                "comment": props.get("comment") or "",
            }
        )

    kg_block = None
    for n in nodes:
        if n.get("type") != "Block":
            continue
        props = n.get("props") if isinstance(n.get("props"), dict) else {}
        bname = str(props.get("name") or str(n.get("id") or "").split("::")[-1])
        if bname.lower() != ql:
            continue
        kg_block = {"id": n.get("id"), "props": props}
        break

    if not variables and kg_block is None:
        return None

    bid = f"Block::{q}"
    # Prefer exact casing from KG
    if kg_block:
        q = str((kg_block.get("props") or {}).get("name") or q)
        bid = str(kg_block.get("id") or bid)
    elif variables:
        q = str(variables[0].get("name") or q)
        # keep query casing from variable name
        for v in variables:
            if str(v.get("name")):
                q = str(v["name"])
                break

    uses_callers: list[dict[str, Any]] = []
    instance_of: list[str] = []
    evidence: list[str] = []
    for e in edges:
        et = str(e.get("type") or "")
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        props = e.get("props") if isinstance(e.get("props"), dict) else {}
        if et == "USES" and (tgt == bid or tgt.endswith(f"::{q}")):
            caller = src.split("::", 1)[-1] if "::" in src else src
            uses_callers.append(
                {
                    "caller": caller,
                    "evidence": props.get("evidence") or "",
                    "network": props.get("network") or "",
                }
            )
            ev = props.get("evidence") or "USES"
            net = props.get("network") or ""
            evidence.append(f"USES {caller}→{q}" + (f" ({ev})" if ev else "") + (f" @ {net}" if net else ""))
        if et == "INSTANCE_OF" and (src == bid or src.endswith(f"::{q}")):
            typ = tgt.split("::", 1)[-1] if "::" in tgt else tgt
            if typ and typ not in instance_of:
                instance_of.append(typ)
                evidence.append(f"INSTANCE_OF {q}→{typ}")

    type_block = instance_of[0] if instance_of else ""
    if not type_block:
        for v in variables:
            dt = _normalize_fb_type_name(str(v.get("data_type") or ""))
            if dt.upper().startswith("FB") or dt.upper().startswith("FC"):
                type_block = dt
                evidence.append(
                    f"Variable {v.get('parent')}::{q} data_type={v.get('data_type')}"
                )
                break

    parents = sorted({str(v.get("parent") or "") for v in variables if v.get("parent")})
    if not parents:
        parents = sorted({c["caller"] for c in uses_callers if c.get("caller")})

    # Only treat as instance if we have Variable and/or external/USES/INSTANCE_OF evidence
    props = (kg_block or {}).get("props") or {}
    is_external = bool(props.get("external"))
    if not variables and not uses_callers and not instance_of and not is_external:
        return None

    return {
        "kind": "instance",
        "name": q,
        "parents": parents,
        "type_block": type_block,
        "instance_of": instance_of,
        "uses_callers": uses_callers,
        "variables": variables,
        "kg_block": kg_block,
        "evidence": evidence,
    }


def _describe_instance_from_kg(job: dict[str, Any], entity: dict[str, Any]) -> str:
    """Evidence-gated description of a multi-instance / external instance node."""
    name = str(entity.get("name") or "")
    type_block = str(entity.get("type_block") or "")
    parents = list(entity.get("parents") or [])
    variables = list(entity.get("variables") or [])
    uses_callers = list(entity.get("uses_callers") or [])
    instance_of = list(entity.get("instance_of") or [])
    evidence = list(entity.get("evidence") or [])
    kg_block = entity.get("kg_block") if isinstance(entity.get("kg_block"), dict) else None
    blocks = {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }

    lines: list[str] = [
        f"**`{name}`**（多实例成员 / 实例数据，非独立程序块）",
        "",
        "说明：该名称出现在知识图谱中，但**不在**工程 Blocks 导出列表中的独立 OB/FB/FC/DB。"
        "以下仅依据图谱边与接口节点，不推断未导出的内部逻辑。",
        "",
        "### 图谱定位",
    ]
    if kg_block:
        props = kg_block.get("props") or {}
        bits = [
            f"节点 `{kg_block.get('id')}`",
            f"标记 block_type=`{props.get('block_type')}`" if props.get("block_type") else "",
            "external=true" if props.get("external") else "",
        ]
        lines.append("- " + "；".join(b for b in bits if b))
    for v in variables[:6]:
        dt = v.get("data_type")
        sec = v.get("section")
        parent = v.get("parent")
        lines.append(
            f"- 接口变量 `{v.get('id') or f'Variable::{parent}::{name}'}`"
            + (f"：section=`{sec}`" if sec else "")
            + (f"，data_type=`{dt}`" if dt else "")
        )
    if parents:
        lines.append(f"- 所属父块：{', '.join(f'`{p}`' for p in parents)}")

    lines.append("")
    lines.append("### 类型与实例关系（边证据）")
    if instance_of:
        for t in instance_of:
            lines.append(f"- `INSTANCE_OF`：`{name}` → **`{t}`**")
    elif type_block:
        lines.append(f"- 类型（来自变量 data_type）：**`{type_block}`**")
    else:
        lines.append("- 图谱中**未找到** `INSTANCE_OF` 或可解析的 FB/FC data_type（无法断言类型块）。")

    if uses_callers:
        lines.append("- 调用/使用关系 `USES`：")
        for c in uses_callers[:8]:
            extra = []
            if c.get("evidence"):
                extra.append(str(c["evidence"]))
            if c.get("network"):
                extra.append(str(c["network"]))
            suffix = f"（{'；'.join(extra)}）" if extra else ""
            lines.append(f"  - `{c.get('caller')}` → `{name}`{suffix}")
    else:
        lines.append("- 未找到指向该实例的 `USES` 边。")

    # Type FB from IR — only facts from job.blocks / folded / IO
    type_name = type_block or (instance_of[0] if instance_of else "")
    if type_name and type_name in blocks:
        lines.append("")
        lines.append(f"### 类型块 `{type_name}`（PLC-IR 证据）")
        b = blocks[type_name]
        meta = " · ".join(
            p
            for p in [
                str(b.get("type") or ""),
                f"编号 {b.get('number')}" if b.get("number") is not None else "",
                str(b.get("language") or ""),
                f"{b.get('networks')} 网络" if b.get("networks") is not None else "",
            ]
            if p
        )
        if meta:
            lines.append(f"- 元数据：{meta}")
        if b.get("comment"):
            lines.append(f"- 注释：{b.get('comment')}")
        lines.extend(_describe_block_function(job, type_name, b))
        lines.extend(_block_assoc_lines(job, type_name))
    elif type_name:
        lines.append("")
        lines.append(f"### 类型块 `{type_name}`")
        lines.append(
            f"- 图谱指向 `{type_name}`，但当前 job 的 Blocks/IR 中**没有**该块的接口与网络正文，"
            "故不描述其内部逻辑。"
        )

    if evidence:
        lines.append("")
        lines.append("### 依据摘要")
        for e in evidence[:12]:
            lines.append(f"- `{e}`")

    lines.append("")
    lines.append(
        "若需查看父块整体逻辑，请点击或 `@` "
        + (" / ".join(f"`{p}`" for p in parents[:3]) if parents else "父级 FB/DB")
        + "。"
    )
    return "\n".join(lines)
