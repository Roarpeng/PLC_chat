"""Contract tests for AF-Studio v5 orthogonal hypergraph API (/api/v2/af-studio/*)."""
from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.af_studio_v5_service import reset_af_studio_caches


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch):
    reset_af_studio_caches()
    monkeypatch.setenv("RESEARCHOS_TIA_SESSION", "0")
    monkeypatch.delenv("AF_STUDIO_STA_URL", raising=False)
    yield
    reset_af_studio_caches()


@pytest.fixture
def client():
    with TestClient(app) as tc:
        yield tc


def test_offline_tia_export_requires_kuka_workspace(client: TestClient) -> None:
    response = client.post("/api/v2/af-studio/export/tia-v19", json={"stationGraphs": {}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "content-disposition" not in response.headers


def test_offline_tia_export_returns_attachment_only_after_reopen(client: TestClient, monkeypatch) -> None:
    from gateway.app.routers import af_studio_v5

    outcome = SimpleNamespace(ok=True, state="NATIVE_ARCHIVED", artifact=None, stage_receipts=[],
                              error_message="", error_code="")
    downloaded_paths = []

    def export_snapshot(snapshot, output):
        assert json.loads(snapshot) == {"projectName": "验收"}
        output.mkdir()
        archive = output / "test.zap19"
        archive.write_bytes(b"archive-response-test")
        downloaded_paths.append(archive)
        outcome.artifact.archive_path = str(archive)
        return outcome

    monkeypatch.setattr(af_studio_v5, "archive_kuka_snapshot", export_snapshot)
    outcome.artifact = SimpleNamespace(reopen_ok=False)
    failed = client.post("/api/v2/af-studio/export/tia-v19", json={"projectName": "验收"})
    assert failed.status_code == 502
    assert "content-disposition" not in failed.headers

    outcome.artifact.reopen_ok = True
    passed = client.post("/api/v2/af-studio/export/tia-v19", json={"projectName": "验收"})
    assert passed.status_code == 200
    assert passed.content == b"archive-response-test"
    assert af_studio_v5.ARCHIVE_NAME in passed.headers["content-disposition"]
    assert not any(path.exists() for path in downloaded_paths)


def _get_seed(client: TestClient) -> dict:
    resp = client.get("/api/v2/af-studio/workspace/seed")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("ok", "code", "data", "message", "error", "evidence_level", "request_id"):
        assert key in body
    assert body["ok"] is True
    assert body["evidence_level"] == "offline"
    return body["data"]


def _start_mock_sta(routes: dict[str, dict]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            payload = routes.get(self.path)
            if payload is None:
                self.send_response(404)
                self.end_headers()
                return
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > 0:
                _ = self.rfile.read(length)
            payload = routes.get(self.path)
            if payload is None:
                self.send_response(404)
                self.end_headers()
                return
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_mother_classes_offline_and_v2_envelope(client: TestClient) -> None:
    resp = client.get("/api/v2/af-studio/mother-classes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["evidence_level"] == "offline"
    data = body["data"]
    assert data["source"] == "builtin"
    driver_classes = {item["driverClass"] for item in data["motherClasses"]}
    assert {
        "FB_AF_AxisMotion",
        "FB_AF_Actuator2Pos",
        "FB_AF_Gripper",
        "FB_AF_VisionSensor",
        "STATION_INPUT_PORT",
        "STATION_OUTPUT_PORT",
    }.issubset(driver_classes)
    assert "FB_AF_AxisMotion" in data["radialMethods"]


def test_mother_classes_sta_bridge_and_unreachable_fallback(client: TestClient, monkeypatch) -> None:
    server, url = _start_mock_sta(
        {
            "/reflect-af-library": {
                "ok": True,
                "realTiaConnected": True,
                "motherClasses": [
                    {"driverClass": "FB_AF_AxisMotion", "title": "TIA实机反射伺服轴"}
                ],
            }
        }
    )
    try:
        monkeypatch.setenv("AF_STUDIO_STA_URL", url)
        resp = client.get("/api/v2/af-studio/mother-classes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["evidence_level"] == "V19_real"
        assert body["data"]["source"] == "tia_openness_sta"
        assert body["data"]["staOnline"] is True
    finally:
        server.shutdown()
        server.server_close()

    # After server shutdown, must cleanly fall back to offline registry
    reset_af_studio_caches()
    fallback = client.get("/api/v2/af-studio/mother-classes")
    assert fallback.status_code == 200
    assert fallback.json()["evidence_level"] == "offline"
    assert fallback.json()["data"]["source"] == "builtin"


def test_workspace_seed_matches_v5_topology(client: TestClient) -> None:
    seed = _get_seed(client)
    assert seed["projectId"] == "AssyLine_01"
    l1_stations = {s["stationId"] for s in seed["projectGraph"]["stations"]}
    assert l1_stations == {"ST10", "ST20", "ST30"}
    assert set(seed["stationHyperGraphs"].keys()) == {"ST10", "ST20", "ST30"}

    st20 = seed["stationHyperGraphs"]["ST20"]
    assert len(st20["spatialNodes"]) == 6
    assert len(st20["guardEdges"]) == 2
    assert [s["stepNo"] for s in st20["temporalSteps"]] == [10, 20, 30, 40, 50]


def test_verify_normal_st20_passes_and_synthesizes_kahn_homing(client: TestClient) -> None:
    seed = _get_seed(client)
    st20 = seed["stationHyperGraphs"]["ST20"]

    resp = client.post("/api/v2/af-studio/verify", json={"station": st20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["evidence_level"] == "offline"

    report = body["data"]
    assert report["passed"] is True
    assert report["issues"] == []

    homing = report["homingResult"]
    assert homing["hasCycleDeadlock"] is False
    assert homing["cycleNodeIds"] == []
    layers = homing["concurrentLayers"]
    assert len(layers) == 2
    layer0_ids = {n["id"] for n in layers[0]}
    layer1_ids = {n["id"] for n in layers[1]}
    assert layer0_ids == {"INST_ST20_GRIP", "INST_ST20_Z"}
    assert layer1_ids == {"INST_ST20_X"}
    assert "o_bPartPresent" in homing["generatedHomeScl"]


def test_verify_missing_z_guardrail_intercepts_and_returns_one_click_patch(client: TestClient) -> None:
    seed = _get_seed(client)
    st20 = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])
    st20["guardEdges"] = [g for g in st20["guardEdges"] if g["id"] != "G_ST20_Z_TO_X"]

    resp = client.post("/api/v2/af-studio/verify", json={"station": st20})
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["passed"] is False
    codes = {i["code"] for i in report["issues"]}
    assert "MISSING_GUARDRAIL" in codes
    assert report["suggestedPatches"]
    patch_edge = report["suggestedPatches"][0]
    assert patch_edge["fromNode"] == "INST_ST20_Z"
    assert patch_edge["toNode"] == "INST_ST20_X"

    # Apply one-click repair patch and verify again -> passes
    st20["guardEdges"].append(patch_edge)
    fixed = client.post("/api/v2/af-studio/verify", json={"station": st20}).json()["data"]
    assert fixed["passed"] is True
    assert fixed["issues"] == []


def test_verify_bfs_reachable_collision_and_actuator_contention(client: TestClient) -> None:
    seed = _get_seed(client)
    st20 = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])

    # Insert X motion while Z is still extended at S45
    st20["temporalSteps"].append(
        {
            "id": "T_S45_COLLIDE",
            "stepNo": 45,
            "title": "碰撞演练步",
            "fromNode": "INST_ST20_Z",
            "fromPort": "OUT_DONE",
            "invocations": [
                {
                    "targetNodeId": "INST_ST20_X",
                    "methodId": "MoveHome",
                    "actionLabel": "Z未退回时强行回零",
                    "targetDiscreteState": "Pos_Home_0",
                    "sclStatement": "MoveAbs(0.0)",
                    "waitPredicateScl": "#INST_ST20_X.o_bDone",
                }
            ],
        }
    )
    res_collision = client.post("/api/v2/af-studio/verify", json={"station": st20}).json()["data"]
    assert res_collision["passed"] is False
    assert any(i["code"] == "COLLISION_REACHABLE" and i["stepNo"] == 45 for i in res_collision["issues"])

    # Test concurrent resource contention in same step
    st20_contention = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])
    st20_contention["temporalSteps"].append(
        {
            "id": "T_S60_CONTEND",
            "stepNo": 60,
            "title": "并发冲突步",
            "fromNode": "INST_ST20_Z",
            "fromPort": "OUT_DONE",
            "invocations": [
                {
                    "targetNodeId": "INST_ST20_X",
                    "methodId": "MovePick",
                    "targetDiscreteState": "Pos_Pick_120",
                    "sclStatement": "MoveAbs(120.0)",
                },
                {
                    "targetNodeId": "INST_ST20_X",
                    "methodId": "MovePress",
                    "targetDiscreteState": "Pos_Press_245",
                    "sclStatement": "MoveAbs(245.0)",
                },
            ],
        }
    )
    res_contend = client.post("/api/v2/af-studio/verify", json={"station": st20_contention}).json()["data"]
    assert res_contend["passed"] is False
    assert any(i["code"] == "ACTUATOR_CONTENTION" for i in res_contend["issues"])


def test_verify_guardrail_cycle_triggers_tarjan_kahn_deadlock(client: TestClient) -> None:
    seed = _get_seed(client)
    st20 = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])
    st20["guardEdges"].append(
        {
            "id": "G_CYCLE_X_TO_Z",
            "fromNode": "INST_ST20_X",
            "fromPort": "OUT_DONE",
            "toNode": "INST_ST20_Z",
            "toPort": "IN_EXEC",
            "requiredSourceState": "Pos_Home_0",
            "diagCodeHex": "16#0299",
            "humanDescription": "反向互锁形成死锁环",
        }
    )

    resp = client.post("/api/v2/af-studio/verify", json={"station": st20})
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["passed"] is False
    homing = report["homingResult"]
    assert homing["hasCycleDeadlock"] is True
    assert set(homing["cycleNodeIds"]) == {"INST_ST20_X", "INST_ST20_Z"}
    assert homing["concurrentLayers"] == []
    assert any(i["code"] == "GUARDRAIL_CYCLE_DEADLOCK" for i in report["issues"])


