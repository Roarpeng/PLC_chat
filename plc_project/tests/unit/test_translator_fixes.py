"""翻译器发射形态修复回归测试（HR001 缺陷清单回流，治本）。

对应两类已知非法 SCL 输出：

- ① ``JMP`` → TIA SCL 跳转关键字必须是 ``GOTO``（配合 Label 部件发的
  ``<label>:`` 标签）；修复覆盖两条发射路径：
  scl.py 自身发射器（``_emit_jump``）与折叠语句消费出口（折叠层
  flgnet_fold 仍发 ``JMP``，由 scl.translate() 统一归一化）。
- ② 系统指令调用（RD_SYS_T / WR_SYS_T / READ_CLK / TIME_TCK…）→
  LAD 命名参数式 ``RD_SYS_T(EN:=.., RET_VAL:=.., OUT:=..)`` 不是合法
  SCL；合法形态是赋值式 ``#RetVal := RD_SYS_T(#t);``（RET_VAL 语义
  参数提为左值，其余按位置传递，EN 门控退化为 IF 包裹）。

片段风格与 test_tia_translate_fixes.py 一致（内嵌 FlgNet XML）。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from agents.plc.tia.flgnet_fold import fold_network
from agents.plc.tia.scl import (
    NetworkTranslator,
    _normalize_goto_stmt,
    _normalize_sys_func_stmt,
    translate_block_to_scl,
)
from agents.plc.tia.simaticml import parse_block_xml

_FLGNET_OPEN = (
    '<FlgNet xmlns="http://www.siemens.com/automation/Openness/'
    'SW/NetworkSource/FlgNet/v5">'
)
_FLGNET_CLOSE = "</FlgNet>"

_JMP_FORBIDDEN_RE = re.compile(r"\bJMP\b")


def _access(uid: int, name: str, scope: str = "LocalVariable") -> str:
    return f'<Access Scope="{scope}" UId="{uid}"><Symbol><Component Name="{name}" /></Symbol></Access>'


# ---------------------------------------------------------------------------
# 片段：条件跳转 + 标签（Contact 门控 → Jump → Label）
# ---------------------------------------------------------------------------

JUMP_LABEL_NET = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "Gate")}
    <Part Name="Contact" UId="23" />
    <Part Name="Jump" Version="1.0" UId="24">
      <TemplateValue Name="Label" Type="String">Skip</TemplateValue>
    </Part>
    <Part Name="Label" Version="1.0" UId="25">
      <TemplateValue Name="Label" Type="String">Skip</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="31"><Powerrail /><NameCon UId="23" Name="in" /></Wire>
    <Wire UId="32"><IdentCon UId="21" /><NameCon UId="23" Name="operand" /></Wire>
    <Wire UId="33"><NameCon UId="23" Name="out" /><NameCon UId="24" Name="in" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""

# 无条件跳转（in 直连电源母线 → cond == TRUE）
JUMP_UNCONDITIONAL_NET = f"""{_FLGNET_OPEN}
  <Parts>
    <Part Name="Jump" Version="1.0" UId="24">
      <TemplateValue Name="Label" Type="String">Done</TemplateValue>
    </Part>
    <Part Name="Label" Version="1.0" UId="25">
      <TemplateValue Name="Label" Type="String">Done</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="31"><Powerrail /><NameCon UId="24" Name="in" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""

# ---------------------------------------------------------------------------
# 片段：RD_SYS_T（EN 直连电源母线 = 无门控）与 EN 门控变体、WR_SYS_T
# ---------------------------------------------------------------------------

RD_SYS_T_NET = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "CurPLCTime", "GlobalVariable")}
    {_access(23, "RetVal", "GlobalVariable")}
    <Part Name="RD_SYS_T" Version="1.0" UId="30">
      <TemplateValue Name="date_type" Type="Type">DTL</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="41"><Powerrail /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="44"><IdentCon UId="23" /><NameCon UId="30" Name="RET_VAL" /></Wire>
    <Wire UId="45"><IdentCon UId="21" /><NameCon UId="30" Name="OUT" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""

RD_SYS_T_EN_GATED_NET = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "CurPLCTime", "GlobalVariable")}
    {_access(23, "RetVal", "GlobalVariable")}
    {_access(24, "Gate")}
    <Part Name="Contact" UId="26" />
    <Part Name="RD_SYS_T" Version="1.0" UId="30">
      <TemplateValue Name="date_type" Type="Type">DTL</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="40"><Powerrail /><NameCon UId="26" Name="in" /></Wire>
    <Wire UId="46"><IdentCon UId="24" /><NameCon UId="26" Name="operand" /></Wire>
    <Wire UId="47"><NameCon UId="26" Name="out" /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="44"><IdentCon UId="23" /><NameCon UId="30" Name="RET_VAL" /></Wire>
    <Wire UId="45"><IdentCon UId="21" /><NameCon UId="30" Name="OUT" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""

