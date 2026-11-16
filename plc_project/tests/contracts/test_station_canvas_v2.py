from __future__ import annotations

import io
import json
from hashlib import sha256
from zipfile import ZipFile

from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.workspace_v2 import WorkspaceStore, get_store
from plc_engine.engineering_ir.station_catalog import PROFILES
from plc_engine.engineering_ir.station_design import StationDesign
from plc_engine.process.station_simulation import simulate_design


def design_document(*, parallel: bool = False) -> dict:
    def node(id_, kind, **fields):
        return {"id": id_, "kind": kind, "name": id_, **fields}

    def edge(id_, source, outcome, target):
        return {"id": id_, "from_id": source, "to_id": target, "outcome": outcome}

    design = {
        "name": "双工位联调",
        "hardware": {
            "cpu": "S7-1200",
            "modules": [{"id": "card", "name": "I/O", "slot": 1, "kind": "DI_DO"}],
            "signals": [],
        },
        "stations": [],
        "flow": {"start": "runA", "nodes": [], "edges": []},
    }
    for i, tag in enumerate(("A", "B")):
        for direction, addr, prefix in (("input", "%I", "fb"), ("output", "%Q", "cmd")):
            design["hardware"]["signals"].append({
                "id": prefix + tag, "name": prefix + tag, "module_id": "card",
                "direction": direction, "address": f"{addr}0.{i}",
            })
        design["stations"].append({
            "id": "station" + tag, "name": "工具工位 " + tag,
            "devices": [{"id": "motor" + tag, "name": "电机", "driver": "motor",
                         "bindings": {"run": "cmd" + tag, "running": "fb" + tag}}],
            "flow": {
                "start": "start" + tag,
                "nodes": [
                    node("start" + tag, "action", device_id="motor" + tag, port="run"),
                    node("wait" + tag, "wait", device_id="motor" + tag, port="running", timeout_ms=500),
                    node("done" + tag, "done"), node("fault" + tag, "fault"),
                ],
                "edges": [
                    edge("entry" + tag, "start" + tag, "next", "wait" + tag),
                    edge("finish" + tag, "wait" + tag, "next", "done" + tag),
                    edge("late" + tag, "wait" + tag, "timeout", "fault" + tag),
                ],
            },
        })
    flow = design["flow"]
    flow["nodes"] = [node("projectDone", "done"), node("projectFault", "fault")]
    if parallel:
        flow["nodes"].append(node("runA", "parallel", station_ids=["stationA", "stationB"]))
        flow["edges"].append(edge("doneAtoB", "runA", "done", "projectDone"))
    else:
        flow["nodes"].extend([node("runA", "station", station_ids=["stationA"]),
                              node("runB", "station", station_ids=["stationB"])])
        flow["edges"].extend([edge("doneAtoB", "runA", "done", "runB"),
                              edge("doneBtoEnd", "runB", "done", "projectDone"),
                              edge("faultBtoEnd", "runB", "fault", "projectFault")])
    flow["edges"].append(edge("faultAtoEnd", "runA", "fault", "projectFault"))
    return design


