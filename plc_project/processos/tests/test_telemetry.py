"""FC-15/16/17 tests: read-only telemetry (honest SIMULATED labelling, MANUAL
defaults, immutability/no-delete, ordering) and field-modification recovery
(three-way diff, frozen drift, unmapped native overrides, UNKNOWN baseline).
All sha256 values are really computed with hashlib — no invented hashes."""
from __future__ import annotations

import contextlib
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.store import ProjectStore
from processos.contract import clamp_contract
from processos.sourcemap import SourceMapEntry, SourceMapRegistry
from processos.store.db import JsonDao, open_db
from processos.telemetry import FieldModificationService, TelemetryService, register_routes

PROJECT_ID = clamp_contract().id  # PRJ_CLAMP


def sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class FakeTrace:
    """Minimal trace_provider: real SourceMapRegistry carrying mapped blocks."""

    def __init__(self, blocks: list[str]) -> None:
        self.sourcemap = SourceMapRegistry()
        for i, b in enumerate(blocks):
            self.sourcemap.add(SourceMapEntry(
                source_map_id=f"src_{i:04d}", semantic_object_id="cm_clamp_a_001",
                release_build_id="build_219", block_name=b, block_kind="FB"))


class FakeBaselineProvider:
    """Duck-typed baselines module: .latest_b2(project_id) -> B2 manifest."""

    def __init__(self, blocks: dict[str, str] | None = None) -> None:
        self.blocks = blocks
        self.calls: list[str] = []

    def latest_b2(self, project_id: str):
        self.calls.append(project_id)
        return {"block_manifest": dict(self.blocks), "archive_sha256": sha("archive")} if self.blocks else None


# ---------- FC-15 telemetry ----------

@pytest.fixture()
def env(tmp_path):
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    app.state.telemetry = TelemetryService(tmp_path / "telemetry.sqlite3")
    app.state.fieldmods = FieldModificationService(
        FakeTrace(["FB_ClampSequence", "FB_ClampA"]), db=tmp_path / "field_overrides.sqlite3")
    register_routes(app)
    yield TestClient(app), app.state.telemetry, app
    app.state.telemetry.close()
    app.state.fieldmods.close()


def test_simulated_source_forces_quality_and_level(env):
    client, _, _ = env
    r = client.post("/api/processos/telemetry/events", json={
        "object_id": "cm_clamp_a_001", "source": "SIMULATED",
        "event_time": "2026-11-15T09:17:08+08:00",
        "payload": {"extended": False}, "quality": "GOOD",  # 调用方谎报 GOOD 也必须被覆盖
    })
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["quality"] == "SIMULATED"
    assert ev["evidence_level"] == "SIMULATED"


def test_manual_upload_defaults_to_reported(env):
    client, svc, _ = env
    ev = svc.ingest("cm_clamp_a_001", "MANUAL_UPLOAD", "2026-11-15T09:20:00+08:00",
                    {"note": "报警截图上传"})
    assert ev["quality"] == "REPORTED"
    assert ev["evidence_level"] == "MANUAL"
    r = client.post("/api/processos/telemetry/events", json={
        "object_id": "cm_clamp_a_001", "source": "MANUAL_UPLOAD",
        "event_time": "2026-11-15T09:21:00+08:00", "payload": {}})
    assert r.json()["quality"] == "REPORTED"


def test_ot_channel_evidence_level_and_quality_passthrough(env):
    _, svc, _ = env
    ev = svc.ingest("cm_clamp_a_001", "OT_CHANNEL", "2026-11-15T09:30:00+08:00",
                    {"sequence": 876}, quality="GOOD")
    assert ev["evidence_level"] == "OT_READ" and ev["quality"] == "GOOD"
    ev2 = svc.ingest("cm_clamp_a_001", "OT_CHANNEL", "2026-11-15T09:31:00+08:00", {})
    assert ev2["quality"] == "UNSPECIFIED"  # 未带质量位不虚构 GOOD


