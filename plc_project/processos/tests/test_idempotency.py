"""§8 tests: Idempotency-Key replay on the mutating POST endpoints.

同 key 同 body 重放返回首次响应且 store 无重复副作用（revision/job/record
不再增加）；同 key 不同 body → 409；不带 key 行为不变。缓存为进程内 dict
（非分布式，见 IdempotencyMiddleware docstring）——这里验证的是单进程语义。
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from processos.api.app import create_app
from processos.contract import clamp_contract

PID = "PRJ_CLAMP"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def client(tmp_path) -> TestClient:
    return TestClient(create_app(db=tmp_path / "idem.sqlite3"))


def _patch_body(request_id: str, base_revision: int = 1, value: int = 5) -> dict:
    return {"base_revision": base_revision, "request_id": request_id, "source": "user",
            "ops": [{"op": "set", "path": "/resources/CM_CLAMP_CYL/params/P1",
                     "value": value}]}


# ---------- patches：同 key 重放，store 无重复副作用 ----------

def test_patch_same_key_same_body_replays_without_side_effect(client):
    client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    url = f"/api/processos/projects/{PID}/patches"
    body = _patch_body("r1")

    r1 = client.post(url, json=body, headers={"Idempotency-Key": "k1"})
    assert r1.status_code == 200 and r1.json()["revision"] == 2
    assert r1.headers.get("idempotency-replayed") is None  # 首次执行，非重放

    r2 = client.post(url, json=body, headers={"Idempotency-Key": "k1"})
    assert r2.status_code == 200
    assert r2.json() == r1.json()  # 首次结果原样返回
    assert r2.headers.get("idempotency-replayed") == "true"
    # store 无重复副作用：revision 停在 2，没有再 +1。
    assert client.get(f"/api/processos/projects/{PID}").json()["revision"] == 2


def test_patch_different_key_executes_and_same_key_different_body_conflicts(client):
    client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    url = f"/api/processos/projects/{PID}/patches"

    r1 = client.post(url, json=_patch_body("r1"), headers={"Idempotency-Key": "k1"})
    assert r1.json()["revision"] == 2
    # 不同 key = 不同幂等请求 → 真执行。
    r2 = client.post(url, json=_patch_body("r2", base_revision=2, value=6),
                     headers={"Idempotency-Key": "k2"})
    assert r2.json()["revision"] == 3
    # 同 key 不同 body → 409（fail-closed，不猜调用方意图）。
    r3 = client.post(url, json=_patch_body("r3", base_revision=3, value=7),
                     headers={"Idempotency-Key": "k1"})
    assert r3.status_code == 409
    assert r3.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert client.get(f"/api/processos/projects/{PID}").json()["revision"] == 3


def test_patch_without_key_behaves_unchanged(client):
    client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    url = f"/api/processos/projects/{PID}/patches"
    assert client.post(url, json=_patch_body("a")).json()["revision"] == 2
    assert client.post(url, json=_patch_body("b", base_revision=2)).json()["revision"] == 3


def test_same_key_different_actor_header_conflicts(client):
    """重放指纹包含 X-Actor-*：换人重放同一 key 不是免检通道。"""
    client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    url = "/api/processos/deployments/records"
    body = {"project_id": PID, "build_id": "build_219",
            "artifact_sha256": sha(b"zap"), "device_id": "PLC_1", "operator": "eng-1"}
    h1 = {"Idempotency-Key": "dep-1", "X-Actor-Id": "cm-1",
          "X-Actor-Role": "CommissioningEngineer"}
    h2 = {"Idempotency-Key": "dep-1", "X-Actor-Id": "cm-2",
          "X-Actor-Role": "CommissioningEngineer"}
    assert client.post(url, json=body, headers=h1).status_code == 200
    assert client.post(url, json=body, headers=h2).status_code == 409


# ---------- deployments/records：登记不重复 ----------

def test_deployment_record_same_key_replays_single_record(client):
    client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    url = "/api/processos/deployments/records"
    body = {"project_id": PID, "build_id": "build_219",
            "artifact_sha256": sha(b"zap-archive"), "device_id": "PLC_1",
            "operator": "eng-1", "result": "COMMISSIONED"}
    headers = {"Idempotency-Key": "dep-1", "X-Actor-Id": "cm-1",
               "X-Actor-Role": "CommissioningEngineer"}

    r1 = client.post(url, json=body, headers=headers)
    assert r1.status_code == 200
    r2 = client.post(url, json=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["record_id"] == r1.json()["record_id"]
    assert r2.headers.get("idempotency-replayed") == "true"
    records = client.get(url, params={"project_id": PID}).json()["records"]
    assert len(records) == 1  # 台账无重复登记


def test_deployment_record_without_key_duplicates_normally(client):
    client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    url = "/api/processos/deployments/records"
    body = {"project_id": PID, "build_id": "build_219",
            "artifact_sha256": sha(b"zap-archive"), "device_id": "PLC_1",
            "operator": "eng-1"}
    headers = {"X-Actor-Id": "cm-1", "X-Actor-Role": "CommissioningEngineer"}
    client.post(url, json=body, headers=headers)
    client.post(url, json=body, headers=headers)  # 无 key：两次都执行
    assert len(client.get(url, params={"project_id": PID}).json()["records"]) == 2


# ---------- deliveries：JOB 不重复创建 ----------

def test_delivery_same_key_replays_single_job(client):
    client.post("/api/processos/projects",
                json={"contract": clamp_contract(with_blocking_question=False).to_dict()})
    # 走通审批门禁：freeze → approve（审批者与修改者分离）→ deliver。
    cs = client.post(f"/api/processos/projects/{PID}/changesets").json()
    apr = client.post(f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve",
                      headers={"X-Actor-Id": "rev-1", "X-Actor-Role": "Reviewer"},
                      json={"by": "field-eng"})
    assert apr.status_code == 200
    url = f"/api/processos/projects/{PID}/deliveries"
    headers = {"Idempotency-Key": "del-1", "X-Actor-Id": "bld-1",
               "X-Actor-Role": "Builder"}

    r1 = client.post(url, headers=headers)
    assert r1.status_code == 200
    r2 = client.post(url, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]
    assert r2.headers.get("idempotency-replayed") == "true"
    # store 里只有一个 delivery job（重复触发未创建第二个）。
    assert len(client.app.state.store.projects[PID].jobs) == 1


# ---------- 范围外端点不受影响 ----------

def test_out_of_scope_post_ignores_the_header(client):
    """带 key 但端点不在 §8 范围内：不缓存、不重放、行为不变。"""
    r1 = client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()},
                     headers={"Idempotency-Key": "k9"})
    r2 = client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()},
                     headers={"Idempotency-Key": "k9"})
    assert r1.status_code == 200  # 重复 project id -> 第二次 422（未被幂等吞掉）
    assert r2.status_code == 422