def test_station_workspace_draft_intent_snapshot_and_import(tmp_path, monkeypatch):
    monkeypatch.setattr("gateway.app.services.plc.station_intent.llm_settings", lambda: None)
    path = tmp_path / "workspace.sqlite3"
    store = WorkspaceStore(db_path=path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        root = "/api/v2/projects/prj_station_contract"
        created = client.post("/api/v2/projects", json={"project_id": "prj_station_contract",
                                                         "station_design": {"name": "新工程"}})
        assert created.status_code == 201
        assert not client.post(root + "/validate", json={}).json()["data"]["passed"]
        assert client.get(root + "/source-package").status_code == 409
        design = design_document()

        def commit(base, draft, key):
            return client.post(root + "/patches", json={"base_revision": base, "request_id": key,
                                                       "ops": [{"op": "set_station_design", "design": draft}]})

        saved = commit(0, design, "manual")
        assert saved.status_code == 200, saved.text
        assert client.post(root + "/validate", json={"base_revision": 1}).json()["data"]["passed"]
        proposal = client.post(root + "/intent", json={"base_revision": 1, "message": "超时改为 2 秒",
                                                      "context_slice": {"station_id": "stationA", "node_id": "waitA"}})
        assert proposal.status_code == 200, proposal.text
        proposed = proposal.json()["data"]["ops"][0]["design"]
        assert proposed["stations"][0]["flow"]["nodes"][1]["timeout_ms"] == 2000
        assert client.get(root + "/ir").json()["data"]["revision"] == 1
        assert commit(1, proposed, "apply-proposal").status_code == 200
        assert commit(1, design, "stale").status_code == 409
        frozen = client.post(root + "/changesets", json={"base_revision": 2}).json()["data"]
        approved = client.post(f"/api/v2/changesets/{frozen['changeset_id']}/approve", json={
            "reviewer_id": "engineer", "explicit": True, "expected_baseline_hash": frozen["before_hash"],
        })
        assert approved.status_code == 200, approved.text
        assert commit(2, design, "change-after-frozen").status_code == 200
        package = client.get(root + "/source-package", params={"changeset_id": frozen["changeset_id"]})
        assert package.status_code == 200, package.text[:300]
        with ZipFile(io.BytesIO(package.content)) as archive:
            files = archive.namelist()
            assert files.count("scl/FB_AF_DRV_motor.scl") == 1
            em = [file for file in files if file.startswith("scl/FB_U1Em")]
            assert len(em) == 2 and any("T#2000ms" in archive.read(file).decode() for file in em)
            mapped = json.loads(archive.read("source-map.json"))
            assert any(item["canvas_node_id"] == "waitA" for item in mapped["mappings"])
            receipt = json.loads(archive.read("af-canvas.json"))
            assert receipt["revision"] == 2
            assert receipt["source_ir_sha256"] == frozen["after_hash"]
            assert all("sha256:" + sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
                       for item in json.loads(archive.read("manifest.json"))["files"])
        inspected = client.post("/api/v2/station-import", files={"file": ("af.zip", package.content)})
        assert inspected.json()["data"]["device_count"] == 2
        imported = client.post("/api/v2/station-import?confirm=true", files={"file": ("af.zip", package.content)})
        new_id = imported.json()["data"]["project_id"]
        assert client.get(f"/api/v2/projects/{new_id}/ir").json()["data"]["ir"]["station_design"] == proposed
        assert client.post("/api/v2/station-import", files={"file": ("invalid.json", b"{}")}).status_code == 422
        reopened = WorkspaceStore(db_path=path)
        try:
            assert reopened.get_ir("prj_station_contract").revision == 3
            assert reopened.get_ir(new_id).station_design == proposed
        finally:
            reopened.close()
    finally:
        app.dependency_overrides.pop(get_store, None)
        store.close()


def test_parallel_waits_for_both_stations_and_routes_timeouts():
    design = StationDesign.model_validate(design_document(parallel=True))
    trace = simulate_design(design, "normal_cycle")
    assert next(item["time_ms"] for item in trace if item["node_id"] == "startA") == next(
        item["time_ms"] for item in trace if item["node_id"] == "startB"
    )
    assert trace[-1]["node_id"] == "projectDone"
    timeout_trace = simulate_design(design, "feedback_timeout")
    assert timeout_trace[-1]["node_id"] == "projectFault"


def test_catalog_actions_natural_language_manual_feedback_and_source(tmp_path, monkeypatch):
    monkeypatch.setattr("gateway.app.services.plc.station_intent.llm_settings", lambda: None)
    store = WorkspaceStore(db_path=tmp_path / "station_steps.sqlite3")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    root = "/api/v2/projects/prj_action_steps"
    draft = design_document(parallel=True)
    station = draft["stations"][0]
    station["devices"] = []
    station["flow"] = {"start": None, "nodes": [], "edges": []}
    for device_id, driver, label in (
        ("gripperA", "pneumatic_gripper", "夹爪 A"),
        ("slideA", "servo", "横移伺服"),
        ("partA", "photoelectric", "工件到位"),
    ):
        bindings = {}
        for port, direction in PROFILES[driver]["ports"].items():
            signal_id = f"{device_id}_{port}"
            index = len(draft["hardware"]["signals"])
            draft["hardware"]["signals"].append({
                "id": signal_id, "name": signal_id, "module_id": "card", "direction": direction,
                "address": f"%{'I' if direction == 'input' else 'Q'}{index // 8}.{index % 8}",
            })
            bindings[port] = signal_id
        station["devices"].append({"id": device_id, "driver": driver, "name": label, "bindings": bindings})

    def propose(revision, message):
        response = client.post(root + "/intent", json={
            "base_revision": revision, "message": message, "context_slice": {"station_id": "stationA"},
        })
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def commit(revision, design):
        response = client.post(root + "/patches", json={
            "base_revision": revision, "request_id": f"steps_{revision}",
            "ops": [{"op": "set_station_design", "design": design}],
        })
        assert response.status_code == 200, response.text

    def trace(revision, scenario):
        response = client.post(root + "/simulate", json={
            "base_revision": revision, "scenario": scenario, "station_id": "stationA",
        })
        assert response.status_code == 200, response.text
        return response.json()["data"]

    try:
        catalog = {item["id"]: item for item in client.get("/api/v2/station-catalog").json()["data"]}
        assert catalog["servo"]["actions"][1]["feedback"] == {"in_position": True, "busy": False}
        assert catalog["servo_to"]["supported"] is False
        created = client.post("/api/v2/projects", json={"project_id": "prj_action_steps", "station_design": draft})
        assert created.status_code == 201, created.text
        proposal = propose(0, "工件到位后，夹爪 A 夹紧。夹紧到位后，横移伺服移动到工作位。"
                              "工作完成后，伺服回原位，再松开夹爪。夹紧等待超过 2 秒就进入故障分支。")
        assert proposal["ops"], proposal
        plan = proposal["ops"][0]["design"]
        nodes = plan["stations"][0]["flow"]["nodes"]
        assert (nodes[0]["device_id"], nodes[0]["port"]) == ("partA", "active")
        assert [node["actions"][0]["action_id"] for node in nodes if node["actions"]] == ["clamp", "work", "home", "release"]
        assert nodes[1]["timeout_ms"] == 2000
        assert nodes[3]["pending_feedback"]
        assert client.get(root + "/ir").json()["data"]["revision"] == 0
        commit(0, plan)
        pending = trace(1, "normal_cycle")
        assert not pending["trace"] and any(issue["node_id"] == nodes[3]["id"] for issue in pending["issues"])
        nodes[3].update(device_id="slideA", port="busy", value=False, pending_feedback=False)
        commit(1, plan)
        followup = propose(2, "在松开前插入等待 300 ms")
        edited = followup["ops"][0]["design"]
        edited_nodes = edited["stations"][0]["flow"]["nodes"]
        assert edited_nodes[5]["duration_ms"] == 300
        commit(2, edited)
        exact_frames = trace(3, "normal_cycle")["trace"]
        wait_frames = [item for item in exact_frames if item["node_id"] == edited_nodes[5]["id"]]
        assert wait_frames[1]["time_ms"] - wait_frames[0]["time_ms"] >= 300
        assert all(item["station_id"] == "stationA" for item in exact_frames)
        assert exact_frames[-1]["event"] == "done"
        assert trace(3, "feedback_timeout")["trace"][-1]["event"] == "fault"
        checked = client.post(root + "/validate", json={"base_revision": 3})
        assert checked.json()["data"]["passed"], checked.text
        preview = client.post(root + "/preview", json={"base_revision": 3}).json()["data"]
        files = preview["scl_files"]
        assert "scl/FB_AF_DRV_pneumatic_gripper.scl" in files
        assert "scl/FB_AF_DRV_servo.scl" in files
        code = next(content for name, content in files.items() if name.endswith("stationA.scl") and "FB_U1Em" in name)
        assert "#R_gripperA_close := TRUE;" in code
        assert "#R_slideA_work := TRUE;" in code
        assert "IF NOT #FirstScan AND" in code
        assert "T#300ms" in code
        adjusted = propose(3, "把夹紧的超时改为 2.5 秒")
        adjusted_nodes = adjusted["ops"][0]["design"]["stations"][0]["flow"]["nodes"]
        assert next(item for item in adjusted_nodes if item["id"] == nodes[1]["id"])["timeout_ms"] == 2500
        parallel = propose(3, "重建工位流程。夹爪 A 夹紧和横移伺服移动到工作位同时执行。")
        grouped = parallel["ops"][0]["design"]["stations"][0]["flow"]["nodes"][0]
        assert len(grouped["actions"]) == 2
        assert [(item["port"], item["value"]) for item in grouped["completion"]] == [
            ("closed", True), ("in_position", True), ("busy", False),
        ]
        conditional = propose(3, "重建工位流程。如果伺服启动失败，夹爪 A 松开。")
        assert not conditional["ops"] and conditional["questions"]
    finally:
        app.dependency_overrides.pop(get_store, None)
        store.close()
