"""P0 traceability facade: object registry + SourceMap + incidents wired together.

Provides the alarm -> object -> AF -> behavior -> source -> handover chain over
the existing ProcessContract / codegen, so any CM or alarm traces back to its
station, EM, step, native block, change history and evidence.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from processos.backends import lower
from processos.codegen import generate
from processos.frameworks import get_profile, register_hr001_af_v19
from processos.incident import IncidentService, build_handover_context, build_object_context
from processos.registry import ObjectRegistry, register_contract
from processos.sourcemap import SourceMapRegistry, build_sourcemap
from processos.store import JsonDao


class TraceabilityService:
    def __init__(self) -> None:
        self.registry = ObjectRegistry()
        self.sourcemap = SourceMapRegistry()
        self.incidents = IncidentService()
        self._ids: dict[str, dict[str, str]] = {}  # project_id -> contract-local id -> object_id
        # Set by processos.store.persistence.attach_persistence; None keeps pure memory.
        self._ids_dao: JsonDao | None = None
        self._store_conn: sqlite3.Connection | None = None

    def register_project(self, project_id: str, contract: Any, physical_station: str | None = None) -> dict[str, str]:
        ids = register_contract(self.registry, contract, physical_station)
        self._ids[project_id] = ids
        if self._ids_dao is not None:
            self._ids_dao.put(project_id, "project_ids", {"ids": ids})
        return ids

    def ids_for(self, project_id: str) -> dict[str, str]:
        return self._ids.get(project_id, {})

    def record_build(self, project_id: str, build_id: str, contract: Any, *,
                     tia_project_id: str = "", tia_plc_id: str = "") -> list[dict[str, Any]]:
        ids = self._ids.get(project_id) or self.register_project(project_id, contract)
        profile = get_profile(contract.target_framework.split("@")[-1]) or register_hr001_af_v19()
        af_project = lower(contract, profile)
        generated = generate(af_project, profile)
        entries = build_sourcemap(ids, af_project, generated, build_id,
                                  tia_project_id=tia_project_id, tia_plc_id=tia_plc_id, registry=self.registry)
        for e in entries:
            self.sourcemap.add(e)
            self.registry.register("sourcemap", e.source_map_id, {"block": e.block_name}, object_id=e.source_map_id)
        build_obj = self.registry.register("build", build_id, {"project": project_id}, status="BUILD_VERIFIED")
        for e in entries:
            self.registry.relate(e.source_map_id, "compiles_to", build_obj.object_id)
        return [e.to_dict() for e in entries]

    def object_context(self, object_id: str, build_id: str | None = None) -> dict[str, Any]:
        return build_object_context(object_id, self.registry, self.sourcemap, build_id, self.incidents)

    def handover(self, incident_id: str) -> dict[str, Any]:
        return build_handover_context(incident_id, self.incidents, self.registry, self.sourcemap)

    def find_object(self, name: str) -> dict[str, Any] | None:
        obj = self.registry.find_by_name(name)
        return obj.to_dict() if obj else None