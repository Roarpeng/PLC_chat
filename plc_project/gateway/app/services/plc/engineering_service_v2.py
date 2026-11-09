"""EngineeringService_v2: candidate-copy patch application, freeze and derive.

The service never writes the IR directly; all writes go through the atomic
kernel patch engine and the WorkspaceStore transaction. Derived projections
are recomputed one-way from the frozen IR.
"""
from __future__ import annotations

import uuid
from typing import Any

from gateway.app.services.plc.workspace_v2 import WorkspaceStore, utc_now
from plc_engine.engineering_ir.contracts import SCHEMA_VERSION, TIA_VERSION
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import (
    ChangeSet,
    DerivedBundle,
    EngineeringIRV2,
    PatchResultV2,
    ValidationReport,
    new_project_ir,
)
from plc_engine.engineering_ir.patch import apply_patch_atomic
from plc_engine.process.pipeline import derive_bundle
from plc_engine.process.scan_simulator import ScanSimulator, build_standard_scenarios
from plc_engine.process.scl_lowering import CompilerService


class EngineeringServiceV2:
    """Application service for V2 project editing and derivation."""

    @staticmethod
    def create_project(
        store: WorkspaceStore,
        project_id: str,
        *,
        ir: EngineeringIRV2 | None = None,
        origin: str = "greenfield",
    ) -> dict[str, Any]:
        """Create a fresh workspace at revision 0."""
        project_ir = ir or new_project_ir(project_id)
        workspace = store.create_project(project_id, project_ir, origin=origin)
        return {
            "project_id": project_id,
            "revision": 0,
            "ir_sha256": project_ir.ir_sha256,
            "af_profile": project_ir.af_profile.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "tia_version": TIA_VERSION,
            "state": workspace.state,
            "evidence_level": EvidenceLevel.PENDING_REAL_MACHINE.value,
        }

    @staticmethod
    def get_ir(store: WorkspaceStore, project_id: str) -> EngineeringIRV2:
        """Read the authoritative IR."""
        return store.get_ir(project_id)

    @staticmethod
    def commit_patch(store: WorkspaceStore, project_id: str, patch: Any) -> PatchResultV2:
        """Atomically apply a CandidatePatch; raises 409/422 kernel errors."""
        if not getattr(patch, "project_id", ""):
            patch.project_id = project_id
        return store.commit_patch(project_id, patch)

    @staticmethod
    def preview_candidate(ir: EngineeringIRV2, patch: Any) -> tuple[EngineeringIRV2, PatchResultV2]:
        """Apply a patch to a candidate copy only (never commits)."""
        return apply_patch_atomic(ir, patch)

    @staticmethod
    def derive(store: WorkspaceStore, project_id: str) -> DerivedBundle:
        """Recompute all derived projections for the current IR."""
        return derive_bundle(store.get_ir(project_id))

    @staticmethod
    def simulate(store: WorkspaceStore, project_id: str, scenario_name: str = "normal_cycle") -> dict[str, Any]:
        """Run one offline Trace scenario (explicitly labelled a prediction)."""
        ir = store.get_ir(project_id)
        scenarios = build_standard_scenarios()
        scenario = scenarios.get(scenario_name)
        if scenario is None:
            raise KeyError(f"unknown scenario {scenario_name!r}; available: {sorted(scenarios)}")
        simulator = ScanSimulator()
        frames = [frame.to_dict() for frame in simulator.run(ir, scenario)]
        return {
            "scenario": scenario.to_dict(),
            "trace": frames,
            "shortest_counterexample": simulator.shortest_counterexample(ir),
            "scan_order": list(simulator.scan_order()),
            "evidence_level": EvidenceLevel.OFFLINE.value,
            "notice": "预测模型 Trace · 非在线 PLC 波形；预测，不是实机验证",
        }

    @staticmethod
    def freeze_changeset(
        store: WorkspaceStore,
        project_id: str,
        *,
        base_revision: int,
        ops: list[Any] | None = None,
    ) -> ChangeSet:
        """Freeze a review pack from the current IR (no TIA write)."""
        from gateway.app.services.plc.validation_v2 import ValidationServiceV2

        ir = store.get_ir(project_id)
        report: ValidationReport = ValidationServiceV2.validate_ir(ir)
        changeset = ChangeSet(
            id=f"cs_{uuid.uuid4().hex[:16]}",
            project_id=project_id,
            base_revision=int(base_revision),
            before_hash=ir.ir_sha256,
            after_hash=ir.ir_sha256,
            spec_hash=ir.compute_spec_hash(),
            status="PROPOSED" if report.passed else "FAILED",
            ops=list(ops or []),
            impacts={
                "components": len(ir.components),
                "steps": len(ir.process.steps),
                "transitions": len(ir.process.transitions),
                "delete_count": 0,
                "safety_block_changes": 0,
            },
            validation=report,
            review_approved=False,
            created_at=utc_now(),
        )
        return store.insert_changeset(changeset)

    @staticmethod
    def approve(
        store: WorkspaceStore,
        changeset_id: str,
        *,
        reviewer: str,
        explicit: bool,
        expected_baseline_hash: str,
    ) -> ChangeSet:
        """Explicit human sign-off with baseline recheck."""
        return store.approve_changeset(
            changeset_id,
            reviewer=reviewer,
            explicit=explicit,
            expected_baseline_hash=expected_baseline_hash,
        )

    @staticmethod
    def blocks(store: WorkspaceStore, project_id: str) -> dict[str, Any]:
        """v1-compatible read-only block index (no write-back)."""
        ir = store.get_ir(project_id)
        manifest, _ = CompilerService(ir.af_profile).lower(ir)
        return {
            "project_id": project_id,
            "revision": ir.revision,
            "blocks": [
                {
                    "name": file.tia_block,
                    "type": file.role,
                    "number": file.block_number,
                    "sha256": file.sha256,
                    "source_ids": file.source_ids,
                }
                for file in sorted(manifest.files, key=lambda f: f.path)
            ],
            "legacy_raw_sha256": ir.legacy_raw_sha256,
            "evidence_level": EvidenceLevel.OFFLINE.value,
        }
