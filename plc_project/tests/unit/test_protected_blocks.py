"""Bug1 回归:know-how / 加密块导出被清空的事故链防护测试。

事故链:加密/知识保护块(know_how / interface_only)导入画布时 scl_body=""
→ 导出时 get_full_scl() 生成空壳 → 写回后 TIA 原始内容被空壳覆盖。

防护分两层:
  1. 主防线:canvas_to_tia_bundle 在 synced 判断**之前**硬跳过 protected 块
     (无论 status 是 synced 还是 draft),跳过名单写入 bundle manifest;
  2. 兜底:get_full_scl 对 protected 块只发完整接口声明 + 空 BEGIN/END +
     [KNOW-HOW PROTECTED] 顶部注释 —— 即使意外被写出也是可读说明而非静默空壳。
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.plc.tia.ir import Block, BlockType, InterfaceSection, Variable
from agents.plc.tia.simaticml import parse_block_xml
from gateway.app.services.plc.canvas_import import _block_to_canvas_block
from plc_engine.canvas_model import CanvasBlock, CanvasNetwork, CanvasState, CanvasVariable
from plc_engine.canvas_tia_transpiler import canvas_to_tia_bundle


def _canvas_two_blocks(protected_status: str = "draft") -> CanvasState:
    """一个 protected FB + 一个普通 FB 的画布(protected 块故意塞了'假体')。"""
    canvas = CanvasState(project_name="ProtectedE2E")
    canvas.blocks["FB_Locked"] = CanvasBlock(
        name="FB_Locked",
        block_type="FB",
        number=10,
        interface=[CanvasVariable(name="Enable", data_type="Bool", section="VAR_INPUT")],
        scl_body="#Enable := TRUE; // 画布上的翻译体,TIA 里才是真体",
        status=protected_status,
        protected=True,
    )
    canvas.blocks["FB_Open"] = CanvasBlock(
        name="FB_Open",
        block_type="FB",
        number=11,
        interface=[CanvasVariable(name="Run", data_type="Bool", section="VAR_INPUT")],
        networks=[CanvasNetwork(id=1, title="logic", scl_text="#Run := TRUE;")],
        status="draft",
    )
    return canvas


def _staged(bundle: Path) -> list[str]:
    return [
        e["block_name"]
        for e in json.loads((bundle / "staged_scls.json").read_text(encoding="utf-8"))
    ]


def _skipped(bundle: Path) -> list[str]:
    return json.loads((bundle / "skipped_protected.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 第 1 层防护:bundle 硬跳过(先于 synced 判断)
# ---------------------------------------------------------------------------

def test_protected_draft_block_excluded_from_bundle(tmp_path: Path) -> None:
    """protected 块即使 status="draft"(被用户改过)也绝不进 bundle。"""
    bundle = canvas_to_tia_bundle(_canvas_two_blocks("draft"), tmp_path / "bundle")

    staged = _staged(bundle)
    assert "FB_Locked" not in staged, "加密块绝不允许写回,TIA 原块必须原样保留"
    assert "FB_Open" in staged, "普通 draft 块不受影响"

    assert _skipped(bundle) == ["FB_Locked"], "跳过名单必须记录被跳过的保护块"

    scl_files = [p.name for p in (bundle / "external_sources").glob("*.scl")]
    assert scl_files == ["FB_Open.scl"], "external_sources 里不允许出现保护块的 .scl"


def test_protected_synced_block_recorded_as_skipped(tmp_path: Path) -> None:
    """synced 的 protected 块同样跳过并记录;普通 synced 块不进跳过名单。"""
    canvas = _canvas_two_blocks("synced")
    canvas.blocks["FB_Open"].status = "synced"
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")

    assert _staged(bundle) == []  # synced 全跳(最小破坏原则不变)
    assert _skipped(bundle) == ["FB_Locked"], "只有保护块进跳过名单"


# ---------------------------------------------------------------------------
# 第 2 层防护:get_full_scl 兜底注释
# ---------------------------------------------------------------------------

def test_get_full_scl_protected_notice_and_interface() -> None:
    blk = _canvas_two_blocks().blocks["FB_Locked"]
    scl = blk.get_full_scl()

    assert "[KNOW-HOW PROTECTED" in scl
    assert "interface only, body not exported" in scl
    assert "must not be overwritten" in scl
    # 完整接口声明保留
    assert "FUNCTION_BLOCK" in scl and '"FB_Locked"' in scl
    assert "VAR_INPUT" in scl and "Enable" in scl
    # 空 BEGIN/END 体:绝不携带画布上的翻译 scl_body
    assert "BEGIN" in scl and "END_FUNCTION_BLOCK" in scl
    assert "#Enable := TRUE" not in scl


def test_get_full_scl_normal_block_unchanged() -> None:
    """普通块回归:get_full_scl 输出不受 protected 字段(默认 False)影响。"""
    scl = _canvas_two_blocks().blocks["FB_Open"].get_full_scl()
    assert "KNOW-HOW PROTECTED" not in scl
    assert "#Run := TRUE;" in scl
    assert scl.startswith('FUNCTION_BLOCK "FB_Open"')


# ---------------------------------------------------------------------------
# 源头标记:parse_block_xml 检测 know_how / 体未导出
# ---------------------------------------------------------------------------

_KNOWHOW_FB_XML = """<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/Openness/SW/ObjectFramework/v3">
  <Engineering version="V19" />
  <SW.Blocks.FB ID="0">
    <AttributeList>
      <Name>FB_VendorSecret</Name>
      <Number>7</Number>
      <ProgrammingLanguage>SCL</ProgrammingLanguage>
    </AttributeList>
    <KnowHowProtection />
    <ObjectList>
      <MultilingualText ID="1" CompositionName="Comment">
        <ObjectList>
          <MultilingualTextItem ID="2" CompositionName="Items">
            <AttributeList>
              <Culture>zh-CN</Culture>
              <Text>Vendor secret block</Text>
            </AttributeList>
          </MultilingualTextItem>
        </ObjectList>
      </MultilingualText>
      <SW.Blocks.InterfaceSection ID="3" CompositionName="Interface">
        <Section Name="Input">
          <Member Name="Enable" Datatype="Bool" />
        </Section>
      </SW.Blocks.InterfaceSection>
    </ObjectList>
  </SW.Blocks.FB>
