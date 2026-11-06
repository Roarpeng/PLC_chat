"""J4 收口单测：7 种节点 patch op 经 ``POST /patch`` HTTP 路径被服务端真正接受。

证明收口接线后端到端可用（前端 NodeEditor op 形状 → IRPatch.from_dict →
_apply_node_op → validate_ir → apply_canvas_patch 原子提交 → 四视图重投影）：

- 服务端 ``IRPatch`` 原生形状（node / parent_id / label）7 种 op 全部 ok=True；
- 前端 NodeEditor 早期顶层负载形状（unit_id / em_id / business_label）双向兼容；
- 非法 op 整批拒绝（422），IR 字节不变（原子性不被接线破坏）。

本文件只覆盖新通道 /patch，不触发存量链、不建 PCEC 事务、真机一律不涉及。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.greenfield_session import registry

PREFIX = "/api/v1/plc/canvas/greenfield"


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset()
    yield
    registry.reset()


def _session(client: TestClient) -> str:
    sid = client.get(f"{PREFIX}/state?project_id=PRJ_PATCH").json()["data"]["session_id"]
    assert client.post(f"{PREFIX}/draft", json={"session_id": sid, "prompt": ""}).status_code == 200
    return sid


def _patch(client: TestClient, sid: str, ops: list[dict]) -> dict:
    resp = client.post(
        f"{PREFIX}/patch",
        json={"session_id": sid, "project_id": "PRJ_PATCH", "ops": ops},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["ok"] is True, data.get("reason") or data.get("violations")
    assert data["applied_ops"] == len(ops)
    assert isinstance(data.get("ir"), dict)
    return data


# 每个 case 独立会话，避免 op 之间互相污染；断言落到 IR 内容而非只看 ok。
_NATIVE_OPS = [
    ("add_unit", [{"op": "add_unit", "node": {"name": "S2", "business_label": "工位2"}}],
     lambda ir: len(ir["units"]) == 2),
    ("add_em", [{"op": "add_em", "parent_id": "U1", "node": {"name": "新工序", "business_label": "工序"}}],
     lambda ir: len(ir["ems"]) == 4),
    ("add_cm", [{"op": "add_cm", "parent_id": "U1EM1", "node": {"business_label": "新执行件"}}],
     lambda ir: len(ir["cms"]) == 4),
    ("remove_node", [{"op": "remove_node", "node_id": "U1EM2_CM3"}],
     lambda ir: len(ir["cms"]) == 2),
    ("rename_node", [{"op": "rename_node", "node_id": "U1", "name": "装配工位A"}],
     lambda ir: ir["units"][0]["name"] == "装配工位A"),
    ("relabel_node", [{"op": "relabel_node", "node_id": "U1", "label": "装配工位B"}],
     lambda ir: ir["units"][0]["business_label"] == "装配工位B"),
    # reparent 需要两个有效工站：先 add_unit 生成 U2，再把 U1EM1 重挂到 U2。
    ("reparent_node",
     [{"op": "add_unit", "node": {"name": "S2"}},
      {"op": "reparent_node", "node_id": "U1EM1", "parent_id": "U2"}],
     lambda ir: any(u["id"] == "U2" for u in ir["units"])
     and any(e["id"] == "U1EM1" and e["unit_id"] == "U2" for e in ir["ems"])),
]


@pytest.mark.parametrize("name,ops,check", _NATIVE_OPS, ids=[c[0] for c in _NATIVE_OPS])
def test_patch_7_node_ops_accepted_over_http(name, ops, check) -> None:
    """7 种 op 以服务端原生形状经 HTTP 提交，全部被接受且 IR 真实变化。"""
    client = TestClient(app)
    sid = _session(client)
    data = _patch(client, sid, ops)
    assert check(data["ir"]), f"{name} 未落到 IR"


def test_patch_frontend_legacy_shape_is_compatible() -> None:
    """前端 NodeEditor 早期顶层负载（unit_id / em_id / business_label）双向兼容。"""
    client = TestClient(app)
    sid = _session(client)
    data = _patch(client, sid, [
        {"op": "add_unit", "name": "S2", "business_label": "工位2"},
        {"op": "add_em", "unit_id": "U1", "name": "新工序", "business_label": "工序"},
        {"op": "add_cm", "em_id": "U1EM1", "business_label": "夹爪"},
        {"op": "relabel_node", "node_id": "U1", "business_label": "旧形状标签"},
    ])
    assert len(data["ir"]["units"]) == 2
    assert len(data["ir"]["ems"]) == 4
    assert len(data["ir"]["cms"]) == 4
    assert data["ir"]["units"][0]["business_label"] == "旧形状标签"


def test_patch_atomic_reject_keeps_ir() -> None:
    """一批中含非法 op → 422 + 整批回滚，IR 字节不变（接线未破坏原子拒绝）。"""
    client = TestClient(app)
    sid = _session(client)
    before = client.get(f"{PREFIX}/state?session_id={sid}").json()["data"]["ir"]
    resp = client.post(
        f"{PREFIX}/patch",
        json={"session_id": sid, "project_id": "PRJ_PATCH",
              "ops": [{"op": "rename_node", "node_id": "U1", "name": "应被回滚"},
                      {"op": "not_a_real_op"}]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "GF_PATCH_ATOMIC_REJECTED"
    after = client.get(f"{PREFIX}/state?session_id={sid}").json()["data"]["ir"]
    assert after == before
