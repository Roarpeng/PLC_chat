"""T-DRAFT-LLM · Greenfield 首版 LLM 结构化解析回归。

覆盖：丰富 spec → IR 数量 / 合法 cm_type / LINKABLE / 「AI 解析」消息 /
契约注入；非法输出重试耗尽 → 诚实回退 planner；LLM 未配置 → planner 直出
且 LLM 零调用。全部 monkeypatch 假 LLM（参考 test_greenfield_chat 的范式）。
"""
from __future__ import annotations

import json
from typing import get_args

import pytest

from gateway.app.services.plc import greenfield_chat as gfchat
from gateway.app.services.plc import greenfield_draft_llm as gfdraft
from gateway.app.services.plc.greenfield_session import GreenfieldSession, registry
from plc_engine.af.af_model import AfCmType
from plc_engine.af.greenfield_contract import CompatContract, IoEntry
from plc_engine.af.greenfield_ports import GreenfieldStage

VALID_CM_TYPES = set(get_args(AfCmType))

KUKA_PROMPT = (
    "视觉引导与KUKA机器人上下料涂胶打磨工位：上位机PC下发配方与视觉拍照完成信号，"
    "KUKA机器人执行上料抓取、涂胶作业、打磨加工与下料步序，气缸夹紧与真空吸盘配合，"
    "光幕或急停触发安全中止"
)


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
    def _impl(messages, settings, **kwargs):
        return json.dumps(payload, ensure_ascii=False), {}

    return _impl


def _configure_llm(monkeypatch, payload_or_func):
    """同时钉死 chat 编排层与 draft 解析层的 LLM 替身（两层各持一份 import）。"""
    fake = payload_or_func if callable(payload_or_func) else _fake_llm(payload_or_func)
    settings = {"base_url": "http://test.local", "api_key": "k", "model": "m"}
    for mod in (gfchat, gfdraft):
        monkeypatch.setattr(mod, "llm_settings", lambda: settings)
        monkeypatch.setattr(mod, "chat_completion_raw", fake)
    return fake


def _rich_spec() -> dict:
    """2 EM / 3 CM / 6 步（含 1 个 900 异常步）的 KUKA 工位规格。"""
    return {
        "project": {"name": "KukaVisionStation", "business_label": "视觉引导KUKA涂胶打磨工位"},
        "units": [{"name": "KukaVisionStation", "business_label": "涂胶打磨工位"}],
        "ems": [
            {"id": 0, "unit": 0, "name": "Gluing", "business_label": "上料与涂胶工序"},
            {"id": 1, "unit": 0, "name": "Polishing", "business_label": "打磨与下料工序"},
        ],
        "cms": [
            {"em": 0, "name": "cylClamp", "cm_type": "LBC_TwoWayActuator", "business_label": "夹紧气缸"},
            {"em": 0, "name": "vacGripper", "cm_type": "LBC_TwoWayActuator", "business_label": "真空吸盘"},
            {"em": 1, "name": "motorPolisher", "cm_type": "LBC_MotorStarter", "business_label": "打磨电机"},
        ],
        "steps": [
            {
                "em": 0, "step_id": 1, "name": "WAIT_PC_RECIPE",
                "actions": ["// 等待上位机配方下发"],
                "transition_condition": "#controlNodes.pcRecv.status.signal",
                "timeout_ms": 10000, "next_step_id": 2, "error_step_id": 999,
            },
            {
                "em": 0, "step_id": 2, "name": "CLAMP_PART",
                "actions": ["#controlNodes.cylClamp.commands.workPosition := TRUE;"],
                "transition_condition": "#controlNodes.cylClamp.status.inWorkPosition",
                "timeout_ms": 3000, "next_step_id": 3, "error_step_id": 999,
            },
            {
                "em": 0, "step_id": 3, "name": "GLUE_APPLY",
                "actions": ["#controlNodes.vacGripper.commands.workPosition := TRUE;"],
                "transition_condition": "#controlNodes.vacGripper.status.inWorkPosition",
                "timeout_ms": 15000, "error_step_id": 999,
            },
            {
                "em": 1, "step_id": 1, "name": "POLISH_START",
                "actions": ["#controlNodes.motorPolisher.commands.forward := TRUE;"],
                "transition_condition": "#controlNodes.motorPolisher.status.running",
                "timeout_ms": 8000, "next_step_id": 2, "error_step_id": 900,
            },
            {
                "em": 1, "step_id": 2, "name": "UNLOAD_PART",
                "actions": ["#controlNodes.vacGripper.commands.homePosition := TRUE;"],
                "transition_condition": "#controlNodes.vacGripper.status.inHomePosition",
                "timeout_ms": 5000, "error_step_id": 999,
            },
            {
                "em": 1, "step_id": 900, "name": "SAFE_ABORT",
                "actions": ["// 光幕或急停：上报并中止"],
                "transition_condition": "TRUE",
                "timeout_ms": 3000, "next_step_id": 999, "error_step_id": 999,
                "branch": {"kind": "else", "condition": "光幕或急停触发安全中止"},
            },
        ],
        "modes": [
            {"id": "MODE_AUTO", "packml_mode": "Production"},
            {"id": "MODE_MANUAL", "packml_mode": "Manual"},
        ],
        "interlocks": [
            {"target": "cylClamp", "expression": "releaseWork AND releaseHome"},
            {"target": "不存在的设备", "expression": "TRUE"},
        ],
    }


