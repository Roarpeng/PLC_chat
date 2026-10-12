"""Post-extract enrichment for PLC-IR interfaces.

Openness ``WithDefaults`` often omits multi-instance timer/counter members
from FB / InstanceDB ``Interface`` XML even though body logic references them
(e.g. ``"IEC_Timer_0_DB".TON(...)`` inside FB ``dc``). This module recovers
those members and mirrors FB interfaces onto typed InstanceDBs.
"""

from __future__ import annotations

import re
from copy import deepcopy

from agents.plc.tia.flgnet_fold import COUNTER_PARTS, TIMER_PARTS
from agents.plc.tia.ir import (
    Block,
    BlockType,
    InterfaceSection,
    PlcProject,
    Variable,
)

_BOX_PARTS = TIMER_PARTS | COUNTER_PARTS

_MULTI_DTYPE = {
    "TON": "TON_TIME",
    "TOF": "TOF_TIME",
    "TP": "TP_TIME",
    "CTU": "CTU_INT",
    "CTD": "CTD_INT",
    "CTUD": "CTUD_INT",
}

# "IEC_Timer_0_DB".TON(  |  #local.TON(  |  bare.TON(
_RE_MULTI_CALL = re.compile(
    r'(?:"(?P<quoted>[^"]+)"|#(?P<local>\w+)|(?P<bare>[A-Za-z_]\w*))'
    r"\.(?P<op>TON|TOF|TP|CTU|CTD|CTUD)\s*\(",
    re.IGNORECASE,
)


def _instance_of_name(block: Block) -> str:
    attrs = block.attributes or {}
    return (
        str(attrs.get("InstanceOfName") or "").strip()
        or str(attrs.get("OfType") or "").strip()
        or str(attrs.get("OfBlock") or "").strip()
    )


def _discover_multi_instances(block: Block) -> dict[str, str]:
    """Map multi-instance name → Siemens datatype from FlgNet / StructuredText."""
    found: dict[str, str] = {}

    def add(name: str, op: str) -> None:
        name = (name or "").strip().strip('"')
        op_u = (op or "").strip().upper()
        if not name or op_u not in _MULTI_DTYPE:
            return
        # Prefer first seen dtype; do not overwrite with empty
        found.setdefault(name, _MULTI_DTYPE[op_u])

    for network in block.networks:
        for part in network.parts.values():
            op = (part.name or "").strip().upper()
            if op not in _BOX_PARTS:
                continue
            inst = part.accesses.get("instance") or part.accesses.get("Instance")
            if inst is not None and inst.root:
                # LocalVariable = true multi-instance; GlobalVariable name may
                # still be multi-instance when Openness quotes IEC_*_DB.
                add(inst.root, op)
            elif part.template_values.get("InstanceDB"):
                add(str(part.template_values["InstanceDB"]), op)

        src = network.source_text or ""
        if not src:
            continue
        for m in _RE_MULTI_CALL.finditer(src):
            name = m.group("quoted") or m.group("local") or m.group("bare") or ""
            add(name, m.group("op") or "")

    return found


def _ensure_static_member(block: Block, name: str, data_type: str, *, comment: str) -> bool:
    if any(v.name == name for v in block.interface):
        return False
    block.interface.append(
        Variable(
            name=name,
            section=InterfaceSection.STATIC,
            data_type=data_type,
            comment=comment,
        )
    )
    return True


def enrich_fb_multi_instances(project: PlcProject) -> int:
    """Add missing Static multi-instance members inferred from FB/FC bodies."""
    added = 0
    for block in project.blocks.values():
        if block.block_type not in {BlockType.FB, BlockType.FC}:
            continue
        for name, dtype in _discover_multi_instances(block).items():
            # Exported DB with same name = single-instance; keep as Block, not FB Static
            other = project.blocks.get(name)
            if other is not None and other.block_type == BlockType.DB:
                continue
            if _ensure_static_member(
                block,
                name,
                dtype,
                comment=f"多实例 {dtype.split('_')[0]}（由网络逻辑推断）",
            ):
                added += 1
                project.extraction_notes.append(
                    f"enriched multi-instance {block.name}.{name} : {dtype}"
                )
    return added


def enrich_instance_dbs(project: PlcProject) -> int:
    """Mirror FB interface onto InstanceDBs and record InstanceOf* attributes."""
    mirrored = 0
    for block in project.blocks.values():
        if block.block_type != BlockType.DB:
            continue
        fb_name = _instance_of_name(block)
        if not fb_name:
            continue
        block.attributes.setdefault("InstanceOfName", fb_name)
        fb = project.blocks.get(fb_name)
        if fb is None or fb.block_type != BlockType.FB:
            continue
        existing = {v.name for v in block.interface}
        added_here = 0
        for var in fb.interface:
            if var.name in existing:
                continue
            block.interface.append(deepcopy(var))
            existing.add(var.name)
            added_here += 1
        if added_here:
            mirrored += added_here
            project.extraction_notes.append(
                f"mirrored interface {fb_name} → {block.name} (+{added_here} members)"
            )
    return mirrored


def enrich_project_interfaces(project: PlcProject) -> PlcProject:
    """Run all interface enrichments after SimaticML extract."""
    enrich_fb_multi_instances(project)
    enrich_instance_dbs(project)
    return project
