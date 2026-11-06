"""T-CHAT · Greenfield 对话管线回归。

覆盖：首版生成分支（零 LLM）/ 使用引导分支 / LLM 问答零改动 / 增量修改原子应用 /
违规整批拒绝 + 自纠重试耗尽 / FROZEN 拒编辑 / LLM 未配置 400 / HTTP 端点与画布事件回流。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc import greenfield_chat as gfchat
from gateway.app.services.plc import greenfield_service as svc
from gateway.app.services.plc.greenfield_session import GreenfieldSession, registry
from plc_engine.af.greenfield_ports import GreenfieldError, GreenfieldStage

PREFIX = "/api/v1/plc/canvas/greenfield"


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset()
    yield
    registry.reset()


@pytest.fixture()
def session() -> GreenfieldSession:
    s = GreenfieldSession()
    registry._sessions[s.session_id] = s
    return s


def _fake_llm(payload: dict):
    """构造 chat_completion_raw 替身（返回固定 JSON 文本）。"""

    def _impl(messages, settings, **kwargs):
        return json.dumps(payload, ensure_ascii=False), {}

    return _impl


def _configure_llm(monkeypatch, payload_or_func):
    monkeypatch.setattr(
        gfchat,
        "llm_settings",
        lambda: {"base_url": "http://test.local", "api_key": "k", "model": "m"},
    )
    monkeypatch.setattr(
        gfchat,
        "chat_completion_raw",
        payload_or_func if callable(payload_or_func) else _fake_llm(payload_or_func),
    )


# ---------------------------------------------------------------- 确定性分支
def test_chat_first_message_generates_draft_without_llm(session, monkeypatch):
    # 钉死未配置：本机若设过 DEEPSEEK_API_KEY，首版分支会优先走 LLM 解析
    monkeypatch.setattr(gfchat, "llm_settings", lambda: None)
    result = gfchat.chat_turn(session, "装配工位：上料与压装两道工序，压装超时中止")
    assert session.ir is not None
    assert session.stage is GreenfieldStage.LINKABLE
    assert result["state"]["has_ir"] is True
    roles = [m["role"] for m in session.messages]
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    assert any(m["role"] == "event" and m["kind"] == "views" for m in session.messages)
    # 响应内的 state 必须包含最新消息流（含最后的助手回复）
    state_msgs = result["state"]["messages"]
    assert state_msgs[-1]["role"] == "assistant"
    assert len(state_msgs) == len(session.messages)


def test_chat_short_question_gets_guide_instead_of_draft(session):
    result = gfchat.chat_turn(session, "怎么开始？")
    assert session.ir is None
    assert "上传" in result["reply"]
    assert session.messages[-1]["kind"] == "text"


# ---------------------------------------------------------------- LLM 分支
def test_chat_answer_intent_changes_nothing(session, monkeypatch):
    svc.draft_from_prompt(session, "")
    before = session.ir.ir_sha256()
    _configure_llm(monkeypatch, {"intent": "answer", "reply": "当前共 2 道工序", "patches": []})
    result = gfchat.chat_turn(session, "现在有几道工序？")
    assert session.ir.ir_sha256() == before
    assert result["reply"] == "当前共 2 道工序"
    assert session.messages[-1]["role"] == "assistant"
    assert session.messages[-1]["kind"] == "text"
    assert sum(session.counters.values()) == 0


def test_chat_edit_intent_applies_patch_atomically(session, monkeypatch):
    svc.draft_from_prompt(session, "")
    step_id = session.ir.steps[0].id
    payload = {
        "intent": "edit",
        "reply": "已把首步超时改为 8000ms",
        "patches": [
            {"op": "set_ir_only_field", "field_path": f"steps.{step_id}.timeout_ms", "value": 8000}
        ],
    }
    _configure_llm(monkeypatch, payload)
    result = gfchat.chat_turn(session, "把首步超时改成8000毫秒")
    assert session.ir.steps[0].timeout_ms == 8000
    assert session.stage is GreenfieldStage.VALIDATING
    last = session.messages[-1]
    assert last["role"] == "assistant" and last["kind"] == "edit"
    assert last["payload"]["applied"] is True
    assert session.views is not None
    assert sum(session.counters.values()) == 0
    assert step_id in json.dumps(result["state"]["ir"]["steps"])


def test_chat_edit_rejected_batch_keeps_ir_and_retries(session, monkeypatch):
    svc.draft_from_prompt(session, "")
    before = session.ir.ir_sha256()
    bad = {
        "intent": "edit",
        "reply": "直连",
        # 跨层直连 CM：I1 非法边，必须被白名单整批拦截
        "patches": [
            {
                "op": "add_edge",
                "edge": {"kind": "E_HIER_UNIT_EM", "src_id": "U1", "dst_id": "U1EM1_CM1"},
            }
        ],
    }
    calls: list[int] = []

    def _flaky(messages, settings, **kwargs):
        calls.append(1)
        return json.dumps(bad, ensure_ascii=False), {}

    _configure_llm(monkeypatch, _flaky)
    result = gfchat.chat_turn(session, "把单元直接连到输送带设备")
    assert session.ir.ir_sha256() == before
    assert len(calls) == 1 + gfchat.MAX_LLM_RETRIES
    last = session.messages[-1]
    assert last["payload"]["applied"] is False
    assert last["payload"]["violations"]
    assert "未能通过规格校验" in result["reply"]


def test_chat_edit_retry_recovers_after_violation(session, monkeypatch):
    svc.draft_from_prompt(session, "")
    step_id = session.ir.steps[0].id
    before = session.ir.ir_sha256()
    bad = {
        "intent": "edit",
        "reply": "x",
        "patches": [
            {"op": "set_ir_only_field", "field_path": "cms.不存在.plcopen.enable", "value": True}
        ],
    }
    good = {
        "intent": "edit",
        "reply": "已修正",
        "patches": [
            {"op": "set_ir_only_field", "field_path": f"steps.{step_id}.timeout_ms", "value": 8000}
        ],
    }
    outputs = [json.dumps(bad), json.dumps(good)]

    def _two_phase(messages, settings, **kwargs):
        return outputs.pop(0), {}

    _configure_llm(monkeypatch, _two_phase)
    result = gfchat.chat_turn(session, "把首步超时改成 8000ms")
    assert session.ir.ir_sha256() != before
    assert session.ir.steps[0].timeout_ms == 8000
    assert session.messages[-1]["payload"]["applied"] is True
    assert result["message"]["payload"]["report_ok"] is True


def test_chat_frozen_rejects_edit_with_hint(session, monkeypatch, tmp_path):
    svc.draft_from_prompt(session, "")
    svc.revalidate(session)
    svc.engineering_summary(session)
    svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path, frozen_by="tester")
    before = session.ir.ir_sha256()
    _configure_llm(
        monkeypatch,
        {
            "intent": "edit",
            "reply": "改",
            "patches": [
                {"op": "set_ir_only_field", "field_path": "steps.U1EM1_S10.timeout_ms", "value": 1}
            ],
        },
    )
    result = gfchat.chat_turn(session, "把首步超时改成 1ms")
    assert session.ir.ir_sha256() == before
    assert "已冻结" in result["reply"]
    assert session.messages[-1]["payload"]["reason"] == "FROZEN"


def test_chat_llm_not_configured(session, monkeypatch):
    svc.draft_from_prompt(session, "")
    monkeypatch.setattr(gfchat, "llm_settings", lambda: None)
    with pytest.raises(GreenfieldError) as excinfo:
        gfchat.chat_turn(session, "解释一下当前架构")
    assert excinfo.value.code == "LLM_NOT_CONFIGURED"


def test_chat_empty_message_rejected(session):
    with pytest.raises(GreenfieldError) as excinfo:
        gfchat.chat_turn(session, "   ")
    assert excinfo.value.code == "GF_CHAT_EMPTY"


def test_load_reference_allowed_from_validating(session):
    """VALIDATING 阶段重载参考实例不再被 upload 门禁 409（回到 LINKABLE 再走全链）。"""
    svc.draft_from_prompt(session, "")
    svc.revalidate(session)
    assert session.stage is GreenfieldStage.VALIDATING
    result = svc.load_reference_fixture(session)
    assert result["has_ir"] is True
    assert result["has_contract"] is True
    assert result["hardware"]["variable_catalog"]["counts"]["external_io"] == 113
    assert any(m["kind"] == "contract" for m in session.messages)


def test_confirm_from_linkable_autotransition(session, tmp_path):
    """LINKABLE 直接确认：自动补一次校验推进 VALIDATING，不再 409（既有 UX 缺口）。"""
    svc.draft_from_prompt(session, "")
    assert session.stage is GreenfieldStage.LINKABLE
    svc.engineering_summary(session)
    svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path, frozen_by="tester")
    assert session.stage is GreenfieldStage.FROZEN
    assert any(m["kind"] == "freeze" for m in session.messages)


def test_confirm_after_restart_same_session_id_gets_next_disk_version(session, tmp_path):
    """网关重启场景：内存 specs 清空但磁盘已有 v1 → 再确认应出 v2 而非 SpecImmutableError。"""
    from gateway.app.services.plc.greenfield_session import GreenfieldSession as GS

    svc.draft_from_prompt(session, "")
    svc.engineering_summary(session)
    svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path, frozen_by="tester")
    assert session.specs[0].spec_version == 1

    # 模拟重启：同 session_id 全新内存会话（磁盘 v1 仍在）
    reborn = GS(session_id=session.session_id)
    svc.draft_from_prompt(reborn, "")
    svc.engineering_summary(reborn)
    svc.confirm_and_freeze(reborn, explicit=True, base_dir=tmp_path, frozen_by="tester")
    assert reborn.specs[0].spec_version == 2
    assert reborn.stage is GreenfieldStage.FROZEN
    assert (tmp_path / "greenfield" / reborn.session_id / "specs" / "v2.json").exists()


# ---------------------------------------------------------------- HTTP 层
def test_chat_endpoint_and_canvas_event_backflow(monkeypatch):
    # 首条消息走 planner 路径：钉死未配置 LLM，防本机环境变量触发真实调用
    monkeypatch.setattr(gfchat, "llm_settings", lambda: None)
    client = TestClient(app)
    sid = client.get(f"{PREFIX}/state").json()["data"]["session_id"]

    # 首条消息 → 首版生成（零 LLM）
    r1 = client.post(f"{PREFIX}/chat", json={"session_id": sid, "message": "装配工位：上料与压装两道工序"})
    assert r1.status_code == 200
    data = r1.json()["data"]
    assert data["state"]["has_ir"] is True
    assert any(m["role"] == "user" for m in data["state"]["messages"])

    # 画布手动编辑 → 系统事件回流对话流
    edge_id = data["state"]["ir"]["edges"][0]["id"]
    r2 = client.post(f"{PREFIX}/links", json={"session_id": sid, "op": "remove_edge", "edge_id": edge_id})
    assert r2.status_code == 200
    msgs = r2.json()["data"]["messages"]
    assert any(m["role"] == "event" and m["kind"] == "edit" for m in msgs)

    # 空消息 → 400
    r3 = client.post(f"{PREFIX}/chat", json={"session_id": sid, "message": " "})
    assert r3.status_code == 400
    assert r3.json()["error"]["code"] == "GF_CHAT_EMPTY"

    # 确认前零副作用铁律不破
    counters = r2.json()["data"]["counters"]
    assert counters == {"ops": 0, "disk_writes": 0, "writebacks": 0, "generations": 0}
