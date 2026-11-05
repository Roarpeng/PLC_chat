"""LLM ops 归一化/校验回归(2026-10-24 E2E 发现的假成功 bug)。

实测 DeepSeek 会自创载荷(update_block + vars_add + type),未归一放行时
前端显示“已执行”但 apply_canvas_patch 静默无效。覆盖:
- vars_add 展开为规范 add_variable
- add_variable 的 type/datatype 键归一为 data_type
- 空载荷 update_block 被拒
- add_variable 指向不存在块被拒
"""

from __future__ import annotations

from plc_engine.canvas_model import CanvasState
from gateway.app.services.plc.chat_ops import validate_ops


def _canvas_with_block() -> CanvasState:
    c = CanvasState(project_name="T")
    from plc_engine.canvas_model import CanvasBlock

    c.blocks["FB_A"] = CanvasBlock(name="FB_A", block_type="FB", number=1, language="SCL")
    return c


def test_update_block_vars_add_expands_to_add_variable() -> None:
    c = _canvas_with_block()
    ops = [
        {
            "op": "update_block",
            "name": "FB_A",
            "vars_add": [{"name": "E2ETestFlag", "type": "Bool"}],
        }
    ]
    cleaned, errors = validate_ops(c, ops)
    assert not errors
    assert cleaned == [
        {
            "op": "add_variable",
            "block": "FB_A",
            "variable": {"name": "E2ETestFlag", "data_type": "Bool"},
        }
    ]


def test_update_block_without_payload_rejected() -> None:
    c = _canvas_with_block()
    cleaned, errors = validate_ops(c, [{"op": "update_block", "name": "FB_A"}])
    assert cleaned == []
    assert any("without payload" in e for e in errors)


def test_add_variable_type_key_normalized() -> None:
    c = _canvas_with_block()
    cleaned, errors = validate_ops(
        c,
        [
            {
                "op": "add_variable",
                "block": "FB_A",
                "variable": {"name": "V1", "type": "Int"},
            }
        ],
    )
    assert not errors
    assert cleaned[0]["variable"]["data_type"] == "Int"
    assert "type" not in cleaned[0]["variable"]


def test_add_variable_unknown_block_rejected() -> None:
    c = _canvas_with_block()
    cleaned, errors = validate_ops(
        c,
        [
            {
                "op": "add_variable",
                "block": "FB_MISSING",
                "variable": {"name": "V1", "data_type": "Bool"},
            }
        ],
    )
    assert cleaned == []
    assert any("unknown block" in e for e in errors)


def test_update_block_with_patch_and_vars_add_keeps_both() -> None:
    c = _canvas_with_block()
    ops = [
        {
            "op": "update_block",
            "name": "FB_A",
            "patch": {"comment": "new comment"},
            "vars_add": [{"name": "V2", "data_type": "Real", "comment": "x"}],
        }
    ]
    cleaned, errors = validate_ops(c, ops)
    assert not errors
    assert len(cleaned) == 2
    assert cleaned[0]["patch"] == {"comment": "new comment"}
    assert cleaned[1] == {
        "op": "add_variable",
        "block": "FB_A",
        "variable": {"name": "V2", "data_type": "Real", "comment": "x"},
    }


def test_question_prompts_never_produce_ops() -> None:
    """「分析项目的报警逻辑」曾是重灾区：报警关键词误建急停变量。"""
    from gateway.app.services.plc.chat_ops import build_chat_ops, build_ops_from_rules
    from plc_engine.canvas_model import CanvasBlock

    c = _canvas_with_block()
    c.blocks["FB_A"].interface = []
    for p in ("分析项目的报警逻辑", "这个项目的报警怎么处理?", "解释一下急停回路", "分析项目"):
        assert build_ops_from_rules(p, c) == [], p
        assert build_chat_ops(p, c, use_llm=False)["ops"] == [], p


def test_edit_prompts_still_produce_ops() -> None:
    from gateway.app.services.plc.chat_ops import build_ops_from_rules

    c = _canvas_with_block()
    c.blocks["FB_A"].interface = []
    ops = build_ops_from_rules("加一个急停按钮", c)
    assert any(op.get("op") == "add_variable" for op in ops)


