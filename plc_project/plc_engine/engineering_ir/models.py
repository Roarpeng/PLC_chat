"""EngineeringIR v2 domain entities (WP-00 / G0 / G1).

``EngineeringIRV2`` is the single writable semantic truth. Every other model
in this module is either a pinned workspace profile, a controlled transaction
object, an artifact descriptor, or a derived result. Domain-specific entities
(ComponentDefinition / DriverSpec / SequenceIR / GuardAST / SourceMap /
ArtifactManifest) are defined once in their owning packages and re-exported
here so that no duplicate implementation exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plc_engine.components.driver_spec import ComponentDefinition, DriverSpec, TypedPort
from plc_engine.engineering_ir.contracts import (
    AF_FOLDER_TREE,
    AF_LIBRARY_ID,
    AF_LIBRARY_VERSION,
    AF_NUMBER_POLICY,
    AF_PROFILE_ID,
    AF_TEMPLATE_SHA256,
    SCHEMA_VERSION,
    TIA_VERSION,
    assert_stable_id,
)
from plc_engine.engineering_ir.evidence import EvidenceLevel, EvidenceTag
from plc_engine.engineering_ir.hashing import (
    canonical_dumps,
    semantic_hash,
    sha256_prefixed,
    spec_hash,
    stable_id_report,
    to_plain,
)
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.guard_ast import GuardAST
from plc_engine.process.sequence_ir import Action, SequenceIR, Step, Transition
from plc_engine.process.source_map import SourceMap, SourceMapping

# --------------------------------------------------------------------------- #
# Pinned profiles / intents
# --------------------------------------------------------------------------- #


@dataclass
class AFProfile:
    """Pinned Automation Framework profile; never silently upgraded."""

    profile_id: str = AF_PROFILE_ID
    library_id: str = AF_LIBRARY_ID
    library_version: str = AF_LIBRARY_VERSION
    template_sha256: str = AF_TEMPLATE_SHA256
    number_policy: str = AF_NUMBER_POLICY
    folder_tree: str = AF_FOLDER_TREE
    tia_version: str = TIA_VERSION

    def assert_consistent_with(self, other: AFProfile) -> None:
        """Raise when two profiles are not byte-identical (version lock)."""
        if self.to_dict() != other.to_dict():
            raise ValueError("AF profile drift: generation/compilation must use the pinned baseline")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "library_id": self.library_id,
            "library_version": self.library_version,
            "template_sha256": self.template_sha256,
            "number_policy": self.number_policy,
            "folder_tree": self.folder_tree,
            "tia_version": self.tia_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AFProfile:
        return cls(
            profile_id=str(data.get("profile_id") or AF_PROFILE_ID),
            library_id=str(data.get("library_id") or AF_LIBRARY_ID),
            library_version=str(data.get("library_version") or AF_LIBRARY_VERSION),
            template_sha256=str(data.get("template_sha256") or AF_TEMPLATE_SHA256),
            number_policy=str(data.get("number_policy") or AF_NUMBER_POLICY),
            folder_tree=str(data.get("folder_tree") or AF_FOLDER_TREE),
            tia_version=str(data.get("tia_version") or TIA_VERSION),
        )


@dataclass
class HardwareIntent:
    """Logical hardware intent; physical addresses stay explicitly unbound."""

    cpu_template: str = ""
    io_binding: str = "unbound"
    device_type_identifier: str = ""
    capability_receipt_id: str = ""
    notes: list[str] = field(default_factory=list)

    def is_cpu_selected(self) -> bool:
        """True only when an approved CPU template has been selected."""
        return bool(self.cpu_template) and bool(self.device_type_identifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_template": self.cpu_template,
            "io_binding": self.io_binding,
            "device_type_identifier": self.device_type_identifier,
            "capability_receipt_id": self.capability_receipt_id,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HardwareIntent:
        return cls(
            cpu_template=str(data.get("cpu_template") or ""),
            io_binding=str(data.get("io_binding") or "unbound"),
            device_type_identifier=str(data.get("device_type_identifier") or ""),
            capability_receipt_id=str(data.get("capability_receipt_id") or ""),
            notes=[str(x) for x in (data.get("notes") or [])],
        )


@dataclass
class ImportedSnapshot:
    """Brownfield-only interface structure (no real-machine write in this batch)."""

    snapshot_id: str = ""
    original_archive_hash: str = ""
    block_index: dict[str, Any] = field(default_factory=dict)
    hardware_hash: str = ""
    safety_block_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "original_archive_hash": self.original_archive_hash,
            "block_index": dict(self.block_index),
            "hardware_hash": self.hardware_hash,
            "safety_block_hash": self.safety_block_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportedSnapshot:
        return cls(
            snapshot_id=str(data.get("snapshot_id") or ""),
            original_archive_hash=str(data.get("original_archive_hash") or ""),
            block_index=dict(data.get("block_index") or {}),
            hardware_hash=str(data.get("hardware_hash") or ""),
            safety_block_hash=str(data.get("safety_block_hash") or ""),
        )


@dataclass
class TiaCapabilityManifest:
    """G0 real-machine capability probe receipt (Q-05 / U-02).

    ``cpu_templates`` is a candidate list reported back to the team lead. A
    template is only ``verified_create_with_item`` after a real CreateWithItem
    probe; without that receipt the selection stays pending_real_machine.
    """

    probe_receipt_id: str = ""
    tia_version: str = TIA_VERSION
    cpu_templates: list[dict[str, Any]] = field(default_factory=list)
    selected_cpu_template: str = ""
    selection_note: str = ""
    probed_at: str = ""
    raw_probe_receipt: dict[str, Any] = field(default_factory=dict)
    evidence_level: EvidenceLevel = EvidenceLevel.PENDING_REAL_MACHINE
    status_receipt: dict[str, Any] = field(default_factory=dict)

    def verified_candidates(self) -> list[dict[str, Any]]:
        """Templates with a real CreateWithItem receipt, in catalog order."""
        return [t for t in self.cpu_templates if bool(t.get("verified_create_with_item"))]

    def candidate_type_ids(self) -> list[str]:
        """All candidate type identifiers for the lead to approve."""
        return [str(t.get("type_identifier") or "") for t in self.cpu_templates if t.get("type_identifier")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_receipt_id": self.probe_receipt_id,
            "tia_version": self.tia_version,
            "cpu_templates": [dict(t) for t in self.cpu_templates],
            "selected_cpu_template": self.selected_cpu_template,
            "selection_note": self.selection_note,
            "probed_at": self.probed_at,
            "raw_probe_receipt": dict(self.raw_probe_receipt),
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
            "status_receipt": dict(self.status_receipt),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TiaCapabilityManifest:
        return cls(
            probe_receipt_id=str(data.get("probe_receipt_id") or ""),
            tia_version=str(data.get("tia_version") or TIA_VERSION),
            cpu_templates=[dict(x) for x in (data.get("cpu_templates") or []) if isinstance(x, dict)],
            selected_cpu_template=str(data.get("selected_cpu_template") or ""),
            selection_note=str(data.get("selection_note") or ""),
            probed_at=str(data.get("probed_at") or ""),
            raw_probe_receipt=dict(data.get("raw_probe_receipt") or {}),
            evidence_level=EvidenceLevel.parse(data.get("evidence_level")),
            status_receipt=dict(data.get("status_receipt") or {}),
        )


# --------------------------------------------------------------------------- #
# Workspace / IR
# --------------------------------------------------------------------------- #


@dataclass
class ProjectWorkspace:
    """Project metadata and revision authority (design 3)."""

    project_id: str = ""
    origin: str = "greenfield"
    tia_version: str = TIA_VERSION
    baseline_hash: str = ""
    current_revision: int = 0
    state: str = "DRAFT"
    evidence_level: EvidenceLevel = EvidenceLevel.PENDING_REAL_MACHINE
    artifact_ids: list[str] = field(default_factory=list)
    af_profile: AFProfile = field(default_factory=AFProfile)
    hardware: HardwareIntent = field(default_factory=HardwareIntent)
    imported_snapshot: ImportedSnapshot | None = None
    created_at: str = ""
    updated_at: str = ""
    _store: Any = None

    def __post_init__(self) -> None:
        if self.project_id:
            assert_stable_id(self.project_id, "project")

    def bind_store(self, store: Any) -> None:
        """Attach the persistence service used by read_ir / commit_patch."""
        self._store = store

    def read_ir(self) -> EngineeringIRV2:
        """Read the authoritative IR through the bound WorkspaceStore."""
        if self._store is None:
            raise RuntimeError("ProjectWorkspace has no bound store; call bind_store() first")
        return self._store.get_ir(self.project_id)

    def commit_patch(self, patch: Any) -> PatchResultV2:
        """Atomically commit a CandidatePatch through the bound store."""
        if self._store is None:
            raise RuntimeError("ProjectWorkspace has no bound store; call bind_store() first")
        return self._store.commit_patch(self.project_id, patch)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "origin": self.origin,
            "tia_version": self.tia_version,
            "baseline_hash": self.baseline_hash,
            "current_revision": int(self.current_revision),
            "state": self.state,
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
            "artifact_ids": list(self.artifact_ids),
            "af_profile": self.af_profile.to_dict(),
            "hardware": self.hardware.to_dict(),
            "imported_snapshot": self.imported_snapshot.to_dict() if self.imported_snapshot else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectWorkspace:
        raw_snapshot = data.get("imported_snapshot")
        return cls(
            project_id=str(data.get("project_id") or ""),
            origin=str(data.get("origin") or "greenfield"),
            tia_version=str(data.get("tia_version") or TIA_VERSION),
            baseline_hash=str(data.get("baseline_hash") or ""),
            current_revision=int(data.get("current_revision") or 0),
            state=str(data.get("state") or "DRAFT"),
            evidence_level=EvidenceLevel.parse(data.get("evidence_level")),
            artifact_ids=[str(x) for x in (data.get("artifact_ids") or [])],
            af_profile=AFProfile.from_dict(data.get("af_profile") or {}),
            hardware=HardwareIntent.from_dict(data.get("hardware") or {}),
            imported_snapshot=ImportedSnapshot.from_dict(raw_snapshot) if isinstance(raw_snapshot, dict) else None,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class SourceBinding:
    """Brownfield interface-only binding (Q-04). Never writable by default."""

    source_id: str = ""
    tia_path: str = ""
    block_type: str = ""
    block_number: int | None = None
    original_xml_sha256: str = ""
    original_hash: str = ""
    source_span: dict[str, Any] = field(default_factory=dict)
    ir_entities: list[str] = field(default_factory=list)
    referenced_by: list[str] = field(default_factory=list)
    writable: str = "requires_review"
    fidelity: str = "unknown"

    def is_protected(self) -> bool:
        """F-blocks and unparseable blocks are always protected."""
        return self.writable == "requires_review" or self.block_type.upper() in ("F", "SAFETY", "FB_SAFETY")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "tia_path": self.tia_path,
            "block_type": self.block_type,
            "block_number": self.block_number,
            "original_xml_sha256": self.original_xml_sha256,
            "original_hash": self.original_hash,
            "source_span": dict(self.source_span),
            "ir_entities": list(self.ir_entities),
            "referenced_by": list(self.referenced_by),
            "writable": self.writable,
            "fidelity": self.fidelity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceBinding:
        number = data.get("block_number")
        return cls(
            source_id=str(data.get("source_id") or ""),
            tia_path=str(data.get("tia_path") or ""),
            block_type=str(data.get("block_type") or ""),
            block_number=int(number) if number not in (None, "") else None,
            original_xml_sha256=str(data.get("original_xml_sha256") or ""),
            original_hash=str(data.get("original_hash") or ""),
            source_span=dict(data.get("source_span") or {}),
            ir_entities=[str(x) for x in (data.get("ir_entities") or [])],
            referenced_by=[str(x) for x in (data.get("referenced_by") or [])],
            writable=str(data.get("writable") or "requires_review"),
            fidelity=str(data.get("fidelity") or "unknown"),
        )


@dataclass
class EngineeringIRV2:
    """The only writable semantic truth of a V2 project."""

    schema_version: str = SCHEMA_VERSION
    project_id: str = ""
    revision: int = 0
    ir_sha256: str = ""
    af_profile: AFProfile = field(default_factory=AFProfile)
    hardware: HardwareIntent = field(default_factory=HardwareIntent)
    components: list[ComponentDefinition] = field(default_factory=list)
    driver_specs: dict[str, DriverSpec] = field(default_factory=dict)
    process: SequenceIR = field(default_factory=SequenceIR)
    source_bindings: list[SourceBinding] = field(default_factory=list)
    views: dict[str, Any] = field(default_factory=lambda: {"layout": {}, "projection_version": "v2-view-1.0"})
    spec_meta: dict[str, Any] = field(default_factory=dict)
    legacy_raw: dict[str, Any] | None = None
    legacy_raw_sha256: str = ""
    receipt: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version!r}; expected {SCHEMA_VERSION}")
        if self.project_id:
            assert_stable_id(self.project_id, "project")

    # ------------------------------------------------------------- hashing --
    def semantic_hash(self) -> str:
        """Compute the canonical semantic hash (layout/timestamps excluded)."""
        return semantic_hash(self.to_dict())

    def refresh_hash(self) -> str:
        """Recompute and store ``ir_sha256``; returns the new value."""
        self.ir_sha256 = self.semantic_hash()
        return self.ir_sha256

    def compute_spec_hash(self) -> str:
        """Freeze hash bound to the pinned AF profile and template."""
        return spec_hash(self.to_dict(), self.af_profile.profile_id, self.af_profile.template_sha256)

    # ----------------------------------------------------------- validation --
    def stable_ids(self) -> list[str]:
        """All stable IDs owned by the IR."""
        ids = [c.id for c in self.components]
        ids.extend(self.driver_specs.keys())
        ids.extend(self.process.step_ids())
        ids.extend(self.process.transition_index().keys())
        ids.extend(b.source_id for b in self.source_bindings)
        return [i for i in ids if i]

    def assert_stable_ids(self) -> None:
        """Validate uniqueness / grammar of all owned IDs (fail-closed)."""
        report = stable_id_report(self.stable_ids())
        if not report["ok"]:
            raise ValueError(f"stable ID violation: {report}")

    # ------------------------------------------------------------ derivation --
    def device_graph(self) -> dict[str, Any]:
        """Deterministic read-only projection: components + their typed ports."""
        nodes: list[dict[str, Any]] = []
        for component in sorted(self.components, key=lambda c: c.id):
            spec = self.driver_specs.get(component.driver_spec_id)
            nodes.append(
                {
                    "id": component.id,
                    "name": component.name,
                    "component_type": component.component_type,
                    "io_bindings": component.io_bindings,
                    "ports": spec.to_dict()["typed_ports"] if spec is not None else {},
                }
            )
        edges = [
            {
                "id": f"E_SEQ_{tr.id}",
                "from": tr.from_step,
                "to": tr.to_step,
                "priority": tr.priority,
                "edge_type": tr.edge_type.value if hasattr(tr.edge_type, "value") else str(tr.edge_type),
            }
            for tr in sorted(self.process.transitions, key=lambda t: t.id)
        ]
        return {"nodes": nodes, "edges": edges, "projection_version": "v2-view-1.0"}

    def mermaid(self) -> str:
        """Deterministic Mermaid flowchart, a one-way IR projection."""
        lines = ["flowchart TD"]
        for step in self.process.steps:
            label = (step.name or step.id).replace('"', "'")
            lines.append(f'    {step.id}["{label}"]')
        for tr in sorted(self.process.transitions, key=lambda t: (t.from_step, -t.priority, t.id)):
            style = "-->" if (tr.edge_type.value if hasattr(tr.edge_type, "value") else str(tr.edge_type)) == "NORMAL" else "-.->"
            lines.append(f"    {tr.from_step} {style} {tr.to_step}")
        return "\n".join(lines)

    def derive_all(self) -> DerivedBundle:
        """Recompute every derived projection through the process pipeline."""
        from plc_engine.process.pipeline import derive_bundle

        return derive_bundle(self)

    # ------------------------------------------------------------- IO --
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "revision": int(self.revision),
            "ir_sha256": self.ir_sha256,
            "af_profile": self.af_profile.to_dict(),
            "hardware": self.hardware.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "driver_specs": {k: v.to_dict() for k, v in sorted(self.driver_specs.items())},
            "process": self.process.to_dict(),
            "source_bindings": [b.to_dict() for b in self.source_bindings],
            "views": to_plain(self.views),
            "spec_meta": dict(self.spec_meta),
            "legacy_raw": self.legacy_raw,
            "legacy_raw_sha256": self.legacy_raw_sha256,
            "receipt": dict(self.receipt),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineeringIRV2:
        raw_specs = data.get("driver_specs") or {}
        specs = {
            str(k): (v if isinstance(v, DriverSpec) else DriverSpec.from_dict(v))
            for k, v in raw_specs.items()
            if isinstance(v, (DriverSpec, dict))
        }
        process_raw = data.get("process") or {}
        process = process_raw if isinstance(process_raw, SequenceIR) else SequenceIR.from_dict(process_raw)
        return cls(
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
            project_id=str(data.get("project_id") or ""),
            revision=int(data.get("revision") or 0),
            ir_sha256=str(data.get("ir_sha256") or ""),
            af_profile=AFProfile.from_dict(data.get("af_profile") or {}),
            hardware=HardwareIntent.from_dict(data.get("hardware") or {}),
            components=[
                c if isinstance(c, ComponentDefinition) else ComponentDefinition.from_dict(c)
                for c in (data.get("components") or [])
            ],
            driver_specs=specs,
            process=process,
            source_bindings=[
                b if isinstance(b, SourceBinding) else SourceBinding.from_dict(b)
                for b in (data.get("source_bindings") or [])
            ],
            views=dict(data.get("views") or {"layout": {}}),
            spec_meta=dict(data.get("spec_meta") or {}),
            legacy_raw=dict(data.get("legacy_raw")) if isinstance(data.get("legacy_raw"), dict) else None,
            legacy_raw_sha256=str(data.get("legacy_raw_sha256") or ""),
            receipt=dict(data.get("receipt") or {}),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


# --------------------------------------------------------------------------- #
# Controlled transaction objects
# --------------------------------------------------------------------------- #


@dataclass
class ValidationReport:
    """Deterministic validation result with node-level issues."""

    passed: bool = True
    issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unchanged_ir_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": bool(self.passed),
            "issues": [dict(i) for i in self.issues],
            "warnings": list(self.warnings),
            "unchanged_ir_hash": self.unchanged_ir_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationReport:
        return cls(
            passed=bool(data.get("passed", True)),
            issues=[dict(i) for i in (data.get("issues") or []) if isinstance(i, dict)],
            warnings=[str(x) for x in (data.get("warnings") or [])],
            unchanged_ir_hash=str(data.get("unchanged_ir_hash") or ""),
        )


@dataclass
class ChangeOp:
    """One atomic semantic change op."""

    op: str = ""
    target_source_id: str = ""
    ir_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "target_source_id": self.target_source_id,
            "ir_id": self.ir_id,
            "payload": dict(self.payload),
            "source_id": self.source_id or self.ir_id or self.target_source_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangeOp:
        return cls(
            op=str(data.get("op") or ""),
            target_source_id=str(data.get("target_source_id") or ""),
            ir_id=str(data.get("ir_id") or ""),
            payload=dict(data.get("payload") or {}),
            source_id=str(data.get("source_id") or ""),
        )


@dataclass
class CandidatePatch:
    """A proposed (never auto-applied) atomic patch batch."""

    candidate_id: str = ""
    project_id: str = ""
    base_revision: int = 0
    request_id: str = ""
    before_hash: str = ""
    after_hash: str = ""
    ops: list[ChangeOp] = field(default_factory=list)
    explanation: str = ""
    questions: list[str] = field(default_factory=list)
    evidence_level: EvidenceLevel = EvidenceLevel.OFFLINE

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "project_id": self.project_id,
            "base_revision": int(self.base_revision),
            "request_id": self.request_id,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "ops": [op.to_dict() for op in self.ops],
            "explanation": self.explanation,
            "questions": list(self.questions),
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidatePatch:
        return cls(
            candidate_id=str(data.get("candidate_id") or ""),
            project_id=str(data.get("project_id") or ""),
            base_revision=int(data.get("base_revision") or 0),
            request_id=str(data.get("request_id") or ""),
            before_hash=str(data.get("before_hash") or ""),
            after_hash=str(data.get("after_hash") or ""),
            ops=[ChangeOp.from_dict(x) if isinstance(x, dict) else x for x in (data.get("ops") or [])],
            explanation=str(data.get("explanation") or ""),
            questions=[str(x) for x in (data.get("questions") or [])],
            evidence_level=EvidenceLevel.parse(data.get("evidence_level")),
        )


@dataclass
class ChangeSet:
    """Frozen diff awaiting explicit human approval."""

    id: str = ""
    project_id: str = ""
    base_revision: int = 0
    before_hash: str = ""
    after_hash: str = ""
    spec_hash: str = ""
    status: str = "PROPOSED"
    ops: list[ChangeOp] = field(default_factory=list)
    impacts: dict[str, Any] = field(default_factory=dict)
    validation: ValidationReport = field(default_factory=ValidationReport)
    review_approved: bool = False
    approved_by: str = ""
    signed_spec_hash: str = ""
    signed_baseline_hash: str = ""
    signed_at: str = ""
    explicit: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "base_revision": int(self.base_revision),
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "spec_hash": self.spec_hash,
            "status": self.status,
            "ops": [op.to_dict() for op in self.ops],
            "impacts": dict(self.impacts),
            "validation": self.validation.to_dict(),
            "review_approved": bool(self.review_approved),
            "approved_by": self.approved_by,
            "signed_spec_hash": self.signed_spec_hash,
            "signed_baseline_hash": self.signed_baseline_hash,
            "signed_at": self.signed_at,
            "explicit": bool(self.explicit),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangeSet:
        return cls(
            id=str(data.get("id") or ""),
            project_id=str(data.get("project_id") or ""),
            base_revision=int(data.get("base_revision") or 0),
            before_hash=str(data.get("before_hash") or ""),
            after_hash=str(data.get("after_hash") or ""),
            spec_hash=str(data.get("spec_hash") or ""),
            status=str(data.get("status") or "PROPOSED"),
            ops=[ChangeOp.from_dict(x) if isinstance(x, dict) else x for x in (data.get("ops") or [])],
            impacts=dict(data.get("impacts") or {}),
            validation=ValidationReport.from_dict(data.get("validation") or {}),
            review_approved=bool(data.get("review_approved", False)),
            approved_by=str(data.get("approved_by") or ""),
            signed_spec_hash=str(data.get("signed_spec_hash") or ""),
            signed_baseline_hash=str(data.get("signed_baseline_hash") or ""),
            signed_at=str(data.get("signed_at") or ""),
            explicit=bool(data.get("explicit", False)),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass
class PatchResultV2:
    """Result of a successfully committed atomic patch."""

    revision: int = 0
    ir_sha256: str = ""
    changed_ir_ids: list[str] = field(default_factory=list)
    source_map_dirty: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_level: EvidenceLevel = EvidenceLevel.OFFLINE
    request_id: str = ""
    idempotent_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": int(self.revision),
            "ir_sha256": self.ir_sha256,
            "changed_ir_ids": list(self.changed_ir_ids),
            "source_map_dirty": list(self.source_map_dirty),
            "warnings": list(self.warnings),
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
            "request_id": self.request_id,
            "idempotent_hit": bool(self.idempotent_hit),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatchResultV2:
        return cls(
            revision=int(data.get("revision") or 0),
            ir_sha256=str(data.get("ir_sha256") or ""),
            changed_ir_ids=[str(x) for x in (data.get("changed_ir_ids") or [])],
            source_map_dirty=[str(x) for x in (data.get("source_map_dirty") or [])],
            warnings=[str(x) for x in (data.get("warnings") or [])],
            evidence_level=EvidenceLevel.parse(data.get("evidence_level")),
            request_id=str(data.get("request_id") or ""),
            idempotent_hit=bool(data.get("idempotent_hit", False)),
        )


# --------------------------------------------------------------------------- #
# Native delivery artifacts
# --------------------------------------------------------------------------- #


@dataclass
class CompileReceipt:
    """Structured real compile receipt; warnings are NEVER folded into success."""

    state: str = ""
    error_count: int = 0
    warning_count: int = 0
    raw_api_receipt: str = ""
    static_gate_passed: bool = False
    compile_ok: bool = False
    evidence_level: EvidenceLevel = EvidenceLevel.PENDING_REAL_MACHINE
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_worker(cls, payload: dict[str, Any], *, raw: str = "", evidence: EvidenceLevel = EvidenceLevel.V19_REAL) -> CompileReceipt:
        """Fail-closed parse of the C# ``compile-plc`` receipt."""
        inner = payload.get("compile") if isinstance(payload.get("compile"), dict) else {}
        if not inner and isinstance(payload.get("error_count"), int):
            inner = payload
        def _as_int(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return -1

        state = str(inner.get("state") or payload.get("state") or "")
        error_count = _as_int(inner.get("errorCount", inner.get("error_count", payload.get("error_count", -1))))
        warning_count = _as_int(inner.get("warningCount", inner.get("warning_count", payload.get("warning_count", -1))))
        has_real_receipt = evidence is EvidenceLevel.V19_REAL and bool(raw or payload)
        compile_ok = error_count == 0 and warning_count >= 0 and has_real_receipt
        diagnostics = [dict(x) for x in (inner.get("diagnostics") or []) if isinstance(x, dict)]
        return cls(
            state=state,
            error_count=error_count,
            warning_count=warning_count,
            raw_api_receipt=raw or canonical_dumps(payload),
            static_gate_passed=bool(inner.get("staticGatePassed", inner.get("static_gate_passed", False))),
            compile_ok=compile_ok,
            evidence_level=evidence,
            diagnostics=diagnostics,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "error_count": int(self.error_count),
            "warning_count": int(self.warning_count),
            "raw_api_receipt": self.raw_api_receipt,
            "static_gate_passed": bool(self.static_gate_passed),
            "compile_ok": bool(self.compile_ok),
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
            "diagnostics": [dict(x) for x in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompileReceipt:
        return cls(
            state=str(data.get("state") or ""),
            error_count=int(data.get("error_count") or 0),
            warning_count=int(data.get("warning_count") or 0),
            raw_api_receipt=str(data.get("raw_api_receipt") or ""),
            static_gate_passed=bool(data.get("static_gate_passed", False)),
            compile_ok=bool(data.get("compile_ok", False)),
            evidence_level=EvidenceLevel.parse(data.get("evidence_level")),
            diagnostics=[dict(x) for x in (data.get("diagnostics") or []) if isinstance(x, dict)],
        )


@dataclass
class NativeTiaArtifact:
    """A real, exactly-bound native TIA archive (never a source ZIP)."""

    artifact_id: str = ""
    job_id: str = ""
    project_id: str = ""
    project_path: str = ""
    archive_path: str = ""
    archive_sha256: str = ""
    size_bytes: int = 0
    kind: str = "zap19"
    compile: CompileReceipt = field(default_factory=CompileReceipt)
    evidence_id: str = ""
    evidence_level: EvidenceLevel = EvidenceLevel.PENDING_REAL_MACHINE
    reopen_ok: bool = False
    receipt: dict[str, Any] = field(default_factory=dict)

    def is_native_archived(self) -> bool:
        """Q-06: only a real compile + reopen + hash may claim archived state."""
        return bool(
            self.reopen_ok
            and self.compile.compile_ok
            and self.compile.error_count == 0
            and self.archive_sha256.startswith("sha256:")
            and self.archive_path
            and self.evidence_level is EvidenceLevel.V19_REAL
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "job_id": self.job_id,
            "project_id": self.project_id,
            "project_path": self.project_path,
            "archive_path": self.archive_path,
            "archive_sha256": self.archive_sha256,
            "size_bytes": int(self.size_bytes),
            "kind": self.kind,
            "compile": self.compile.to_dict(),
            "evidence_id": self.evidence_id,
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
            "reopen_ok": bool(self.reopen_ok),
            "receipt": dict(self.receipt),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NativeTiaArtifact:
        return cls(
            artifact_id=str(data.get("artifact_id") or ""),
            job_id=str(data.get("job_id") or ""),
            project_id=str(data.get("project_id") or ""),
            project_path=str(data.get("project_path") or ""),
            archive_path=str(data.get("archive_path") or ""),
            archive_sha256=str(data.get("archive_sha256") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
            kind=str(data.get("kind") or "zap19"),
            compile=CompileReceipt.from_dict(data.get("compile") or {}),
            evidence_id=str(data.get("evidence_id") or ""),
            evidence_level=EvidenceLevel.parse(data.get("evidence_level")),
            reopen_ok=bool(data.get("reopen_ok", False)),
            receipt=dict(data.get("receipt") or {}),
        )


@dataclass
class DerivedBundle:
    """All one-way projections computed from a frozen IR."""

    ir_sha256: str = ""
    device_graph: dict[str, Any] = field(default_factory=dict)
    mermaid: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    trace_scenarios: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    scl_files: dict[str, str] = field(default_factory=dict)
    source_map: SourceMap = field(default_factory=SourceMap)
    manifest: ArtifactManifest = field(default_factory=ArtifactManifest)
    validation: ValidationReport = field(default_factory=ValidationReport)
    evidence_level: EvidenceLevel = EvidenceLevel.OFFLINE
    notice: str = "offline prediction, not a real machine verification"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ir_sha256": self.ir_sha256,
            "device_graph": self.device_graph,
            "mermaid": self.mermaid,
            "trace": self.trace,
            "trace_scenarios": self.trace_scenarios,
            "scl_files": dict(self.scl_files),
            "source_map": self.source_map.to_dict(),
            "manifest": self.manifest.to_dict(include_content=False),
            "validation": self.validation.to_dict(),
            "evidence_level": self.evidence_level.value if isinstance(self.evidence_level, EvidenceLevel) else str(self.evidence_level),
            "notice": self.notice,
        }


def new_project_ir(project_id: str, *, origin: str = "greenfield") -> EngineeringIRV2:
    """Build a fresh, deterministic IR for a new project (revision 0)."""
    ir = EngineeringIRV2(project_id=project_id, schema_version=SCHEMA_VERSION, revision=0)
    ir.spec_meta = {"origin": origin, "stage": "DRAFT", "spec_version": "v0"}
    ir.views = {"layout": {}, "projection_version": "v2-view-1.0"}
    ir.refresh_hash()
    return ir


def evidence_tag_to_dict(tag: EvidenceTag) -> dict[str, Any]:
    """Convenience helper for API responses."""
    return tag.to_dict()


__all__ = [
    "AFProfile",
    "Action",
    "ArtifactFile",
    "ArtifactManifest",
    "CandidatePatch",
    "ChangeOp",
    "ChangeSet",
    "CompileReceipt",
    "ComponentDefinition",
    "DerivedBundle",
    "DriverSpec",
    "EngineeringIRV2",
    "EvidenceLevel",
    "EvidenceTag",
    "GuardAST",
    "HardwareIntent",
    "ImportedSnapshot",
    "NativeTiaArtifact",
    "PatchResultV2",
    "ProjectWorkspace",
    "SequenceIR",
    "SourceBinding",
    "SourceMap",
    "SourceMapping",
    "Step",
    "TiaCapabilityManifest",
    "Transition",
    "TypedPort",
    "ValidationReport",
    "evidence_tag_to_dict",
    "new_project_ir",
    "sha256_prefixed",
]
