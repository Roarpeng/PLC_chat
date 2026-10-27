"""Project / Conversation 两层存储(P 线,契约 docs/25 §1):CRUD 往返、级联删除、迁移幂等。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from gateway.app.main import create_app
from gateway.app.services.plc import project_store, session_store

H = {"X-API-Key": "ros_ak_dev_change_me"}


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    return TestClient(create_app())


def _proj(pid: str = "prj-aaa111bbb222", name: str = "HR001") -> dict:
    return {
        "id": pid,
        "project_name": name,
        "canvas": {
            "project_name": name,
            "blocks": {"B1": {"name": "B1"}},
            "hmi_widgets": {},
            "tags": {},
        },
        "created_at": 1000.0,
        "updated_at": 2000.0,
    }


def _conv(cid: str, pid: str, title: str = "对话一") -> dict:
    return {
        "id": cid,
        "project_id": pid,
        "title": title,
        "messages": [{"id": "m1", "role": "user", "text": "分析项目", "ts": 1500}],
        "created_at": 1200.0,
        "updated_at": 1800.0,
    }


# ---------------- 存储层 ----------------


def test_project_crud_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    meta = project_store.put_project(_proj())
    # meta 轻量:canvas 不进 meta
    assert meta == {"id": "prj-aaa111bbb222", "name": "HR001", "updated_at": 2000.0, "conversation_count": 0}
    assert "canvas" not in meta
    lst = project_store.list_projects()
    assert len(lst) == 1 and lst[0]["name"] == "HR001"
    # 完整对象含 canvas + 实时 count
    full = project_store.get_project("prj-aaa111bbb222")
    assert full is not None and full["canvas"]["blocks"]["B1"]["name"] == "B1"
    assert full["conversation_count"] == 0
    # 覆盖更新
    p2 = _proj()
    p2["canvas"]["blocks"]["B2"] = {"name": "B2"}
    p2["updated_at"] = 3000.0
    project_store.put_project(p2)
    assert project_store.get_project("prj-aaa111bbb222")["canvas"]["blocks"]["B2"]["name"] == "B2"
    assert project_store.list_projects()[0]["updated_at"] == 3000.0
    # 删除幂等
    assert project_store.delete_project("prj-aaa111bbb222") == 0
    assert project_store.delete_project("prj-aaa111bbb222") == 0
    assert project_store.get_project("prj-aaa111bbb222") is None


def test_conversation_crud_and_count_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    project_store.put_project(_proj())
    project_store.put_conversation(_conv("cv-111111111111", "prj-aaa111bbb222"))
    project_store.put_conversation(_conv("cv-222222222222", "prj-aaa111bbb222", "对话二"))
    # put_project 重算 conversation_count(遍历 conversations meta 过滤 project_id)
    meta = project_store.put_project(_proj())
    assert meta["conversation_count"] == 2
    # 对话增删也同步所属工程 count
    project_store.put_conversation(_conv("cv-333333333333", "prj-aaa111bbb222", "对话三"))
    assert project_store.list_projects()[0]["conversation_count"] == 3
    assert project_store.delete_conversation("cv-333333333333") is True
    assert project_store.list_projects()[0]["conversation_count"] == 2
    # 列表只含该工程的对话 meta,按 updated_at 降序
    metas = project_store.list_conversations("prj-aaa111bbb222")
    assert [m["id"] for m in metas] == ["cv-111111111111", "cv-222222222222"]
    assert all("messages" not in m and "canvas" not in m for m in metas)
    # 完整对话含 messages、不含 canvas
    full = project_store.get_conversation("cv-111111111111")
    assert full is not None
    assert full["messages"][0]["text"] == "分析项目"
    assert "canvas" not in full
    assert project_store.get_conversation("cv-none") is None


def test_delete_project_cascades_conversations(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    project_store.put_project(_proj("prj-keep0000001", "保留工程"))
    project_store.put_project(_proj("prj-drop0000001", "删除工程"))
    project_store.put_conversation(_conv("cv-keep00000001", "prj-keep0000001"))
    project_store.put_conversation(_conv("cv-keep00000002", "prj-keep0000001"))
    project_store.put_conversation(_conv("cv-drop00000001", "prj-drop0000001"))
    cascaded = project_store.delete_project("prj-drop0000001")
    assert cascaded == 1
    assert project_store.get_conversation("cv-drop00000001") is None
    # 其他工程与其对话不受影响
    assert project_store.get_project("prj-keep0000001") is not None
    assert len(project_store.list_conversations("prj-keep0000001")) == 2
    assert project_store.list_projects()[0]["conversation_count"] == 2


def test_store_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    import pytest

    # 非法 id / 缺 project_name / 缺 canvas
    with pytest.raises(ValueError):
        project_store.put_project({"id": "../escape", "project_name": "x", "canvas": {}})
    with pytest.raises(ValueError):
        project_store.put_project({"id": "prj-ok0000000001", "project_name": "  ", "canvas": {}})
    with pytest.raises(ValueError):
        project_store.put_project({"id": "prj-ok0000000001", "project_name": "x"})
    # 对话:非法 id / 缺 project_id / 缺 messages
    with pytest.raises(ValueError):
        project_store.put_conversation({"id": "bad id!", "project_id": "p", "messages": []})
    with pytest.raises(ValueError):
        project_store.put_conversation({"id": "cv-ok0000000001", "messages": []})
    with pytest.raises(ValueError):
        project_store.put_conversation({"id": "cv-ok0000000001", "project_id": "prj-x00000000001"})
    assert project_store.get_project("../escape") is None
    assert project_store.delete_project("../escape") is None
    assert project_store.delete_conversation("bad id!") is None


def test_bad_meta_files_skipped_in_list(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    proot = project_store.projects_root()
    (proot / "prj-good00000001").mkdir(parents=True)
    (proot / "prj-good00000001" / "meta.json").write_text(
        '{"id":"prj-good00000001","name":"ok","updated_at":5,"conversation_count":0}',
        encoding="utf-8",
    )
    (proot / "prj-broken0000001").mkdir(parents=True)
    (proot / "prj-broken0000001" / "meta.json").write_text("{ not json", encoding="utf-8")
    assert [m["id"] for m in project_store.list_projects()] == ["prj-good00000001"]


def test_new_ids_shape():
    pid = project_store.new_project_id()
    cid = project_store.new_conversation_id()
    assert pid.startswith("prj-") and len(pid) == 16
    assert cid.startswith("cv-") and len(cid) == 15


# ---------------- 迁移 ----------------


def _old_session(sid: str, title: str, canvas_name: str, n_msgs: int) -> dict:
    return {
        "id": sid,
        "title": title,
        "createdAt": 100.0,
        "updatedAt": 200.0,
        "messages": [
            {"id": f"{sid}-m{i}", "role": "user", "text": "问", "ts": 150.0}
            for i in range(n_msgs)
        ],
        "canvas": {
            "project_name": canvas_name,
            "blocks": {"B0": {"name": "B0"}} if n_msgs else {},
            "hmi_widgets": {},
            "tags": {},
        },
    }


def test_migrate_from_sessions_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    # 两个 session 同属 HR001(canvas.project_name),第三个从标题「·」后段取工程名
    session_store.put_session(_old_session("s-hr1", "会话一", "HR001", 2))
    session_store.put_session(_old_session("s-hr2", "会话二", "HR001", 1))
    session_store.put_session(_old_session("s-imp", "导入 · 夹紧工站", "", 0))

    stats = project_store.migrate_from_sessions()
    assert stats == {"projects_migrated": 2, "conversations_migrated": 3}
    # 工程归并正确,画布取自首个 session
    metas = {m["name"]: m for m in project_store.list_projects()}
    assert set(metas) == {"HR001", "夹紧工站"}
    assert metas["HR001"]["conversation_count"] == 2
    hr = project_store.get_project(metas["HR001"]["id"])
    assert hr["canvas"]["project_name"] == "HR001" and "B0" in hr["canvas"]["blocks"]
    # 对话沿用原 session id,消息迁移,画布不进对话
    conv = project_store.get_conversation("s-hr1")
    assert conv is not None
    assert conv["project_id"] == metas["HR001"]["id"]
    assert len(conv["messages"]) == 2 and "canvas" not in conv
    # 幂等:二次运行按 project_name 匹配 + session id 识别,全部跳过
    assert project_store.migrate_from_sessions() == {
        "projects_migrated": 0,
        "conversations_migrated": 0,
    }
    assert len(project_store.list_projects()) == 2


# ---------------- API 路由 ----------------


def test_project_api_roundtrip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    base = "/api/v1/plc/canvas"
    # POST 新建(未传 canvas → 空白画布)
    r = client.post(f"{base}/projects", json={"project_name": "HR001"}, headers=H)
    assert r.status_code == 200, r.text
    proj = r.json()["data"]
    pid = proj["id"]
    assert pid.startswith("prj-") and proj["canvas"]["project_name"] == "HR001"
    # GET 列表(meta,无 canvas)
    r = client.get(f"{base}/projects", headers=H)
    assert [m["id"] for m in r.json()["data"]] == [pid]
    assert "canvas" not in r.json()["data"][0]
    # PUT 更新(整对象 upsert)
    proj["canvas"]["blocks"]["B1"] = {"name": "B1"}
    proj["updated_at"] = 9999.0
    r = client.put(f"{base}/projects/{pid}", json=proj, headers=H)
    assert r.status_code == 200 and r.json()["data"]["name"] == "HR001"
    assert client.get(f"{base}/projects/{pid}", headers=H).json()["data"]["canvas"]["blocks"]["B1"]
    # POST 空对话 / 列表 / 完整
    r = client.post(f"{base}/projects/{pid}/conversations", json={"title": "工艺讨论"}, headers=H)
    assert r.status_code == 200, r.text
    cid = r.json()["data"]["id"]
    assert cid.startswith("cv-") and r.json()["data"]["messages"] == []
    r = client.get(f"{base}/projects/{pid}/conversations", headers=H)
    assert [m["id"] for m in r.json()["data"]] == [cid]
    # PUT 对话(只带消息)
    conv = r.json()["data"][0]
    conv["messages"] = [{"id": "m1", "role": "user", "text": "hi", "ts": 1}]
    r = client.put(f"{base}/conversations/{cid}", json=conv, headers=H)
    assert r.status_code == 200
    full = client.get(f"{base}/conversations/{cid}", headers=H).json()["data"]
    assert full["messages"][0]["text"] == "hi" and "canvas" not in full
    # 工程计数同步
    assert client.get(f"{base}/projects/{pid}", headers=H).json()["data"]["conversation_count"] == 1
    # DELETE 对话 → 计数回落
    assert client.delete(f"{base}/conversations/{cid}", headers=H).status_code == 200
    assert client.get(f"{base}/conversations/{cid}", headers=H).status_code == 404
    assert client.get(f"{base}/projects/{pid}", headers=H).json()["data"]["conversation_count"] == 0
    # DELETE 工程 → 级联 + 二次删除幂等
    client.post(f"{base}/projects/{pid}/conversations", json={"title": "x"}, headers=H)
    r = client.delete(f"{base}/projects/{pid}", headers=H)
    assert r.status_code == 200 and r.json()["data"]["conversations_removed"] == 1
    assert client.get(f"{base}/projects/{pid}", headers=H).status_code == 404
    assert client.delete(f"{base}/projects/{pid}", headers=H).status_code == 200


def test_project_api_validation_and_migrate(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    base = "/api/v1/plc/canvas"
    # 缺 project_name → 400
    r = client.post(f"{base}/projects", json={}, headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PLC_PROJECT_INVALID"
    # PUT 缺 canvas → 400
    r = client.put(
        f"{base}/projects/prj-x00000000001", json={"id": "prj-x00000000001", "project_name": "x"}, headers=H
    )
    assert r.status_code == 400
    # PUT 对话缺 messages → 400
    r = client.put(
        f"{base}/conversations/cv-x00000000001",
        json={"id": "cv-x00000000001", "project_id": "prj-x00000000001"},
        headers=H,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PLC_CONVERSATION_INVALID"
    # 不存在:GET 404;DELETE 幂等成功(对齐 sessions 语义,防陈旧副本复活式抖动)
    assert client.get(f"{base}/projects/prj-none00000001", headers=H).status_code == 404
    assert client.get(f"{base}/conversations/cv-none00000001", headers=H).status_code == 404
    assert client.delete(f"{base}/conversations/cv-none00000001", headers=H).status_code == 200
    # 在不存在的工程下建对话 → 404
    r = client.post(f"{base}/projects/prj-none00000001/conversations", json={"title": "x"}, headers=H)
    assert r.status_code == 404
    # 迁移端点:造旧 session → POST migrate → 幂等
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    session_store.put_session(_old_session("s-api1", "会话", "API工程", 1))
    r = client.post(f"{base}/projects/migrate", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"projects_migrated": 1, "conversations_migrated": 1}
    r = client.post(f"{base}/projects/migrate", headers=H)
    assert r.json()["data"] == {"projects_migrated": 0, "conversations_migrated": 0}
    names = [m["name"] for m in client.get(f"{base}/projects", headers=H).json()["data"]]
    assert names == ["API工程"]
