"""any2scl 回写链 fail-closed 门禁单测（docs/16 §4 / §7）。

验证 ``agents.plc.tia.coverage.assert_scl_safe_for_writeback``：

- 干净输入放行；无证据（空/非 dict）一律拦下（fail-closed）；
- 未翻译 TODO / 不可折叠部件 / GRAPH 降级 / 五类缺陷模式任一存在即抛
  ``SclWritebackUnsafeError``，且异常携带去重块名清单；
- 不改变 ``build_coverage_report`` 等既有函数的返回结构（向后兼容），
  门禁本身对入参无副作用。

坏样本逐字/等价取自 ``docs/16-lad2scl-offline-validation.md`` §3.1、§3.2、
§4 与 §7.1（修复前真实输出），不是凭空编造。
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agents.plc.tia.coverage import (
    SCL_DEFECT_PATTERNS,
    SclWritebackUnsafeError,
    assert_scl_safe_for_writeback,
    build_coverage_report,
    scan_scl_defects,
)
from agents.plc.tia.ir import Block, BlockType, Network, Part, PlcProject

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _clean_scl() -> str:
    return (
        "IF #Start AND NOT (#EStop) THEN\n"
        "    #Run := TRUE;\n"
        "ELSE\n"
        "    #Run := FALSE;\n"
        "END_IF;"
    )


def _clean_project() -> PlcProject:
    project = PlcProject(name="GateDemo", tia_version="V19")
    block = Block(name="FB_Clean", block_type=BlockType.FB, programming_language="LAD")
    network = Network(id="1", title="logic")
    network.parts["1"] = Part(name="Contact", part_type="Contact", uuid="1")
    block.networks.append(network)
    project.add_block(block)
    return project


def _warning(code: str, blocks: list[str], *, count: int = 0) -> dict[str, Any]:
    return {
        "level": "warning",
        "code": code,
        "message": "degradation",
        "affected_blocks": blocks,
        "count": count or len(blocks),
    }


def _codes(exc: SclWritebackUnsafeError) -> set[str]:
    return {str(issue.get("code")) for issue in exc.issues}


# ---------------------------------------------------------------------------
# 干净输入放行
# ---------------------------------------------------------------------------


def test_clean_bare_mapping_passes() -> None:
    assert assert_scl_safe_for_writeback({"FB_Clean": _clean_scl()}) is True


def test_clean_full_result_passes() -> None:
    project = _clean_project()
    coverage = build_coverage_report(project, {"FB_Clean": _clean_scl()})
    result = {
        "project": project,
        "scl_sources": {"FB_Clean": _clean_scl()},
        "coverage": coverage,
        "conversion_report": {"blocks": [{"block": "FB_Clean", "status": "converted"}]},
    }
    assert assert_scl_safe_for_writeback(result) is True


def test_clean_coverage_only_passes() -> None:
    """build_coverage_report 输出（无 SCL 文本）也应能判定为安全。"""
    coverage = build_coverage_report(_clean_project(), {"FB_Clean": _clean_scl()})
    assert assert_scl_safe_for_writeback(coverage) is True


# ---------------------------------------------------------------------------
# (1) 未翻译 TODO
# ---------------------------------------------------------------------------


def test_untranslated_todo_in_scl_text_blocks_writeback() -> None:
    bad = "(* TODO[InRange] uid=101 pins={-} *)"
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback({"FB_Todo": bad})
    assert "untranslated_todo" in _codes(exc.value)
    assert exc.value.blocks == ["FB_Todo"]


def test_untranslated_todo_from_coverage_rows_blocks_writeback() -> None:
    """无 SCL 文本时，coverage.blocks[].todo_parts / status=parsed 仍要拦。"""
    coverage = {
        "todo_count": 2,
        "warning_count": 0,
        "warnings": [],
        "blocks": [
            {"block": "FB_Parsed", "status": "parsed", "todo_parts": ["MOVE_BLK_VARIANT"]},
            {"block": "FB_Converted", "status": "converted", "todo_parts": []},
        ],
    }
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback(coverage)
    assert "untranslated_todo" in _codes(exc.value)
    assert exc.value.blocks == ["FB_Parsed"]


def test_untranslated_todo_from_conversion_report_blocks_writeback() -> None:
    conversion = {
        "total_blocks": 1,
        "converted": 0,
        "parsed": 1,
        "blocks": [{"block": "FB_Parsed", "status": "parsed"}],
    }
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback({"conversion_report": conversion})
    assert "untranslated_todo" in _codes(exc.value)
    assert exc.value.blocks == ["FB_Parsed"]


# ---------------------------------------------------------------------------
# (2) 不可折叠部件 / GRAPH 降级
# ---------------------------------------------------------------------------


def test_unfoldable_parts_blocks_writeback() -> None:
    coverage = {
        "todo_count": 0,
        "blocks": [{"block": "FC_Unknown", "status": "converted", "todo_parts": []}],
        "warnings": [_warning("coverage.unresolved_parts", ["FC_Unknown", "FC_Other"], count=2)],
    }
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback(coverage)
    assert "unfoldable_parts" in _codes(exc.value)
    assert exc.value.blocks == ["FC_Other", "FC_Unknown"]


def test_graph_downgrade_blocks_writeback() -> None:
    coverage = {
        "todo_count": 0,
        "blocks": [],
        "warnings": [_warning("coverage.graph_not_executable", ["FB_Graph"])],
    }
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback(coverage)
    assert "graph_not_executable" in _codes(exc.value)
    assert exc.value.blocks == ["FB_Graph"]


# ---------------------------------------------------------------------------
# (3) 五类缺陷模式：文本痕迹
# ---------------------------------------------------------------------------

#: 每个坏样本对应 docs/16 修复前真实输出（逐字或等价最小片段）。
_BAD_SCL: dict[str, str] = {
    # §3.1 FC2300 net5 修复前：整网只剩数学框 TODO，计算逻辑丢失。
    "S1_statement_loss": "(* TODO[Mul] *)\n(* TODO[Add] *)",
    # §3.2 FB5002 net1 修复前：共享支路被伪环守卫替换。
    "S2_loop_guard": "#Aux.DT2 := ((* loop guard *) AND #i_OpenDoorPmt) AND #Aux.DT2;",
    # §3.1 FB2009 net1 / FB1040 net7 修复前：TypedConstant 未映射 → PT 空。
    "S3_empty_literal": '#Timer_StationToolOn.TON(IN := TRUE, PT := );',
    # §4 S4 解析层显式退化留痕（极性反转的可靠文本代理）。
    "S4_negation_loss": "(* TODO[Negated] uid=36 *)",
    # §3.2 FB2009 net1 修复前：SR 实例/参数全丢 → 空箱体调用。
    "S5_driver_loss": "Sr();",
}


@pytest.mark.parametrize("defect_code,bad_scl", sorted(_BAD_SCL.items()))
def test_each_defect_pattern_is_detected_and_blocks_writeback(
    defect_code: str, bad_scl: str
) -> None:
    assert defect_code in SCL_DEFECT_PATTERNS
    assert defect_code in scan_scl_defects(bad_scl)
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback({"FB_Bad": bad_scl})
    assert defect_code in _codes(exc.value)
    assert exc.value.blocks == ["FB_Bad"]


def test_scan_scl_defects_clean_text_is_empty() -> None:
    assert scan_scl_defects(_clean_scl()) == {}


def test_line_comment_quoted_true_does_not_trigger_s3() -> None:
    """解释性 // 注释里出现 "TRUE" 不能误报 S3（只看代码文本）。"""
    scl = '// 含义：当 "TRUE" 条件成立时置位\n#Run := TRUE;'
    assert scan_scl_defects(scl) == {}


