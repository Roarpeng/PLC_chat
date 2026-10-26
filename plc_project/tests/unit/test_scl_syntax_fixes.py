"""真实工程 HR001 暴露的 SCL 语法缺陷回归测试。

每个用例都对应一次真机（TIA Portal V19 + Openness）编译失败，修复前
在 HR001（85 块机器人工程）上实测：
  - 46 个块生成空 ``X : Struct;`` → 「STRUCT 关键字后有不正确的 ';'」
  - 14 个块重复声明 PT/ET/IN/Q → 重名
  - 1 个块 ``VAR_CONSTANT`` → 「设定值 VAR_CONSTANT 无效」
  - 1 个块多行横幅注释未逐行加 // → 「设定值 VAR_OUTPUT 无效」
  - 1 个块 ``S5Time : Time`` / ``String : String[5]`` → 「设定值 S5Time 无效」

测试工程 CanvasE2E 只有 4 个简单块，以上一条都覆盖不到。
"""

from __future__ import annotations

from agents.plc.tia.ir import Block, BlockType, InterfaceSection, Variable
from agents.plc.tia.scl import _sc_ident, translate_block_to_scl


def _struct_var(name: str, members: list[Variable], section=InterfaceSection.STATIC) -> Variable:
    return Variable(name=name, section=section, data_type="Struct", members=members)


def test_struct_is_expanded_not_emitted_empty():
    """STRUCT 必须展开成员，不能输出空的 ``X : Struct;``。"""
    block = Block(
        name="FB_StructTest",
        number=1,
        block_type=BlockType.FB,
        programming_language="LAD",
        interface=[
            _struct_var(
                "Ctrl",
                [
                    Variable(name="Start", data_type="Bool"),
                    Variable(name="Speed", data_type="Int"),
                ],
            )
        ],
    )
    scl = translate_block_to_scl(block)
    assert ": Struct;" not in scl.replace(" ", "") or "END_STRUCT" in scl
    assert "Ctrl : Struct" in scl
    assert "Start : Bool;" in scl
    assert "Speed : Int;" in scl
    assert "END_STRUCT;" in scl


def test_nested_struct_is_expanded_recursively():
    inner = _struct_var("Inner", [Variable(name="Flag", data_type="Bool")])
    outer = _struct_var("Outer", [inner, Variable(name="Count", data_type="DInt")])
    block = Block(
        name="FB_Nested",
        number=2,
        block_type=BlockType.FB,
        interface=[outer],
    )
    scl = translate_block_to_scl(block)
    assert scl.count("END_STRUCT;") == 2
    assert "Flag : Bool;" in scl
    assert "Count : DInt;" in scl


def test_duplicate_static_vars_declared_once():
    """同名变量只能声明一次：多个 TON 实例推断出的 PT/ET/IN/Q 不能重复。"""
    block = Block(
        name="FB_Dup",
        number=3,
        block_type=BlockType.FB,
        interface=[
            Variable(name="PT", data_type="Time"),
            Variable(name="ET", data_type="Time"),
            Variable(name="PT", data_type="Time"),
            Variable(name="ET", data_type="Time"),
            Variable(name="IN", data_type="Bool"),
            Variable(name="IN", data_type="Bool"),
            Variable(name="Q", data_type="Bool"),
            Variable(name="Q", data_type="Bool"),
        ],
    )
    scl = translate_block_to_scl(block)
    assert scl.count("PT : Time;") == 1
    assert scl.count("ET : Time;") == 1
    assert scl.count("IN : Bool;") == 1
    assert scl.count("Q : Bool;") == 1


def test_constant_section_uses_var_constant_keyword():
    """``VAR CONSTANT``（带空格）才是合法 SCL，``VAR_CONSTANT`` 会被 TIA 拒绝。"""
    block = Block(
        name="FB_Const",
        number=4,
        block_type=BlockType.FB,
        interface=[Variable(name="MAX_LEN", section=InterfaceSection.CONSTANT, data_type="Int", start_value="100")],
    )
    scl = translate_block_to_scl(block)
    assert "VAR CONSTANT" in scl
    assert "VAR_CONSTANT" not in scl
    assert "MAX_LEN : Int := 100;" in scl


def test_multiline_header_comment_fully_commented():
    """多行块注释必须逐行加 //，否则裸文本会被当代码（VAR_OUTPUT 无效）。"""
    block = Block(
        name="FB_Banner",
        number=5,
        block_type=BlockType.FB,
        header_comment="************************************************\n上海某公司\nV2014.10.25\n******",
        interface=[Variable(name="X", data_type="Bool")],
    )
    scl = translate_block_to_scl(block)
    for line in scl.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        assert stripped.startswith(("//", "FUNCTION_BLOCK", "VAR", "END_VAR", "BEGIN", "END_FUNCTION_BLOCK", "X :")) or stripped.startswith(
            ("(*",)
        ), "多行注释产生了裸文本行: %r" % line


def test_multiline_network_comment_fully_commented():
    from agents.plc.tia.ir import Network

    block = Block(
        name="FB_NetComment",
        number=6,
        block_type=BlockType.FB,
        interface=[Variable(name="X", data_type="Bool")],
        networks=[Network(id="1", title="第一行\n第二行", comment="注释甲\n注释乙")],
    )
    scl = translate_block_to_scl(block)
    assert "// 第二行" in scl
    assert "// 注释乙" in scl


def test_reserved_and_space_identifiers_are_quoted():
    """变量名带空格或撞上保留类型名时必须加双引号。"""
    assert _sc_ident("Reserved Word 18") == '"Reserved Word 18"'
    assert _sc_ident("S5Time") == '"S5Time"'
    assert _sc_ident("String") == '"String"'
    assert _sc_ident("Char") == '"Char"'
    assert _sc_ident("NormalName") == "NormalName"
    assert _sc_ident("Motor1") == "Motor1"


