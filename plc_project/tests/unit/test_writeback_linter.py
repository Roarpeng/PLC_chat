"""writeback_linter 单测：V3.0 蓝图 Tab5 五条静态规则。

所有 SCL 片段都内联成字符串，不读外部文件。
"""

from __future__ import annotations

import pytest

from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_linter import LintError, assert_clean, lint_block, lint_bundle


def fb(name: str, body: str) -> BlockArtifact:
    """把片段包装成一个 FB 块（片段里自带 BEGIN/END_FUNCTION_BLOCK）。"""
    return BlockArtifact(name=name, kind="FB", source=body)


def rules(findings: list) -> list[str]:
    return [f.rule for f in findings]


def by_rule(findings: list, rule: str) -> list:
    return [f for f in findings if f.rule == rule]


# --------------------------------------------------------------------------
# 干净的块：零 finding
# --------------------------------------------------------------------------

FB_CLEAN = """FUNCTION_BLOCK "FB_Clean"
VAR_INPUT
  xStart : Bool;
  iCount : Int;
END_VAR
VAR
  statStep : Int;
  iMax : Int;
END_VAR
VAR_TEMP
  tTmp : Bool;
END_VAR
BEGIN
  // 启动时清零：中文注释不触发任何规则
  #statStep := 0;
  IF #xStart AND #iCount < #iMax THEN
    #tTmp := TRUE;
    #statStep := 10;
  END_IF;
END_FUNCTION_BLOCK
"""


def test_clean_block_has_no_findings() -> None:
    assert lint_block(fb("FB_Clean", FB_CLEAN)) == []


def test_clean_bundle_is_assertable() -> None:
    assert_clean([fb("FB_Clean", FB_CLEAN)], bom_enabled=False)  # 只有 R5 warning，不阻断


# --------------------------------------------------------------------------
# R1 符号作用域定界符
# --------------------------------------------------------------------------

FB_R1_BARE = """FUNCTION_BLOCK "FB_R1"
VAR_INPUT
  xStart : Bool;
END_VAR
VAR
  statStep : Int;
END_VAR
BEGIN
  statStep := 0;
  IF xStart THEN
    #statStep := 1;
  END_IF;
END_FUNCTION_BLOCK
"""


def test_r1_local_variable_without_hash_is_error() -> None:
    findings = by_rule(lint_block(fb("FB_R1", FB_R1_BARE)), "R1")
    hits = [f for f in findings if "缺少 # 前缀" in f.message]
    assert {f.line for f in hits} == {9, 10}
    assert all(f.severity == "error" for f in hits)
    assert "statStep" in hits[0].message


def test_r1_local_variable_with_hash_is_clean() -> None:
    assert by_rule(lint_block(fb("FB_Clean", FB_CLEAN)), "R1") == []


# 被调 FB 的形式参数名与本块声明重名时不能误判（LAD 转换代码里极常见）
FB_R1_NAMED_ARG = """FUNCTION_BLOCK "FB_R1Arg"
VAR
  iEnable : Bool;
  oLamp : Bool;
  Cyl_Lift : FB_Cylinder;
END_VAR
BEGIN
  #Cyl_Lift(iEnable := #iEnable, oLamp => "Q0.6");
END_FUNCTION_BLOCK
"""


def test_r1_callee_named_argument_is_not_flagged() -> None:
    assert by_rule(lint_block(fb("FB_R1Arg", FB_R1_NAMED_ARG)), "R1") == []


FB_R1_CJK = """FUNCTION_BLOCK "FB_R1Cjk"
VAR
  xStart : Bool;
END_VAR
BEGIN
  "Motor状态" := TRUE;
  Motor状态 := #xStart;
END_FUNCTION_BLOCK
"""


def test_r1_chinese_global_without_quotes_is_error() -> None:
    hits = [f for f in by_rule(lint_block(fb("FB_R1Cjk", FB_R1_CJK)), "R1") if "含中文" in f.message]
    assert len(hits) == 1
    assert hits[0].line == 7
    assert '写成 "Motor状态"' in hits[0].message


def test_r1_chinese_global_with_quotes_is_clean() -> None:
    src = FB_R1_CJK.replace("  Motor状态 := #xStart;\n", "")
    assert by_rule(lint_block(fb("FB_R1Cjk", src)), "R1") == []


FB_R1_COMMENT = """FUNCTION_BLOCK "FB_R1Cmt"
VAR
  statStep : Int;
  xStart : Bool;
END_VAR
BEGIN
  // 这里写 statStep := 1; 是注释，不该报 R1
  (* 中文注释 Motor状态 也不该报 R1 *)
  #statStep := 0;
END_FUNCTION_BLOCK
"""


def test_r1_comment_content_is_ignored() -> None:
    assert by_rule(lint_block(fb("FB_R1Cmt", FB_R1_COMMENT)), "R1") == []


# --------------------------------------------------------------------------
# R2 单线圈唯一性
# --------------------------------------------------------------------------

