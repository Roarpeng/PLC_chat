"""TIA Openness XML 块接口证据库（只读解析，供 autofix 规则做类型对账）。

数据源：TIA Openness 导出目录 ``…/export/plc/<CPU>/blocks/*.xml``
（SimaticML 方言，Interface 子树带独立命名空间
``http://www.siemens.com/automation/Openness/SW/Interface/v5``）。

设计约束：
- 纯解析、无画布 / gateway 依赖——``plc_engine.canvas_model`` 单向依赖本模块，
  反向绝不 import（避免环）；
- XML 是类型的唯一权威：成员名、类型串（含 ``Array[0..15] of Bool`` 维度）、
  UDT / 多实例 FB 引用（``Datatype="&quot;UDT_Step&quot;"``）、IEC_TIMER 展开，
  全部以 XML 导出为准；
- 内存缓存由调用方管理：本模块不自建全局缓存，``load_block_interfaces``
  可选接收调用方持有的 ``cache`` 字典（命中即复用，未命中解析后回填），
  保证函数行为可测、可失效。

覆盖的 SimaticML 结构（真机 HR001 导出实测形态）：
- 块载体：``SW.Blocks.FB`` / ``SW.Blocks.FC`` / ``SW.Blocks.OB`` /
  ``SW.Blocks.GlobalDB`` / ``SW.Blocks.InstanceDB`` / ``SW.Types.PADT``（UDT）；
- 块名：``AttributeList/Name``；
- 接口：``AttributeList/Interface/Sections/Section[@Name]``
  （Input/Output/InOut/Static/Temp/Constant/None/Return）；
- ``Member[@Name,@Datatype]``：
  - ``Struct`` → 直接嵌 ``<Member>`` 子成员；
  - UDT / 多实例 FB 引用 → ``Datatype='"UDT_Step"'`` + ``<Sections>`` 展开体；
  - ``IEC_TIMER`` / ``IEC_COUNTER`` → ``<Sections><Section Name="None">``
    展开 PT/ET/IN/Q（多实例定时器的成员证据）；
  - 数组 → 维度全部编码在类型串（``Array[0..15] of Bool``、
    ``Array[0..2, 0..31] of Int``、``Array[0..300] of "UDT_TypePara"``）。

未覆盖项（解析时静默降级，不影响其余成员）：
- 字符串下标界（``Array['a'..'z']``）——下标回退 0；
- ``AttributeList/BooleanAttribute`` 等成员属性（SetPoint 等，与类型对账无关）；
- know-how 保护块的体（只有接口，本来也只有接口可解析）。
"""

from __future__ import annotations

import glob
import html
import os
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from plc_engine.xml_guard import assert_no_dtd

#: SimaticML Interface 子树命名空间（V19 导出为 v5）
INTERFACE_NS: str = "http://www.siemens.com/automation/Openness/SW/Interface/v5"

#: Document 直下的块载体元素名（其余元素一律跳过）
_BLOCK_ELEMENT_NAMES: tuple[str, ...] = (
    "SW.Blocks.FB",
    "SW.Blocks.FC",
    "SW.Blocks.OB",
    "SW.Blocks.GlobalDB",
    "SW.Blocks.InstanceDB",
    "SW.Types.PADT",
)

#: ``Datatype="Array[0..15] of Bool"`` 的维度段提取
_ARRAY_TYPE_RE = re.compile(r"^Array\s*\[([^]]*)\]", re.IGNORECASE)

#: 单个维度界 ``0..15``（非整数界不匹配 → 下标回退 0）
_DIM_RANGE_RE = re.compile(r"^(-?\d+)\s*\.\.\s*(-?\d+)$")


@dataclass
class InterfaceMember:
    """接口成员节点：类型串 + 嵌套成员树。

    ``data_type`` 保留 XML 原始类型串（实体已反转义）：
    ``"Bool"``、``"Array[0..15] of Bool"``、``'"UDT_Step"'``（带引号的
    UDT / 多实例 FB 引用）、``"IEC_TIMER"`` 等；``members`` 承载
    Struct 直接嵌套、UDT / FB 多实例 ``Sections`` 展开、IEC_TIMER 展开
    三种来源（按名合并，同名冲突以先出现者为准）。
    ``section`` 为该成员所在声明区（顶层成员才有意义，如 ``Static``）。
    """

    name: str
    data_type: str = ""
    section: str = ""
    members: dict[str, InterfaceMember] = field(default_factory=dict)