def test_reserved_ident_in_declaration():
    block = Block(
        name="DB_Reserved",
        number=7,
        block_type=BlockType.DB,
        interface=[
            Variable(name="Reserved Word 1", data_type="Word"),
            Variable(name="S5Time", data_type="Time"),
            Variable(name="Normal", data_type="Bool"),
        ],
    )
    scl = translate_block_to_scl(block)
    assert '"Reserved Word 1" : Word;' in scl
    assert '"S5Time" : Time;' in scl
    assert "Normal : Bool;" in scl


def test_instance_db_is_not_generated():
    """实例 DB 由 TIA 随 FB 自动创建，生成它必然与 FB 接口不一致。"""
    from agents.plc.tia.ir import PlcProject

    inst_db = Block(
        name="DB1060_AutoStep",
        number=1060,
        block_type=BlockType.DB,
        attributes={"InstanceOfName": "FB1060_AutoStep"},
        interface=[Variable(name="CycleTime", data_type='"FB5008_CycleTime"')],
    )
    global_db = Block(
        name="DB1009_Constant",
        number=1009,
        block_type=BlockType.DB,
        interface=[Variable(name="K", data_type="Int")],
    )
    fb = Block(name="FB1060_AutoStep", number=1060, block_type=BlockType.FB)
    project = PlcProject(
        name="T",
        blocks={"DB1060_AutoStep": inst_db, "DB1009_Constant": global_db, "FB1060_AutoStep": fb},
    )
    from agents.plc.tia.scl import convert_project_to_scl

    out = convert_project_to_scl(project)
    assert "DB1060_AutoStep" not in out, "实例 DB 不该生成 SCL"
    assert "DB1009_Constant" in out, "全局 DB 仍要生成"
    assert "FB1060_AutoStep" in out


def test_struct_members_parsed_from_simaticml(tmp_path):
    """嵌套 <Member Datatype="Struct"> 必须被递归解析，否则 SCL 只能生成空 Struct。"""
    from agents.plc.tia.simaticml import parse_interface

    xml = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.FB ID="0">
    <AttributeList><Interface>
      <Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4">
        <Section Name="Static">
          <Member Name="HorDrillStep" Datatype="Struct">
            <Comment><MultiLanguageText Lang="zh-CN">水平钻孔</MultiLanguageText></Comment>
            <Member Name="Busy" Datatype="Bool" />
            <Member Name="Depth" Datatype="Int" />
          </Member>
          <Member Name="Plain" Datatype="Bool" />
        </Section>
      </Sections>
    </Interface></AttributeList>
  </SW.Blocks.FB>
</Document>
"""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    iface = None
    for node in root.iter():
        if node.tag.endswith("Interface"):
            iface = node
            break
    assert iface is not None
    variables = parse_interface(iface)
    names = {v.name: v for v in variables}
    assert "HorDrillStep" in names
    assert names["HorDrillStep"].comment == "水平钻孔"
    assert len(names["HorDrillStep"].members) == 2
    assert {m.name for m in names["HorDrillStep"].members} == {"Busy", "Depth"}


def test_writeback_bundle_skips_synced_blocks(tmp_path):
    """未改动的块（synced）不能被重写进 TIA。

    真实工程 HR001 实测：画布 89 块全部 synced 时若非全量重写，会把原工程
    编译错误从 0 推到 1007。写回 bundle 必须只含真正改动过的块。
    """
    import json

    from plc_engine.canvas_model import CanvasBlock, CanvasState
    from plc_engine.canvas_tia_transpiler import canvas_to_tia_bundle

    canvas = CanvasState(
        project_name="T",
        blocks={
            "FB_Synced": CanvasBlock(
                name="FB_Synced",
                block_type="FB",
                status="synced",
                scl_body="FUNCTION_BLOCK \"FB_Synced\"\nVAR\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK\n",
            ),
            "FB_Draft": CanvasBlock(
                name="FB_Draft",
                block_type="FB",
                status="draft",
                scl_body="FUNCTION_BLOCK \"FB_Draft\"\nVAR\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK\n",
            ),
        },
    )
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")
    staged = json.loads((bundle / "staged_scls.json").read_text(encoding="utf-8"))
    # staged_scls 契约 v2(软件单元感知):[{path, software_unit, block_name}]
    names = [e["block_name"] for e in staged]
    assert "FB_Draft" in names, "改动过的块必须写回"
    assert "FB_Synced" not in names, "未改动的块不得重写"
    entry = next(e for e in staged if e["block_name"] == "FB_Draft")
    assert entry["path"].endswith("FB_Draft.scl"), entry["path"]
    assert entry["software_unit"] in ("", None), "未声明软件单元时为空"


def test_all_synced_canvas_produces_empty_bundle(tmp_path):
    """全部 synced 时 bundle 不该含任何 SCL（走纯编译验证路径）。"""
    import json

    from plc_engine.canvas_model import CanvasBlock, CanvasState
    from plc_engine.canvas_tia_transpiler import canvas_to_tia_bundle

    canvas = CanvasState(
        project_name="T",
        blocks={
            "FB_A": CanvasBlock(name="FB_A", block_type="FB", status="synced", scl_body="FUNCTION_BLOCK \"FB_A\"\nBEGIN\nEND_FUNCTION_BLOCK\n"),
            "FB_B": CanvasBlock(name="FB_B", block_type="FB", status="synced", scl_body="FUNCTION_BLOCK \"FB_B\"\nBEGIN\nEND_FUNCTION_BLOCK\n"),
        },
    )
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "b2")
    staged = json.loads((bundle / "staged_scls.json").read_text(encoding="utf-8"))
    assert staged == []
