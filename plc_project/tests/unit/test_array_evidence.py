"""array_evidence 单测：手写最小 SimaticML 片段驱动的接口证据解析。

fixture 刻意贴近 HR001 真机导出形态（Interface 子树带 v5 命名空间、
Struct 直嵌 Member、UDT / 多实例 FB 引用带 Sections 展开、IEC_TIMER
带 None 段、维度编码在 Datatype 串里），但不依赖真机数据目录——
单测必须离线可跑。
"""

from __future__ import annotations

from pathlib import Path

from plc_engine.array_evidence import (
    InterfaceMember,
    array_dims,
    array_lower_bounds,
    default_subscript,
    find_member,
    is_array_type,
    load_block_interfaces,
    parse_block_xml_text,
    resolve_member,
)

_INTERFACE_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"

# ---------------------------------------------------------------------------
# 手写最小 SimaticML fixture
# ---------------------------------------------------------------------------

#: FB fixture：Struct 直嵌 / IEC_TIMER 展开 / UDT 引用 / 多实例 FB / 双维数组
FB_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V19" />
  <SW.Blocks.FB ID="0">
    <AttributeList>
      <Name>FB990_Test</Name>
      <Interface><Sections xmlns="{_INTERFACE_NS}">
  <Section Name="Input">
    <Member Name="i_Start" Datatype="Bool" />
  </Section>
  <Section Name="Output" />
  <Section Name="InOut" />
  <Section Name="Static">
    <Member Name="Aux" Datatype="Struct">
      <Member Name="HoleNo" Datatype="Int" />
      <Member Name="Heart" Datatype="IEC_TIMER" Version="1.0">
        <Sections>
          <Section Name="None">
            <Member Name="PT" Datatype="Time" />
            <Member Name="ET" Datatype="Time" />
            <Member Name="IN" Datatype="Bool" />
            <Member Name="Q" Datatype="Bool" />
          </Section>
        </Sections>
      </Member>
    </Member>
    <Member Name="EdgeDetc" Datatype="Struct">
      <Member Name="Pulse" Datatype="Array[0..15] of Bool" />
    </Member>
    <Member Name="MainStep" Datatype="&quot;UDT_Step&quot;">
      <Sections>
        <Section Name="None">
          <Member Name="Start" Datatype="Bool" />
        </Section>
      </Sections>
    </Member>
    <Member Name="SafetyDoor" Datatype="&quot;FB5002_SafetyDoorV1&quot;">
      <Sections>
        <Section Name="Input">
          <Member Name="i_DoorOverRide" Datatype="Bool" />
        </Section>
        <Section Name="Output" />
      </Sections>
    </Member>
    <Member Name="Map" Datatype="Array[0..2, 1..5] of Int" />
  </Section>
  <Section Name="Temp">
    <Member Name="StepPls" Datatype="Bool" />
  </Section>
</Sections></Interface>
    </AttributeList>
  </SW.Blocks.FB>
</Document>
"""

#: DB fixture：Struct 嵌套 + 1 起界数组（DB1900.Para.Auto_Force 同款形态）
DB_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V19" />
  <SW.Blocks.GlobalDB ID="0">
    <AttributeList>
      <Name>DB990_Comm</Name>
      <Interface><Sections xmlns="{_INTERFACE_NS}">
  <Section Name="Static">
    <Member Name="Para" Datatype="Struct">
      <Member Name="Auto_Force" Datatype="Array[1..200] of Real" />
      <Member Name="HorConcreteZ" Datatype="Real" />
    </Member>
  </Section>
</Sections></Interface>
    </AttributeList>
  </SW.Blocks.GlobalDB>
</Document>
"""

#: 非 SimaticML 块 XML（无块载体元素）→ 应被跳过
NOT_A_BLOCK_XML = """<?xml version="1.0" encoding="utf-8"?>
<Document><Engineering version="V19" /><Other ID="0"><AttributeList /></Other></Document>
"""

#: 非法 XML → 应被跳过（不得抛出）
BROKEN_XML = '<?xml version="1.0"?><Document><unclosed>'


def _fb_tree() -> dict[str, InterfaceMember]:
    parsed = parse_block_xml_text(FB_XML)
    assert parsed is not None
    name, tree = parsed
    assert name == "FB990_Test"
    return tree


# ---------------------------------------------------------------------------
# parse_block_xml_text：纯文本入口
# ---------------------------------------------------------------------------