def is_array_type(data_type: str) -> bool:
    """类型串是否为数组（``Array[…]`` 前缀，大小写不敏感）。"""
    return bool(_ARRAY_TYPE_RE.match((data_type or "").strip()))


def array_dims(data_type: str) -> int:
    """数组维数：``Array[0..15] of Bool`` → 1，``Array[0..2, 0..31]`` → 2。

    非数组返回 0；维度段解析失败（罕见字符下标界）按 1 维兜底。
    """
    m = _ARRAY_TYPE_RE.match((data_type or "").strip())
    if not m:
        return 0
    dims_part = m.group(1).strip()
    if not dims_part:
        return 0
    return dims_part.count(",") + 1


def array_lower_bounds(data_type: str) -> list[int]:
    """各维下界：``Array[0..15] of Bool`` → [0]，``Array[1..200] of Real`` → [1]。

    非整数界（如字符界）该维回退 0——调用方据此补出的下标一定能编译。
    """
    m = _ARRAY_TYPE_RE.match((data_type or "").strip())
    if not m:
        return []
    bounds: list[int] = []
    for part in m.group(1).split(","):
        rng = _DIM_RANGE_RE.match(part.strip())
        bounds.append(int(rng.group(1)) if rng else 0)
    return bounds


def default_subscript(data_type: str) -> str:
    """按数组各维下界生成默认下标文本：``[0]``、``[0,1]``。

    注意不是机械 ``[0]``：HR001 真机存在 ``Array[1..200] of Real``
    （DB1900.Para.Auto_Force）这类 1 起界数组，盲补 ``[0]`` 直接越界，
    补下界值才既确定又可编译。非数组返回空串。
    """
    if not is_array_type(data_type):
        return ""
    return "[" + ",".join(str(b) for b in array_lower_bounds(data_type)) + "]"


def _members_from_parent(elem: ET.Element, section: str) -> dict[str, InterfaceMember]:
    """收集一个成员节点下的全部嵌套成员（Struct 直嵌 + Sections 展开）。

    SimaticML 的三种嵌套形态在这里归一：
    1. ``<Member Datatype="Struct">`` 直接嵌 ``<Member>``；
    2. UDT / 多实例 FB 引用带 ``<Sections><Section Name="Input/…">``；
    3. ``IEC_TIMER`` 带 ``<Sections><Section Name="None">``（PT/ET/IN/Q）。
    """
    out: dict[str, InterfaceMember] = {}
    ns = f"{{{INTERFACE_NS}}}"
    for child in elem.findall(f"{ns}Member"):
        node = _parse_member(child, section)
        out.setdefault(node.name, node)
    for sec in elem.findall(f"{ns}Sections/{ns}Section"):
        sec_name = sec.get("Name") or ""
        for child in sec.findall(f"{ns}Member"):
            node = _parse_member(child, sec_name)
            out.setdefault(node.name, node)
    return out


def _parse_member(elem: ET.Element, section: str) -> InterfaceMember:
    """递归解析一个 ``<Member>`` 节点（类型串原样保留，实体已反转义）。"""
    node = InterfaceMember(
        name=elem.get("Name") or "",
        data_type=elem.get("Datatype") or "",
        section=section,
    )
    node.members = _members_from_parent(elem, section)
    return node


def parse_block_xml_text(xml_text: str) -> tuple[str, dict[str, InterfaceMember]] | None:
    """纯文本入口：一段 SimaticML 块 XML → (块名, 顶层成员树)。

    不落盘、无 IO——单测直接喂手写最小片段。识别不了（非块 XML /
    缺块名 / XML 非法）返回 None，绝不抛出。
    """
    try:
        assert_no_dtd(xml_text)  # 导出 XML 属半信任输入，先拒 DTD/实体声明
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError):
        return None
    for tag in _BLOCK_ELEMENT_NAMES:
        blk = root.find(tag)
        if blk is None:
            continue
        name_elem = blk.find("AttributeList/Name")
        name = (name_elem.text or "").strip() if name_elem is not None else ""
        if not name:
            return None
        ns = f"{{{INTERFACE_NS}}}"
        iface = blk.find("AttributeList/Interface")
        tops: dict[str, InterfaceMember] = {}
        if iface is not None:
            sections = iface.find(f"{ns}Sections")
            if sections is None:
                # 无命名空间的降级：个别手工导出丢 xmlns，按本地名再找一遍
                sections = iface.find("Sections")
            for sec in list(sections) if sections is not None else []:
                sec_name = sec.get("Name") or ""
                members = sec.findall(f"{ns}Member") or sec.findall("Member")
                for child in members:
                    node = _parse_member(child, sec_name)
                    tops.setdefault(node.name, node)
        return name, tops
    return None