WR_SYS_T_NET = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "NewTime", "GlobalVariable")}
    {_access(23, "RetVal", "GlobalVariable")}
    <Part Name="WR_SYS_T" Version="1.0" UId="30" />
  </Parts>
  <Wires>
    <Wire UId="41"><Powerrail /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="44"><IdentCon UId="23" /><NameCon UId="30" Name="RET_VAL" /></Wire>
    <Wire UId="45"><IdentCon UId="21" /><NameCon UId="30" Name="IN" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""


def _parse_fragment(flgnet: str, block_name: str = "FB_Frag"):
    """Parse one FlgNet fragment embedded in a minimal LAD FB document."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n<Document>\n'
        '  <SW.Blocks.FB ID="0">\n'
        f'    <AttributeList><Name>{block_name}</Name><Number>99</Number>\n'
        "      <ProgrammingLanguage>LAD</ProgrammingLanguage>\n"
        "    </AttributeList>\n"
        '    <ObjectList>\n'
        '      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">\n'
        "        <AttributeList>\n"
        f"          <NetworkSource>{flgnet}</NetworkSource>\n"
        "          <ProgrammingLanguage>LAD</ProgrammingLanguage>\n"
        "        </AttributeList>\n"
        "      </SW.Blocks.CompileUnit>\n"
        "    </ObjectList>\n"
        "  </SW.Blocks.FB>\n"
        "</Document>\n"
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "frag.xml"
        path.write_text(xml, encoding="utf-8")
        return parse_block_xml(path)


def _translate(flgnet: str, *, fold: bool) -> list[str]:
    """Translate one fragment network.

    ``fold=True`` 镜像真实管线（evidence 侧 attach_folded 后 translate 消费
    折叠语句）；``fold=False`` 走 scl.py 自身发射路径（字符串版机器，
    translate_block_to_scl 未挂折叠时的形态）。
    """
    block = _parse_fragment(flgnet)
    network = block.networks[0]
    if fold:
        network.folded = fold_network(network)
    return NetworkTranslator(block, network).translate()


# ---------------------------------------------------------------------------
# ① JMP → GOTO
# ---------------------------------------------------------------------------


def test_jump_emits_goto_self_emit_path() -> None:
    """自发射路径：条件跳转发 ``IF #Gate THEN GOTO Skip; END_IF;``，绝无 JMP。"""
    stmts = _translate(JUMP_LABEL_NET, fold=False)
    assert "IF #Gate THEN GOTO Skip; END_IF;" in stmts
    assert "Skip:" in stmts
    assert not _JMP_FORBIDDEN_RE.search("\n".join(stmts))


def test_jump_emits_goto_folded_path() -> None:
    """折叠路径：折叠层遗留的 ``JMP`` 在 translate 消费出口归一化为 GOTO。"""
    stmts = _translate(JUMP_LABEL_NET, fold=True)
    assert "IF #Gate THEN GOTO Skip; END_IF;" in stmts
    assert "Skip:" in stmts
    assert not _JMP_FORBIDDEN_RE.search("\n".join(stmts))


def test_unconditional_jump_emits_bare_goto_both_paths() -> None:
    """无条件跳转（cond == TRUE）两条路径都发裸 ``GOTO Done;``。"""
    for fold in (False, True):
        stmts = _translate(JUMP_UNCONDITIONAL_NET, fold=fold)
        assert "GOTO Done;" in stmts, f"fold={fold}: {stmts}"
        assert not _JMP_FORBIDDEN_RE.search("\n".join(stmts)), f"fold={fold}: {stmts}"


def test_block_level_translation_has_no_jmp() -> None:
    """整块翻译（translate_block_to_scl，未挂折叠 → 自发射路径）零 JMP。"""
    block = _parse_fragment(JUMP_LABEL_NET)
    scl = translate_block_to_scl(block)
    assert "GOTO Skip;" in scl
    assert not _JMP_FORBIDDEN_RE.search(scl)


def test_normalize_goto_stmt_only_touches_jump_statements() -> None:
    """归一化只改 JMP 语句形态；普通语句原样返回（不误伤）。"""
    assert _normalize_goto_stmt("JMP Done;") == "GOTO Done;"
    assert (
        _normalize_goto_stmt("IF #A AND #B THEN JMP Done; END_IF;")
        == "IF #A AND #B THEN GOTO Done; END_IF;"
    )
    assert _normalize_goto_stmt("#Out := TRUE;") == "#Out := TRUE;"
    assert _normalize_goto_stmt("// 注释里提到 JMP 也不是语句") == "// 注释里提到 JMP 也不是语句"