def test_question_phrazed_edit_intent_still_works() -> None:
    """「怎么创建 FB X?」带问号但是明确编辑指令,必须仍然出 ops。"""
    from gateway.app.services.plc.chat_ops import build_ops_from_rules

    c = _canvas_with_block()
    ops = build_ops_from_rules("怎么创建 FB Sorter?", c)
    assert any(op.get("op") == "add_block" for op in ops)


def test_needs_think_routing() -> None:
    """工业可靠优先:简单直答,复杂 think。"""
    from gateway.app.services.plc.chat_ops import needs_think

    c = _canvas_with_block()
    from plc_engine.canvas_model import CanvasBlock

    c.blocks["FB_B"] = CanvasBlock(name="FB_B", block_type="FB", number=2, language="SCL")
    # 简单:短且无复杂信号
    assert needs_think("FB_A 是干嘛的", c) is False
    assert needs_think("列出 FB_A 的变量", c) is False
    # 复杂:命中复杂信号 / 长输入 / 跨块引用
    assert needs_think("分析这个项目的联锁架构", c) is True
    assert needs_think("为什么要加互锁", c) is True
    assert needs_think("把 FB_A 和 FB_B 的逻辑重构到新 EM 里,考虑时序与安全联锁", c) is True
    assert needs_think("FB_A FB_B", c) is True  # ≥2 块引用
    assert needs_think("哈" * 100, c) is True  # 长输入


def test_history_reaches_llm_ops_prompt(monkeypatch):
    """指代性指令依据 recent_conversation 解析——历史必须进 _llm_ops 的 prompt。"""
    import gateway.app.services.plc.chat_ops as co

    captured = {}

    class _FakeSettings(dict):
        pass

    def fake_raw(messages, settings, **kw):
        captured["user"] = messages[-1]["content"]
        return '{"ops": []}', {}

    import gateway.app.services.plc.llm_explain as le

    monkeypatch.setattr(le, "llm_settings", lambda: {"base_url": "u", "api_key": "k", "model": "m"})
    monkeypatch.setattr(le, "chat_completion_raw", fake_raw)

    from plc_engine.canvas_model import create_empty_canvas

    canvas = create_empty_canvas("T")
    ctx = {"history": [{"role": "system", "text": "1. 在 MainDB 添加变量 i_bEnable Bool"}]}
    co.build_chat_ops("按步骤全部修改", canvas, context=ctx, use_llm=True)
    assert "recent_conversation" in captured["user"]
    assert "i_bEnable" in captured["user"]


def test_uservar_placeholder_renamed_by_convention():
    from gateway.app.services.plc.chat_ops import validate_ops

    c = _canvas_with_block()
    cleaned, _ = validate_ops(
        c,
        [
            {
                "op": "add_variable",
                "block": "FB_A",
                "variable": {"name": "UserVar_304", "data_type": "Bool", "section": "VAR_INPUT"},
            }
        ],
    )
    assert cleaned[0]["variable"]["name"] == "i_UserVar_304"
    # 用户显式命名绝不被改
    cleaned2, _ = validate_ops(
        c,
        [
            {
                "op": "add_variable",
                "block": "FB_A",
                "variable": {"name": "MyEnable", "data_type": "Bool", "section": "VAR_INPUT"},
            }
        ],
    )
    assert cleaned2[0]["variable"]["name"] == "MyEnable"


# ---------------------------------------------------------------------------
# 工站级受控槽位编辑 (P0-B 交付项)
# ---------------------------------------------------------------------------

def test_detect_station_slot_intent() -> None:
    from gateway.app.services.plc.chat_ops import detect_station_slot_intent
    from plc_engine.canvas_model import create_empty_canvas

    c = create_empty_canvas("T")
    # 互锁识别
    st, kind = detect_station_slot_intent("在 ST10 升降气缸下降前增加夹爪原位互锁", c)
    assert st == "ST10"
    assert kind == "slot4_Interlock"

    # 步序识别
    st2, kind2 = detect_station_slot_intent("修改 EM1 的步序 20 转移条件", c)
    assert st2 == "EM1"
    assert kind2 == "slot3_SeqAuto"

    # 纯提问不触发出 ops
    st3, kind3 = detect_station_slot_intent("ST10 的互锁逻辑是什么？", c)
    assert st3 is None
    assert kind3 is None

    # 非工站指令
    st4, kind4 = detect_station_slot_intent("加一个急停按钮", c)
    assert st4 is None
    assert kind4 is None


