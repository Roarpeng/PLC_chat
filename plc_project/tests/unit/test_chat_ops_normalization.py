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
