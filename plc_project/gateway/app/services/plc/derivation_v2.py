"""DerivationService_v2: single orchestration facade for all IR projections.

Design 4.1 requires validate / simulate / preview endpoints to recompute
one-way derivatives from the frozen IR. This service is the ONLY place the
router calls; the actual algorithms live in ``plc_engine.process.*`` and the
validation gate in ``validation_v2.py`` — no duplicate implementation.
"""
from __future__ import annotations

from typing import Any

from gateway.app.services.plc.engineering_service_v2 import EngineeringServiceV2
from gateway.app.services.plc.validation_v2 import ValidationServiceV2
from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine.engineering_ir.models import DerivedBundle


class DerivationServiceV2:
    """Recompute DeviceGraph / Mermaid / Trace / SCL / SourceMap / Manifest."""

    def __init__(self, store: WorkspaceStore) -> None:
        self.store = store

    def derive_all(self, project_id: str) -> DerivedBundle:
        """Full one-way derivation bundle for the current authoritative IR."""
        return EngineeringServiceV2.derive(self.store, project_id)

    def validate(self, project_id: str) -> dict[str, Any]:
        """Static gate result (9 check families + manifest import order)."""
        return ValidationServiceV2.static_gate(self.store.get_ir(project_id))

    def simulate(self, project_id: str, scenario: str = "normal_cycle") -> dict[str, Any]:
        """One deterministic offline Trace scenario."""
        return EngineeringServiceV2.simulate(self.store, project_id, scenario)

    def preview(self, project_id: str, *, include_scl: bool = True) -> dict[str, Any]:
        """IR preview: manifest, SourceMap, SCL files, Mermaid, validation."""
        bundle = self.derive_all(project_id)
        return {
            "artifact_manifest": bundle.manifest.to_dict(include_content=False),
            "source_map": bundle.source_map.to_dict(),
            "scl_files": bundle.scl_files if include_scl else {},
            "mermaid": bundle.mermaid,
            "device_graph": bundle.device_graph,
            "validation": bundle.validation.to_dict(),
            "evidence_level": bundle.evidence_level.value
            if hasattr(bundle.evidence_level, "value") else str(bundle.evidence_level),
            "notice": bundle.notice,
        }

    def source_map_dirty(self, changed_ir_ids: list[str]) -> list[str]:
        """Map changed IR ids to generated TIA blocks needing re-derivation."""
        dirty: set[str] = set()
        for ident in changed_ir_ids:
            if ident.startswith("hardware."):
                continue
            if ident.startswith("S") or ident.startswith("T"):
                dirty.add("FB_Sequence")
            else:
                dirty.add("FB_Drivers")
        return sorted(dirty)
