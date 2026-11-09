"""G3 / blueprint A5: deterministic offline Trace, five scenarios, golden snapshot."""
from __future__ import annotations

import json
from pathlib import Path

from plc_engine.engineering_ir.contracts import SCAN_ORDER
from plc_engine.process.scan_simulator import (
    NOTICE,
    ScanSimulator,
    build_standard_scenarios,
)
from tests.v2_fixtures import build_valid_demo_ir

GOLDEN = Path(__file__).resolve().parents[1] / "snapshots" / "v2" / "trace_scenarios.golden.json"


def test_five_scenarios_match_golden_snapshot() -> None:
    ir = build_valid_demo_ir()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    simulator = ScanSimulator()
    assert sorted(build_standard_scenarios()) == sorted(golden["scenarios"])
    for name, scenario in sorted(build_standard_scenarios().items()):
        frames = simulator.run(ir, scenario)
        expected = golden["scenarios"][name]
        assert len(frames) == expected["frames"], name
        assert frames[-1].active_step == expected["last_step"], name
        assert frames[0].active_step == expected["first_step"], name
        assert frames[-1].alarms == expected["alarms"], name
        assert frames[-1].evidence_level == "offline"
        assert frames[-1].data_source == "offline_model"


def test_trace_is_deterministic() -> None:
    ir = build_valid_demo_ir()
    simulator = ScanSimulator()
    scenario = build_standard_scenarios()["normal_cycle"]
    first = [frame.to_dict() for frame in simulator.run(ir, scenario)]
    second = [frame.to_dict() for frame in simulator.run(ir, scenario)]
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_trace_is_labelled_prediction_not_real_machine() -> None:
    ir = build_valid_demo_ir()
    frame = ScanSimulator().run(ir, build_standard_scenarios()["normal_cycle"])[0]
    assert frame.evidence_level == "offline"
    assert "预测" in frame.notice and "不是实机验证" in frame.notice
    assert frame.data_source == "offline_model"
    assert "非在线 PLC 波形" in NOTICE


def test_trace_frames_have_all_documented_fields() -> None:
    ir = build_valid_demo_ir()
    frame = ScanSimulator().run(ir, build_standard_scenarios()["extend_timeout"])[-1].to_dict()
    for key in ("cycle", "time_ms", "active_step", "conditions", "actions",
                "driver_states", "outputs", "alarms", "source_map_refs",
                "evidence_level", "data_source", "notice"):
        assert key in frame


def test_extend_timeout_reaches_fault_with_alarm() -> None:
    ir = build_valid_demo_ir()
    frames = ScanSimulator().run(ir, build_standard_scenarios()["extend_timeout"])
    assert frames[-1].active_step == "FAULT"
    assert any("EXTEND_TIMEOUT" in a for a in frames[-1].alarms)
    assert any("timeout" in a.lower() for a in frames[-1].alarms)


def test_safety_permit_loss_inhibits_commands() -> None:
    ir = build_valid_demo_ir()
    frames = ScanSimulator().run(ir, build_standard_scenarios()["safety_permit_lost"])
    assert frames[-1].active_step == "FAULT"
    assert any("safety_permit_lost" in a for a in frames[-1].alarms)
    assert all(not value for value in frames[-1].outputs.values())


def test_scan_order_is_fixed_and_documented() -> None:
    simulator = ScanSimulator()
    assert simulator.scan_order() == SCAN_ORDER
    assert simulator.scan_order()[0] == "FREEZE_INPUT_SNAPSHOT"
    assert simulator.scan_order()[-1] == "EMIT_OUTPUTS_AND_ALARMS"


def test_shortest_counterexample_is_not_a_bare_failure_message() -> None:
    ir = build_valid_demo_ir()
    path = ScanSimulator().shortest_counterexample(ir)
    assert path == ["S0", "FAULT"]


def test_hold_1s_to_2s_changes_trace() -> None:
    ir = build_valid_demo_ir()
    simulator = ScanSimulator()
    scenario = build_standard_scenarios()["normal_cycle"]
    before = [f.to_dict() for f in simulator.run(ir, scenario)]
    ir.process.step_index()["S2"].min_duration_ms = 2000
    ir.refresh_hash()
    after = [f.to_dict() for f in simulator.run(ir, scenario)]
    assert before != after
