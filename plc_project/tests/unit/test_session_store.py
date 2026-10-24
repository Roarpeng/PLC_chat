"""服务端会话存储 CRUD(历史跟服务走升级,2026-10-24)。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from gateway.app.main import create_app
from gateway.app.services.plc import session_store


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    return TestClient(create_app())


H = {"X-API-Key": "ros_ak_dev_change_me"}


def test_session_crud_roundtrip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    sess = {
        "id": "s-test-1",
        "title": "会话一",
        "createdAt": 1000,
        "updatedAt": 2000,
        "messages": [{"id": "m1", "role": "user", "text": "分析项目", "ts": 1500}],
        "canvas": {"project_name": "P", "blocks": {"B1": {"name": "B1"}}, "hmi_widgets": {}, "tags": {}},
    }
    # PUT upsert
    r = client.put("/api/v1/plc/canvas/sessions/s-test-1", json=sess, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["msgCount"] == 1
    # GET list 只含 meta,不含 canvas
    r = client.get("/api/v1/plc/canvas/sessions", headers=H)
    assert r.status_code == 200
    lst = r.json()["data"]
    assert len(lst) == 1 and lst[0]["title"] == "会话一" and "canvas" not in lst[0]
    # GET 单会话完整
    r = client.get("/api/v1/plc/canvas/sessions/s-test-1", headers=H)
    assert r.status_code == 200
    assert r.json()["data"]["canvas"]["blocks"]["B1"]["name"] == "B1"
    # 覆盖更新
    sess["updatedAt"] = 3000
    sess["messages"].append({"id": "m2", "role": "system", "text": "回答", "ts": 2900})
    client.put("/api/v1/plc/canvas/sessions/s-test-1", json=sess, headers=H)
    lst = client.get("/api/v1/plc/canvas/sessions", headers=H).json()["data"]
    assert lst[0]["msgCount"] == 2 and lst[0]["updatedAt"] == 3000
    # DELETE
    r = client.delete("/api/v1/plc/canvas/sessions/s-test-1", headers=H)
    assert r.status_code == 200
    assert client.get("/api/v1/plc/canvas/sessions/s-test-1", headers=H).status_code == 404


def test_session_validation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # 非法 id
    r = client.put(
        "/api/v1/plc/canvas/sessions/../escape", json={"id": "../escape"}, headers=H
    )
    assert r.status_code in (400, 404)
    # 缺 messages/canvas
    r = client.put(
        "/api/v1/plc/canvas/sessions/s-bad",
        json={"id": "s-bad", "title": "x"},
        headers=H,
    )
    assert r.status_code == 400
    # 不存在的会话:GET 404;DELETE 幂等成功(并记墓碑,防陈旧副本复活)
    assert client.get("/api/v1/plc/canvas/sessions/s-none", headers=H).status_code == 404
    assert client.delete("/api/v1/plc/canvas/sessions/s-none", headers=H).status_code == 200


def test_session_store_bad_files_skipped_in_list(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    root = session_store.sessions_root()
    (root / "s-good").mkdir(parents=True)
    (root / "s-good" / "meta.json").write_text(
        '{"id":"s-good","title":"ok","updatedAt":5}', encoding="utf-8"
    )
    (root / "s-broken").mkdir(parents=True)
    (root / "s-broken" / "meta.json").write_text("{ not json", encoding="utf-8")
    metas = session_store.list_sessions()
    assert [m["id"] for m in metas] == ["s-good"]


def test_tombstones_prevent_resurrection(tmp_path, monkeypatch):
    """删除写墓碑;墓碑表可查;同 id 重新 PUT 会清墓碑(合法复活)。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    from gateway.app.services.plc import session_store as ss

    sess = {
        "id": "s-t1",
        "title": "t",
        "createdAt": 1,
        "updatedAt": 2,
        "messages": [],
        "canvas": {"project_name": "P", "blocks": {}},
    }
    ss.put_session(sess)
    assert "s-t1" not in ss.list_tombstones()
    # 删除 → 墓碑 + 目录移除(幂等:再删一次仍成功)
    assert ss.delete_session("s-t1") is True
    assert ss.delete_session("s-t1") is True
    assert ss.list_tombstones().get("s-t1", 0) > 0
    assert ss.get_session("s-t1") is None
    # 墓碑后同 id 重新创建 → 墓碑清除
    ss.put_session(sess)
    assert "s-t1" not in ss.list_tombstones()
    assert ss.get_session("s-t1") is not None


def test_deleted_endpoint_and_idempotent_delete(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    sess = {
        "id": "s-x",
        "title": "x",
        "createdAt": 1,
        "updatedAt": 2,
        "messages": [],
        "canvas": {"project_name": "P", "blocks": {}},
    }
    client.put("/api/v1/plc/canvas/sessions/s-x", json=sess, headers=H)
    r = client.delete("/api/v1/plc/canvas/sessions/s-x", headers=H)
    assert r.status_code == 200
    # 幂等:重复 DELETE 不再 404
    r2 = client.delete("/api/v1/plc/canvas/sessions/s-x", headers=H)
    assert r2.status_code == 200
    # 墓碑端点
    r3 = client.get("/api/v1/plc/canvas/sessions/deleted", headers=H)
    assert r3.status_code == 200
    assert "s-x" in r3.json()["data"]["deleted"]
