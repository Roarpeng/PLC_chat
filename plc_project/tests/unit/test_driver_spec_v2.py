"""G2: typed ports, Driver FSM, SafetyPermit arbitration, reverse interlock."""
from __future__ import annotations

from plc_engine.components.catalog import DriverCatalog
from plc_engine.components.driver_fsm import DriverMode, DriverState, arbitrate_mode
from plc_engine.components.driver_fsm import DriverFSM
from plc_engine.components.driver_spec import PortDataType, PortRole


def make_fsm(timeout_ms: int = 100):
    catalog = DriverCatalog()
    spec = catalog.create_spec("double_acting_cylinder", overrides={"move_timeout_ms": timeout_ms})
    return DriverFSM(spec, "CM1"), spec


def test_typed_ports_are_complete_and_unbound() -> None:
    _, spec = make_fsm()
    assert spec.required_ports()
    assert {"CmdExtend", "CmdRetract", "SafetyPermit", "SensorOut", "SensorIn"}.issubset(spec.typed_ports)
    assert spec.typed_ports["CmdExtend"].data_type is PortDataType.BOOL
    assert spec.typed_ports["SafetyPermit"].role is PortRole.SAFETY
    assert spec.bound_addresses() == {}
    assert spec.assert_no_fictional_address() == []


def test_driver_fsm_happy_cycle() -> None:
    fsm, _ = make_fsm()
    assert fsm.step(auto_extend=True, sensor_out=False).state is DriverState.EXTENDING
    assert fsm.step(auto_extend=True, sensor_out=True).state is DriverState.EXTENDED
    assert fsm.step(auto_retract=True).state is DriverState.RETRACTING
    assert fsm.step(auto_retract=True, sensor_in=True).state is DriverState.RETRACTED
    assert fsm.runtime.q_extend is False or fsm.runtime.q_retract is False  # never both


def test_extend_timeout_enters_fault_and_requires_reset() -> None:
    fsm, _ = make_fsm(timeout_ms=30)
    fsm.step(auto_extend=True)
    for _ in range(5):
        runtime = fsm.step(auto_extend=True)
    assert runtime.state is DriverState.FAULT
    assert runtime.error_id == "EXTEND_TIMEOUT"
    assert fsm.step(reset=True).state is DriverState.IDLE
    assert fsm.runtime.error_id == ""


def test_retract_timeout_enters_fault() -> None:
    fsm, _ = make_fsm(timeout_ms=30)
    fsm.step(auto_extend=True)                       # IDLE -> EXTENDING
    fsm.step(auto_extend=True, sensor_out=True)      # EXTENDING -> EXTENDED
    fsm.step(auto_retract=True)                      # EXTENDED -> RETRACTING
    for _ in range(5):
        runtime = fsm.step(auto_retract=True)
    assert runtime.state is DriverState.FAULT
    assert runtime.error_id == "RETRACT_TIMEOUT"


def test_safety_permit_is_the_sole_gate() -> None:
    assert arbitrate_mode(auto_extend=True, auto_retract=False, manual_extend=False,
                          manual_retract=False, mode=DriverMode.AUTO,
                          safety_permit=False) == (False, False)
    fsm, _ = make_fsm(timeout_ms=1000)
    fsm.step(auto_extend=True, safety_permit=True)
    runtime = fsm.step(auto_extend=True, safety_permit=False)
    assert runtime.state is DriverState.FAULT
    assert runtime.error_id == "SAFETY_PERMIT_LOST"
    assert runtime.q_extend is False and runtime.q_retract is False


def test_manual_auto_arbitration_is_unique() -> None:
    assert arbitrate_mode(auto_extend=False, auto_retract=False, manual_extend=True,
                          manual_retract=False, mode=DriverMode.MANUAL,
                          safety_permit=True) == (True, False)
    assert arbitrate_mode(auto_extend=True, auto_retract=False, manual_extend=False,
                          manual_retract=False, mode=DriverMode.MANUAL,
                          safety_permit=True) == (False, False)


def test_reverse_outputs_are_never_both_true() -> None:
    assert arbitrate_mode(auto_extend=True, auto_retract=True, manual_extend=False,
                          manual_retract=False, mode=DriverMode.AUTO,
                          safety_permit=True) == (False, False)
    fsm, _ = make_fsm()
    runtime = fsm.step(auto_extend=True, auto_retract=True)
    assert not (runtime.q_extend and runtime.q_retract)
