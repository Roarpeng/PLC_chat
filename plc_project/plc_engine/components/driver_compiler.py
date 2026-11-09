"""DriverSpec -> AF control module / UDT / FB interface lowering (WP-02).

This is a pure, read-only projection: it never writes files, never assigns a
block number from thin air and never generates a physical address. The
``official_lbc`` mode references the official library block; ``self_contained``
emits a local FB interface description instead.
"""
from __future__ import annotations

from typing import Any

from plc_engine.components.catalog import DriverCatalog
from plc_engine.components.driver_spec import (
    CompileMode,
    ComponentDefinition,
    DriverSpec,
    PortDirection,
)
from plc_engine.engineering_ir.contracts import AF_PROFILE_ID


class DriverCompiler:
    """Deterministic lowering of driver specs into AF-facing declarations."""

    def __init__(self, catalog: DriverCatalog | None = None) -> None:
        self.catalog = catalog or DriverCatalog()

    def compile(
        self,
        spec: DriverSpec,
        component: ComponentDefinition,
        *,
        af_profile_id: str = AF_PROFILE_ID,
    ) -> dict[str, Any]:
        """Return an AF declaration bundle for one component."""
        template = self.catalog.get(component.component_type)
        af_template = dict(template.af_template) if template else {}
        inputs: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []
        for port in sorted(spec.typed_ports.values(), key=lambda p: p.name):
            entry = {
                "name": port.name,
                "data_type": port.data_type.value if hasattr(port.data_type, "value") else str(port.data_type),
                "role": port.role.value if hasattr(port.role, "value") else str(port.role),
                "binding": port.binding,
                "writer": port.writer,
                "source": port.source.value if hasattr(port.source, "value") else str(port.source),
            }
            if port.direction is PortDirection.OUTPUT:
                outputs.append(entry)
            else:
                inputs.append(entry)

        mode = spec.compile_mode.value if isinstance(spec.compile_mode, CompileMode) else str(spec.compile_mode)
        if mode == CompileMode.OFFICIAL_LBC.value:
            fb_name = af_template.get("fb") or spec.lbc_name
            implementation = "official_lbc_reference_only"
            scl_body = ""
        else:
            fb_name = af_template.get("self_contained_fb") or f"FB_{component.id}"
            implementation = "self_contained_local_fb"
            scl_body = self._self_contained_scl(spec, component)

        return {
            "component_id": component.id,
            "component_name": component.name,
            "component_type": component.component_type,
            "af_profile_id": af_profile_id,
            "compile_mode": mode,
            "implementation": implementation,
            "cm_control_node": af_template.get("cm_control_node") or f"CN_{component.id}",
            "udt": af_template.get("udt") or f"UDT_{component.id}",
            "fb": fb_name,
            "fb_interfaces": {"inputs": inputs, "outputs": outputs},
            "parameters": dict(spec.parameters),
            "move_timeout_ms": int(spec.move_timeout_ms),
            "safety_permit_required": bool(spec.safety_permit_required),
            "scl_body": scl_body,
            "io_bindings": component.io_bindings,
            "physical_addresses": [],
            "block_number": None,
            "source_ids": [component.id, spec.id],
            "template_sha256": template.sha256 if template else "",
        }

    def compile_all(self, ir: Any, *, af_profile_id: str = AF_PROFILE_ID) -> list[dict[str, Any]]:
        """Lower every component of an IR in stable ID order."""
        result: list[dict[str, Any]] = []
        for component in sorted(ir.components, key=lambda c: c.id):
            spec = ir.driver_specs.get(component.driver_spec_id)
            if spec is None:
                continue
            result.append(self.compile(spec, component, af_profile_id=af_profile_id))
        return result

    @staticmethod
    def _self_contained_scl(spec: DriverSpec, component: ComponentDefinition) -> str:
        """Deterministic SCL stub body for self-contained mode (no addresses)."""
        lines = [
            f"// source_id: {component.id} / {spec.id}",
            "// compile_mode: self_contained ; AF profile pinned at generation",
            f"// move_timeout_ms := {int(spec.move_timeout_ms)};",
            "// SafetyPermit is a SOFTWARE interlock only, not a safety integrity claim.",
        ]
        for port in sorted(spec.typed_ports.values(), key=lambda p: p.name):
            lines.append(f"// {port.direction.value}: {port.name} : {port.data_type.value}; // {port.role.value}, unbound")
        lines.append("// Reverse outputs are interlocked by arbitrate_single_writer().")
        return "\n".join(lines) + "\n"
