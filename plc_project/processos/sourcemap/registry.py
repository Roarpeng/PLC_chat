"""FC-01 · Release-bound SourceMap registry.

Binds semantic object -> behavior step -> release build -> TIA block / instance
DB / SCL span, with ownership and compiler mapping version. Some XML/blocks or
real compile diagnostics give no precise line; the minimum guarantee is
block-level location — line numbers are never fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from processos.store import JsonDao

MAPPING_VERSION = "processos-scl/1"


@dataclass
class SourceMapEntry:
    source_map_id: str
    semantic_object_id: str
    release_build_id: str
    block_name: str
    block_kind: str
    behavior_step_id: str = ""
    tia_project_id: str = ""
    tia_plc_id: str = ""
    instance_db: str = ""
    network_id: str | None = None
    scl_line_range: tuple[int, int] | None = None
    symbol_refs: list[str] = field(default_factory=list)
    alarm_refs: list[str] = field(default_factory=list)
    compiler_mapping_version: str = MAPPING_VERSION
    ownership: str = "GENERATED"  # GENERATED | MANAGED_NATIVE_OVERRIDE | OFFICIAL_LIBRARY

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_map_id": self.source_map_id, "semantic_object_id": self.semantic_object_id,
            "behavior_step_id": self.behavior_step_id, "release_build_id": self.release_build_id,
            "tia_project_id": self.tia_project_id, "tia_plc_id": self.tia_plc_id,
            "block_name": self.block_name, "block_kind": self.block_kind, "instance_db": self.instance_db,
            "network_id": self.network_id,
            "scl_line_range": list(self.scl_line_range) if self.scl_line_range else None,
            "symbol_refs": list(self.symbol_refs), "alarm_refs": list(self.alarm_refs),
            "compiler_mapping_version": self.compiler_mapping_version, "ownership": self.ownership,
        }


def source_entry_from_dict(data: dict[str, Any]) -> SourceMapEntry:
    """Rebuild a SourceMapEntry from its persisted dict (line range back to a tuple)."""
    lines = data.get("scl_line_range")
    return SourceMapEntry(
        source_map_id=data["source_map_id"],
        semantic_object_id=data.get("semantic_object_id", ""),
        release_build_id=data["release_build_id"],
        block_name=data["block_name"],
        block_kind=data.get("block_kind", ""),
        behavior_step_id=data.get("behavior_step_id", ""),
        tia_project_id=data.get("tia_project_id", ""),
        tia_plc_id=data.get("tia_plc_id", ""),
        instance_db=data.get("instance_db", ""),
        network_id=data.get("network_id"),
        scl_line_range=tuple(lines) if lines else None,
        symbol_refs=list(data.get("symbol_refs") or []),
        alarm_refs=list(data.get("alarm_refs") or []),
        compiler_mapping_version=data.get("compiler_mapping_version", MAPPING_VERSION),
        ownership=data.get("ownership", "GENERATED"),
    )


class SourceMapRegistry:
    def __init__(self, dao: JsonDao | None = None) -> None:
        self._entries: dict[str, SourceMapEntry] = {}
        self._dao = dao
        if dao is not None:
            for row in dao.list_by_kind("sourcemap"):
                e = source_entry_from_dict(row)
                self._entries[e.source_map_id] = e

    def add(self, entry: SourceMapEntry) -> SourceMapEntry:
        self._entries[entry.source_map_id] = entry
        if self._dao is not None:
            self._dao.put(entry.source_map_id, "sourcemap", entry.to_dict())
        return entry

    def get(self, source_map_id: str) -> SourceMapEntry | None:
        return self._entries.get(source_map_id)

    def for_build(self, build_id: str) -> list[SourceMapEntry]:
        return [e for e in self._entries.values() if e.release_build_id == build_id]

    def resolve(self, object_id: str, build_id: str | None = None) -> list[SourceMapEntry]:
        return [e for e in self._entries.values()
                if e.semantic_object_id == object_id and (build_id is None or e.release_build_id == build_id)]

    def all_entries(self) -> list[SourceMapEntry]:
        return list(self._entries.values())


def build_sourcemap(
    ids_map: dict[str, str],
    af_project: Any,
    generated: Any,
    build_id: str,
    *,
    tia_project_id: str = "",
    tia_plc_id: str = "",
    registry: Any = None,
) -> list[SourceMapEntry]:
    """Bridge codegen source_map + AfProject blocks into release-bound entries.

    ``ids_map`` maps contract-local ids (step/CM) to stable object_ids. Lines are
    grouped per (file, node); absent lines fall back to block-level (None).
    """
    block_by_file = {}
    for blk in af_project.blocks:
        block_by_file[blk.name + ".scl"] = blk

    spans: dict[tuple[str, str], list[int]] = {}
    for m in generated.source_map:
        spans.setdefault((m["file"], m["node"]), []).append(m["line"])

    entries: list[SourceMapEntry] = []
    seen: set[tuple[str, str]] = set()
    for (file, node), lines in spans.items():
        blk = block_by_file.get(file)
        block_name = blk.name if blk else file.rsplit(".", 1)[0]
        block_kind = blk.kind if blk else "FB"
        instance_db = af_project.instance_dbs.get(block_name, "")
        semantic_id = ids_map.get(node, "")
        if registry is not None and semantic_id:
            obj = registry.get(semantic_id)
            is_step = obj is not None and obj.kind == "behavior_step"
        else:
            is_step = node.startswith("S_")
        key = (semantic_id or node, block_name)
        if key in seen:
            continue
        seen.add(key)
        entries.append(SourceMapEntry(
            source_map_id=f"src_{build_id}_{len(entries) + 1:04d}",
            semantic_object_id=semantic_id,
            behavior_step_id=node if is_step else "",
            release_build_id=build_id,
            block_name=block_name, block_kind=block_kind, instance_db=instance_db,
            tia_project_id=tia_project_id, tia_plc_id=tia_plc_id,
            scl_line_range=(min(lines), max(lines)) if lines else None,
            symbol_refs=[node],
        ))

    # CM driver blocks: block-level location for each device (no fabricated lines).
    for blk in af_project.blocks:
        if blk.role != "cm_driver":
            continue
        cm_local = blk.source_ids[0] if blk.source_ids else ""
        semantic_id = ids_map.get(cm_local, "")
        if not semantic_id or (semantic_id, blk.name) in seen:
            continue
        seen.add((semantic_id, blk.name))
        entries.append(SourceMapEntry(
            source_map_id=f"src_{build_id}_{len(entries) + 1:04d}",
            semantic_object_id=semantic_id, release_build_id=build_id,
            block_name=blk.name, block_kind=blk.kind,
            instance_db=af_project.instance_dbs.get(blk.name, ""),
            tia_project_id=tia_project_id, tia_plc_id=tia_plc_id,
            scl_line_range=None, symbol_refs=[cm_local],
        ))
    return entries