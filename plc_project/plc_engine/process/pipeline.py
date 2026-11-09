"""One-way derivation pipeline: frozen IR -> all projections (design 4.1).

Mermaid / DeviceGraph / Trace / SCL / SourceMap are pure functions of the IR.
Nothing here ever writes back to the IR; the frontend only holds view state.
"""
from __future__ import annotations

from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import DerivedBundle, EngineeringIRV2
from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.process.scan_simulator import ScanSimulator, build_standard_scenarios
from plc_engine.process.scl_lowering import CompilerService


def derive_bundle(ir: EngineeringIRV2) -> DerivedBundle:
    """Recompute every derived artifact for one frozen IR."""
    ir_hash = ir.ir_sha256 or ir.semantic_hash()
    validation = ValidationEngine().validate(ir)
    manifest, source_map = CompilerService(ir.af_profile).lower(ir)
    scl_files = {file.path: file.content for file in sorted(manifest.files, key=lambda f: f.path)}

    simulator = ScanSimulator()
    scenarios = build_standard_scenarios()
    normal = scenarios["normal_cycle"]
    trace = [frame.to_dict() for frame in simulator.run(ir, normal)]
    trace_scenarios = {
        name: [frame.to_dict() for frame in simulator.run(ir, scenario)]
        for name, scenario in sorted(scenarios.items())
    }
    return DerivedBundle(
        ir_sha256=ir_hash,
        device_graph=ir.device_graph(),
        mermaid=ir.mermaid(),
        trace=trace,
        trace_scenarios=trace_scenarios,
        scl_files=scl_files,
        source_map=source_map,
        manifest=manifest,
        validation=validation,
        evidence_level=EvidenceLevel.OFFLINE,
        notice="offline prediction, not a real machine verification; Trace = 预测，不是实机验证",
    )
