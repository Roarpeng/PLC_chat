"""工艺需求卡存储 + 草稿端点 + PCEC 弱关联(契约 docs/22 §1/§2,并行线 B)。

覆盖:store CRUD 往返/校验拒绝/idempotent delete/坏文件跳过/超限拒绝、
路由列表-单个-404-upsert-删除、draft 端点(mock LLM:来源标注/未知值进
open_questions/结构不符重试一次再 502/未配置 400/草稿不落盘)、
confirm-writeback 可选 requirement_id 透传进事务 intent。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import create_app
from gateway.app.services.plc import requirement_store

H = {"X-API-Key": "ros_ak_dev_change_me"}
_REQ_ID_RE = re.compile(r"^req-[0-9a-f]{12}$")
_CHANGE_ID_RE = re.compile(r"^chg-[0-9a-f]{12}$")


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    return TestClient(create_app())


def _requirement(rid: str = "req-111111111111", **over: Any) -> dict[str, Any]:
    req: dict[str, Any] = {
        "requirement_id": rid,
        "project_name": "HR001_PLC_20260509",
        "created_at": 1790000000.0,
        "updated_at": 1790000000.0,
        "confirmation_status": "proposed",
        "intent_summary": "安全门关闭且自动模式有效时允许启动电机",
        "items": [
            {
                "id": "it-1",
                "kind": "precondition",
                "text": "安全门已关闭(FB5002_SafetyDoorV1 闭锁)",
                "source": "engineering",
                "source_ref": "FB5002_SafetyDoorV1",
            },
            {"id": "it-2", "kind": "sequence", "text": "启动后电机运行并自锁", "source": "user", "source_ref": ""},
            {"id": "it-3", "kind": "acceptance", "text": "急停后电机不得自恢复", "source": "inferred", "source_ref": ""},
        ],
        "open_questions": ["夹紧超时时间取多少?(必须工程师确认)"],
        "linked_blocks": ["FB5002_SafetyDoorV1"],
        "linked_signals": [],
        "task_kind": "improve",
        "origin_prompt": "加一个安全门联锁",
    }
    req.update(over)
    return req


# ------------------------------------------------------------------ 存储 CRUD --


def test_store_crud_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    rid = "req-111111111111"
    stored = requirement_store.put_requirement(_requirement())
    assert stored["requirement_id"] == rid
    assert stored["task_kind"] == "improve"
    assert len(stored["items"]) == 3
    root = requirement_store.requirements_root()
    assert (root / rid / "requirement.json").is_file()
    assert (root / rid / "meta.json").is_file()
    assert requirement_store.get_requirement(rid) == stored  # 深度相等往返
    metas = requirement_store.list_requirements()
    assert metas == [
        {
            "id": rid,
            "summary": "安全门关闭且自动模式有效时允许启动电机",
            "status": "proposed",
            "updated_at": stored["updated_at"],
            "task_kind": "improve",
        }
    ]
    # 更新:created_at 保留、updated_at 刷新、confirmed 只改状态
    req2 = _requirement(confirmation_status="confirmed", updated_at=1.0)
    stored2 = requirement_store.put_requirement(req2)
    assert stored2["created_at"] == stored["created_at"]
    assert stored2["updated_at"] >= stored["updated_at"]
    assert requirement_store.get_requirement(rid)["confirmation_status"] == "confirmed"
    # 删除幂等;非法 id 拒绝
    assert requirement_store.delete_requirement(rid) is True
    assert requirement_store.get_requirement(rid) is None
    assert requirement_store.delete_requirement(rid) is True
    assert requirement_store.delete_requirement("bad-id") is False
    assert requirement_store.list_requirements() == []


def test_store_defaults_for_minimal_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    stored = requirement_store.put_requirement(
        {
            "requirement_id": "req-222222222222",
            "confirmation_status": "proposed",
            "intent_summary": "一句话意图",
            "items": [{"kind": "constraint", "text": "禁用手动超控", "source": "user"}],
        }
    )
    assert stored["project_name"] == ""
    assert stored["open_questions"] == []
    assert stored["linked_blocks"] == []
    assert stored["linked_signals"] == []
    assert stored["task_kind"] == "understand"  # 缺省任务态
    assert stored["origin_prompt"] == ""
    assert stored["items"][0]["id"] == "it-1"  # 条目 id 缺省补齐
    assert stored["items"][0]["source_ref"] == ""


@pytest.mark.parametrize(
    "over",
    [
        {"requirement_id": "req-XYZ!!!"},
        {"requirement_id": "req-abcdef12345g"},
        {"requirement_id": ""},
        {"confirmation_status": "draft"},
        {"confirmation_status": ""},
        {"task_kind": "hack"},
        {"items": "not-a-list"},
        {"items": [{"kind": "timing", "text": "x", "source": "user"}]},  # kind 非五类
        {"items": [{"kind": "sequence", "text": "x", "source": "guess"}]},  # source 非三态
        {"items": [{"kind": "sequence", "text": "", "source": "user"}]},  # 缺 text
        {"items": ["not-an-object"]},
    ],
)
def test_store_rejects_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, over: dict) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    with pytest.raises(ValueError):
        requirement_store.put_requirement(_requirement(**over))


def test_store_list_desc_and_bad_files_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    root = requirement_store.requirements_root()
    a, b, c = "req-aaaaaaaaaaaa", "req-bbbbbbbbbbbb", "req-cccccccccccc"
    requirement_store.put_requirement(_requirement(rid=a))
    requirement_store.put_requirement(_requirement(rid=b))
    requirement_store.put_requirement(_requirement(rid=c))
    # 手工改写 meta 的 updated_at 以获得确定性排序(降序)
    for rid, ts in ((a, 100.0), (b, 300.0), (c, 200.0)):
        meta_path = root / rid / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["updated_at"] = ts
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    assert [m["id"] for m in requirement_store.list_requirements()] == [b, c, a]
    # 坏 meta(非 JSON / 非 dict)跳过,不炸列表
    (root / b / "meta.json").write_text("{oops", encoding="utf-8")
    (root / c / "meta.json").write_text("[1,2]", encoding="utf-8")
    assert [m["id"] for m in requirement_store.list_requirements()] == [a]
    # 损坏的 requirement.json 不影响列表(列表只读 meta)
    assert requirement_store.get_requirement(b) is not None


def test_store_rejects_oversize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(requirement_store, "_MAX_REQUIREMENT_BYTES", 1024)
    req = _requirement(items=[{"kind": "constraint", "text": "x" * 4096, "source": "user"}])
    with pytest.raises(ValueError, match="too large"):
        requirement_store.put_requirement(req)


# ------------------------------------------------------------------ 路由 CRUD --


def test_requirements_router_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    rid = "req-111111111111"
    # PUT upsert → 返回规范形整卡
    r = client.put(f"/api/v1/plc/canvas/requirements/{rid}", json=_requirement(), headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["requirement_id"] == rid
    assert r.json()["data"]["items"][0]["kind"] == "precondition"
    # 列表只含 meta(无 items)
    r = client.get("/api/v1/plc/canvas/requirements", headers=H)
    assert r.status_code == 200
    lst = r.json()["data"]
    assert len(lst) == 1 and lst[0]["id"] == rid and "items" not in lst[0]
    assert lst[0]["task_kind"] == "improve" and lst[0]["status"] == "proposed"
    # 单个完整对象
    r = client.get(f"/api/v1/plc/canvas/requirements/{rid}", headers=H)
    assert r.status_code == 200
    assert r.json()["data"]["open_questions"][0].startswith("夹紧超时")
    # 校验拒绝 → 400 PLC_REQUIREMENT_INVALID
    bad = _requirement(items=[{"kind": "timing", "text": "x", "source": "user"}])
    r = client.put(f"/api/v1/plc/canvas/requirements/{rid}", json=bad, headers=H)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "PLC_REQUIREMENT_INVALID"
    # 不存在 → 404 PLC_REQUIREMENT_NOT_FOUND
    r = client.get("/api/v1/plc/canvas/requirements/req-999999999999", headers=H)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "PLC_REQUIREMENT_NOT_FOUND"
    # 删除幂等;非法 id 404
    assert client.delete(f"/api/v1/plc/canvas/requirements/{rid}", headers=H).status_code == 200
    assert client.delete(f"/api/v1/plc/canvas/requirements/{rid}", headers=H).status_code == 200
    assert client.get(f"/api/v1/plc/canvas/requirements/{rid}", headers=H).status_code == 404
    assert client.delete("/api/v1/plc/canvas/requirements/nope", headers=H).status_code == 404


# ------------------------------------------------------------ draft 端点(LLM) --

_CANVAS = {
    "project_name": "HR001_PLC",
    "blocks": {
        "FB5002_SafetyDoorV1": {"name": "FB5002_SafetyDoorV1", "status": "draft"},
        "MotorCtrl": {"name": "MotorCtrl", "status": "draft"},
    },
    "hmi_widgets": {},
    "tags": {},
}

_GOOD_DRAFT = {
    "project_name": "",
    "intent_summary": "安全门关闭且自动模式有效时允许启动电机",
    "items": [
        {
            "id": "it-1",
            "kind": "precondition",
            "text": "安全门已关闭(FB5002_SafetyDoorV1 闭锁)",
            "source": "engineering",
            "source_ref": "FB5002_SafetyDoorV1",
        },
        {"id": "it-2", "kind": "sequence", "text": "启动后电机运行并自锁", "source": "user", "source_ref": ""},
        {"id": "it-3", "kind": "exception", "text": "急停后需手动复位方可再启动", "source": "inferred", "source_ref": ""},
    ],
    "open_questions": ["夹紧超时时间取多少?(必须工程师确认)"],
    "task_kind": "diagnose",  # 请求体 task_kind 优先,应被 improve 覆盖
}


def _mock_llm(
    monkeypatch: pytest.MonkeyPatch, outputs: list[str], *, configured: bool = True
) -> list[dict[str, Any]]:
    """替换 llm_settings / chat_completion_raw;记录调用(参数含 json_mode)。"""
    import gateway.app.services.plc.llm_explain as llm_explain

    calls: list[dict[str, Any]] = []
    settings = {"base_url": "http://llm.test/v1", "api_key": "k", "model": "m"}

    def _fake_settings() -> dict[str, str] | None:
        return settings if configured else None

    def _fake_raw(messages: list, st: dict, *, timeout_s: float = 60.0,
                  max_tokens: int | None = None, json_mode: bool = False,
                  think: bool = False) -> tuple[str, dict]:
        calls.append(
            {"messages": messages, "json_mode": json_mode, "max_tokens": max_tokens}
        )
        return outputs[min(len(calls) - 1, len(outputs) - 1)], {}

    monkeypatch.setattr(llm_explain, "llm_settings", _fake_settings)
    monkeypatch.setattr(llm_explain, "chat_completion_raw", _fake_raw)
    return calls


def test_draft_ok_sources_and_open_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    calls = _mock_llm(monkeypatch, [json.dumps(_GOOD_DRAFT, ensure_ascii=False)])

    r = client.post(
        "/api/v1/plc/canvas/requirements/draft",
        json={"prompt": "加一个安全门联锁,启动前必须关门", "canvas": _CANVAS, "task_kind": "improve"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    draft = r.json()["data"]
    assert _REQ_ID_RE.match(draft["requirement_id"])
    assert draft["confirmation_status"] == "proposed"  # 恒 proposed
    assert draft["task_kind"] == "improve"  # 请求体优先于 LLM 输出
    assert draft["origin_prompt"] == "加一个安全门联锁,启动前必须关门"
    assert draft["project_name"] == "HR001_PLC"  # LLM 空串 → 画布名兜底
    # 来源三态标注保留;engineering 带块名证据
    sources = {it["id"]: (it["source"], it["source_ref"]) for it in draft["items"]}
    assert sources["it-1"] == ("engineering", "FB5002_SafetyDoorV1")
    assert sources["it-2"][0] == "user"
    assert sources["it-3"][0] == "inferred"
    # 未知数值(超时)进 open_questions,不进 items
    assert any("超时" in q for q in draft["open_questions"])
    assert not any("超时" in it["text"] and any(c.isdigit() for c in it["text"]) for it in draft["items"])
    # linked_blocks 从 items 提及的画布块名匹配(MotorCtrl 未提及,不进)
    assert draft["linked_blocks"] == ["FB5002_SafetyDoorV1"]
    # 调用约束:json_mode + 系统提示词带块名清单
    assert len(calls) == 1
    assert calls[0]["json_mode"] is True
    joined = "".join(calls[0]["messages"][0]["content"]) + calls[0]["messages"][1]["content"]
    assert "FB5002_SafetyDoorV1" in joined
    # 草稿不落盘:存储列表保持为空
    assert client.get("/api/v1/plc/canvas/requirements", headers=H).json()["data"] == []


def test_draft_retry_once_then_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    fenced = "```json\n" + json.dumps(_GOOD_DRAFT, ensure_ascii=False) + "\n```"
    calls = _mock_llm(monkeypatch, ["这不是 JSON,直接 garbage", fenced])

    r = client.post(
        "/api/v1/plc/canvas/requirements/draft",
        json={"prompt": "安全门联锁", "canvas": _CANVAS},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert len(calls) == 2  # 垃圾一次 + 重试一次
    assert r.json()["data"]["intent_summary"] == _GOOD_DRAFT["intent_summary"]  # 围栏容忍
    assert r.json()["data"]["task_kind"] == "diagnose"  # 请求体缺省 → 采用 LLM 输出
    # 双缺省(请求体与 LLM 都不给)→ understand
    payload = dict(_GOOD_DRAFT)
    payload.pop("task_kind")
    draft = requirement_store.requirement_from_llm_payload(
        json.dumps(payload, ensure_ascii=False), prompt="p", block_names=["FB5002_SafetyDoorV1"]
    )
    assert draft["task_kind"] == "understand"


def test_draft_garbage_after_retry_502(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    calls = _mock_llm(monkeypatch, ["垃圾输出"])
    r = client.post(
        "/api/v1/plc/canvas/requirements/draft",
        json={"prompt": "随便", "canvas": _CANVAS},
        headers=H,
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "LLM_CALL_FAILED"
    assert len(calls) == 2  # 重试一次仍不符 → 502


def test_draft_llm_not_configured_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    calls = _mock_llm(monkeypatch, ["{}"], configured=False)
    r = client.post(
        "/api/v1/plc/canvas/requirements/draft",
        json={"prompt": "安全门联锁", "canvas": _CANVAS},
        headers=H,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "LLM_NOT_CONFIGURED"
    assert calls == []  # 未配置时绝不发起调用

    r = client.post("/api/v1/plc/canvas/requirements/draft", json={"canvas": _CANVAS}, headers=H)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "PROMPT_REQUIRED"


def test_draft_llm_runtime_error_502(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端点不可达(RuntimeError)→ 立即 502,不重试。"""
    import gateway.app.services.plc.llm_explain as llm_explain

    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        llm_explain, "llm_settings", lambda: {"base_url": "http://x", "api_key": "k", "model": "m"}
    )

    def _boom(*args: Any, **kwargs: Any) -> tuple[str, dict]:
        raise RuntimeError("LLM 端点不可达")

    monkeypatch.setattr(llm_explain, "chat_completion_raw", _boom)
    r = client.post(
        "/api/v1/plc/canvas/requirements/draft",
        json={"prompt": "x", "canvas": _CANVAS},
        headers=H,
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "LLM_CALL_FAILED"


# ------------------------------------------- confirm-writeback requirement_id 透传 --


def test_confirm_writeback_requirement_passthrough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """可选 requirement_id 透传进事务 intent(读改写账本,不动 compile_jobs)。"""
    from plc_engine import pcec
    from plc_engine.canvas_model import create_empty_canvas

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "HR001.ap19").write_text("<Project/>", encoding="utf-8")

    from gateway.app.services.plc import compile_jobs as cj

    job_calls: list[dict[str, Any]] = []

    def _fake_create_job(canvas: dict, **kwargs: Any) -> dict[str, Any]:
        job_calls.append(kwargs)
        return {"id": "job-1", "status": "queued", "change_id": kwargs.get("change_id", "")}

    monkeypatch.setattr(cj, "create_compile_job", _fake_create_job)

    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": create_empty_canvas("Demo").to_dict(),
            "project_path": str(proj / "HR001.ap19"),
            "requirement_id": "req-abcdef123456",
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    change_id = r.json()["data"]["change_id"]
    assert _CHANGE_ID_RE.match(change_id)
    chg = pcec.get_change(change_id)
    assert chg is not None
    assert chg["intent"]["requirement_id"] == "req-abcdef123456"
    assert chg["status"] == "approved"  # 透传只补 intent,不改状态机
    assert job_calls and job_calls[0]["change_id"] == change_id

    # 不带 requirement_id → intent 无该字段(兼容优先,零变化)
    r2 = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": create_empty_canvas("Demo").to_dict(),
            "project_path": str(proj / "HR001.ap19"),
        },
        headers=H,
    )
    assert r2.status_code == 200, r2.text
    chg2 = pcec.get_change(r2.json()["data"]["change_id"])
    assert chg2 is not None
    assert "requirement_id" not in chg2["intent"]

    # 非法格式 requirement_id 不透传(正则约束),但写回照常
    r3 = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": create_empty_canvas("Demo").to_dict(),
            "project_path": str(proj / "HR001.ap19"),
            "requirement_id": "not-a-req-id",
        },
        headers=H,
    )
    assert r3.status_code == 200, r3.text
    chg3 = pcec.get_change(r3.json()["data"]["change_id"])
    assert chg3 is not None
    assert "requirement_id" not in chg3["intent"]
