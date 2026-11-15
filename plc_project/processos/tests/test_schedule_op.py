"""需求 c（Unit 级编排）最小 op：``set_operation_schedule``。

声明 EM（工位/操作）的执行顺序、资源占用与并行组，写入契约层 ``schedule``
可选字段并把 resource_ids 落到对应 operation；构造期与执行期双重校验，
negative 全覆盖（fail-closed，模式沿用 test_scenario_timing_op）。
"""
from __future__ import annotations

import pytest

from processos.contract import Patch, PatchOp, clamp_contract
from processos.contract.model import Operation, ProcessContract, Resource
from processos.contract.patch import PATCH_OPS, PatchError, apply_patch


def _multi_em_contract() -> ProcessContract:
    """Clamp 契约 + 送料/压装两个 EM（多工位编排的最小真实形状）。"""
    c = clamp_contract()
    res_feed = Resource(id="CM_FEED_CYL", name="送料气缸", kind="cylinder",
                        commands=["Extend", "Retract"], feedback=["Extended", "Retracted"])
    res_press = Resource(id="CM_PRESS_CYL", name="压装机", kind="press",
                         commands=["Press"], feedback=["Pressed"])
    feed = Operation(id="OP_FEED", name="送料", unit="U_ASSEMBLY",
                     em="EM_FEED", resource_ids=["CM_FEED_CYL"])
    press = Operation(id="OP_PRESS", name="压装", unit="U_ASSEMBLY",
                      em="EM_PRESS", resource_ids=["CM_PRESS_CYL"])
    return ProcessContract(
        id=c.id, name=c.name, target_framework=c.target_framework, unit=c.unit,
        resources=[*c.resources, res_feed, res_press],
        operations=[*c.operations, feed, press],
        invariants=c.invariants, open_questions=c.open_questions,
        scenarios=c.scenarios, provenance=c.provenance,
    )


def _legal_schedule() -> list[dict]:
    return [
        {"em": "EM_FEED", "order": 0, "resource_ids": ["CM_FEED_CYL"]},
        {"em": "EM_CLAMP", "order": 1, "resource_ids": ["CM_CLAMP_CYL"],
         "parallel_with": ["EM_PRESS"]},
        {"em": "EM_PRESS", "order": 2, "resource_ids": ["CM_PRESS_CYL"],
         "parallel_with": ["EM_CLAMP"], "mode": "auto"},
    ]


def _sched_op(schedule=None, **overrides):
    kwargs = {"op": "set_operation_schedule", "path": "/schedule",
              "value": _legal_schedule() if schedule is None else schedule}
    kwargs.update(overrides)
    return PatchOp(kwargs["op"], kwargs["path"], kwargs["value"])


# ---------- positive ----------

def test_schedule_op_in_patch_ops_whitelist():
    assert "set_operation_schedule" in PATCH_OPS


def test_schedule_op_applies_declaration_and_materializes_resources():
    patched, rev = apply_patch(
        _multi_em_contract(), Patch(base_revision=1, ops=[_sched_op()]), 1)
    assert rev == 2
    assert [e["em"] for e in patched.schedule] == ["EM_FEED", "EM_CLAMP", "EM_PRESS"]
    assert patched.schedule[0]["order"] == 0
    assert patched.schedule[1]["parallel_with"] == ["EM_PRESS"]
    assert patched.schedule[2]["mode"] == "auto"
    # resource_ids 落到对应 operation（契约层语义承载）
    feed = next(o for o in patched.operations if o.em == "EM_FEED")
    assert feed.resource_ids == ["CM_FEED_CYL"]
    clamp = next(o for o in patched.operations if o.em == "EM_CLAMP")
    assert clamp.resource_ids == ["CM_CLAMP_CYL"]
    # 规范化：条目缺省字段补齐为确定形状（往返无损的前提）
    assert patched.schedule[0] == {"em": "EM_FEED", "order": 0,
                                   "resource_ids": ["CM_FEED_CYL"],
                                   "mode": "", "parallel_with": []}


