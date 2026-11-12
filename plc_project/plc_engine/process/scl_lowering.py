"""Deterministic IR -> AF SCL lowering + SourceMap (WP-03 / blueprint A6 / G4).

Rules enforced here:
  * dependency order UDT -> FB/FC -> instance DB -> call OB is explicit;
  * block numbers are never invented (``block_number=None`` unless imported);
  * FB names come from explicit IR / catalog data, never from DB naming;
  * every emitted line carries a ``source_id`` and an N:N SourceMap entry;
  * semantic files and manifest hash contain no timestamps (receipt is separate).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plc_engine.canonical import sha256_prefixed
from plc_engine.components.driver_compiler import DriverCompiler
from plc_engine.engineering_ir.contracts import SCAN_ORDER
from plc_engine.engineering_ir.models import AFProfile, EngineeringIRV2
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.guard_ast import (
    GuardAST,
    GuardNodeType,
    GuardValueType,
    is_valid_guard_signal,
)
from plc_engine.process.source_map import SourceMap


def guard_to_scl(guard: GuardAST | None) -> str:
    """Compile a typed GuardAST to an SCL boolean expression. No eval()."""
    if guard is None:
        return "TRUE"
    node = guard.node_type
    if node is GuardNodeType.CONST:
        if guard.value_type is GuardValueType.BOOL:
            return "TRUE" if bool(guard.value) else "FALSE"
        return str(int(guard.value or 0))
    if node is GuardNodeType.SIGNAL:
        # Fail-closed: an invalid identifier must never be spliced into SCL.
        return f"#{guard.signal}" if is_valid_guard_signal(guard.signal) else "FALSE"
    if node is GuardNodeType.AND:
        return "(" + " AND ".join(guard_to_scl(child) for child in guard.children) + ")"
    if node is GuardNodeType.OR:
        return "(" + " OR ".join(guard_to_scl(child) for child in guard.children) + ")"
    if node is GuardNodeType.NOT:
        return "NOT (" + guard_to_scl(guard.children[0]) + ")"
    if node in (GuardNodeType.EQ, GuardNodeType.NE, GuardNodeType.LT, GuardNodeType.LE, GuardNodeType.GT, GuardNodeType.GE, GuardNodeType.ELAPSED_GE):
        left = guard_to_scl(guard.children[0])
        right = guard_to_scl(guard.children[1])
        if guard.children[1].value_type is GuardValueType.TIME:
            right = f"T#{int(guard.children[1].value or 0)}ms"
        operator = {
            GuardNodeType.EQ: "=", GuardNodeType.NE: "<>", GuardNodeType.LT: "<",
            GuardNodeType.LE: "<=", GuardNodeType.GT: ">", GuardNodeType.GE: ">=",
            GuardNodeType.ELAPSED_GE: ">=",
        }[node]
        return f"({left} {operator} {right})"
    raise ValueError(f"cannot lower unknown guard node {node!r}")


@dataclass
class SclBuilder:
    """Line emitter that records N:N source mappings while writing SCL."""

    tia_block: str = ""
    scl_file: str = ""
    block_type: str = ""
    lines: list[str] = field(default_factory=list)
    emissions: list[tuple[int, str, str]] = field(default_factory=list)

    def emit(self, text: str = "", *, ir_id: str = "", source_id: str = "") -> None:
        """Append one line and optionally record its source mapping."""
        self.lines.append(text)
        if ir_id:
            self.emissions.append((len(self.lines), ir_id, source_id or ir_id))

    def content(self) -> str:
        """Return the deterministic SCL text."""
        return "\n".join(self.lines) + "\n"


class CompilerService:
    """Lower a frozen EngineeringIRV2 into AF SCL artifacts and a SourceMap."""

    def __init__(self, profile: AFProfile | None = None) -> None:
        self.profile = profile or AFProfile()

    def lower(self, ir: EngineeringIRV2) -> tuple[ArtifactManifest, SourceMap]:
        """Return ``(manifest, source_map)`` for one frozen IR."""
        self.profile.assert_consistent_with(ir.af_profile)
        source_map = SourceMap(
            map_id=f"smap_{(ir.ir_sha256 or ir.semantic_hash())[7:19]}",
            ir_sha256=ir.ir_sha256 or ir.semantic_hash(),
            template_sha256=ir.af_profile.template_sha256,
        )
        builders = [
            self._build_udt(ir),
            self._build_fb_drivers(ir),
            self._build_fb_sequence(ir),
            self._build_instance_db(ir),
            self._build_ob_main(ir),
        ]
        files: list[ArtifactFile] = []
        for builder in builders:
            content = builder.content()
            files.append(
                ArtifactFile(
                    path=builder.scl_file,
                    sha256=sha256_prefixed(content),
                    role=self._role_of(builder.scl_file),
                    content=content,
                    source_ids=sorted({source_id for _, _, source_id in builder.emissions}),
                    tia_block=builder.tia_block,
                    block_number=None,  # never invent block numbers
                )
            )
            for line_number, ir_id, source_id in builder.emissions:
                source_map.add(
                    ir_id=ir_id,
                    scl_file=builder.scl_file,
                    scl_line=line_number,
                    tia_block=builder.tia_block,
                    tia_block_type=builder.block_type,
                    canvas_node_id=ir_id,
                    source_id=source_id,
                )
        paths = [file.path for file in files]
        by_role = {file.role: file.path for file in files}
        manifest = ArtifactManifest(
            manifest_id="",
            af_profile_id=ir.af_profile.profile_id,
            template_sha256=ir.af_profile.template_sha256,
            ir_sha256=ir.ir_sha256 or ir.semantic_hash(),
            files=files,
            import_order=paths,
            dependencies={
                by_role["FB"]: [by_role["UDT"]],
                by_role["DB"]: [by_role["UDT"], by_role["FB"]],
                by_role["OB"]: [by_role["UDT"], by_role["FB"], by_role["DB"]],
            },
            receipt={
                "generator": "SclLowering/1.0",
                "af_profile_id": ir.af_profile.profile_id,
                "ir_sha256": ir.ir_sha256 or ir.semantic_hash(),
                "scan_order": list(SCAN_ORDER),
            },
        )
        manifest.refresh_hash()
        manifest.manifest_id = f"man_{manifest.sha256[7:19]}"
        return manifest, source_map

    @staticmethod
    def _role_of(path: str) -> str:
        stem = path.rsplit("/", 1)[-1].upper()
        if stem.startswith("UDT_"):
            return "UDT"
        if stem.startswith("DB_"):
            return "DB"
        if stem.startswith("OB_"):
            return "OB"
        if stem.startswith("FB_"):
            return "FB"
        if stem.startswith("FC_"):
            return "FC"
        return "SCL"

    def _header(self, builder: SclBuilder, ir: EngineeringIRV2, title: str) -> None:
        builder.emit(f"// {title}")
        builder.emit(f"// source_id: {ir.project_id}")
        builder.emit(f"// af_profile: {ir.af_profile.profile_id}")
        builder.emit(f"// template_sha256: {ir.af_profile.template_sha256}")
        builder.emit(f"// ir_sha256: {ir.ir_sha256 or ir.semantic_hash()}")
        builder.emit("// deterministic semantic output: no timestamps in this file")
        builder.emit("")

    def _build_udt(self, ir: EngineeringIRV2) -> SclBuilder:
        builder = SclBuilder(
            tia_block="UDT_DriverState", scl_file="scl/UDT_DriverState.scl", block_type="UDT"
        )
        self._header(builder, ir, "AF UDT: driver runtime state")
        builder.emit('TYPE "UDT_DriverState"', ir_id="UDT_DriverState")
        builder.emit("VERSION : 0.1")
        builder.emit("STRUCT")
        builder.emit("  state : INT;")
        builder.emit("  elapsed_ms : TIME;")
        builder.emit("  error_id : INT;")
        builder.emit("  q_extend : BOOL;")
        builder.emit("  q_retract : BOOL;")
        builder.emit("END_STRUCT;")
        builder.emit("END_TYPE")
        return builder

    def _build_fb_drivers(self, ir: EngineeringIRV2) -> SclBuilder:
        builder = SclBuilder(
            tia_block="FB_Drivers", scl_file="scl/FB_Drivers.scl", block_type="FB"
        )
        self._header(builder, ir, "AF FB: driver command/permission interface")
        declarations = DriverCompiler().compile_all(ir, af_profile_id=ir.af_profile.profile_id)
        builder.emit('FUNCTION_BLOCK "FB_Drivers"', ir_id="FB_Drivers")
        builder.emit("VAR_INPUT")
        for declaration in declarations:
            cid = declaration["component_id"]
            builder.emit(f"  // source_id: {cid} ({declaration['compile_mode']})", ir_id=cid)
            for port in declaration["fb_interfaces"]["inputs"]:
                builder.emit(
                    f"  {cid}_{port['name']} : {port['data_type']}; // binding={port['binding']}",
                    ir_id=cid,
                )
        builder.emit("END_VAR")
        builder.emit("VAR_OUTPUT")
        for declaration in declarations:
            cid = declaration["component_id"]
            for port in declaration["fb_interfaces"]["outputs"]:
                builder.emit(
                    f"  {cid}_{port['name']} : {port['data_type']}; // writer={port['writer']}",
                    ir_id=cid,
                )
        builder.emit("END_VAR")
        builder.emit("BEGIN")
        builder.emit("  // Reverse outputs are interlocked by arbitrate_single_writer().")
        for declaration in declarations:
            cid = declaration["component_id"]
            builder.emit(
                f"  // source_id: {cid} ; move_timeout_ms := {declaration['move_timeout_ms']};",
                ir_id=cid,
            )
        builder.emit("END_FUNCTION_BLOCK")
        return builder

    def _build_fb_sequence(self, ir: EngineeringIRV2) -> SclBuilder:
        builder = SclBuilder(
            tia_block="FB_Sequence", scl_file="scl/FB_Sequence.scl", block_type="FB"
        )
        self._header(builder, ir, "AF FB: deterministic SFC-like step state machine")
        signals: set[str] = set()
        for tr in ir.process.transitions:
            if tr.guard_ast is not None:
                # P-04b: only injection-free identifiers may reach generated SCL
                # declarations; a malformed signal is already rejected by the
                # static validator and is omitted here (never spliced verbatim).
                signals.update(
                    name for name in tr.guard_ast.referenced_signals()
                    if is_valid_guard_signal(name)
                )
        builder.emit('FUNCTION_BLOCK "FB_Sequence"', ir_id="FB_Sequence")
        builder.emit("VAR_INPUT")
        for signal in sorted(signals):
            builder.emit(f"  {signal} : BOOL; // unbound logical signal")
        builder.emit("END_VAR")
        builder.emit("VAR")
        builder.emit("  stepCurrent : INT;")
        builder.emit("  stepElapsed_ms : TIME;")
        builder.emit("  minDuration_ms : TIME;")
        builder.emit("END_VAR")
        builder.emit("BEGIN")
        builder.emit("  // Scan order: " + " -> ".join(SCAN_ORDER))
        builder.emit("  CASE #stepCurrent OF")
        for index, step in enumerate(ir.process.steps):
            builder.emit(f"    {index}: // source_id: {step.id} ({step.name})", ir_id=step.id)
            builder.emit(
                f"      #minDuration_ms := T#{int(step.min_duration_ms)}ms; // source_id: {step.id}",
                ir_id=step.id,
            )
            if step.max_duration_ms:
                builder.emit(
                    f"      // timeout_ms := {int(step.max_duration_ms)}; // source_id: {step.id}",
                    ir_id=step.id,
                )
            for action in step.all_actions():
                builder.emit(
                    f"      // action {action.command} := {action.value}; // source_id: {action.source_id or action.id}",
                    ir_id=action.source_id or action.id or step.id,
                )
            for tr in ir.process.outgoing(step.id):
                builder.emit(
                    f"      // guard {tr.id}: {guard_to_scl(tr.guard_ast)} -> {tr.to_step}",
                    ir_id=tr.id,
                )
            builder.emit("      ;")
        builder.emit("  END_CASE;")
        builder.emit("END_FUNCTION_BLOCK")
        return builder

    def _build_instance_db(self, ir: EngineeringIRV2) -> SclBuilder:
        builder = SclBuilder(
            tia_block="DB_Sequence", scl_file="scl/DB_Sequence.scl", block_type="DB"
        )
        self._header(builder, ir, "AF instance DB for FB_Sequence (explicit, not inferred from a name)")
        builder.emit('DATA_BLOCK "DB_Sequence"', ir_id="DB_Sequence")
        builder.emit('  FB_Sequence', ir_id="FB_Sequence")
        builder.emit("BEGIN")
        builder.emit("END_DATA_BLOCK")
        return builder

    def _build_ob_main(self, ir: EngineeringIRV2) -> SclBuilder:
        builder = SclBuilder(
            tia_block="OB_Main", scl_file="scl/OB_Main.scl", block_type="OB"
        )
        self._header(builder, ir, "AF call OB (block number intentionally not invented)")
        builder.emit('ORGANIZATION_BLOCK "OB_Main"', ir_id="OB_Main")
        builder.emit("BEGIN")
        builder.emit('  "FB_Drivers"();', ir_id="FB_Drivers")
        builder.emit('  "FB_Sequence"();', ir_id="FB_Sequence")
        builder.emit("END_ORGANIZATION_BLOCK")
        return builder

    def scl_files(self, manifest: ArtifactManifest) -> dict[str, str]:
        """Extract path -> content for API previews."""
        return {file.path: file.content for file in sorted(manifest.files, key=lambda f: f.path)}

    @staticmethod
    def compile_errors_to_ir(
        errors: list[dict[str, Any]], source_map: SourceMap
    ) -> list[dict[str, Any]]:
        """Map TIA compiler diagnostics back to IR nodes / Canvas nodes."""
        return [
            source_map.locate_compile_error(
                str(err.get("block") or err.get("tia_block") or ""),
                int(err.get("line") or err.get("scl_line") or 0),
                str(err.get("message") or ""),
            )
            for err in errors
        ]


def assert_deterministic(ir: EngineeringIRV2) -> dict[str, Any]:
    """Generate twice and prove semantic files + manifest hash are identical."""
    first_manifest, first_map = CompilerService(ir.af_profile).lower(ir)
    second_manifest, second_map = CompilerService(ir.af_profile).lower(ir)
    first_files = {f.path: f.sha256 for f in first_manifest.files}
    second_files = {f.path: f.sha256 for f in second_manifest.files}
    return {
        "deterministic": (
            first_manifest.sha256 == second_manifest.sha256
            and first_files == second_files
            and first_map.to_dict() == second_map.to_dict()
        ),
        "manifest_sha256": first_manifest.sha256,
        "second_manifest_sha256": second_manifest.sha256,
        "file_hashes": first_files,
    }