def _candidate_xml_files(export_dir: str) -> list[str]:
    """枚举导出目录下的块 XML，兼容三种传参形态：

    - ``…/export/plc``（内含 ``<CPU>/blocks/*.xml``，任务书给定的顶层形态）；
    - ``…/export/plc/<CPU>``（内含 ``blocks/*.xml``）；
    - ``…/export/plc/<CPU>/blocks``（直接就是 *.xml）。
    """
    pats = [
        os.path.join(export_dir, "*.xml"),
        os.path.join(export_dir, "blocks", "*.xml"),
        os.path.join(export_dir, "*", "blocks", "*.xml"),
        # Openness 导出根形态:export/plc/<CPU>/blocks/*.xml(四层——
        # 真机 hr001 目录即此形态,调用方直接传 export 根也能命中)
        os.path.join(export_dir, "plc", "*", "blocks", "*.xml"),
    ]
    seen: dict[str, None] = {}  # 有序去重（同一文件可能被多个形态重复命中）
    for pat in pats:
        for fp in sorted(glob.glob(pat)):
            seen.setdefault(os.path.abspath(fp), None)
    return list(seen)


def load_block_interfaces(
    export_dir: str, *, cache: dict[str, dict[str, InterfaceMember]] | None = None
) -> dict[str, dict[str, InterfaceMember]]:
    """解析导出目录 → ``{块名: {顶层成员名: InterfaceMember}}``。

    - 单文件解析失败 / 非块 XML → 跳过该文件（证据宁缺毋错）；
    - 目录不存在 / 无可解析块 → 空 dict（调用方自然降级回无证据行为）；
    - ``cache`` 由调用方持有：键为 ``abspath(export_dir)``，命中直接返回，
      未命中解析后回填——本模块不自建全局缓存，失效策略归调用方。
    - 同名块（多 CPU 目录）以文件名排序后出现者为准，先到先得。
    """
    key = os.path.abspath(export_dir)
    if cache is not None and key in cache:
        return cache[key]
    interfaces: dict[str, dict[str, InterfaceMember]] = {}
    for fp in _candidate_xml_files(export_dir):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                parsed = parse_block_xml_text(fh.read())
        except OSError:
            continue
        if parsed is None:
            continue
        name, tops = parsed
        interfaces.setdefault(name, tops)
    if cache is not None:
        cache[key] = interfaces
    return interfaces


def _find_child(node: InterfaceMember, seg: str) -> InterfaceMember | None:
    """在成员树里找一个孩子：精确命中优先，其次大小写不敏感兜底
    （SCL 标识符大小写不敏感，XML 与画布两侧大小写漂移不该丢证据）。"""
    hit = node.members.get(seg)
    if hit is not None:
        return hit
    low = seg.lower()
    for k, v in node.members.items():
        if k.lower() == low:
            return v
    return None


def find_member(
    block_iface: dict[str, InterfaceMember] | None, member_path: str
) -> InterfaceMember | None:
    """解析点分路径 → 成员节点本体（含嵌套成员树，供调用方展开 Struct 类型）。

    路径清洗规则与 :func:`resolve_member` 一致；未命中返回 None。
    """
    if not block_iface or not member_path:
        return None
    path = member_path.strip().removeprefix("#")
    if path.startswith('"'):
        close = path.find('"', 1)
        if close != -1:
            path = path[close + 1 :]
    path = path.strip().lstrip(".").strip()
    if not path:
        return None
    segs = [s.strip() for s in path.split(".") if s.strip()]
    if not segs:
        return None
    # 根段也容忍与树根重复的块名前缀（"DB1900.DB1900.Para" 这类双重前缀）
    node = _find_child_root(block_iface, segs[0])
    if node is None and len(segs) > 1:
        node = _find_child_root(block_iface, segs[1])
        if node is not None:
            segs = segs[1:]
    if node is None:
        return None
    for seg in segs[1:]:
        nxt = _find_child(node, seg)
        if nxt is None:
            return None
        node = nxt
    return node