# ---------------------------------------------------------------------------
# ② 系统指令调用 → 赋值式
# ---------------------------------------------------------------------------


def test_rd_sys_t_self_emit_assignment_form() -> None:
    """自发射路径：``"RetVal" := RD_SYS_T("CurPLCTime");``，无命名参数。"""
    stmts = _translate(RD_SYS_T_NET, fold=False)
    joined = "\n".join(stmts)
    assert '"RetVal" := RD_SYS_T("CurPLCTime");' in stmts
    # 旧非法形态（LAD 命名参数式）不得再出现
    assert "RET_VAL :=" not in joined and "RET_VAL =>" not in joined
    assert "OUT :=" not in joined and "OUT =>" not in joined
    assert "EN :=" not in joined


def test_rd_sys_t_folded_normalized_to_assignment_form() -> None:
    """折叠路径：折叠层的命名参数式（EN:=/RET_VAL=>/OUT=>）被归一化为赋值式。"""
    stmts = _translate(RD_SYS_T_NET, fold=True)
    joined = "\n".join(stmts)
    assert '"RetVal" := RD_SYS_T("CurPLCTime");' in stmts
    assert "RET_VAL" not in joined and "OUT =>" not in joined


def test_rd_sys_t_en_gated_wraps_if_both_paths() -> None:
    """EN 由触点驱动 → 赋值式调用包 ``IF #Gate THEN … END_IF;``（两路径）。"""
    for fold in (False, True):
        stmts = _translate(RD_SYS_T_EN_GATED_NET, fold=fold)
        joined = "\n".join(stmts)
        assert 'IF #Gate THEN "RetVal" := RD_SYS_T("CurPLCTime"); END_IF;' in stmts, (
            f"fold={fold}: {stmts}"
        )
        assert "EN :=" not in joined, f"fold={fold}: EN 门控不得残留命名参数: {stmts}"


def test_wr_sys_t_assignment_form_both_paths() -> None:
    """WR_SYS_T 同理：``"RetVal" := WR_SYS_T("NewTime");``（IN 按位置传）。"""
    for fold in (False, True):
        stmts = _translate(WR_SYS_T_NET, fold=fold)
        assert '"RetVal" := WR_SYS_T("NewTime");' in stmts, f"fold={fold}: {stmts}"


def test_block_level_sys_func_assignment_form() -> None:
    """整块翻译输出赋值式系统函数调用，无命名参数残留。"""
    block = _parse_fragment(RD_SYS_T_NET)
    scl = translate_block_to_scl(block)
    assert '"RetVal" := RD_SYS_T("CurPLCTime");' in scl
    assert "RET_VAL" not in scl


def test_normalize_sys_func_stmt_variants() -> None:
    """归一化单元行为：=> / := 两种命名参数、EN 恢复 IF、未知语句不动。"""
    # 折叠层实际输出形态（=> 输出参数绑定）
    assert (
        _normalize_sys_func_stmt('RD_SYS_T(RET_VAL => "RetVal", OUT => "CurPLCTime");')
        == '"RetVal" := RD_SYS_T("CurPLCTime");'
    )
    # 参数顺序无关 + EN 门控恢复为 IF 包裹
    assert (
        _normalize_sys_func_stmt('RD_SYS_T(EN := #Gate, OUT => "t", RET_VAL := "rv");')
        == 'IF #Gate THEN "rv" := RD_SYS_T("t"); END_IF;'
    )
    # EN 为常量 TRUE → 无包裹
    assert (
        _normalize_sys_func_stmt("WR_SYS_T(EN := TRUE, RET_VAL => #rv, IN => #nt);")
        == "#rv := WR_SYS_T(#nt);"
    )
    # 无参系统函数
    assert _normalize_sys_func_stmt("TIME_TCK(RET_VAL => #Ticks);") == "#Ticks := TIME_TCK();"
    assert _normalize_sys_func_stmt("READ_CLK(RET_VAL => #rv, OUT => #t);") == "#rv := READ_CLK(#t);"
    # 非已知系统函数 / 普通块调用 / 缺 RET_VAL 落点：原样返回，绝不猜改
    assert _normalize_sys_func_stmt('"Other_DB"(IN := #a);') == '"Other_DB"(IN := #a);'
    assert _normalize_sys_func_stmt("#x := #y;") == "#x := #y;"
    assert _normalize_sys_func_stmt('RD_SYS_T(OUT => "t");') == 'RD_SYS_T(OUT => "t");'
