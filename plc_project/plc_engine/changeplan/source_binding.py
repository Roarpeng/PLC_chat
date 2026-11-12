"""Brownfield SourceBinding — full-fidelity imported block record (WP-05).

Extends the lightweight IR binding (which is a one-way IR projection) with the
import-specific fields required by Q-04: ``source_block_id``, ``original_hash``,
``source_span``, ``ir_ids``, ``writable``, ``referenced_by``, ``fidelity``.
No second implementation: this is an inheritance extension of the IR entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plc_engine.engineering_ir.models import SourceBinding as IRSourceBinding


@dataclass
class SourceBinding(IRSourceBinding):
    """Imported-source record; original object is never modified in this batch."""

    source_block_id: str = ""
    ir_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.source_id and self.source_block_id:
            self.source_id = self.source_block_id
        if not self.source_block_id and self.source_id:
            self.source_block_id = self.source_id
        if not self.ir_ids and self.ir_entities:
            self.ir_ids = list(self.ir_entities)

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload.update({
            "source_block_id": self.source_block_id or self.source_id,
            "original_hash": self.original_hash or self.original_xml_sha256,
            "source_span": dict(self.source_span),
            "ir_ids": list(self.ir_ids or self.ir_entities),
            "writable": self.writable,
            "referenced_by": list(self.referenced_by),
            "fidelity": self.fidelity,
        })
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceBinding":
        base = IRSourceBinding.from_dict(data)
        return cls(
            source_id=base.source_id,
            tia_path=base.tia_path,
            block_type=base.block_type,
            block_number=base.block_number,
            original_xml_sha256=base.original_xml_sha256,
            original_hash=str(data.get("original_hash") or base.original_hash),
            source_span=dict(data.get("source_span") or base.source_span),
            ir_entities=list(data.get("ir_entities") or base.ir_entities),
            referenced_by=list(data.get("referenced_by") or base.referenced_by),
            writable=str(data.get("writable") or base.writable),
            fidelity=str(data.get("fidelity") or base.fidelity),
            source_block_id=str(data.get("source_block_id") or data.get("source_id") or ""),
            ir_ids=[str(x) for x in (data.get("ir_ids") or data.get("ir_entities") or [])],
        )

    def is_protected(self) -> bool:
        """F-blocks / unparseable blocks are always protected."""
        return (
            self.writable == "requires_review"
            or self.fidelity in ("unparseable", "protected")
            or self.block_type.upper() in ("F", "SAFETY", "FB_SAFETY")
        )
