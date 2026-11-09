"""DriverCatalog: the four standard component templates (WP-02 / G2).

Templates are data (``templates/*.json``), never executable code. The catalog
explicitly distinguishes the official LBC compile mode from the self-contained
mode, and an unmatched device type is reported as ``custom_pending`` rather
than guessed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_engine.canonical import canonical_dumps, sha256_prefixed
from plc_engine.components.driver_spec import (
    CompileMode,
    ComponentDefinition,
    DriverSpec,
    FieldSource,
    TypedPort,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
CUSTOM_PENDING = "custom_pending"


@dataclass
class DriverTemplate:
    """One declarative driver template loaded from JSON."""

    component_type: str = ""
    driver_template: str = ""
    lbc_name: str = ""
    default_compile_mode: CompileMode = CompileMode.OFFICIAL_LBC
    compile_modes: list[str] = field(default_factory=list)
    safety_permit_required: bool = True
    move_timeout_ms: int = 3000
    states: list[str] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    typed_ports: list[TypedPort] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    af_template: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_type": self.component_type,
            "driver_template": self.driver_template,
            "lbc_name": self.lbc_name,
            "default_compile_mode": self.default_compile_mode.value,
            "compile_modes": list(self.compile_modes),
            "safety_permit_required": bool(self.safety_permit_required),
            "move_timeout_ms": int(self.move_timeout_ms),
            "states": list(self.states),
            "transitions": [dict(x) for x in self.transitions],
            "typed_ports": [p.to_dict() for p in self.typed_ports],
            "parameters": dict(self.parameters),
            "af_template": dict(self.af_template),
            "keywords": list(self.keywords),
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriverTemplate:
        raw_ports = data.get("typed_ports") or []
        ports = [TypedPort.from_dict(p) if isinstance(p, dict) else p for p in raw_ports]
        try:
            default_mode = CompileMode(str(data.get("default_compile_mode") or CompileMode.OFFICIAL_LBC.value))
        except ValueError:
            default_mode = str(data.get("default_compile_mode") or "")
        return cls(
            component_type=str(data.get("component_type") or ""),
            driver_template=str(data.get("driver_template") or ""),
            lbc_name=str(data.get("lbc_name") or ""),
            default_compile_mode=default_mode,
            compile_modes=[str(x) for x in (data.get("compile_modes") or [])],
            safety_permit_required=bool(data.get("safety_permit_required", True)),
            move_timeout_ms=int(data.get("move_timeout_ms") or 3000),
            states=[str(x) for x in (data.get("states") or [])],
            transitions=[dict(x) for x in (data.get("transitions") or []) if isinstance(x, dict)],
            typed_ports=ports,
            parameters=dict(data.get("parameters") or {}),
            af_template=dict(data.get("af_template") or {}),
            keywords=[str(x) for x in (data.get("keywords") or [])],
            sha256=str(data.get("sha256") or ""),
        )


class DriverCatalog:
    """Registry of the four standard drivers."""

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        self.templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR
        self._templates: dict[str, DriverTemplate] = {}
        self._load_errors: list[str] = []
        self.load()

    def load(self) -> None:
        """Load and hash every declarative template; malformed ones are refused."""
        self._templates = {}
        self._load_errors = []
        if not self.templates_dir.is_dir():
            self._load_errors.append(f"templates directory missing: {self.templates_dir}")
            return
        for path in sorted(self.templates_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                template = DriverTemplate.from_dict(raw)
                template.sha256 = sha256_prefixed(path.read_bytes())
                if not template.component_type:
                    raise ValueError("template.component_type is required")
                if not template.typed_ports:
                    raise ValueError("template.typed_ports must not be empty")
                self._templates[template.component_type] = template
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._load_errors.append(f"{path.name}: {exc}")

    @property
    def load_errors(self) -> list[str]:
        """Deterministic list of refused template files."""
        return list(self._load_errors)

    def types(self) -> list[str]:
        """All registered component types, sorted."""
        return sorted(self._templates)

    def get(self, component_type: str) -> DriverTemplate | None:
        """Look up a template by component type; unknown returns None."""
        return self._templates.get(component_type)

    def template_sha256(self, component_type: str) -> str:
        """Content hash of one template (used for reproducibility receipts)."""
        template = self.get(component_type)
        return template.sha256 if template else ""

    def catalog_sha256(self) -> str:
        """Deterministic hash of the whole catalog (sorted template hashes)."""
        return sha256_prefixed(
            canonical_dumps({name: t.to_dict() for name, t in sorted(self._templates.items())})
        )

    def match_from_text(self, message: str) -> str:
        """Rule-first NL entity classification; unknown maps to custom_pending."""
        text = str(message or "").lower()
        best_type = CUSTOM_PENDING
        best_score = 0
        for template in self._templates.values():
            score = sum(1 for keyword in template.keywords if keyword.lower() in text)
            if score > best_score:
                best_score = score
                best_type = template.component_type
        return best_type if best_score else CUSTOM_PENDING

    def create_spec(
        self,
        component_type: str,
        *,
        spec_id: str = "",
        compile_mode: CompileMode | str | None = None,
        overrides: dict[str, Any] | None = None,
        field_sources: dict[str, str] | None = None,
        open_questions: list[str] | None = None,
    ) -> DriverSpec:
        """Materialise a DriverSpec from a template (never invents IO addresses)."""
        template = self.get(component_type)
        if template is None:
            raise KeyError(f"unknown component_type {component_type!r}; use {CUSTOM_PENDING!r} instead of guessing")
        mode = compile_mode or template.default_compile_mode
        if not isinstance(mode, CompileMode):
            mode = CompileMode(str(mode))
        if mode.value not in template.compile_modes:
            raise ValueError(f"compile_mode {mode.value!r} is not supported by {component_type!r}")
        ports = {port.name: TypedPort.from_dict(port.to_dict()) for port in template.typed_ports}
        parameters = dict(template.parameters)
        overrides = dict(overrides or {})
        for key, value in overrides.items():
            if key in parameters or key in ("move_timeout_ms",):
                parameters[key] = value
            elif key in ports:
                port = ports[key]
                if isinstance(value, dict):
                    ports[key] = TypedPort.from_dict({**port.to_dict(), **value})
            else:
                parameters[key] = value
        timeout = int(parameters.get("move_timeout_ms") or template.move_timeout_ms)
        spec = DriverSpec(
            id=spec_id or f"DRV_{component_type}",
            component_type=component_type,
            typed_ports=ports,
            parameters=parameters,
            states=list(template.states),
            transitions=[dict(t) for t in template.transitions],
            compile_mode=mode,
            safety_permit_required=bool(template.safety_permit_required),
            move_timeout_ms=timeout,
            lbc_name=template.lbc_name,
            field_sources=dict(field_sources or {}),
            open_questions=list(open_questions or []),
        )
        for port in spec.typed_ports.values():
            if port.binding is not None:
                raise ValueError(f"template port {port.name} must stay unbound/null")
        return spec

    def create_component(
        self,
        component_type: str,
        *,
        component_id: str,
        name: str = "",
        compile_mode: CompileMode | str | None = None,
        overrides: dict[str, Any] | None = None,
        field_sources: dict[str, str] | None = None,
        open_questions: list[str] | None = None,
        source: FieldSource = FieldSource.USER_EXPLICIT,
    ) -> tuple[ComponentDefinition, DriverSpec]:
        """Create a component and its bound DriverSpec with stable IDs."""
        template = self.get(component_type)
        if template is None:
            raise KeyError(f"unknown component_type {component_type!r}")
        spec_id = f"DRV_{component_id}"
        spec = self.create_spec(
            component_type,
            spec_id=spec_id,
            compile_mode=compile_mode,
            overrides=overrides,
            field_sources=field_sources,
            open_questions=open_questions,
        )
        component = ComponentDefinition(
            id=component_id,
            name=name or f"{component_type}:{component_id}",
            component_type=component_type,
            driver_template=template.driver_template,
            driver_spec_id=spec_id,
            source=source,
            io_bindings=None,
            parameters=dict(spec.parameters),
            metadata={"template_sha256": template.sha256, "compile_mode": spec.compile_mode.value},
        )
        return component, spec

    def af_binding(self, component_type: str) -> dict[str, Any]:
        """Read-only AF template mapping for one component type."""
        template = self.get(component_type)
        return dict(template.af_template) if template else {}


DEFAULT_CATALOG: DriverCatalog | None = None


def default_catalog() -> DriverCatalog:
    """Process-wide cached catalog (templates are immutable on disk)."""
    global DEFAULT_CATALOG
    if DEFAULT_CATALOG is None:
        DEFAULT_CATALOG = DriverCatalog()
    return DEFAULT_CATALOG
