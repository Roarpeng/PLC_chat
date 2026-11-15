"""§4 租约式项目写锁（缺口 4）：互斥 409、过期夺取、release 再取、renew、
持久化 roundtrip、HTTP 三端点 X-Lock-Owner 接入、无头（anonymous）兼容。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.contract import clamp_contract
from processos.locks import ProjectLockManager

PID = "PRJ_CLAMP"


# ---------- ProjectLockManager 单元（进程内） ----------

def test_acquire_mutual_exclusion_and_reentrant_refresh():
    mgr = ProjectLockManager()
    a1 = mgr.acquire(PID, "alice")
    assert a1["ok"] and a1["lock_id"].startswith("LCK-") and a1["expires_at"]
    blocked = mgr.acquire(PID, "bob")
    assert blocked["ok"] is False
    assert blocked["holder"] == "alice" and blocked["expires_at"] == a1["expires_at"]
    again = mgr.acquire(PID, "alice")  # 重入：同 owner 幂等，沿用 lock_id
    assert again["ok"] and again["lock_id"] == a1["lock_id"]


def test_expired_lease_can_be_taken_over():
    mgr = ProjectLockManager()
    a = mgr.acquire(PID, "alice", lease_seconds=0)  # 立即过期
    assert a["ok"]
    b = mgr.acquire(PID, "bob")  # 过期租约可夺取（故障恢复=超时自动释放）
    assert b["ok"] and b["lock_id"] != a["lock_id"]
    assert mgr.status(PID)["holder"] == "bob"


def test_release_then_reacquire_and_non_holder_cannot_release():
    mgr = ProjectLockManager()
    mgr.acquire(PID, "alice")
    denied = mgr.release(PID, "bob")
    assert denied["ok"] is False and denied["holder"] == "alice"
    ok = mgr.release(PID, "alice")
    assert ok["ok"] and ok["released"] is True
    assert mgr.status(PID) == {"locked": False}
    nxt = mgr.acquire(PID, "bob")  # release 后可再取
    assert nxt["ok"]


def test_renew_extends_only_live_holder_lease():
    mgr = ProjectLockManager()
    mgr.acquire(PID, "alice", lease_seconds=60)
    denied = mgr.renew(PID, "bob")
    assert denied["ok"] is False
    ok = mgr.renew(PID, "alice", lease_seconds=600)
    assert ok["ok"] and ok["expires_at"] >= mgr.status(PID)["expires_at"]
    assert mgr.renew(PID, "alice")["ok"] is True  # 持有者可反复续约

    # 过期租约被夺取后：新持有者可续约，旧持有者不能
    mgr2 = ProjectLockManager()
    a = mgr2.acquire("PRJ_X", "alice", lease_seconds=0)  # 立即过期
    assert a["ok"]
    assert mgr2.acquire("PRJ_X", "bob")["ok"] is True  # 夺取
    assert mgr2.renew("PRJ_X", "bob", 600)["ok"] is True
    assert mgr2.renew("PRJ_X", "alice")["ok"] is False  # alice 已不是持有者


def test_negative_lease_rejected():
    mgr = ProjectLockManager()
    with pytest.raises(ValueError):
        mgr.acquire(PID, "alice", lease_seconds=-5)


def test_blank_owner_normalizes_to_anonymous():
    mgr = ProjectLockManager()
    got = mgr.acquire(PID, "   ")
    assert got["ok"] and got["holder"] == "anonymous"


# ---------- 持久化 roundtrip（JsonDao namespace "locks"） ----------

def test_persistence_roundtrip_across_manager_instances(tmp_path):
    db = str(tmp_path / "locks.sqlite3")
    m1 = ProjectLockManager(db=db)
    a = m1.acquire(PID, "alice", lease_seconds=900)
    assert a["ok"]

    m2 = ProjectLockManager(db=db)  # 新实例（模拟重启后）看到同一租约
    blocked = m2.acquire(PID, "bob")
    assert blocked["ok"] is False and blocked["holder"] == "alice"
    assert m2.status(PID) == {"locked": True, "expired": False, "holder": "alice",
                              "lock_id": a["lock_id"],
                              "expires_at": a["expires_at"]}
    assert m1.release(PID, "alice")["ok"] is True
    assert m2.acquire(PID, "bob")["ok"] is True  # 释放后他人可取


# ---------- HTTP 接入：patches / deliveries / approve ----------

REVIEWER = {"X-Actor-Id": "reviewer_wang", "X-Actor-Role": "Reviewer"}
BUILDER = {"X-Actor-Id": "builder_li", "X-Actor-Role": "Builder"}


@pytest.fixture()
def env(tmp_path):
    app = create_app(ProjectStore(), db=tmp_path / "http.sqlite3")
    client = TestClient(app)
    r = client.post("/api/processos/projects",
                    json={"contract": clamp_contract(with_blocking_question=False).to_dict()})
    assert r.status_code == 200, r.text
    yield {"app": app, "client": client}
    app.state.trace.close()


_PATCH = {"base_revision": 1, "request_id": "r1",
          "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_HOLD/duration_ms",
                   "value": 2500}]}


def test_http_lock_held_conflict_and_release(env):
    client = env["client"]
    mgr = env["app"].state.locks
    held = mgr.acquire(PID, "owner_a", lease_seconds=300)
    assert held["ok"]

    other = {"X-Lock-Owner": "owner_b"}
    r = client.post(f"/api/processos/projects/{PID}/patches", json=_PATCH, headers=other)
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "LOCK_HELD" and body["holder"] == "owner_a"
    assert body["expires_at"] == held["expires_at"]
    assert client.get(f"/api/processos/projects/{PID}").json()["revision"] == 1  # 无副作用

    assert mgr.release(PID, "owner_a")["ok"]
    r2 = client.post(f"/api/processos/projects/{PID}/patches", json=_PATCH, headers=other)
    assert r2.status_code == 200 and r2.json()["revision"] == 2
    assert mgr.status(PID) == {"locked": False}  # 请求结束自动 release


def test_http_lock_owner_himself_passes_and_lock_falls_back_to_actor_id(env):
    client = env["client"]
    mgr = env["app"].state.locks
    assert mgr.acquire(PID, "owner_a", lease_seconds=300)["ok"]
    # 持有者本人（X-Lock-Owner）请求放行（重入），请求结束释放
    r = client.post(f"/api/processos/projects/{PID}/patches",
                    json=_PATCH, headers={"X-Lock-Owner": "owner_a"})
    assert r.status_code == 200
    assert mgr.status(PID) == {"locked": False}

    # 缺省 X-Lock-Owner 时用 X-Actor-Id 作为 owner
    assert mgr.acquire(PID, "eng_x", lease_seconds=300)["ok"]
    blocked = client.post(f"/api/processos/projects/{PID}/patches",
                          json=dict(_PATCH, base_revision=2, request_id="r2"),
                          headers={"X-Actor-Id": "eng_y"})
    assert blocked.status_code == 409 and blocked.json()["holder"] == "eng_x"
    assert mgr.release(PID, "eng_x")["ok"]
    ok = client.post(f"/api/processos/projects/{PID}/patches",
                     json=dict(_PATCH, base_revision=2, request_id="r2"),
                     headers={"X-Actor-Id": "eng_y"})
    assert ok.status_code == 200


def test_http_deliveries_and_approve_locked(env):
    client = env["client"]
    mgr = env["app"].state.locks
    cs = client.post(f"/api/processos/projects/{PID}/changesets").json()

    assert mgr.acquire(PID, "owner_z", lease_seconds=300)["ok"]
    ap = client.post(f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve",
                     headers=REVIEWER | {"X-Lock-Owner": "owner_other"},
                     json={"by": "engineer_zhao"})
    assert ap.status_code == 409 and ap.json()["code"] == "LOCK_HELD"

    dl = client.post(f"/api/processos/projects/{PID}/deliveries",
                     headers=BUILDER | {"X-Lock-Owner": "owner_other"})
    assert dl.status_code == 409 and dl.json()["code"] == "LOCK_HELD"
    mgr.release(PID, "owner_z")

    # 释放后正常走通（审批 + 构建）
    ap2 = client.post(f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve",
                      headers=REVIEWER, json={"by": "engineer_zhao"})
    assert ap2.status_code == 200
    job = client.post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
    assert job.status_code == 200 and job.json()["status"] == "QUEUED"


def test_http_no_header_requests_self_lock_and_release(env):
    """无头（anonymous）连续变更请求不受锁阻塞（每请求自取自放）。"""
    client = env["client"]
    for i, base in enumerate((1, 2, 3), start=1):
        r = client.post(f"/api/processos/projects/{PID}/patches",
                        json=dict(_PATCH, base_revision=base, request_id=f"seq{i}"))
        assert r.status_code == 200, r.text
    assert client.get(f"/api/processos/projects/{PID}").json()["revision"] == 4
    assert env["app"].state.locks.status(PID) == {"locked": False}
