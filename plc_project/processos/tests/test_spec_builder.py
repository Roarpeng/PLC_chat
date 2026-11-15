"""Spec-builder + from-spec route tests (wizard §b step orchestration).

Fail-closed contract: every dangling step reference / off-contract command /
empty step list / unknown resource must surface as 422 {error}; a valid spec
lowers to the same contract shape from-hardware produces.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api import ProjectStore
from processos.api.spec_routes import register_routes
from processos.contract import ProcessContract
from processos.spec_builder import build_contract_from_spec


@pytest.fixture()
def client():
    # bare app: the route module must work with just app.state.store attached
    app = FastAPI()
    app.state.store = ProjectStore()
    register_routes(app)
    return TestClient(app)


def _spec(**overrides):
    spec = {
        "id": "PRJ_SPEC1", "name": "装配站",
        "cpu": {"series": "S7-1500", "order_no": "6ES7511-1AK02-0AB0",
                "firmware": "V2.9", "label": "CPU 1511-1 PN"},
        "network": {"ip": "192.168.0.1", "subnet": "255.255.255.0", "device_name": "plc_1"},
        "devices": [
            {"type": "cylinder", "name": "夹紧气缸", "id": "CM_CLAMP",
             "params": {"timeout_ms": 3000, "hold_ms": 2000}},
            {"type": "sensor", "name": "到位检测", "id": "CM_SENSE", "params": {}},
        ],
        "operations": [{
            "em": "EM_CLAMP", "name": "夹紧与检测",
            "resource_ids": ["CM_CLAMP", "CM_SENSE"],
            "steps": [
                {"id": "S_CLOSE", "name": "夹紧", "guard": {"signal": "Extended", "op": "==", "value": True},
                 "actions": [{"command": "Extend"}], "timeout_ms": 3000,
                 "failure_target": "S_FAULT", "next": "S_CHECK"},
                {"id": "S_CHECK", "name": "检测", "guard": {"signal": "Detected", "op": "==", "value": True},
                 "actions": [], "timeout_ms": 2000, "next": ""},
                {"id": "S_FAULT", "name": "故障保持", "actions": [], "next": ""},
            ],
        }],
        "invariants": [{"id": "INV_ORDER", "expr": "NOT (Extended AND Detected)", "scope": "global", "severity": "warning"}],
    }
    spec.update(overrides)
    return spec


def _step(spec, **patch):
    step = {**spec["operations"][0]["steps"][0], **patch}
    return {**spec, "operations": [{**spec["operations"][0], "steps": [step, *spec["operations"][0]["steps"][1:]]}]}


# ---------- builder ----------

def test_full_spec_builds_contract_structure():
    contract = ProcessContract.from_dict(build_contract_from_spec(_spec()))
    assert contract.id == "PRJ_SPEC1"
    assert [r.id for r in contract.resources] == ["CM_CLAMP", "CM_SENSE"]
    clamp = contract.resource("CM_CLAMP")
    assert clamp.commands == ["Extend", "Retract"]           # type contract reused
    assert clamp.feedback == ["Extended", "Retracted"]
    assert clamp.io_bindings == {"Extended": "unbound", "Retracted": "unbound"}
    op = contract.operations[0]
    assert op.id == "OP_EM_CLAMP" and op.em == "EM_CLAMP"
    assert op.resource_ids == ["CM_CLAMP", "CM_SENSE"]
    assert [s.id for s in op.steps] == ["S_CLOSE", "S_CHECK", "S_FAULT"]
    close = op.steps[0]
    assert close.guard == "Extended"
    assert [a.to_dict() for a in close.entry] == [{"target": "CM_CLAMP", "command": "Extend", "value": True}]
    assert [a.to_dict() for a in close.exit] == [{"target": "CM_CLAMP", "command": "Extend", "value": False}]
    assert close.timeout_ms == 3000 and close.failure_target == "S_FAULT" and close.next == "S_CHECK"
    assert op.steps[1].guard == "Detected"                    # value honoured
    inv = {i.id: i for i in contract.invariants}
    assert "INV_CM_CLAMP" in inv                              # cylinder conflict auto-derived
    assert "INV_ORDER" in inv and inv["INV_ORDER"].severity == "warning"
    assert contract.scenarios == []                           # honest: nothing synthesized
    assert contract.validate_structure() == []
    assert contract.provenance.origin == "explicit-spec"


def test_guard_false_value_negates_signal():
    spec = _step(_spec(), guard={"signal": "Extended", "op": "==", "value": False})
    contract = ProcessContract.from_dict(build_contract_from_spec(spec))
    assert contract.operations[0].steps[0].guard == "NOT Extended"


def test_timeout_defaults_to_zero_when_absent():
    spec = _step(_spec())
    spec["operations"][0]["steps"][0].pop("timeout_ms")
    contract = ProcessContract.from_dict(build_contract_from_spec(spec))
    assert contract.operations[0].steps[0].timeout_ms == 0


@pytest.mark.parametrize("patch", [
    {"next": "S_GONE"},                                       # dangling next
    {"failure_target": "S_GONE"},                             # dangling failure_target
    {"actions": [{"command": "Vibrate"}]},                    # off-contract command
    {"timeout_ms": 0},                                        # non-positive timeout
    {"timeout_ms": -5},
    {"guard": {"signal": "Extended", "op": "!=", "value": True}},   # bad op
    {"guard": {"signal": "Extended", "op": "==", "value": 1}},      # non-bool value
    {"guard": {"signal": "", "op": "==", "value": True}},           # empty signal
])
def test_invalid_steps_raise_value_error(patch):
    with pytest.raises(ValueError):
        build_contract_from_spec(_step(_spec(), **patch))


def test_empty_steps_rejected():
    spec = _spec()
    spec["operations"][0]["steps"] = []
    with pytest.raises(ValueError):
        build_contract_from_spec(spec)


def test_unknown_resource_reference_rejected():
    spec = _spec()
    spec["operations"][0]["resource_ids"] = ["CM_NOPE"]
    with pytest.raises(ValueError, match="CM_NOPE"):
        build_contract_from_spec(spec)


def test_empty_resource_ids_rejected():
    spec = _spec()
    spec["operations"][0]["resource_ids"] = []
    with pytest.raises(ValueError):
        build_contract_from_spec(spec)


def test_ambiguous_command_between_resources_rejected():
    spec = _spec()
    spec["devices"].append({"type": "cylinder", "name": "第二气缸", "id": "CM_CLAMP2", "params": {}})
    spec["operations"][0]["resource_ids"] = ["CM_CLAMP", "CM_CLAMP2"]
    with pytest.raises(ValueError, match="ambiguous"):
        build_contract_from_spec(spec)


def test_duplicate_step_device_operation_ids_rejected():
    spec = _spec()
    spec["operations"][0]["steps"][1] = {**spec["operations"][0]["steps"][1], "id": "S_CLOSE"}
    with pytest.raises(ValueError, match="duplicate step"):
        build_contract_from_spec(spec)
    spec2 = _spec()
    spec2["devices"][1] = {**spec2["devices"][1], "id": "CM_CLAMP"}
    with pytest.raises(ValueError, match="duplicate device"):
        build_contract_from_spec(spec2)
    spec3 = _spec()
    spec3["operations"].append({**spec3["operations"][0]})
    with pytest.raises(ValueError, match="duplicate operation"):
        build_contract_from_spec(spec3)


def test_unknown_device_type_rejected():
    spec = _spec()
    spec["devices"][1] = {"type": "phaser", "name": "X", "id": "CM_X", "params": {}}
    with pytest.raises(ValueError, match="unknown device type"):
        build_contract_from_spec(spec)


def test_spec_invariant_validation():
    base = _spec()
    dup = _spec()
    dup["invariants"][0]["id"] = "INV_CM_CLAMP"               # collides with auto-derived
    with pytest.raises(ValueError, match="duplicate invariant"):
        build_contract_from_spec(dup)
    bad = _spec()
    bad["invariants"][0]["severity"] = "fatal"
    with pytest.raises(ValueError, match="severity"):
        build_contract_from_spec(bad)
    assert build_contract_from_spec(base)                     # sane baseline still passes


def test_at_least_one_device_and_operation():
    spec = _spec()
    spec["devices"] = []
    with pytest.raises(ValueError):
        build_contract_from_spec(spec)
    spec = _spec()
    spec["operations"] = []
    with pytest.raises(ValueError):
        build_contract_from_spec(spec)


# ---------- route (bare FastAPI + app.state.store) ----------

def test_route_creates_project_from_spec(client):
    r = client.post("/api/processos/projects/from-spec", json=_spec())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == "PRJ_SPEC1" and body["revision"] == 1
    assert body["contract"]["operations"][0]["steps"][0]["id"] == "S_CLOSE"
    assert "PRJ_SPEC1" in client.app.state.store.projects


def test_route_assigns_project_id_when_missing(client):
    spec = _spec()
    spec.pop("id")
    r = client.post("/api/processos/projects/from-spec", json=spec)
    assert r.status_code == 200
    assert r.json()["project_id"].startswith("PRJ_")


@pytest.mark.parametrize("patch", [
    {"next": "S_GONE"},
    {"actions": [{"command": "Vibrate"}]},
    {"timeout_ms": 0},
])
def test_route_maps_validation_errors_to_422(client, patch):
    r = client.post("/api/processos/projects/from-spec", json=_step(_spec(), **patch))
    assert r.status_code == 422
    assert isinstance(r.json()["error"], str) and r.json()["error"]


def test_route_empty_steps_422(client):
    spec = _spec()
    spec["operations"][0]["steps"] = []
    r = client.post("/api/processos/projects/from-spec", json=spec)
    assert r.status_code == 422
    assert "step" in r.json()["error"]


def test_route_unknown_resource_422(client):
    spec = _spec()
    spec["operations"][0]["resource_ids"] = ["CM_NOPE"]
    r = client.post("/api/processos/projects/from-spec", json=spec)
    assert r.status_code == 422


def test_register_routes_is_idempotent():
    app = FastAPI()
    app.state.store = ProjectStore()
    register_routes(app)
    register_routes(app)
    paths = [r.path for r in app.routes if getattr(r, "path", "") == "/api/processos/projects/from-spec"]
    assert len(paths) == 1