def test_block_comment_todo_is_still_detected() -> None:
    """S1/S2 左痕在 (* ... *) 块注释里，去 // 行注释不影响。"""
    assert "S2_loop_guard" in scan_scl_defects("(* loop guard *)")
    assert "S1_statement_loss" in scan_scl_defects("(* TODO[CoilTON] *)")


def test_s4_negated_parts_conservation_blocks_writeback() -> None:
    """S4 极性反转无稳定文本 token：借 PlcProject 的 negated 部件做守恒检查。

    含 <Negated Name="operand"/> 的块，其最终 SCL 必须出现 ``NOT (``；
    否则按 S4 拦下（修复前 EMMode/i_AutoRunning 极性反转的机理复现）。
    """
    project = _clean_project()
    part = project.blocks["FB_Clean"].networks[0].parts["1"]
    part.negated = True
    part.negated_pins = {"operand"}

    lost = "#Run := #EMMode AND #i_AutoRunning;"  # NOT 全丢
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback({"project": project, "scl_sources": {"FB_Clean": lost}})
    assert "S4_negation_loss" in _codes(exc.value)
    assert exc.value.blocks == ["FB_Clean"]

    # 恢复 NOT 后不再触发 S4
    restored = "#Run := NOT (#EMMode) AND NOT (#i_AutoRunning);"
    assert assert_scl_safe_for_writeback(
        {"project": project, "scl_sources": {"FB_Clean": restored}}
    ) is True