def test_schedule_op_roundtrip_and_contract_dict_lossless():
    patched, _ = apply_patch(
        _multi_em_contract(), Patch(base_revision=1, ops=[_sched_op()]), 1)
    doc = patched.to_dict()
    assert ProcessContract.from_dict(doc).to_dict() == doc  # from_dict/to_dict 往返无损
    op = PatchOp.from_dict({"op": "set_operation_schedule", "schedule": _legal_schedule()})
    assert op.path == "/schedule"  # 缺省 path 规范化为 /schedule
    d = op.to_dict()
    assert d["op"] == "set_operation_schedule" and d["schedule"] == _legal_schedule()
    assert PatchOp.from_dict(d).value == _legal_schedule()  # op 字典形状往返


def test_schedule_op_overwrite_and_empty_clears():
    c = _multi_em_contract()
    patched, _ = apply_patch(c, Patch(base_revision=1, ops=[_sched_op()]), 1)
    empty = [{"em": "EM_CLAMP", "order": 0, "resource_ids": []}]
    patched2, _ = apply_patch(
        patched, Patch(base_revision=2, ops=[_sched_op(empty)]), 2)
    assert patched2.schedule == [{"em": "EM_CLAMP", "order": 0,
                                  "resource_ids": [], "mode": "", "parallel_with": []}]
    patched3, _ = apply_patch(
        patched2, Patch(base_revision=3, ops=[_sched_op([])]), 3)  # 空调度=显式清空
    assert patched3.schedule == []


# ---------- negative（构造期校验：fail-closed） ----------

@pytest.mark.parametrize("schedule,match", [
    ("not-a-list", "schedule' list"),
    (["not-an-object"], "must be an object"),
    ([{"order": 0, "resource_ids": []}], "non-empty 'em'"),
    ([{"em": "", "order": 0, "resource_ids": []}], "non-empty 'em'"),
    ([{"em": 7, "order": 0, "resource_ids": []}], "non-empty 'em'"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": []},
      {"em": "EM_FEED", "order": 1, "resource_ids": []}], "duplicate em"),
    ([{"em": "EM_FEED", "order": "0", "resource_ids": []}], "non-negative integer"),
    ([{"em": "EM_FEED", "order": True, "resource_ids": []}], "non-negative integer"),
    ([{"em": "EM_FEED", "order": -1, "resource_ids": []}], "non-negative integer"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": []},
      {"em": "EM_CLAMP", "order": 0, "resource_ids": []}], "duplicate order"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": "CM_FEED_CYL"}], "list of strings"),
    ([{"em": "EM_FEED", "order": 0}], "list of strings"),          # 缺 resource_ids
    ([{"em": "EM_FEED", "order": 0, "resource_ids": [], "mode": 3}], "'mode' must be a string"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": [],
       "parallel_with": "EM_CLAMP"}], "list of strings"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": [],
       "parallel_with": ["EM_FEED"]}], "must not name itself"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": [],
       "parallel_with": ["EM_CLAMP", "EM_CLAMP"]}], "duplicate ems"),
    ([{"em": "EM_FEED", "order": 0, "resource_ids": [], "extra": 1}], "unknown fields"),
])
def test_schedule_op_construction_rejects_bad_input(schedule, match):
    with pytest.raises(PatchError, match=match):
        _sched_op(schedule)


# ---------- negative（执行期校验：对 live 契约文档） ----------

def test_schedule_op_unknown_em_rejected():
    with pytest.raises(PatchError, match="no operation with em 'EM_NOPE'"):
        apply_patch(_multi_em_contract(), Patch(base_revision=1, ops=[
            _sched_op([{"em": "EM_NOPE", "order": 0, "resource_ids": []}])]), 1)


def test_schedule_op_unknown_resource_rejected():
    with pytest.raises(PatchError, match="unknown resource 'CM_GHOST'"):
        apply_patch(_multi_em_contract(), Patch(base_revision=1, ops=[
            _sched_op([{"em": "EM_CLAMP", "order": 0, "resource_ids": ["CM_GHOST"]}])]), 1)


def test_schedule_op_parallel_with_unknown_em_rejected():
    with pytest.raises(PatchError, match="parallel_with unknown em 'EM_GHOST'"):
        apply_patch(_multi_em_contract(), Patch(base_revision=1, ops=[
            _sched_op([{"em": "EM_CLAMP", "order": 0, "resource_ids": [],
                        "parallel_with": ["EM_GHOST"]}])]), 1)