FB_R2_DIRECT = """FUNCTION_BLOCK "FB_R2"
VAR_INPUT
  xStart : Bool;
END_VAR
BEGIN
  "Q0.0" := #xStart;
END_FUNCTION_BLOCK
"""

FB_R2_BINDING = """FUNCTION_BLOCK "FB_R2Ok"
VAR_INPUT
  xStart : Bool;
END_VAR
VAR
  Cyl_Lift : FB_Cylinder;
END_VAR
BEGIN
  #Cyl_Lift(i_xSenHome := #xStart, q_xOutHome => "Q0.0", q_xOutDown => %Q0.4);
END_FUNCTION_BLOCK
"""


def test_r2_physical_output_on_assign_left_is_error() -> None:
    hits = [f for f in by_rule(lint_block(fb("FB_R2", FB_R2_DIRECT)), "R2") if ":= 左侧" in f.message]
    assert len(hits) == 1
    assert hits[0].line == 6
    assert hits[0].severity == "error"
    assert "输出绑定" in hits[0].message


def test_r2_fb_output_binding_is_allowed() -> None:
    hits = [f for f in by_rule(lint_block(fb("FB_R2Ok", FB_R2_BINDING)), "R2") if "绑定" in f.message or "左侧" in f.message]
    assert hits == []  # q_xOutHome => "Q0.0" 是合法写法


FB_R2_TWICE = """FUNCTION_BLOCK "FB_R2Twice"
VAR_INPUT
  xStart : Bool;
  xStop : Bool;
END_VAR
BEGIN
  "Q0.2" := #xStart;
  "Q0.2" := #xStop;
END_FUNCTION_BLOCK
"""


def test_r2_same_block_twice_is_error() -> None:
    findings = by_rule(lint_block(fb("FB_R2Twice", FB_R2_TWICE)), "R2")
    dup = [f for f in findings if "被赋值 2 次" in f.message]
    assert len(dup) == 1
    assert dup[0].line == 8


FB_R2_A = """FUNCTION_BLOCK "FB_R2A"
VAR
  xStart : Bool;
END_VAR
BEGIN
  "Q0.5" := #xStart;
END_FUNCTION_BLOCK
"""

FB_R2_B = """FUNCTION_BLOCK "FB_R2B"
VAR
  xStop : Bool;
END_VAR
BEGIN
  "Q0.5" := #xStop;
END_FUNCTION_BLOCK
"""


def test_r2_cross_block_double_write_is_error() -> None:
    findings = by_rule(lint_bundle([fb("FB_R2A", FB_R2_A), fb("FB_R2B", FB_R2_B)]), "R2")
    cross = [f for f in findings if "多个块同时赋值" in f.message]
    assert len(cross) == 1
    assert "FB_R2A" in cross[0].block and "FB_R2B" in cross[0].block
    # 单块层面各自只有一条"直接赋值"错误，跨块错误只在 bundle 出现
    assert len([f for f in by_rule(lint_block(fb("FB_R2A", FB_R2_A)), "R2")]) == 1


# --------------------------------------------------------------------------
# R3 状态机内禁放有状态指令
# --------------------------------------------------------------------------

FB_R3_HIT = """FUNCTION_BLOCK "FB_R3"
VAR_INPUT
  xStart : Bool;
END_VAR
VAR
  iStep : Int;
  tonDelay : TON;
END_VAR
BEGIN
  CASE #iStep OF
    1:
      #tonDelay(IN := #xStart, PT := T#1s);
  END_CASE;
END_FUNCTION_BLOCK
"""

FB_R3_OK = """FUNCTION_BLOCK "FB_R3Ok"
VAR_INPUT
  xStart : Bool;
END_VAR
VAR
  iStep : Int;
  tonDelay : TON;
  Cyl_Lift : FB_Cylinder;
END_VAR
BEGIN
  #tonDelay(IN := #xStart, PT := T#1s);
  CASE #iStep OF
    1:
      #Cyl_Lift(i_xSenHome := #xStart, q_xOutHome => "Q0.3");
      #iStep := 2;
  END_CASE;
END_FUNCTION_BLOCK
"""

FB_R3_NESTED = """FUNCTION_BLOCK "FB_R3Nest"
VAR_INPUT
  xStart : Bool;
END_VAR
VAR
  iStep : Int;
  iSub : Int;
  rtEdge : R_TRIG;
END_VAR
BEGIN
  CASE #iStep OF
    1:
      CASE #iSub OF
        1:
          #rtEdge(CLK := #xStart);
      END_CASE;
  END_CASE;
END_FUNCTION_BLOCK
"""


def test_r3_stateful_instance_call_inside_case_is_error() -> None:
    hits = by_rule(lint_block(fb("FB_R3", FB_R3_HIT)), "R3")
    assert len(hits) == 1
    assert hits[0].line == 12
    assert "第 10 行" in hits[0].message  # CASE 起始行
    assert "残留" in hits[0].message