def test_without_project_s4_text_pattern_still_works() -> None:
    """拿不到 PlcProject 时，S4 显式退化留痕仍能被文本扫描拦住。"""
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback({"scl_sources": {"FB_Neg": _BAD_SCL["S4_negation_loss"]}})
    assert "S4_negation_loss" in _codes(exc.value)


# ---------------------------------------------------------------------------
# 组合 / fail-closed / 向后兼容
# ---------------------------------------------------------------------------


def test_multiple_issues_carry_deduped_block_list_and_all_codes() -> None:
    result = {
        "scl_sources": {
            "FB_A": "(* TODO[Mul] *)\n(* TODO[Add] *)",
            "FB_B": "#Aux.DT2 := ((* loop guard *) AND #x);",
        },
        "coverage": {
            "todo_count": 2,
            "blocks": [
                {"block": "FB_A", "status": "parsed", "todo_parts": ["Mul", "Add"]},
                {"block": "FB_B", "status": "converted", "todo_parts": []},
            ],
            "warnings": [_warning("coverage.unresolved_parts", ["FB_A"])],
        },
    }
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback(result)
    assert {
        "untranslated_todo",
        "unfoldable_parts",
        "S1_statement_loss",
        "S2_loop_guard",
    } <= _codes(exc.value)
    assert exc.value.blocks == ["FB_A", "FB_B"]  # 去重、排序
    message = str(exc.value)
    assert "FB_A" in message and "FB_B" in message
    assert "受影响块清单" in message


@pytest.mark.parametrize("bad_input", [{}, [], None, "not-a-dict", 0])
def test_no_evidence_is_fail_closed(bad_input: Any) -> None:
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback(bad_input)
    assert "no_evidence" in _codes(exc.value)


def test_gate_does_not_mutate_input_and_keeps_coverage_shape() -> None:
    """向后兼容：门禁只读；build_coverage_report 返回结构/内容一字不变。"""
    project = _clean_project()
    coverage = build_coverage_report(project, {"FB_Clean": _clean_scl()})
    before = copy.deepcopy(coverage)
    required_keys = {
        "project_name", "todo_count", "todo_rate", "translated_rate", "warnings",
        "warning_count", "converted", "parsed", "interface_only", "unknown",
        "total_blocks", "blocks", "categories", "language_histogram", "todo_histogram",
        "top_untranslated_parts",
    }
    assert required_keys <= set(coverage)
    assert assert_scl_safe_for_writeback(coverage) is True
    assert coverage == before  # 无副作用


def test_all_five_patterns_are_distinct_and_nonempty() -> None:
    assert len(SCL_DEFECT_PATTERNS) == 5
    assert all(patterns for patterns in SCL_DEFECT_PATTERNS.values())
    assert set(SCL_DEFECT_PATTERNS) == {
        "S1_statement_loss",
        "S2_loop_guard",
        "S3_empty_literal",
        "S4_negation_loss",
        "S5_driver_loss",
    }