def resolve_member(
    block_iface: dict[str, InterfaceMember] | None, member_path: str
) -> dict[str, object]:
    """在块成员树里解析点分路径 → 类型证据。

    - ``block_iface``：``load_block_interfaces`` 结果里的单块成员树；
      为 None / 空 → ``found=False``（无证据，不是错误）。
    - ``member_path``：``"Aux.Heart"``、``"Para.Auto_Force"``；
      也容忍 ``DB 名+路径``（``'"DB1900_Communication_PC".Para.X'``，
      引号块名前缀被剥离——块选择由调用方完成）与 ``#`` 前缀。
    - 返回：``{"found", "data_type", "is_array", "dims", "bounds",
      "subscript", "section"}``——``dims`` 为维数，``bounds`` 为各维
      ``(下界, 上界)``，``subscript`` 为可直接拼进 SCL 的默认下标
      （如 ``"[0]"`` / ``"[1]"``，见 :func:`default_subscript`）。

    路径中途穿过数组（如 ``Arr[0].x`` 里查 ``Arr.x``）视为未命中——
    无下标穿数组本就是 R2 要修的对象，不是解析器要兜的语义。
    """
    result: dict[str, object] = {
        "found": False,
        "data_type": "",
        "is_array": False,
        "dims": 0,
        "bounds": [],
        "subscript": "",
        "section": "",
    }
    node = find_member(block_iface, member_path)
    if node is None:
        return result
    result.update(
        found=True,
        data_type=node.data_type,
        is_array=is_array_type(node.data_type),
        dims=array_dims(node.data_type),
        bounds=_bounds_pairs(node.data_type),
        subscript=default_subscript(node.data_type),
        section=node.section,
    )
    return result


def _find_child_root(tree: dict[str, InterfaceMember], seg: str) -> InterfaceMember | None:
    """根段查找（顶层 dict 无大小写兜底的 dict.get 之外的包装）。"""
    hit = tree.get(seg)
    if hit is not None:
        return hit
    low = seg.lower()
    for k, v in tree.items():
        if k.lower() == low:
            return v
    return None


def _bounds_pairs(data_type: str) -> list[tuple[int, int]]:
    """各维 ``(下界, 上界)`` 对；非整数界回退 ``(0, 0)``。"""
    m = _ARRAY_TYPE_RE.match((data_type or "").strip())
    if not m:
        return []
    pairs: list[tuple[int, int]] = []
    for part in m.group(1).split(","):
        rng = _DIM_RANGE_RE.match(part.strip())
        pairs.append((int(rng.group(1)), int(rng.group(2))) if rng else (0, 0))
    return pairs


# ---------------------------------------------------------------------------
# 原生 SCL 正文还原（StructuredText v4 → SCL 文本）
# ---------------------------------------------------------------------------

_ST_TOKEN_RE = re.compile(
    r'<Token Text="([^"]*)"[^>]*/>'
    r'|<Blank Num="(\d+)"[^>]*/>'
    r'|<NewLine Num="(\d+)"[^>]*/>'
    r'|<LineComment[^>]*>\s*<Text[^>]*>([^<]*)</Text>'
    r'|<Access ([^>]*)>(.*?)</Access>',
    re.S,
)


def _render_access(scope: str, inner: str) -> str:
    """Access 元素 → SCL 操作数文本。

    - LiteralConstant: ConstantValue 原文;
    - Local*: ``#a.b``; Global*: ``"a".b``（首组件带引号，成员路径点接）;
    - 组件名含空格 → 该组件加引号。所有文本均做 XML 实体反转义。
    """
    scope = (scope or "").strip()
    m = re.search(r"<ConstantValue[^>]*>([^<]*)</ConstantValue>", inner)
    if m:
        return html.unescape(m.group(1))
    names = [mm.group(1) for mm in re.finditer(r'<Component Name="([^"]*)"', inner)]
    if not names:
        return ""
    parts: list[str] = []
    for i, nm in enumerate(names):
        nm = html.unescape(nm)
        need_quote = " " in nm
        if (scope.startswith("Global") and i == 0) or need_quote:
            parts.append(f'"{nm}"')
        else:
            parts.append(nm)
    prefix = "" if scope.startswith("Global") else "#"
    return prefix + ".".join(parts)