</Document>
"""

_BODYLESS_FB_XML = _KNOWHOW_FB_XML.replace("FB_VendorSecret", "FB_NoBody").replace(
    "    <KnowHowProtection />\n", ""
)

_NORMAL_FB_XML = _BODYLESS_FB_XML.replace("FB_NoBody", "FB_Normal").replace(
    "      <SW.Blocks.InterfaceSection ID=\"3\" CompositionName=\"Interface\">",
    """      <SW.Blocks.CompileUnit ID="10" CompositionName="CompileUnits">
        <NetworkSource>
          <StructuredText>
            <Token Text="#Enable" />
            <Blank Num="1" />
            <Token Text=":=" UId="0" />
            <Blank Num="1" />
            <Token Text="TRUE" />
            <Token Text=";" />
            <NewLine Num="1" />
          </StructuredText>
        </NetworkSource>
      </SW.Blocks.CompileUnit>
      <SW.Blocks.InterfaceSection ID="3" CompositionName="Interface">""",
)

_BODYLESS_DB_XML = """<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/Openness/SW/ObjectFramework/v3">
  <Engineering version="V19" />
  <SW.Blocks.GlobalDB ID="0">
    <AttributeList>
      <Name>DB_Data</Name>
      <Number>5</Number>
    </AttributeList>
    <ObjectList>
      <SW.Blocks.InterfaceSection ID="3" CompositionName="Interface">
        <Section Name="None">
          <Member Name="Value" Datatype="Int" />
        </Section>
      </SW.Blocks.InterfaceSection>
    </ObjectList>
  </SW.Blocks.GlobalDB>