def test_parse_fb_struct_udt_multinstance_timer() -> None:
    """Struct 直嵌 / UDT 引用 / 多实例 FB / IEC_TIMER 展开全部入树。"""
    tree = _fb_tree()
    assert set(tree) == {
        "i_Start",
        "Aux",
        "EdgeDetc",
        "MainStep",
        "SafetyDoor",
        "Map",
        "StepPls",
    }
    # 声明区落在节点上（顶层成员）
    assert tree["i_Start"].section == "Input"
    assert tree["Aux"].section == "Static"
    assert tree["StepPls"].section == "Temp"

    # Struct 直嵌
    aux = tree["Aux"]
    assert aux.data_type == "Struct"
    assert set(aux.members) == {"HoleNo", "Heart"}
    assert aux.members["HoleNo"].data_type == "Int"

    # IEC_TIMER 多实例：None 段展开 PT/ET/IN/Q
    heart = aux.members["Heart"]
    assert heart.data_type == "IEC_TIMER"
    assert set(heart.members) == {"PT", "ET", "IN", "Q"}
    assert heart.members["PT"].data_type == "Time"

    # UDT 引用：类型串保留引号 + Sections 展开
    assert tree["MainStep"].data_type == '"UDT_Step"'
    assert tree["MainStep"].members["Start"].data_type == "Bool"

    # 多实例 FB 引用：引号类型 + Input 段成员可见
    assert tree["SafetyDoor"].data_type == '"FB5002_SafetyDoorV1"'
    assert tree["SafetyDoor"].members["i_DoorOverRide"].data_type == "Bool"


def test_parse_skips_non_block_and_broken_xml() -> None:
    """非块 XML → None；非法 XML → None（绝不抛出）。"""
    assert parse_block_xml_text(NOT_A_BLOCK_XML) is None
    assert parse_block_xml_text(BROKEN_XML) is None
    assert parse_block_xml_text("") is None


# ---------------------------------------------------------------------------
# load_block_interfaces：目录枚举 + 调用方缓存
# ---------------------------------------------------------------------------


def test_load_block_interfaces_nested_cpu_layout(tmp_path: Path) -> None:
    """顶层传参（含 <CPU>/blocks/*.xml）与 blocks 直传两种形态都能解析。"""
    blocks_dir = tmp_path / "CPU_1200" / "blocks"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "a_FB990_Test.xml").write_text(FB_XML, encoding="utf-8")
    (blocks_dir / "b_DB990_Comm.xml").write_text(DB_XML, encoding="utf-8")
    (blocks_dir / "c_broken.xml").write_text(BROKEN_XML, encoding="utf-8")
    (blocks_dir / "d_not_block.xml").write_text(NOT_A_BLOCK_XML, encoding="utf-8")

    # 顶层目录（任务书给定形态：export/plc 之下是 <CPU>/blocks）
    ifaces = load_block_interfaces(str(tmp_path))
    assert set(ifaces) == {"FB990_Test", "DB990_Comm"}
    assert ifaces["DB990_Comm"]["Para"].members["Auto_Force"].data_type == ("Array[1..200] of Real")

    # blocks 目录直传
    ifaces2 = load_block_interfaces(str(blocks_dir))
    assert set(ifaces2) == {"FB990_Test", "DB990_Comm"}

    # 中间层（<CPU> 目录，内含 blocks/）
    ifaces3 = load_block_interfaces(str(tmp_path / "CPU_1200"))
    assert set(ifaces3) == {"FB990_Test", "DB990_Comm"}


def test_load_block_interfaces_cache_is_caller_owned(tmp_path: Path) -> None:
    """cache 字典由调用方持有：命中返回同一对象；目录不存在 → 空 dict。"""
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    (blocks_dir / "a.xml").write_text(FB_XML, encoding="utf-8")

    cache: dict[str, dict[str, InterfaceMember]] = {}
    first = load_block_interfaces(str(blocks_dir), cache=cache)
    assert len(cache) == 1
    second = load_block_interfaces(str(blocks_dir), cache=cache)
    assert second is first  # 命中缓存，未重新解析

    assert load_block_interfaces(str(tmp_path / "nope")) == {}


# ---------------------------------------------------------------------------
# resolve_member / find_member：路径解析
# ---------------------------------------------------------------------------