def _render_st_node(node: ET.Element) -> str:
    """递归渲染 StructuredText 子树 → SCL 文本。

    覆盖 Token/Blank/NewLine/LineComment/Access/Instruction/Parameter 七要素;
    Instruction(调用名)与 Parameter(形参名)的名字都在属性里,正文不含——
    必须显式补出(真机 FB1010:ENCO/READ_DBL 系调用名曾因此整段丢失)。
    """
    tag = node.tag.rsplit("}", 1)[-1]
    if tag == "Token":
        return node.get("Text", "")
    if tag == "Blank":
        return " " * int(node.get("Num", "1"))
    if tag == "NewLine":
        return "\n" * int(node.get("Num", "1"))
    if tag == "LineComment":
        inner = node.find("{*}Text")
        return "// " + ((inner.text or "") if inner is not None else "")
    if tag == "Access":
        # Access 可能是普通操作数(子节点 Symbol/Constant),也可能是表达式
        # 容器(内含 Instruction)——后者按子序列渲染
        if any(c.tag.rsplit("}", 1)[-1] == "Instruction" for c in node):
            return _render_st_children(node)
        return _render_access(node.get("Scope", ""), ET.tostring(node, encoding="unicode"))
    if tag == "Instruction":
        return (node.get("Name", "")) + _render_st_children(node)
    if tag == "Parameter":
        return (node.get("Name", "")) + _render_st_children(node)
    return _render_st_children(node)


def _render_st_children(node: ET.Element) -> str:
    return "".join(_render_st_node(c) for c in node)


#: 单个块 XML 的解析大小上限(防御不可信输入的资源耗尽)
_ST_XML_MAX_BYTES = 20 * 1024 * 1024


def reconstruct_structured_text(xml_text: str) -> dict[str, str]:
    """从块 XML 提取原生 SCL 正文：``{块名: SCL 正文文本}``。

    仅原生 SCL 语言块含 ``<StructuredText>``（LAD/FBD 块没有）；递归渲染
    Token/Blank/NewLine/LineComment/Access/Instruction/Parameter 七要素
    （Instruction/Parameter 名在属性、可任意嵌套，正则方案会丢调用名）。
    安全门：defusedxml 解析（拒绝 DTD 实体扩展）+ 输入大小上限 +
    拒绝 DOCTYPE/ENTITY 声明；失败返回空 dict（调用方自然降级）。
    """
    if "<StructuredText" not in xml_text or "<Token" not in xml_text:
        return {}
    if len(xml_text) > _ST_XML_MAX_BYTES:
        return {}
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        return {}
    name_m = re.search(r"<Name>([^<]+)</Name>", xml_text)
    if not name_m:
        return {}
    from defusedxml.ElementTree import fromstring as safe_fromstring

    try:
        root = safe_fromstring(xml_text)
    except Exception:  # noqa: BLE001 — 坏 XML 只降级(该块无原生正文可用)
        return {}
    body_parts: list[str] = []
    for st in root.iter():
        if st.tag.rsplit("}", 1)[-1] != "StructuredText":
            continue
        body_parts.append(_render_st_children(st))
    body_parts = [p for p in body_parts if p.strip()]
    if not body_parts:
        return {}
    return {name_m.group(1): "\n".join(body_parts)}


def load_native_scl_bodies(
    export_dir: str, *, cache: dict[str, dict[str, str]] | None = None
) -> dict[str, str]:
    """导出目录 → ``{块名: 原生 SCL 正文}``（仅原生 SCL 语言块，LAD 块不含）。"""
    key = os.path.abspath(export_dir)
    if cache is not None and key in cache:
        return cache[key]
    bodies: dict[str, str] = {}
    for fp in _candidate_xml_files(export_dir):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                bodies.update(reconstruct_structured_text(fh.read()))
        except OSError:
            continue
    if cache is not None:
        cache[key] = bodies
    return bodies


def load_tag_types(export_dir: str) -> dict[str, str]:
    """导出目录 tags/*.xml → ``{tag 名: DataTypeName}``（权威类型表）。

    画布导入推导的 tag 类型存在误差(真机 U1Em1:ITempErr 画布记 Int、
    工程实为 Bool)——PLC_IO.xml 是工程导出的唯一权威。
    """
    types: dict[str, str] = {}
    tags_dir = Path(export_dir)
    for cand in (tags_dir / "plc", tags_dir):
        for sub in (cand, *cand.glob("*/tags")):
            if sub.is_dir():
                for fp in sorted(sub.glob("*.xml")):
                    try:
                        text = fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    for m in re.finditer(
                        r"<DataTypeName>([^<]+)</DataTypeName>.*?"
                        r"<LogicalAddress>[^<]+</LogicalAddress>\s*<Name>([^<]+)</Name>",
                        text, re.S,
                    ):
                        types[m.group(2)] = m.group(1)
                if types:
                    return types
    return types
