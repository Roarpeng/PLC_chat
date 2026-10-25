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
