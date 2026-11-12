"""Single fail-closed policy for imported physical addresses (P-09).

Before T09, ``patch.py`` allowed ``source=imported`` addresses while
``validation.py`` rejected every ``%`` address unconditionally. This module is
the ONE authoritative rule used by both:

An imported physical address is accepted ONLY when the IR carries the original
``source_binding`` for that component (with an original hash and
``writable=requires_review``). Otherwise it is rejected as a fictional address.
No physical address is ever invented by the Greenfield path.
"""
from __future__ import annotations

from typing import Any

IMPORTED_SOURCE = "imported"
REQUIRED_WRITABLE = "requires_review"


def source_value(component: Any) -> str:
    """Return the plain string value of a FieldSource-like enum/str."""
    return str(getattr(component.source, "value", component.source))


def imported_address_is_backed(
    ir: Any,
    component_id: str,
    component_source: str,
    address: str,
) -> bool:
    """True only for an imported address backed by an original source_binding."""
    if component_source != IMPORTED_SOURCE:
        return False
    if not isinstance(address, str) or not address.startswith("%"):
        return False
    for binding in getattr(ir, "source_bindings", None) or []:
        bound_ids: set[str] = {
            str(getattr(binding, "source_id", "") or ""),
            *[str(x) for x in (getattr(binding, "ir_entities", None) or [])],
            *[str(x) for x in (getattr(binding, "ir_ids", None) or [])],
        }
        if component_id not in bound_ids:
            continue
        original = str(getattr(binding, "original_hash", "") or "") or str(
            getattr(binding, "original_xml_sha256", "") or ""
        )
        if not original:
            continue
        if str(getattr(binding, "writable", "") or "") != REQUIRED_WRITABLE:
            continue
        return True
    return False