def test_build_chat_ops_station_slot_interlock_rule_flow() -> None:
    from gateway.app.services.plc.chat_ops import build_chat_ops
    from plc_engine.canvas_model import create_empty_canvas

    canvas = create_empty_canvas("T")
    prompt = "在 ST10 升降气缸下降前增加夹爪原位互锁"

    res = build_chat_ops(prompt, canvas, use_llm=False)
    assert res["ok"] is True
    assert res["source"] == "rules_slot_editor"
    assert res["station_id"] == "ST10"
    assert res["estimated_tokens"] < 1500
    assert res["delta"]["modified_slots"] == ["slot4_Interlock"]
    assert "Cyl_Lift.releaseWork" in res["delta"]["patch"]
    assert "#Cyl_Grip.q_xInHome" in res["delta"]["patch"]["Cyl_Lift.releaseWork"]

    # 检查 Diff Summary（自然语言可解释，严禁直接倾倒底层巨量 SCL）
    diff = res["diff_summary"]
    assert diff["station_id"] == "ST10"
    assert len(diff["entries"]) >= 1
    assert diff["entries"][0]["slot"] == "Slot 4 (@INTERLOCK)"
    assert diff["entries"][0]["target"] == "Cyl_Lift.releaseWork"
    assert "变更前" in diff["text"]
    assert "变更后" in diff["text"]
    assert "#Cyl_Grip.q_xInHome" in diff["text"]


def test_build_chat_ops_station_slot_step_flow() -> None:
    from gateway.app.services.plc.chat_ops import build_chat_ops
    from plc_engine.canvas_model import create_empty_canvas

    canvas = create_empty_canvas("T")
    prompt = "修改 ST10 步序 20 转移条件"

    res = build_chat_ops(prompt, canvas, use_llm=False)
    assert res["ok"] is True
    assert res["delta"]["modified_slots"] == ["slot3_SeqAuto"]
    assert "step_20.transition" in res["delta"]["patch"]
    assert res["diff_summary"]["station_id"] == "ST10"


def test_build_chat_ops_station_slot_llm_flow(monkeypatch) -> None:
    import json
    from gateway.app.services.plc.chat_ops import build_chat_ops
    from plc_engine.canvas_model import create_empty_canvas
    import gateway.app.services.plc.llm_explain as le

    llm_payload = {
        "stationId": "ST10",
        "modifiedSlots": ["slot4_Interlock"],
        "patch": {
            "Cyl_Lift.releaseWork": '#i_stOpMode.xSafetyOk AND "DB_AxisX".xInPos AND #Cyl_Grip.q_xInHome',
        },
        "explanation": "LLM 受控编辑：在升降下降前增加夹爪原位互锁",
    }

    def fake_raw(messages, settings, **kw):
        return json.dumps(llm_payload), {"prompt_tokens": 300, "completion_tokens": 50}

    monkeypatch.setattr(le, "llm_settings", lambda: {"base_url": "u", "api_key": "k", "model": "m"})
    monkeypatch.setattr(le, "chat_completion_raw", fake_raw)

    canvas = create_empty_canvas("T")
    prompt = "在 ST10 升降气缸下降前增加夹爪原位互锁"

    res = build_chat_ops(prompt, canvas, use_llm=True)
    assert res["ok"] is True
    assert res["source"] == "llm_slot_editor"
    assert res["station_id"] == "ST10"
    assert res["explanation"] == "LLM 受控编辑：在升降下降前增加夹爪原位互锁"
    assert "#Cyl_Grip.q_xInHome" in res["delta"]["patch"]["Cyl_Lift.releaseWork"]
