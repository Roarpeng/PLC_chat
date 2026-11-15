"""FC-03 tests: B1/B2/B3 baselines, two comparisons and the DriftGate (PLAN §4/§11).

Every SHA256 is really computed (§12: never fabricate checksums) and every
blocked path must surface the §11 SafetyError code over HTTP 409 — fail-closed,
never downgraded to a warning. Each service operation opens/closes its own
SQLite connection, so tmp_path cleanup never hits a held handle.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.store import ProjectStore
from processos.baselines import BaselineService, register_routes
from processos.contract import clamp_contract
from processos.safety import SafetyError

PID = "PRJ_CLAMP"
BASE = f"/api/processos/projects/{PID}/baselines"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def svc(tmp_path):
    return BaselineService(tmp_path / "baselines.sqlite3")


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())  # demo project PRJ_CLAMP
    app.state.baselines = BaselineService(tmp_path / "baselines.sqlite3")  # explicit tmp db
    register_routes(app)
    return TestClient(app)


def _record_full(service: BaselineService, *, archive: bytes = b"zap19-archive-v1") -> None:
    """B1 + B2 + field-verified B3 whose checksum matches the B2 archive."""
    service.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    service.record_b2(PID, "build_219", sha(archive),
                      {"FB_Clamp": sha(b"fb-clamp-v1"), "DB_Clamp": sha(b"db-clamp-v1")})
    service.record_b3(PID, "build_219", verification="FIELD_VERIFIED",
                      plc_checksum=sha(archive), device_id="PLC_1", operator="eng-1")


# ---------- 1. record B1/B2/B3 + compare MATCH -> OK_TO_PROCEED ----------

def test_match_ok_to_proceed_and_gate_passes(svc):
    b1 = svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1, profile_id="hr001_af_v19")
    assert (b1["kind"], b1["status"]) == ("B1", "FROZEN")
    b2 = svc.record_b2(PID, "build_219", sha(b"zap19-archive-v1"),
                       {"FB_Clamp": sha(b"fb-clamp-v1")})
    assert (b2["kind"], b2["status"]) == ("B2", "FROZEN")
    b3 = svc.record_b3(PID, "build_219", verification="FIELD_VERIFIED",
                       plc_checksum=sha(b"zap19-archive-v1"), device_id="PLC_1")
    assert (b3["kind"], b3["status"]) == ("B3", "VERIFIED")

    result = svc.compare(PID)
    assert result["verdict"] == "OK_TO_PROCEED"
    assert result["b2_vs_b3"] == "MATCH"
    assert result["differences"] == []
    assert result["latest_b1"]["spec_hash"] == b1["spec_hash"]
    assert result["latest_b2"]["archive_sha256"] == b2["archive_sha256"]
    assert result["latest_b3"]["deployed_build_id"] == "build_219"
    assert svc.plc_state_known(PID) is True

    gate = svc.gate_change(PID)
    assert gate["ok"] is True and gate["verdict"] == "OK_TO_PROCEED"


def test_http_happy_path_match_and_gate(client):
    arc = sha(b"zap19-archive-v1")
    r = client.post(f"{BASE}/b1", json={"spec_hash": "sha256:" + sha(b"spec-v1"), "revision": 2})
    assert r.status_code == 200 and r.json()["kind"] == "B1"
    r = client.post(f"{BASE}/b2", json={"build_id": "build_219", "archive_sha256": arc,
                                        "block_manifest": {"FB_Clamp": sha(b"fb-clamp-v1")}})
    assert r.status_code == 200 and r.json()["status"] == "FROZEN"
    r = client.post(f"{BASE}/b3", json={"deployed_build_id": "build_219",
                                        "verification": "FIELD_VERIFIED", "plc_checksum": arc,
                                        "device_id": "PLC_1", "operator": "eng-1"})
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED"

    listed = client.get(BASE).json()["baselines"]
    assert [b["kind"] for b in listed] == ["B1", "B2", "B3"]
    cmp = client.post(f"{BASE}/compare").json()
    assert (cmp["verdict"], cmp["b2_vs_b3"]) == ("OK_TO_PROCEED", "MATCH")
    gate = client.post(f"{BASE}/gate")
    assert gate.status_code == 200
    assert gate.json()["ok"] is True


# ---------- 2. tampered B3 checksum -> FROZEN_DRIFT / DRIFT_DETECTED 409 ----------

def test_tampered_checksum_is_frozen_drift_http_409(client):
    client.post(f"{BASE}/b1", json={"spec_hash": "sha256:" + sha(b"spec-v1"), "revision": 1})
    client.post(f"{BASE}/b2", json={"build_id": "build_219",
                                    "archive_sha256": sha(b"zap19-archive-v1"),
                                    "block_manifest": {"FB_Clamp": sha(b"fb-clamp-v1")}})
    # field reports a different (really computed) checksum: the PLC image was edited
    client.post(f"{BASE}/b3", json={"deployed_build_id": "build_219",
                                    "verification": "FIELD_VERIFIED",
                                    "plc_checksum": sha(b"field-edited-archive")})
    cmp = client.post(f"{BASE}/compare").json()
    assert cmp["verdict"] == "FROZEN_DRIFT"
    assert cmp["b2_vs_b3"] == "DRIFT"
    assert any(d["kind"] == "ARCHIVE_SHA256_MISMATCH" for d in cmp["differences"])

    gate = client.post(f"{BASE}/gate")
    assert gate.status_code == 409
    body = gate.json()
    assert body["code"] == "DRIFT_DETECTED"
    assert body["details"]["verdict"] == "FROZEN_DRIFT"
    assert body["error"]


# ---------- 3. SELF_REPORTED B3 -> UNVERIFIED_ONLINE / UNKNOWN_PLC_STATE ----------

def test_self_reported_b3_is_unverified_online(svc):
    svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    svc.record_b2(PID, "build_219", sha(b"zap19-archive-v1"), {})
    b3 = svc.record_b3(PID, "build_219", verification="SELF_REPORTED",
                       plc_checksum=sha(b"zap19-archive-v1"))
    assert b3["status"] == "UNVERIFIED_ONLINE"  # Build ID self-report is not verification
    assert svc.plc_state_known(PID) is False

    result = svc.compare(PID)
    assert result["verdict"] == "UNVERIFIED_ONLINE"
    assert result["b2_vs_b3"] == "UNKNOWN"
    with pytest.raises(SafetyError) as ei:
        svc.gate_change(PID)
    assert ei.value.code == "UNKNOWN_PLC_STATE"
    assert ei.value.http_status == 409
    assert ei.value.details["verdict"] == "UNVERIFIED_ONLINE"


def test_no_b3_at_all_blocks_gate(client):
    client.post(f"{BASE}/b1", json={"spec_hash": "sha256:" + sha(b"spec-v1"), "revision": 1})
    client.post(f"{BASE}/b2", json={"build_id": "build_219",
                                    "archive_sha256": sha(b"zap19-archive-v1"), "block_manifest": {}})
    gate = client.post(f"{BASE}/gate")
    assert gate.status_code == 409
    assert gate.json()["code"] == "UNKNOWN_PLC_STATE"


# ---------- 4. gate_delivery hash mismatch -> BUILD_ARTIFACT_MISMATCH 409 ----------

def test_gate_delivery_hash_mismatch_blocks(svc):
    svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    approved = "sha256:" + sha(b"approved-spec")
    built = "sha256:" + sha(b"build-input-spec")
    with pytest.raises(SafetyError) as ei:
        svc.gate_delivery(PID, approved, built)
    assert ei.value.code == "BUILD_ARTIFACT_MISMATCH"
    assert ei.value.http_status == 409
    assert ei.value.details["approved_spec_hash"] == approved
    assert ei.value.details["build_input_spec_hash"] == built
    assert svc.gate_delivery(PID, approved, approved)["ok"] is True


def test_gate_delivery_without_b1_blocks(svc):
    with pytest.raises(SafetyError) as ei:
        svc.gate_delivery(PID, "sha256:" + sha(b"s"), "sha256:" + sha(b"s"))
    assert ei.value.code == "DRIFT_DETECTED"
    assert ei.value.http_status == 409
    assert ei.value.details["reason"] == "missing B1"


# ---------- 5. persistence roundtrip ----------

def test_persistence_roundtrip_reads_records(tmp_path):
    db = tmp_path / "baselines.sqlite3"
    _record_full(BaselineService(db))  # connections are per-op: nothing stays open
    second = BaselineService(db)
    records = second.baselines(PID)
    assert [r["kind"] for r in records] == ["B1", "B2", "B3"]
    assert second.plc_state_known(PID) is True
    result = second.compare(PID)
    assert result["verdict"] == "OK_TO_PROCEED" and result["b2_vs_b3"] == "MATCH"


# ---------- 6. unknown project -> 404 ----------

def test_unknown_project_is_404(client):
    url = "/api/processos/projects/PRJ_NOPE/baselines"
    assert client.get(url).status_code == 404
    assert client.post(url + "/b1", json={"spec_hash": "sha256:" + sha(b"x"), "revision": 1}).status_code == 404
    assert client.post(url + "/compare").status_code == 404
    assert client.post(url + "/gate").status_code == 404


# ---------- fail-closed details: history, binding, idempotency ----------

def test_b2_history_appends_and_compare_uses_latest(svc):
    svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    v1, v2 = sha(b"zap19-archive-v1"), sha(b"zap19-archive-v2")
    svc.record_b2(PID, "build_219", v1, {"FB_Clamp": sha(b"fb-1")})
    svc.record_b2(PID, "build_219", v1, {"FB_Clamp": sha(b"fb-1")})  # identical -> rewrite
    svc.record_b2(PID, "build_219", v2, {"FB_Clamp": sha(b"fb-2")})  # new version -> append
    b2s = [r for r in svc.baselines(PID) if r["kind"] == "B2"]
    assert len(b2s) == 2  # history preserved; rewrite did not duplicate
    assert svc.compare(PID)["latest_b2"]["archive_sha256"] == v2


def test_unbound_deployed_build_blocks_even_on_matching_checksum(svc):
    svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    arc = sha(b"zap19-archive-v1")
    svc.record_b2(PID, "build_219", arc, {})
    # field-verified image claiming an unknown build id: binding is not provable
    svc.record_b3(PID, "build_field_edited", verification="FIELD_VERIFIED", plc_checksum=arc)
    result = svc.compare(PID)
    assert result["b2_vs_b3"] == "UNKNOWN"
    assert result["verdict"] == "FROZEN_DRIFT"  # fail-closed, not a warning
    assert any(d["kind"] == "UNKNOWN_BUILD_BINDING" for d in result["differences"])


def test_verified_without_checksum_blocks(svc):
    svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    svc.record_b2(PID, "build_219", sha(b"zap19-archive-v1"), {})
    svc.record_b3(PID, "build_219", verification="FIELD_VERIFIED")  # no identity captured
    result = svc.compare(PID)
    assert result["b2_vs_b3"] == "UNKNOWN" and result["verdict"] == "FROZEN_DRIFT"
    assert any(d["kind"] == "MISSING_PLC_CHECKSUM" for d in result["differences"])


def test_register_routes_is_idempotent(tmp_path):
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    service = BaselineService(tmp_path / "baselines.sqlite3")
    app.state.baselines = service
    register_routes(app)
    before = len(app.routes)
    register_routes(app)  # second mount: no duplicate routes, no service replacement
    assert len(app.routes) == before
    assert app.state.baselines is service