def test_compile_generates_four_deterministic_scl_targets(client: TestClient) -> None:
    seed = _get_seed(client)
    st20 = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])

    first = client.post("/api/v2/af-studio/compile", json={"station": st20}).json()["data"]
    blocks = {b["name"]: b for b in first["blocks"]}
    assert set(blocks.keys()) == {
        "FB_ST20_AutoSeq",
        "FB_ST20_HomeSeq",
        "FC_ST20_GuardDiag",
        "DB_ST20_Instances",
    }
    for blk in blocks.values():
        assert len(blk["merkleHash"]) == 8
        assert len(blk["interfaceHash"]) == 8
        assert blk["sclCode"].strip()

    # Layout x/y changes must NOT alter semantic Merkle hashes
    st20["spatialNodes"][0]["x"] = 999
    st20["spatialNodes"][0]["position"]["x"] = 999
    second = client.post("/api/v2/af-studio/compile", json={"station": st20}).json()["data"]
    assert second["blockHashes"] == first["blockHashes"]


def test_merkle_sync_lifecycle_and_honest_evidence_level(client: TestClient, monkeypatch) -> None:
    seed = _get_seed(client)
    st20 = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])

    # 1. First sync -> all 4 blocks DIRTY
    r1 = client.post(
        "/api/v2/af-studio/merkle-sync",
        json={"project_id": "prj_merkle_test", "station": st20},
    )
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["evidence_level"] == "offline"
    assert b1["data"]["dirtyCount"] == 4
    assert b1["data"]["unchangedCount"] == 0
    assert {blk["status"] for blk in b1["data"]["blocks"]} == {"DIRTY"}

    # 2. Second sync unchanged -> 0 DIRTY, 4 UNCHANGED
    r2 = client.post(
        "/api/v2/af-studio/merkle-sync",
        json={"project_id": "prj_merkle_test", "station": st20},
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["evidence_level"] == "offline"
    assert b2["data"]["dirtyCount"] == 0
    assert b2["data"]["unchangedCount"] == 4

    # 3. Modify single step -> ONLY 1 DIRTY (FB_ST20_AutoSeq)
    st20_mod = copy.deepcopy(st20)
    st20_mod["temporalSteps"][2]["invocations"][0]["sclStatement"] = "MoveAbs(248.5)"
    st20_mod["temporalSteps"][2]["sclCall"] = "MoveAbs(248.5)"
    r3 = client.post(
        "/api/v2/af-studio/merkle-sync",
        json={"project_id": "prj_merkle_test", "station": st20_mod},
    )
    assert r3.status_code == 200
    b3 = r3.json()
    assert b3["evidence_level"] == "offline"
    assert b3["data"]["dirtyCount"] == 1
    assert b3["data"]["unchangedCount"] == 3
    assert b3["data"]["dirtyBlocks"] == ["FB_ST20_AutoSeq"]

    # 4. With project_path but no real TIA STA online -> must NEVER claim V19_real
    r4 = client.post(
        "/api/v2/af-studio/merkle-sync",
        json={
            "project_id": "prj_merkle_real_check",
            "station": st20,
            "project_path": r"C:\Projects\Demo.ap19",
        },
    )
    assert r4.status_code == 200
    b4 = r4.json()
    assert b4["evidence_level"] == "pending_real_machine"
    assert b4["evidence_level"] != "V19_real"
    assert b4["data"]["tiaSynced"] is False
    assert "未连博途" in b4["data"]["notice"]

    # 5. With project_path + STA returning compileOk=True -> returns V19_real
    server, url = _start_mock_sta({"/merkle-sync": {"ok": True, "compileOk": True, "elapsedMs": 1120}})
    try:
        monkeypatch.setenv("AF_STUDIO_STA_URL", url)
        r5 = client.post(
            "/api/v2/af-studio/merkle-sync",
            json={
                "project_id": "prj_merkle_real_ok",
                "station": st20,
                "project_path": r"C:\Projects\Demo.ap19",
            },
        )
        assert r5.status_code == 200
        b5 = r5.json()
        assert b5["evidence_level"] == "V19_real"
        assert b5["data"]["tiaSynced"] is True
        assert b5["data"]["compileOk"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_copilot_ghost_patch_nl_and_table_cold_start_dedup(client: TestClient) -> None:
    seed = _get_seed(client)
    st20 = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])

    # Natural language NG reject branch
    nl_resp = client.post(
        "/api/v2/af-studio/copilot/ghost-patch",
        json={"station": st20, "prompt": "增加视觉 NG 去抛料位虚影分支"},
    )
    assert nl_resp.status_code == 200
    tx = nl_resp.json()["data"]
    assert tx["verificationPassed"] is True
    assert tx["verifierWarnings"] == []
    step_nos = [s["stepNo"] for s in tx["addedTemporalSteps"]]
    assert step_nos == [35, 36]
    assert "410" in tx["addedTemporalSteps"][0]["actionLabel"]
    assert "OpenGrip" in tx["addedTemporalSteps"][1]["sclCall"]

    # Table cold start deduplicates repeated device rows into 1 SpatialInstanceNode
    st30 = copy.deepcopy(seed["stationHyperGraphs"]["ST30"])
    pinned_before = {n["id"]: (n["x"], n["y"]) for n in st30["spatialNodes"] if n.get("isPinned")}
    tbl_resp = client.post(
        "/api/v2/af-studio/copilot/ghost-patch",
        json={
            "station": st30,
            "io_table_rows": [
                {
                    "name": "NG剔除吹气气缸",
                    "driverClass": "FB_AF_Actuator2Pos",
                    "instanceDb": "DB_ST30_CylReject",
                    "diHome": "%I20.2",
                    "doWork": "%Q20.1",
                }
            ],
            "timing_table_rows": [
                {
                    "stepNo": 25,
                    "title": "测高超差NG剔除伸出",
                    "target": "NG剔除吹气气缸",
                    "action": "伸出剔除NG品",
                    "sclCall": "ExtendWork()",
                    "fromNode": "INST_ST30_LASER",
                },
                {
                    "stepNo": 28,
                    "title": "剔除气缸退回原位",
                    "target": "DB_ST30_CylReject",
                    "action": "缩回原位",
                    "sclCall": "RetractHome()",
                    "fromNode": "INST_ST30_LASER",
                },
            ],
        },
    )
    assert tbl_resp.status_code == 200
    tbl_tx = tbl_resp.json()["data"]
    assert len(tbl_tx["addedNodes"]) == 1
    assert tbl_tx["addedNodes"][0]["instanceDb"] == "DB_ST30_CylReject"
    assert len(tbl_tx["addedTemporalSteps"]) == 2
    assert tbl_tx["verificationPassed"] is True
    # Pinned existing nodes keep exact original positions
    for n in st30["spatialNodes"]:
        if n["id"] in pinned_before:
            assert (n["x"], n["y"]) == pinned_before[n["id"]]