def test_schedule_op_ambiguous_em_rejected():
    c = _multi_em_contract()
    twin = Operation(id="OP_CLAMP_2", name="重复 EM", unit="U_ASSEMBLY",
                     em="EM_CLAMP", resource_ids=[])
    c2 = ProcessContract(
        id=c.id, name=c.name, target_framework=c.target_framework, unit=c.unit,
        resources=c.resources, operations=[*c.operations, twin],
        invariants=c.invariants, open_questions=c.open_questions,
        scenarios=c.scenarios, provenance=c.provenance)
    with pytest.raises(PatchError, match="ambiguous em 'EM_CLAMP'"):
        apply_patch(c2, Patch(base_revision=1, ops=[_sched_op()]), 1)


# ---------- 原子性（与其他 op 混合 patch：fail-closed，契约不被部分污染） ----------

def test_schedule_op_mixed_patch_atomic_fail_closed():
    c = _multi_em_contract()
    before = c.to_dict()
    bad = Patch(base_revision=1, ops=[
        PatchOp("set", "/name", "改名会被整体回滚"),
        _sched_op([{"em": "EM_NOPE", "order": 0, "resource_ids": []}]),
    ])
    with pytest.raises(PatchError, match="no operation with em 'EM_NOPE'"):
        apply_patch(c, bad, 1)
    assert c.to_dict() == before  # 原契约零改动（deepcopy 隔离，set op 不残留）


def test_schedule_op_mixed_patch_applies_together():
    c = _multi_em_contract()
    patched, rev = apply_patch(c, Patch(base_revision=1, ops=[
        PatchOp("set", "/name", "编排后的工站"),
        _sched_op(),
    ]), 1)
    assert rev == 2
    assert patched.name == "编排后的工站"
    assert [e["em"] for e in patched.schedule] == ["EM_FEED", "EM_CLAMP", "EM_PRESS"]


def test_schedule_op_stale_base_revision_conflicts():
    from processos.contract.patch import RevisionConflict
    with pytest.raises(RevisionConflict):
        apply_patch(_multi_em_contract(),
                    Patch(base_revision=99, ops=[_sched_op()]), 1)


# ---------- HTTP 端到端（wire 形状即前端 apiOrch 发送的形状） ----------

def test_schedule_op_http_roundtrip_422_and_409(tmp_path):
    from fastapi.testclient import TestClient
    from processos.api import ProjectStore, create_app

    client = TestClient(create_app(ProjectStore(), db=tmp_path / "orch.sqlite3"))
    r = client.post("/api/processos/projects", json={"contract": _multi_em_contract().to_dict()})
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]

    saved = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 1, "request_id": "orch-1", "source": "user",
        "ops": [{"op": "set_operation_schedule",
                 "schedule": [{"em": "EM_FEED", "order": 0, "resource_ids": ["CM_FEED_CYL"]},
                              {"em": "EM_CLAMP", "order": 1, "resource_ids": ["CM_CLAMP_CYL"],
                               "parallel_with": ["EM_PRESS"]},
                              {"em": "EM_PRESS", "order": 2, "resource_ids": ["CM_PRESS_CYL"],
                               "parallel_with": ["EM_CLAMP"]}]}],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    doc = saved.json()["contract"]
    assert [e["em"] for e in doc["schedule"]] == ["EM_FEED", "EM_CLAMP", "EM_PRESS"]

    again = client.get(f"/api/processos/projects/{pid}")
    assert again.json()["contract"]["schedule"] == doc["schedule"]  # GET 往返保持调度声明

    bad = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 2,
        "ops": [{"op": "set_operation_schedule",
                 "schedule": [{"em": "EM_NOPE", "order": 0, "resource_ids": []}]}],
    })
    assert bad.status_code == 422 and "no operation with em 'EM_NOPE'" in bad.json()["error"]

    stale = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 1,  # 已到 2 → 409
        "ops": [{"op": "set_operation_schedule",
                 "schedule": [{"em": "EM_CLAMP", "order": 0, "resource_ids": []}]}],
    })
    assert stale.status_code == 409
