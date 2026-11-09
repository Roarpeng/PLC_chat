"""N:N SourceMap: Canvas node <-> IR id <-> SCL line <-> TIA block (WP-03 / G4).

A single IR entity may emit several SCL lines in several TIA blocks, and one
TIA block may contain lines from several IR entities. Block names are never
inferred from DB naming; every mapping carries an explicit ``source_id``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceMapping:
    """One explicit edge of the N:N source mapping."""

    ir_id: str = ""
    canvas_node_id: str = ""
    scl_file: str = ""
    scl_line: int = 0
    tia_block: str = ""
    tia_block_type: str = ""
    source_id: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ir_id": self.ir_id,
            "canvas_node_id": self.canvas_node_id,
            "scl_file": self.scl_file,
            "scl_line": int(self.scl_line),
            "tia_block": self.tia_block,
            "tia_block_type": self.tia_block_type,
            "source_id": self.source_id,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceMapping:
        return cls(
            ir_id=str(data.get("ir_id") or ""),
            canvas_node_id=str(data.get("canvas_node_id") or ""),
            scl_file=str(data.get("scl_file") or ""),
            scl_line=int(data.get("scl_line") or 0),
            tia_block=str(data.get("tia_block") or ""),
            tia_block_type=str(data.get("tia_block_type") or ""),
            source_id=str(data.get("source_id") or ""),
            note=str(data.get("note") or ""),
        )


@dataclass
class SourceMap:
    """Bidirectional, deterministic N:N mapping with compile-error lookup."""

    map_id: str = ""
    ir_sha256: str = ""
    template_sha256: str = ""
    mappings: list[SourceMapping] = field(default_factory=list)

    def add(
        self,
        *,
        ir_id: str,
        scl_file: str,
        scl_line: int,
        tia_block: str,
        tia_block_type: str = "",
        canvas_node_id: str = "",
        source_id: str = "",
        note: str = "",
    ) -> SourceMapping:
        """Append one mapping and return it."""
        mapping = SourceMapping(
            ir_id=ir_id,
            canvas_node_id=canvas_node_id or ir_id,
            scl_file=scl_file,
            scl_line=int(scl_line),
            tia_block=tia_block,
            tia_block_type=tia_block_type,
            source_id=source_id or ir_id,
            note=note,
        )
        self.mappings.append(mapping)
        return mapping

    def locate(self, tia_block: str, scl_line: int) -> list[dict[str, Any]]:
        """TIA block + line -> list of IR references (N side is preserved)."""
        hits = [
            m for m in self.mappings
            if m.tia_block == tia_block and m.scl_line == int(scl_line)
        ]
        if not hits:
            # Nearest preceding line in the same block (compiler line drift).
            candidates = [m for m in self.mappings if m.tia_block == tia_block and m.scl_line <= int(scl_line)]
            if candidates:
                best_line = max(m.scl_line for m in candidates)
                hits = [m for m in candidates if m.scl_line == best_line]
        return [
            {
                "ir_id": m.ir_id,
                "canvas_node_id": m.canvas_node_id,
                "source_id": m.source_id,
                "scl_file": m.scl_file,
                "scl_line": m.scl_line,
                "tia_block": m.tia_block,
            }
            for m in sorted(hits, key=lambda x: (x.ir_id, x.scl_line))
        ]

    def reverse_locate(self, ir_id: str) -> list[dict[str, Any]]:
        """IR id -> all SCL / TIA locations (N side is preserved)."""
        hits = [m for m in self.mappings if m.ir_id == ir_id]
        return [
            {
                "scl_file": m.scl_file,
                "scl_line": m.scl_line,
                "tia_block": m.tia_block,
                "tia_block_type": m.tia_block_type,
                "source_id": m.source_id,
                "canvas_node_id": m.canvas_node_id,
            }
            for m in sorted(hits, key=lambda x: (x.scl_file, x.scl_line, x.tia_block))
        ]

    def locate_compile_error(self, tia_block: str, scl_line: int, message: str = "") -> dict[str, Any]:
        """Map a compiler diagnostic back to concrete IR nodes / Canvas nodes."""
        refs = self.locate(tia_block, scl_line)
        return {
            "tia_block": tia_block,
            "scl_line": int(scl_line),
            "message": message,
            "mapped": bool(refs),
            "ir_refs": refs,
            "canvas_node_ids": sorted({r["canvas_node_id"] for r in refs}),
            "source_ids": sorted({r["source_id"] for r in refs}),
        }

    def ir_ids(self) -> list[str]:
        """All mapped IR ids, deterministically sorted."""
        return sorted({m.ir_id for m in self.mappings if m.ir_id})

    def to_dict(self) -> dict[str, Any]:
        return {
            "map_id": self.map_id,
            "ir_sha256": self.ir_sha256,
            "template_sha256": self.template_sha256,
            "mappings": [m.to_dict() for m in self.mappings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceMap:
        return cls(
            map_id=str(data.get("map_id") or ""),
            ir_sha256=str(data.get("ir_sha256") or ""),
            template_sha256=str(data.get("template_sha256") or ""),
            mappings=[
                SourceMapping.from_dict(x) if isinstance(x, dict) else x
                for x in (data.get("mappings") or [])
            ],
        )
