"""Deterministic ValidationEngine (fail-closed, design 1.5 / blueprint A4).

IR-level checks live here; graph/guard/resource checks are delegated to
``plc_engine.process.graph_validation`` so that the same rules are shared by
the compiler and the simulator. Unknown == fail: "no findings" only means
these checks passed, never that machine safety is proven.
"""
from __future__ import annotations

from typing import Any

from plc_engine.engineering_ir.contracts import SCHEMA_VERSION
from plc_engine.engineering_ir.hashing import stable_id_report
from plc_engine.engineering_ir.models import (
    CandidatePatch,
    EngineeringIRV2,
    ValidationReport,
)


def _issue(source_id: str, reason: str, field_name: str = "") -> dict[str, Any]:
    return {"source_id": source_id, "node_id": source_id, "field": field_name, "reason": reason}


class ValidationEngine:
    """Pure, deterministic static validation of an EngineeringIRV2."""

    def validate(self, ir: EngineeringIRV2) -> ValidationReport:
        """Return a full ValidationReport with node-level issues."""
        issues: list[dict[str, Any]] = []
        warnings: list[str] = []

        if ir.schema_version != SCHEMA_VERSION:
            issues.append(_issue(ir.project_id, f"schema_version {ir.schema_version!r} is not {SCHEMA_VERSION}", "schema_version"))
        if not ir.project_id:
            issues.append(_issue("", "project_id is required", "project_id"))

        id_report = stable_id_report(ir.stable_ids())
        for duplicate in id_report["duplicate_ids"]:
            issues.append(_issue(duplicate, "duplicate stable ID", "id"))
        for malformed in id_report["malformed_ids"]:
            issues.append(_issue(malformed, "malformed stable ID", "id"))

        # Component / driver contract checks.
        for component in ir.components:
            spec = ir.driver_specs.get(component.driver_spec_id)
            if spec is None:
                if component.driver_spec_id:
                    issues.append(_issue(component.id, f"unknown driver_spec_id {component.driver_spec_id!r}", "driver_spec_id"))
                continue
            for port_name, port in sorted(spec.typed_ports.items()):
                if not port_name or port.name != port_name:
                    issues.append(_issue(component.id, f"typed port key/name mismatch: {port_name!r}", "typed_ports"))
                if not hasattr(port.data_type, "value"):
                    issues.append(_issue(component.id, f"port {port_name} has unknown data_type {port.data_type!r}", "data_type"))
                if not hasattr(port.direction, "value"):
                    issues.append(_issue(component.id, f"port {port_name} has unknown direction {port.direction!r}", "direction"))
                if not hasattr(port.role, "value"):
                    issues.append(_issue(component.id, f"port {port_name} has unknown role {port.role!r}", "role"))
                if port.role.value == "COMMAND" and not port.writer:
                    issues.append(_issue(component.id, f"command port {port_name} has no single writer", "writer"))
            for address_issue in spec.assert_no_fictional_address():
                issues.append(_issue(component.id, address_issue, "io_bindings"))
            if not spec.required_ports():
                issues.append(_issue(component.id, "driver has no required ports", "typed_ports"))
            if spec.move_timeout_ms <= 0:
                issues.append(_issue(component.id, "driver must declare a positive move_timeout_ms", "move_timeout_ms"))
            if component.io_bindings is not None:
                for key, address in component.io_bindings.items():
                    if isinstance(address, str) and address.startswith("%"):
                        issues.append(
                            _issue(component.id, f"greenfield component {key} must not invent physical address {address}", "io_bindings")
                        )
            for question in spec.open_questions:
                warnings.append(f"{component.id}: {question}")

        if ir.hardware.io_binding not in (None, "", "unbound"):
            issues.append(_issue("hardware", "greenfield hardware io_binding must stay unbound", "io_binding"))

        issues.extend(
            _issue("", reason, "process")
            for reason in ir.process.validate_references()
        )

        # Graph / Guard / resource / parallel-semantics checks (shared rules).
        from plc_engine.process.graph_validation import validate_process

        issues.extend(validate_process(ir))

        return ValidationReport(
            passed=not issues,
            issues=sorted(issues, key=lambda i: (str(i.get("source_id") or ""), str(i.get("reason") or ""))),
            warnings=sorted(set(warnings)),
            unchanged_ir_hash=ir.ir_sha256,
        )

    def validate_patch(self, ir: EngineeringIRV2, patch: CandidatePatch) -> ValidationReport:
        """Validate a patch against ``ir`` without committing anything."""
        from plc_engine.engineering_ir.patch import (
            PatchConflictError,
            SemanticValidationError,
            apply_patch_atomic,
        )

        try:
            candidate, _ = apply_patch_atomic(ir, patch)
        except PatchConflictError as exc:
            return ValidationReport(
                passed=False,
                issues=[_issue(ir.project_id, str(exc), "base_revision")],
                unchanged_ir_hash=ir.ir_sha256,
            )
        except SemanticValidationError as exc:
            return ValidationReport(
                passed=False,
                issues=list(exc.issues),
                unchanged_ir_hash=exc.unchanged_ir_hash,
            )
        return self.validate(candidate)