def test_events_sorted_ascending_and_filtered(env):
    client, svc, _ = env
    for ts in ["2026-11-15T12:00:00+08:00", "2026-11-15T09:00:00+08:00", "2026-11-15T10:30:00+08:00"]:
        svc.ingest("cm_clamp_a_001", "OT_CHANNEL", ts, {"t": ts})
    svc.ingest("cm_other", "OT_CHANNEL", "2026-11-15T08:00:00+08:00", {})
    got = client.get("/api/processos/objects/cm_clamp_a_001/telemetry").json()["events"]
    times = [e["event_time"] for e in got]
    assert times == sorted(times) and len(times) == 3
    assert all(e["object_id"] == "cm_clamp_a_001" for e in got)


def test_read_only_no_delete_or_overwrite_capability(env):
    client, svc, app = env
    # 服务层：刻意不存在任何删除/覆盖方法
    for forbidden in ("delete", "delete_event", "remove", "update", "overwrite", "put", "patch"):
        assert not hasattr(svc, forbidden), f"TelemetryService must not expose {forbidden}()"
    # 路由层：telemetry 路径不注册任何 DELETE/PUT/PATCH 方法
    dangerous = [
        r for r in app.routes
        if (getattr(r, "path", "").endswith("/telemetry") or "/telemetry/" in getattr(r, "path", ""))
        and set(getattr(r, "methods", set()) or set()) & {"DELETE", "PUT", "PATCH"}
    ]
    assert dangerous == []
    # 原件不可覆盖：重复 ingest 只会追加新事件（不同 event_id），旧事件原样保留
    e1 = svc.ingest("cm_clamp_a_001", "OT_CHANNEL", "2026-11-15T09:00:00+08:00", {"seq": 1})
    e2 = svc.ingest("cm_clamp_a_001", "OT_CHANNEL", "2026-11-15T09:00:00+08:00", {"seq": 1})
    assert e1["event_id"] != e2["event_id"]
    assert svc.get(e1["event_id"]) is not None


def test_invalid_source_and_fields_422(env):
    client, _, _ = env
    r = client.post("/api/processos/telemetry/events", json={
        "object_id": "cm_x", "source": "TELEPATHY", "event_time": "2026-11-15T09:00:00+08:00",
        "payload": {}})
    assert r.status_code == 422
    r2 = client.post("/api/processos/telemetry/events", json={
        "object_id": "cm_x", "source": "OT_CHANNEL"})
    assert r2.status_code == 422


def test_telemetry_persistence_roundtrip(tmp_path):
    path = tmp_path / "tel_roundtrip.sqlite3"
    svc = TelemetryService(path)
    svc.ingest("cm_clamp_a_001", "SIMULATED", "2026-11-15T09:00:00+08:00", {"step": "S_EXTEND"})
    svc.close()
    revived = TelemetryService(path)
    events = revived.events_for("cm_clamp_a_001")
    assert len(events) == 1 and events[0]["quality"] == "SIMULATED"
    revived.close()


# ---------- FC-16/17 field modification recovery ----------

def _b2(blocks: dict[str, str]) -> dict:
    return {"block_manifest": dict(blocks), "archive_sha256": sha("archive")}


def _field_state(blocks: dict[str, str]) -> dict:
    return {"blocks": [{"block_name": n, "content_sha256": s} for n, s in blocks.items()]}