</Document>
"""


def _write(tmp_path: Path, name: str, xml: str) -> Path:
    f = tmp_path / name
    f.write_text(xml, encoding="utf-8")
    return f


def test_parse_block_xml_marks_knowhow_block_interface_only(tmp_path: Path) -> None:
    block = parse_block_xml(_write(tmp_path, "FB_VendorSecret.xml", _KNOWHOW_FB_XML))
    assert block is not None
    assert block.interface_only is True, "显式 KnowHowProtection 标记必须置 interface_only"


def test_parse_block_xml_marks_bodyless_code_block_interface_only(tmp_path: Path) -> None:
    block = parse_block_xml(_write(tmp_path, "FB_NoBody.xml", _BODYLESS_FB_XML))
    assert block is not None
    assert block.networks == [] and not block.source_text
    assert block.interface_only is True, "FB/FC/OB 无网络且无源文本 = 体未导出"


def test_parse_block_xml_db_without_body_not_marked(tmp_path: Path) -> None:
    block = parse_block_xml(_write(tmp_path, "DB_Data.xml", _BODYLESS_DB_XML))
    assert block is not None
    assert block.interface_only is False, "DB/UDT 本来就没有程序体,不算保护"


def test_parse_block_xml_normal_block_not_marked(tmp_path: Path) -> None:
    block = parse_block_xml(_write(tmp_path, "FB_Normal.xml", _NORMAL_FB_XML))
    assert block is not None
    assert block.networks, "带 StructuredText 网络的普通块应有网络"
    assert block.interface_only is False


# ---------------------------------------------------------------------------
# 全链:导入 → 标记 protected → (用户改动 draft) → 导出跳过
# ---------------------------------------------------------------------------

def test_ir_block_interface_only_marks_canvas_protected(tmp_path: Path) -> None:
    ir_block = Block(
        name="FB_Chained",
        number=3,
        block_type=BlockType.FB,
        programming_language="SCL",
        interface=[
            Variable(name="In", section=InterfaceSection.INPUT, data_type="Bool"),
        ],
        networks=[],
        source_text="",
        interface_only=True,
    )
    canvas = CanvasState(project_name="Chain")
    canvas.blocks["FB_Chained"] = _block_to_canvas_block(ir_block, canvas.blocks)
    cb = canvas.blocks["FB_Chained"]
    assert cb.protected is True, "导入时 interface_only 必须传导为 CanvasBlock.protected"

    # 事故场景复现:导入后用户在画布上动了它(draft)—— 旧实现会把空壳写回 TIA
    cb.status = "draft"
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")
    assert "FB_Chained" not in _staged(bundle)
    assert "FB_Chained" in _skipped(bundle)


def test_knowhow_xml_import_to_bundle_end_to_end(tmp_path: Path) -> None:
    """SimaticML know_how XML → parse → canvas → draft → bundle 全链跳过。"""
    xml = _write(tmp_path, "FB_VendorSecret.xml", _KNOWHOW_FB_XML)
    ir_block = parse_block_xml(xml)
    assert ir_block is not None and ir_block.interface_only is True

    canvas = CanvasState(project_name="KH")
    canvas.blocks[ir_block.name] = _block_to_canvas_block(ir_block, canvas.blocks)
    cb = canvas.blocks[ir_block.name]
    assert cb.protected is True

    cb.status = "draft"  # 即使被改过也绝不写回
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")
    assert ir_block.name not in _staged(bundle)
    assert ir_block.name in _skipped(bundle)


# ---------------------------------------------------------------------------
# 持久化往返:protected 标记不能在 to_dict/from_dict 中丢失
# ---------------------------------------------------------------------------

def test_canvas_state_roundtrip_preserves_protected() -> None:
    canvas = _canvas_two_blocks()
    restored = CanvasState.from_dict(canvas.to_dict())
    assert restored.blocks["FB_Locked"].protected is True
    assert restored.blocks["FB_Open"].protected is False
    # 往返后的保护块仍然产出 KNOW-HOW 说明而非翻译空壳
    assert "[KNOW-HOW PROTECTED" in restored.blocks["FB_Locked"].get_full_scl()
