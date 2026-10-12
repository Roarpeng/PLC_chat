"""Siemens failsafe (F) block / tag detection — bounded, no codegen."""

from __future__ import annotations

from agents.plc.tia.ir import Block, PlcProject, Tag, TagTable

_TRUTHY = {"true", "1", "yes", "on", "enabled", "failsafe", "safety"}

_SAFETY_ATTR_TOKENS = (
    "isfailsafe",
    "failsafe",
    "safety",
    "fprogramme",
    "fprogram",
    "fruntime",
)

_SAFETY_LANGS = {
    "F-LAD",
    "F_LAD",
    "FLAD",
    "F-FBD",
    "F_FBD",
    "FFBD",
    "F-SCL",
    "F_SCL",
    "FSCL",
    "F-STL",
    "F_STL",
}

_SAFETY_NAME_PREFIXES = ("F-", "F_", "FOB", "FFB", "FFC", "FDB")


def _norm(text: str) -> str:
    return (text or "").lower().replace("-", "").replace("_", "").replace(" ", "")


def is_safety_language(lang: str) -> bool:
    raw = (lang or "").strip().upper().replace(" ", "")
    if raw in _SAFETY_LANGS:
        return True
    return raw.startswith("F-") or raw.startswith("F_")


def is_safety_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    upper = n.upper()
    if upper.startswith(_SAFETY_NAME_PREFIXES):
        return True
    return upper.startswith("SAFETY") or "FAILSAFE" in upper


def is_safety_tag(tag: Tag, table: TagTable | None = None) -> bool:
    if is_safety_name(tag.name):
        return True
    if table is not None and is_safety_name(table.name):
        return True
    blob = f"{tag.comment} {tag.logical_address}".upper()
    return "FAILSAFE" in blob or "%F" in blob.replace(" ", "")


def detect_block_safety(block: Block) -> bool:
    """True for F-OB / F-FB / F-FC / F-DB from name, language, or SimaticML markers."""
    if getattr(block, "is_safety", False):
        return True
    if is_safety_name(block.name):
        return True
    if is_safety_language(block.programming_language):
        return True
    for key, raw in (block.attributes or {}).items():
        kn = _norm(key)
        if any(token in kn for token in _SAFETY_ATTR_TOKENS):
            v = (raw or "").strip().lower()
            if v in _TRUTHY or v == "":
                return True
    blob = f"{block.header_comment}".lower()
    return "failsafe" in blob or "f-runtime" in blob or "safety program" in blob


def apply_safety_flags(project: PlcProject) -> PlcProject:
    """Set ``Block.is_safety`` on every block; never invent failsafe bodies."""
    for block in project.blocks.values():
        block.is_safety = detect_block_safety(block)
    return project


def safety_tag_names(project: PlcProject) -> set[str]:
    names: set[str] = set()
    for table in project.tag_tables.values():
        for tag in table.tags:
            if is_safety_tag(tag, table):
                names.add(tag.name)
    return names