def test_field_match_when_field_equals_b2(env):
    client, _, _ = env
    blocks = {"FB_ClampSequence": sha("v1"), "FB_ClampA": sha("v2")}
    r = client.post(f"/api/processos/projects/{PROJECT_ID}/field-modifications", json={
        "field_state": _field_state(blocks),
        "b2_manifest": _b2(blocks),
        "captured_at": "2026-11-15T11:00:00+08:00",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["b2_vs_b3"] == "MATCH" and out["drift_detected"] is False
    assert out["frozen"] is False and out["error_code"] is None
    assert out["changed_blocks"] == [] and out["unmapped_native_code"] == []


def test_field_drift_freezes_and_reports_changed_blocks(tmp_path):
    svc = FieldModificationService(FakeTrace(["FB_ClampSequence", "FB_ClampA"]),
                                   db=tmp_path / "drift.sqlite3")
    try:
        b2_blocks = {"FB_ClampSequence": sha("v1"), "FB_ClampA": sha("v2")}
        field_blocks = {"FB_ClampSequence": sha("v1"), "FB_ClampA": sha("field-edited")}
        out = svc.recover("PRJ_CLAMP", _field_state(field_blocks), b2_manifest=_b2(b2_blocks))
        assert out["b2_vs_b3"] == "DRIFT" and out["drift_detected"] is True
        assert out["frozen"] is True and out["error_code"] == "DRIFT_DETECTED"
        assert [c["block_name"] for c in out["changed_blocks"]] == ["FB_ClampA"]
        assert out["changed_blocks"][0]["reason"] == "content_differs"
        assert out["three_way"]["design_changed"] == []  # 无 B1 视角留空
        assert "design_baseline_b1" in out["three_way"]["unknown"]
    finally:
        svc.close()


def test_unmapped_field_block_creates_managed_override(tmp_path):
    path = tmp_path / "field_overrides.sqlite3"
    # OB_HOTFIX 在现场新增，且不在 SourceMap（FakeTrace 只有 FB_ClampSequence）与 B2
    b2_blocks = {"FB_ClampSequence": sha("v1")}
    field_blocks = {"FB_ClampSequence": sha("v1"), "OB_HOTFIX": sha("field-only")}
    svc = FieldModificationService(FakeTrace(["FB_ClampSequence"]), db=path)
    out = svc.recover("PRJ_CLAMP", _field_state(field_blocks), b2_manifest=_b2(b2_blocks))
    assert out["unmapped_native_code"] == ["OB_HOTFIX"]
    ov = out["managed_native_overrides"][0]
    assert ov["override_id"].startswith("mno_")
    assert ov["block_name"] == "OB_HOTFIX"
    assert ov["ownership"] == "MANAGED_NATIVE_OVERRIDE"
    assert ov["protected_by"] == "EXPLICIT_OWNERSHIP"
    assert "不得自动覆盖" in ov["note"]
    assert out["drift_detected"] is True and out["error_code"] == "DRIFT_DETECTED"
    svc.close()
    # override 记录已持久化到 namespace "field_overrides"（短命连接直接验证）
    with contextlib.closing(open_db(path)) as conn:
        raw = JsonDao(conn, "field_overrides").list_by_kind("managed_native_override")
        assert len(raw) == 1 and raw[0]["override_id"] == ov["override_id"]
    # 重启后 override 登记仍在（只读登记，不覆盖任何工程文件）
    revived = FieldModificationService(FakeTrace(["FB_ClampSequence"]), db=path)
    assert [o["override_id"] for o in revived.overrides_for("PRJ_CLAMP")] == [ov["override_id"]]
    revived.close()


def test_no_baseline_is_unknown_and_fail_closed(tmp_path):
    svc = FieldModificationService(FakeTrace(["FB_ClampSequence"]),
                                   db=tmp_path / "unknown.sqlite3")  # 无 baseline_provider
    try:
        out = svc.recover("PRJ_CLAMP", _field_state({"FB_ClampSequence": sha("v1")}))
        assert out["b2_vs_b3"] == "UNKNOWN"
        assert out["drift_detected"] is None
        assert out["error_code"] == "UNKNOWN_PLC_STATE"
        assert out["frozen"] is True  # fail-closed：未知也冻结
        assert out["changed_blocks"] == [] and out["unmapped_native_code"] == []
    finally:
        svc.close()


def test_baseline_provider_used_when_no_explicit_manifest(tmp_path):
    path = tmp_path / "provider.sqlite3"
    blocks = {"FB_ClampSequence": sha("v1")}
    provider = FakeBaselineProvider(blocks)
    svc = FieldModificationService(FakeTrace(list(blocks)), baseline_provider=provider, db=path)
    empty = None
    try:
        out = svc.recover("PRJ_CLAMP", _field_state(blocks))
        assert provider.calls == ["PRJ_CLAMP"]  # 走了 provider
        assert out["b2_vs_b3"] == "MATCH" and out["error_code"] is None
        # provider 无 B2（latest_b2 -> None）时按未知处理
        empty = FieldModificationService(FakeTrace([]), baseline_provider=FakeBaselineProvider(None), db=path)
        unknown = empty.recover("PRJ_CLAMP", _field_state({"FB_ClampSequence": sha("v1")}))
        assert unknown["b2_vs_b3"] == "UNKNOWN" and unknown["error_code"] == "UNKNOWN_PLC_STATE"
    finally:
        if empty is not None:
            empty.close()
        svc.close()


def test_known_design_block_missing_from_b2_is_field_change(tmp_path):
    svc = FieldModificationService(FakeTrace(["FB_ClampSequence", "FB_ClampA"]),
                                   db=tmp_path / "design_missing.sqlite3")
    try:
        # FB_ClampA 在 SourceMap 里但现场版本不在 B2 manifest：现场新增（非 unmapped）
        b2_blocks = {"FB_ClampSequence": sha("v1")}
        field_blocks = {"FB_ClampSequence": sha("v1"), "FB_ClampA": sha("v2")}
        out = svc.recover("PRJ_CLAMP", _field_state(field_blocks), b2_manifest=_b2(b2_blocks))
        assert out["unmapped_native_code"] == []
        assert [c["block_name"] for c in out["changed_blocks"]] == ["FB_ClampA"]
        assert out["changed_blocks"][0]["reason"] == "missing_from_b2"
        assert out["three_way"]["field_changed"] == ["FB_ClampA"]
        assert out["b2_vs_b3"] == "DRIFT"
    finally:
        svc.close()


def test_field_state_validation_422(env):
    client, _, _ = env
    r = client.post(f"/api/processos/projects/{PROJECT_ID}/field-modifications", json={
        "field_state": {"blocks": [{"block_name": "FB_X", "content_sha256": "not-a-sha"}]},
        "b2_manifest": _b2({"FB_X": sha("v1")}),
    })
    assert r.status_code == 422
    r2 = client.post(f"/api/processos/projects/{PROJECT_ID}/field-modifications", json={
        "field_state": {"blocks": []}})
    assert r2.status_code == 200  # 空现场状态 vs 无基准 -> UNKNOWN（合法，不猜）
    assert r2.json()["b2_vs_b3"] == "UNKNOWN"


def test_duck_typed_bridge_to_real_baseline_service(tmp_path):
    """集成兼容：真实 BaselineService（record_b2/baselines，无 latest_b2）可直接注入。"""
    from processos.baselines import BaselineService

    baselines = BaselineService(tmp_path / "b2_ledger.sqlite3")
    blocks = {"FB_ClampSequence": sha("v1"), "FB_ClampA": sha("v2")}
    baselines.record_b2(PROJECT_ID, "build_219", sha("archive"), block_manifest=blocks)
    svc = FieldModificationService(FakeTrace(list(blocks)), baseline_provider=baselines,
                                   db=tmp_path / "bridge.sqlite3")
    try:
        out = svc.recover(PROJECT_ID, _field_state(blocks))
        assert out["b2_vs_b3"] == "MATCH" and out["error_code"] is None
        drifted = _field_state({**blocks, "FB_ClampA": sha("edited")})
        out2 = svc.recover(PROJECT_ID, drifted)
        assert out2["b2_vs_b3"] == "DRIFT" and out2["frozen"] is True
    finally:
        svc.close()