def test_cutset_snapshot_prunes_i10_0_and_traces_st10_i0_4(client: TestClient) -> None:
    seed = _get_seed(client)
    resp = client.post(
        "/api/v2/af-studio/diagnostics/cutset-snapshot",
        json={
            "project_graph": seed["projectGraph"],
            "station_graphs": seed["stationHyperGraphs"],
            "fault_station_id": "ST20",
            "fault_step_no": 30,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["evidence_level"] == "offline"
    data = body["data"]

    assert data["faultResolved"] is False
    assert any(p["terminal"] == "%I10.0" and p["signalValue"] is True for p in data["prunedHealthyEdges"])
    assert any(f["diagCode"] == "#0203" and f["signalValue"] is False for f in data["falsifiedEdges"])
    assert len(data["rootCauses"]) == 1
    rc = data["rootCauses"][0]
    assert rc["stationId"] == "ST10"
    assert rc["nodeId"] == "INST_ST10_TRANS"
    assert rc["physicalTerminal"] == "%I0.4"
    assert rc["cabinetWireTag"] == "X12:04"

    fly = data["cameraFlySteps"]
    assert len(fly) == 3
    assert [step["layer"] for step in fly] == ["STATION", "PROJECT", "STATION"]
    assert fly[0]["stationId"] == "ST20"
    assert fly[2]["stationId"] == "ST10"
    assert fly[2]["focusNodeId"] == "INST_ST10_TRANS"

    # Passing repaired %I0.4=True resolves the cut-set
    repaired = client.post(
        "/api/v2/af-studio/diagnostics/cutset-snapshot",
        json={
            "project_graph": seed["projectGraph"],
            "station_graphs": seed["stationHyperGraphs"],
            "fault_station_id": "ST20",
            "fault_step_no": 30,
            "live_signals": {"ST20_CylZ.%I10.0": True, "ST10_CylTrans.%I0.4": True},
        },
    ).json()["data"]
    assert repaired["faultResolved"] is True
    assert repaired["falsifiedEdges"] == []


def test_camelcase_compatibility_and_error_envelopes(client: TestClient) -> None:
    seed = _get_seed(client)
    st20_no_guard = copy.deepcopy(seed["stationHyperGraphs"]["ST20"])
    st20_no_guard["guardEdges"] = [
        g for g in st20_no_guard["guardEdges"] if g["id"] != "G_ST20_Z_TO_X"
    ]

    # Copilot guardrail proposal + verify with camelCase ghostTx
    guard_tx = client.post(
        "/api/v2/af-studio/copilot/ghost-patch",
        json={"station": st20_no_guard, "prompt": "请补齐安全防撞护栏"},
    ).json()["data"]
    assert len(guard_tx["addedGuardEdges"]) == 1
    assert guard_tx["verificationPassed"] is True

    verified = client.post(
        "/api/v2/af-studio/verify",
        json={"station": st20_no_guard, "ghostTx": guard_tx},
    ).json()["data"]
    assert verified["passed"] is True

    # CamelCase merkle-sync & cutset-snapshot
    sync_res = client.post(
        "/api/v2/af-studio/merkle-sync",
        json={
            "projectId": "prj_camel",
            "station": seed["stationHyperGraphs"]["ST20"],
            "previousHashes": {},
        },
    )
    assert sync_res.status_code == 200
    assert sync_res.json()["data"]["dirtyCount"] == 4

    cut_res = client.post(
        "/api/v2/af-studio/diagnostics/cutset-snapshot",
        json={
            "projectGraph": seed["projectGraph"],
            "stationGraphs": seed["stationHyperGraphs"],
            "faultStationId": "ST20",
            "faultStepNo": 30,
            "liveSignals": {"%I10.0": True, "%I0.4": False},
        },
    )
    assert cut_res.status_code == 200
    assert cut_res.json()["data"]["rootCauses"][0]["physicalTerminal"] == "%I0.4"

    # Empty copilot request -> 422 error envelope
    bad_copilot = client.post(
        "/api/v2/af-studio/copilot/ghost-patch",
        json={"station": seed["stationHyperGraphs"]["ST20"]},
    )
    assert bad_copilot.status_code == 422
    assert bad_copilot.json()["ok"] is False

    # Missing fault station -> 404 error envelope
    bad_cutset = client.post(
        "/api/v2/af-studio/diagnostics/cutset-snapshot",
        json={
            "projectGraph": seed["projectGraph"],
            "stationGraphs": seed["stationHyperGraphs"],
            "faultStationId": "ST99",
            "faultStepNo": 30,
        },
    )
    assert bad_cutset.status_code == 404
    assert bad_cutset.json()["ok"] is False