def test_r3_stateful_outside_case_is_clean() -> None:
    assert by_rule(lint_block(fb("FB_R3Ok", FB_R3_OK)), "R3") == []


def test_r3_element_fb_call_is_not_flagged() -> None:
    findings = lint_block(fb("FB_R3Ok", FB_R3_OK))
    assert by_rule(findings, "R3") == []  # #Cyl_Lift(...) 留在 CASE 内合法


def test_r3_nested_case_points_to_innermost() -> None:
    block = fb("FB_R3Nest", FB_R3_NESTED)
    hits = by_rule(lint_block(block), "R3")
    assert len(hits) == 1
    lines = FB_R3_NESTED.splitlines()
    inner_case_line = next(i for i, text in enumerate(lines, 1) if text.strip().startswith("CASE #iSub"))
    call_line = next(i for i, text in enumerate(lines, 1) if "#rtEdge(" in text)
    assert hits[0].line == call_line
    assert f"第 {inner_case_line} 行" in hits[0].message


# --------------------------------------------------------------------------
# R4 数据类型隐式转换
# --------------------------------------------------------------------------

FB_R4_MIX = """FUNCTION_BLOCK "FB_R4"
VAR_INPUT
  iCount : Int;
  diTotal : DInt;
  rRatio : Real;
END_VAR
BEGIN
  IF #iCount = #diTotal THEN
    ;
  END_IF;
  IF #rRatio > #iCount THEN
    ;
  END_IF;
END_FUNCTION_BLOCK
"""

FB_R4_OK = """FUNCTION_BLOCK "FB_R4Ok"
VAR_INPUT
  iCount : Int;
  iMax : Int;
END_VAR
VAR
  tDelay : Time;
END_VAR
BEGIN
  IF #iCount < #iMax THEN
    #tDelay := T#500ms;
  END_IF;
  #tDelay := TIME#2s;
END_FUNCTION_BLOCK
"""


def test_r4_int_vs_dint_and_real_comparison_warns() -> None:
    hits = by_rule(lint_block(fb("FB_R4", FB_R4_MIX)), "R4")
    assert {f.line for f in hits} == {8, 11}
    assert all(f.severity == "warning" for f in hits)
    assert "隐式转换" in hits[0].message


def test_r4_same_type_comparison_and_time_constant_is_clean() -> None:
    assert by_rule(lint_block(fb("FB_R4Ok", FB_R4_OK)), "R4") == []


FB_R4_TIME_BARE = """FUNCTION_BLOCK "FB_R4T"
VAR
  tDelay : Time;
END_VAR
BEGIN
  #tDelay := 500;
END_FUNCTION_BLOCK
"""


def test_r4_bare_number_to_time_variable_warns() -> None:
    hits = by_rule(lint_block(fb("FB_R4T", FB_R4_TIME_BARE)), "R4")
    assert len(hits) == 1
    assert hits[0].line == 6
    assert "T#500ms" in hits[0].message


def test_r4_bare_number_to_int_variable_is_not_reported() -> None:
    src = FB_R4_TIME_BARE.replace("tDelay : Time;", "iDelay : Int;")
    assert by_rule(lint_block(fb("FB_R4T", src)), "R4") == []


# --------------------------------------------------------------------------
# R5 UTF-8 BOM
# --------------------------------------------------------------------------

ASCII_BLOCK = """FUNCTION_BLOCK "FB_Ascii"
VAR
  xStart : Bool;
END_VAR
BEGIN
  #xStart := TRUE;
END_FUNCTION_BLOCK
"""


def test_r5_chinese_without_bom_declaration_warns() -> None:
    hits = by_rule(lint_bundle([fb("FB_Clean", FB_CLEAN)], bom_enabled=False), "R5")
    assert len(hits) == 1
    assert hits[0].severity == "warning"
    assert "UTF-8 BOM" in hits[0].message


def test_r5_bom_enabled_by_default() -> None:
    assert by_rule(lint_bundle([fb("FB_Clean", FB_CLEAN)]), "R5") == []


def test_r5_pure_ascii_block_never_warns() -> None:
    assert by_rule(lint_bundle([fb("FB_Ascii", ASCII_BLOCK)], bom_enabled=False), "R5") == []


# --------------------------------------------------------------------------
# assert_clean
# --------------------------------------------------------------------------


def test_assert_clean_raises_on_error() -> None:
    with pytest.raises(LintError) as excinfo:
        assert_clean([fb("FB_R1", FB_R1_BARE)])
    assert excinfo.value.findings
    assert any(f.severity == "error" for f in excinfo.value.findings)
    assert isinstance(excinfo.value, ValueError)


def test_assert_clean_passes_on_clean_bundle() -> None:
    assert_clean([fb("FB_Ascii", ASCII_BLOCK), fb("FB_R4Ok", FB_R4_OK)])
