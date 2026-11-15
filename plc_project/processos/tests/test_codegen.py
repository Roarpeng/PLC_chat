"""WS3 codegen golden tests — executable SCL, SourceMap, coverage assertions."""
from __future__ import annotations

from processos.backends import lower
from processos.codegen import expected_from_sequence, generate
from processos.codegen.coverage import CoverageCounter
from processos.contract import clamp_contract
from processos.frameworks import register_hr001_af_v19


def _generated():
    profile = register_hr001_af_v19()
    contract = clamp_contract()
    project = lower(contract, profile)
    return generate(project, profile), contract


def test_scl_is_executable_not_comments():
    gen, _ = _generated()
    seq = next(v for k, v in gen.files.items() if k.endswith("_SEQ.scl"))
    assert "Extend := TRUE" in seq
    assert "Retract := TRUE" in seq
    assert "T#3000ms" in seq
    assert "T#2000ms" in seq
    assert "CASE #Step OF" in seq
    assert "TON_TIME" in seq
    assert "#Reset AND #Retracted AND NOT #Extended" in seq
    assert "// action" not in seq and "// guard" not in seq
    assert "TON_S_EXTEND(IN := NOT #Extended" in seq
    assert "TON_S_RETRACT(IN := NOT #Retracted" in seq


def test_coverage_assertions_pass():
    gen, contract = _generated()
    assert gen.coverage_assertions_passed
    seq = contract.operations[0].steps
    exp = expected_from_sequence([s.to_dict() for s in seq])
    assert gen.coverage["lowered_steps"] >= exp["steps"]
    assert gen.coverage["lowered_actions"] >= exp["actions"]
    assert gen.coverage["lowered_timers"] >= exp["timers"]


def test_source_map_maps_to_step():
    gen, _ = _generated()
    assert gen.source_map
    nodes = {m["node"] for m in gen.source_map}
    assert "S_EXTEND" in nodes
    extend_lines = [m for m in gen.source_map if m["node"] == "S_EXTEND"]
    assert all(m["line"] > 0 for m in extend_lines)


def test_hold_duration_change_reflected():
    profile = register_hr001_af_v19()
    contract = clamp_contract()
    contract.operations[0].step("S_HOLD").duration_ms = 4000
    gen = generate(lower(contract, profile), profile)
    seq = next(v for k, v in gen.files.items() if k.endswith("_SEQ.scl"))
    assert "T#4000ms" in seq
    assert "T#2000ms" not in seq


def test_ob_main_not_excluded():
    gen, _ = _generated()
    assert "OB_Main.scl" in gen.files
    assert "END_ORGANIZATION_BLOCK" in gen.files["OB_Main.scl"]


def test_driver_single_writer_arbitration():
    gen, _ = _generated()
    drv = next(v for k, v in gen.files.items() if k.endswith("_DRV.scl"))
    assert "AND NOT #CmdRetract" in drv
    assert "#Extended AND #Retracted" in drv


def test_manifest_hash_deterministic():
    g1, _ = _generated()
    g2, _ = _generated()
    assert g1.manifest_hash == g2.manifest_hash
    assert g1.manifest_hash.startswith("sha256:")


def test_coverage_fails_when_under_lowered():
    seq = [s.to_dict() for s in clamp_contract().operations[0].steps]
    exp = expected_from_sequence(seq)
    under = CoverageCounter(steps=exp["steps"], actions=0, guards=0, timers=0)
    lowered = under.as_dict()
    passed = all(lowered[k] >= exp[k] for k in exp)
    assert not passed