def test_resolve_member_struct_path_and_timer() -> None:
    tree = _fb_tree()
    r = resolve_member(tree, "Aux.Heart")
    assert r["found"] is True
    assert r["data_type"] == "IEC_TIMER"
    assert r["is_array"] is False and r["dims"] == 0
    assert r["section"] == "Static"  # 嵌套成员继承声明区语境
    node = find_member(tree, "Aux.Heart")
    assert node is not None and node.members["Q"].data_type == "Bool"


def test_resolve_member_array_facts() -> None:
    tree = _fb_tree()
    r = resolve_member(tree, "EdgeDetc.Pulse")
    assert (r["found"], r["data_type"], r["is_array"], r["dims"]) == (
        True,
        "Array[0..15] of Bool",
        True,
        1,
    )
    assert r["bounds"] == [(0, 15)]
    assert r["subscript"] == "[0]"

    g = resolve_member(tree, "Map")
    assert g["is_array"] is True and g["dims"] == 2
    assert g["bounds"] == [(0, 2), (1, 5)]
    assert g["subscript"] == "[0,1]"


def test_resolve_member_one_based_array_subscript_is_lower_bound() -> None:
    """1 起界数组（DB1900.Para.Auto_Force 同款）：下标必须取下界 [1]，
    机械补 [0] 会直接越界编译失败。"""
    parsed = parse_block_xml_text(DB_XML)
    assert parsed is not None
    _, db_tree = parsed
    r = resolve_member(db_tree, "Para.Auto_Force")
    assert r["found"] is True
    assert r["data_type"] == "Array[1..200] of Real"
    assert r["subscript"] == "[1]"


def test_resolve_member_not_found_variants() -> None:
    tree = _fb_tree()
    for bad in ("Nope", "Aux.Nope", "Aux.Heart.Nope", ""):
        assert resolve_member(tree, bad)["found"] is False, bad
    # 尾随点 tolerated（宽容清洗，不影响真实调用形态——调用方路径
    # 恒以成员名结尾）
    assert resolve_member(tree, "Aux.")["data_type"] == "Struct"
    # 空树 / None 树 → 无证据（不是异常）
    assert resolve_member(None, "Aux")["found"] is False
    assert resolve_member({}, "Aux")["found"] is False


def test_resolve_member_tolerates_block_prefix_and_case() -> None:
    """容忍 "DB 名+路径" / ``#`` 前缀；大小写漂移不丢证据（SCL 不区分大小写）。"""
    parsed = parse_block_xml_text(DB_XML)
    assert parsed is not None
    _, db_tree = parsed
    r = resolve_member(db_tree, '"DB990_Comm".Para.Auto_Force')
    assert r["found"] is True and r["is_array"] is True
    assert resolve_member(db_tree, "#Para.HorConcreteZ")["data_type"] == "Real"
    assert resolve_member(_fb_tree(), "aux.heart")["data_type"] == "IEC_TIMER"


def test_resolve_member_path_through_array_is_not_found() -> None:
    """无下标穿数组（``Arr.x`` 查 ``Arr.x`` 成员）→ 未命中：那是要修的
    缺陷语义，不是解析器要兜的。"""
    tree = _fb_tree()
    assert resolve_member(tree, "Map.Anything")["found"] is False


# ---------------------------------------------------------------------------
# 数组类型小工具
# ---------------------------------------------------------------------------


def test_array_type_helpers() -> None:
    assert is_array_type("Array[0..15] of Bool") is True
    assert is_array_type("array[0..1] of Int") is True  # 大小写不敏感
    assert is_array_type("Bool") is False
    assert is_array_type("") is False

    assert array_dims("Array[0..15] of Bool") == 1
    assert array_dims("Array[0..2, 1..5] of Int") == 2
    assert array_dims("Array[0..2, 0..31, 0..3] of Byte") == 3
    assert array_dims('Array[0..300] of "UDT_TypePara"') == 1
    assert array_dims("Struct") == 0

    assert array_lower_bounds("Array[0..15] of Bool") == [0]
    assert array_lower_bounds("Array[1..200] of Real") == [1]
    assert array_lower_bounds("Array[0..2, 1..5] of Int") == [0, 1]
    # 非整数界（字符下标界）：该维回退 0，保证补出的下标可编译
    assert array_lower_bounds("Array['a'..'z'] of Char") == [0]

    assert default_subscript("Array[0..15] of Bool") == "[0]"
    assert default_subscript("Array[1..200] of Real") == "[1]"
    assert default_subscript("Array[0..2, 1..5] of Int") == "[0,1]"
    assert default_subscript("Bool") == ""