# ---------------------------------------------------------------- 成功路径
def test_llm_draft_rich_spec_builds_linkable_ir(session, monkeypatch):
    calls: list[list[dict]] = []

    def _rec(messages, settings, **kwargs):
        calls.append(messages)
        return json.dumps(_rich_spec(), ensure_ascii=False), {}

    _configure_llm(monkeypatch, _rec)
    result = gfchat.chat_turn(session, KUKA_PROMPT)

    assert len(calls) == 1  # 一次成型，无重试
    ir = session.ir
    assert ir is not None
    assert len(ir.units) == 1
    assert len(ir.ems) == 2
    assert len(ir.cms) == 3
    assert len(ir.steps) >= 6
    assert all(cm.cm_type in VALID_CM_TYPES for cm in ir.cms)
    assert session.stage is GreenfieldStage.LINKABLE
    assert session.report is not None and session.report.ok
    assert "AI 解析生成首版" in result["reply"]
    assert result["message"]["payload"]["source"] == "ai_draft"
    assert sum(session.counters.values()) == 0

    # 步号规范：正常步 10/20/30…，异常步 900，错误步引用 999
    em1 = ir.ems[0]
    assert sorted(s.step_id for s in ir.steps if s.em_id == em1.id) == [10, 20, 30]
    first = next(s for s in ir.steps if s.em_id == em1.id and s.step_id == 10)
    assert first.next_step_id == 20  # 旧步号 1→2 引用被改写为 10→20
    assert first.error_step_id == 999
    abort = next(s for s in ir.steps if s.step_id == 900)
    assert abort.branch.get("kind") == "else"

    # 联锁：可解析目标 → inferred 来源（自动进待确认）；不可解析 → 挂起问题
    assert ir.interlocks and ir.interlocks[0].source == "inferred"
    assert ir.interlocks[0].target_id == "U1EM1_CM1"  # cylClamp
    assert any("未能关联" in q for q in session.report.open_questions)

    # 控制节点 / 作业 / 模式齐备（from_af_project 既有确定性逻辑）
    assert len(ir.control_nodes) == 2
    assert {m.id for m in ir.modes} == {"MODE_AUTO", "MODE_MANUAL"}


def test_llm_draft_with_contract_injects_compat_refs(session, monkeypatch):
    contract = CompatContract(
        receipt_id="R-TEST-1",
        io_entries=[
            IoEntry(name="KukaStart", logical_address="%I0.0"),
            IoEntry(name="ClampFwd", logical_address="%Q0.1"),
        ],
    )
    session.contract = contract
    _configure_llm(monkeypatch, _rich_spec())

    def _capture_user_payload(messages, settings, **kwargs):
        # 契约目录必须随提示送给 LLM（帮助关联真实设备名）
        assert "KukaStart" in messages[1]["content"]
        return json.dumps(_rich_spec(), ensure_ascii=False), {}

    _configure_llm(monkeypatch, _capture_user_payload)
    gfchat.chat_turn(session, KUKA_PROMPT)

    ir = session.ir
    assert ir is not None
    assert ir.compat_refs and ir.io_bindings  # 契约注入复用 from_af_project
    assert ir.spec_meta.receipt_id == "R-TEST-1"
    assert len(ir.io_bindings) == len(ir.cms)


# ---------------------------------------------------------------- 回退路径
@pytest.mark.parametrize(
    "raw",
    [
        "这不是 JSON {{{",
        json.dumps({"ems": []}, ensure_ascii=False),
        json.dumps(
            {"ems": [{"name": "A"}], "cms": [{"em": 0, "name": "x", "cm_type": "LBC_不存在"}]},
            ensure_ascii=False,
        ),
    ],
)
def test_llm_draft_invalid_output_falls_back_to_planner(session, monkeypatch, raw):
    calls: list[int] = []

    def _bad(messages, settings, **kwargs):
        calls.append(1)
        return raw, {}

    _configure_llm(monkeypatch, _bad)
    result = gfchat.chat_turn(session, KUKA_PROMPT)

    assert len(calls) == 1 + gfdraft.MAX_DRAFT_RETRIES  # 重试耗尽
    assert session.ir is not None  # planner 兜底仍有首版
    assert session.stage is GreenfieldStage.LINKABLE
    assert result["state"]["has_ir"] is True
    assert any("回退" in n for n in session.notes)
    assert "AI 结构化解析未成功" in result["reply"]


def test_llm_draft_retry_recovers_after_schema_error(session, monkeypatch):
    bad = '{"ems": []}'
    outputs = [bad, json.dumps(_rich_spec(), ensure_ascii=False)]

    def _two_phase(messages, settings, **kwargs):
        return outputs.pop(0), {}

    _configure_llm(monkeypatch, _two_phase)
    result = gfchat.chat_turn(session, KUKA_PROMPT)

    assert len(outputs) == 0  # 第二次被消费
    assert len(session.ir.ems) == 2
    assert "AI 解析生成首版" in result["reply"]


def test_llm_draft_not_configured_uses_planner_with_zero_llm_calls(session, monkeypatch):
    calls: list[int] = []

    def _count(messages, settings, **kwargs):
        calls.append(1)
        return "{}", {}

    monkeypatch.setattr(gfchat, "llm_settings", lambda: None)
    monkeypatch.setattr(gfdraft, "llm_settings", lambda: None)
    monkeypatch.setattr(gfdraft, "chat_completion_raw", _count)

    result = gfchat.chat_turn(session, KUKA_PROMPT)

    assert calls == []  # LLM 零调用
    assert session.ir is not None
    assert session.stage is GreenfieldStage.LINKABLE
    assert result["state"]["has_ir"] is True
    assert "AI 解析" not in result["reply"]
    assert not any("AI 结构化解析" in n for n in session.notes)
    assert sum(session.counters.values()) == 0
