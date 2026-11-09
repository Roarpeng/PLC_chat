"""Service-layer validation orchestration (WP-00 / G4 static gate)."""
from __future__ import annotations

from typing import Any

from plc_engine.engineering_ir.models import EngineeringIRV2, ValidationReport
from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.process.artifact_manifest import ArtifactManifest
from plc_engine.process.scl_lowering import CompilerService


class ValidationServiceV2:
    """Wraps the deterministic kernel validator for the API layer."""

    @staticmethod
    def validate_ir(ir: EngineeringIRV2) -> ValidationReport:
        """Run all nine static check families on an IR."""
        return ValidationEngine().validate(ir)

    @staticmethod
    def validate_project(store: Any, project_id: str) -> ValidationReport:
        """Validate the current authoritative IR of a project."""
        return ValidationEngine().validate(store.get_ir(project_id))

    @staticmethod
    def static_gate(ir: EngineeringIRV2) -> dict[str, Any]:
        """Full SOURCE_READY static gate: IR validation + deterministic lowering.

        A failed gate blocks ``SOURCE_READY`` and therefore blocks any TIA
        delivery. Manifest import order must be UDT -> FB/FC -> DB -> OB.
        """
        report = ValidationEngine().validate(ir)
        manifest, source_map = CompilerService(ir.af_profile).lower(ir)
        order_issues = manifest.validate_import_order()
        issues = list(report.issues)
        issues.extend(
            {
                "source_id": "ArtifactManifest",
                "node_id": "import_order",
                "field": "import_order",
                "reason": problem,
            }
            for problem in order_issues
        )
        parallel_issues = [i for i in issues if "UNSUPPORTED_PARALLEL_SEMANTICS" in str(i.get("reason"))]
        return {
            "passed": not issues,
            "issues": sorted(issues, key=lambda i: (str(i.get("source_id")), str(i.get("reason")))),
            "unchanged_ir_hash": ir.ir_sha256,
            "manifest_sha256": manifest.sha256,
            "source_map_entries": len(source_map.mappings),
            "unsupported_parallel_semantics": bool(parallel_issues),
            "evidence_level": "offline",
        }

    @staticmethod
    def assert_source_ready(ir: EngineeringIRV2, manifest: ArtifactManifest | None = None) -> tuple[bool, list[dict[str, Any]]]:
        """Return ``(ready, issues)`` for the SOURCE_READY state."""
        gate = ValidationServiceV2.static_gate(ir)
        ready = bool(gate["passed"])
        if manifest is not None and manifest.validate_import_order():
            ready = False
        return ready, list(gate["issues"])
