"""SimaticML XML parser — Openness block/tag-table exports -> PLC-IR.

Every TIA block (LAD, FBD, SCL, STL, GRAPH) exports to SimaticML via
Openness `PlcBlock.Export(...)`. This module parses those exports into
the PLC-IR model without needing TIA Portal installed.

Supported document types:
- Simatic.ML          (FB / FC / OB blocks)
- Simatic.TagTable.ML (PLC tag tables)
- Simatic.TypeTable.ML / UDT exports (best-effort as DB/UDT interface)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from agents.plc.tia.ir import (
    Access,
    AccessScope,
    AlarmObject,
    Block,
    BlockType,
    CfcChart,
    FoldedNetwork,
    GraphStep,
    GraphTransition,
    HardwareDevice,
    HmiDevice,
    InterfaceSection,
    Network,
    Part,
    PlcProject,
    SafetyUnitInfo,
    Tag,
    TagTable,
    TechnologyObject,
    Variable,
    WatchTable,
    Wire,
    WireEndpoint,
)
from agents.plc.tia.parallel import map_parallel

_SECTION_MAP = {
    "Input": InterfaceSection.INPUT,
    "Output": InterfaceSection.OUTPUT,
    "InOut": InterfaceSection.IN_OUT,
    "Static": InterfaceSection.STATIC,
    "Temp": InterfaceSection.TEMP,
    "Constant": InterfaceSection.CONSTANT,
    "Return": InterfaceSection.RETURN,
}

_BLOCK_TYPE_BY_SUFFIX = {"FB": BlockType.FB, "FC": BlockType.FC, "OB": BlockType.OB, "DB": BlockType.DB}

# Real Openness V17–V20 exports use typed roots (SW.Blocks.OB / FB / …).
# Older ResearchOS fixtures use SW.Blocks.ObjectSW + <DocumentType>.
_BLOCK_ROOT_TAGS = {
    "SW.Blocks.OB": BlockType.OB,
    "SW.Blocks.FB": BlockType.FB,
    "SW.Blocks.FC": BlockType.FC,
    "SW.Blocks.GlobalDB": BlockType.DB,
    "SW.Blocks.InstanceDB": BlockType.DB,
    "SW.Blocks.ArrayDB": BlockType.DB,
    "SW.Blocks.ObjectSW": None,  # type comes from DocumentType
    "SW.Types.PlcStruct": BlockType.UDT,
}


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(el: ET.Element) -> list[ET.Element]:
    return list(el)


def _attr(el: ET.Element, name: str) -> str:
    return el.get(name) or ""


def _detect_document_type(root: ET.Element) -> str:
    for el in root.iter():
        if _strip_ns(el.tag) == "DocumentType":
            return (el.text or "").strip()
    return ""


def _find_block_root(root: ET.Element) -> tuple[ET.Element | None, BlockType | None]:
    """Locate the primary SW.Blocks.* / PlcStruct element and inferred type."""
    for node in root:
        tag = _strip_ns(node.tag)
        if tag in _BLOCK_ROOT_TAGS:
            return node, _BLOCK_ROOT_TAGS[tag]
        # Some exports nest under Document only; also accept deep match for fixtures
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag in _BLOCK_ROOT_TAGS:
            return node, _BLOCK_ROOT_TAGS[tag]
    return None, None


def _block_type_from_doc(doc_type: str, inferred: BlockType | None, is_udt: bool) -> BlockType:
    if inferred is not None:
        return inferred
    if is_udt or doc_type.endswith("TypeTable.ML"):
        return BlockType.UDT
    suffix = doc_type.split(".")[-1].upper() if doc_type else ""
    if suffix in _BLOCK_TYPE_BY_SUFFIX:
        return _BLOCK_TYPE_BY_SUFFIX[suffix]
    return BlockType.DB


# ---------------------------------------------------------------------------
# Access parsing
# ---------------------------------------------------------------------------

def parse_access(access_el: ET.Element) -> Access:
    scope_attr = _attr(access_el, "Scope")
    if scope_attr == "LocalVariable":
        scope = AccessScope.LOCAL
    elif scope_attr in {"GlobalVariable", "TypedValue"}:
        scope = AccessScope.GLOBAL
    elif scope_attr in {"Constant", "LiteralConstant"}:
        scope = AccessScope.LITERAL
    else:
        scope = AccessScope.UNKNOWN

    symbols: list[str] = []
    # Classic fixture shape: <Symbol><Component Name=…/></Symbol>
    for node in access_el.iter():
        if _strip_ns(node.tag) == "Symbol":
            for comp in node:
                if _strip_ns(comp.tag) == "Component":
                    symbols.append(_attr(comp, "Name"))
    # Openness V19 Call Instance / some Access nodes: direct <Component Name=…/>
    if not symbols:
        for node in access_el:
            if _strip_ns(node.tag) == "Component":
                name = _attr(node, "Name")
                if name:
                    symbols.append(name)

    absolute = _parse_absolute_address(access_el)
    data_type = ""
    raw = ".".join(symbols) or absolute
    root = ""
    path: tuple[str, ...] = ()

    # LiteralConstant: <Constant><ConstantType/><ConstantValue/></Constant>
    if scope == AccessScope.LITERAL:
        const_val = ""
        const_type = ""
        for node in access_el.iter():
            tag = _strip_ns(node.tag)
            if tag == "ConstantValue":
                const_val = (node.text or "").strip()
            elif tag == "ConstantType":
                const_type = (node.text or "").strip()
        if const_val:
            raw = const_val
            data_type = const_type
    elif symbols:
        root = symbols[0]
        if scope == AccessScope.LOCAL and root.startswith("#"):
            root = root[1:]
        path = tuple(symbols[1:]) if len(symbols) > 1 else ()
    elif absolute:
        # Absolute-only access (e.g. %M0.5)
        scope = AccessScope.GLOBAL if scope == AccessScope.UNKNOWN else scope
        raw = absolute

    if not data_type:
        for node in access_el.iter():
            if _strip_ns(node.tag) == "PredefinedAttribute":
                if _attr(node, "Name") == "DataType":
                    data_type = _attr(node, "Value")
    return Access(
        scope=scope,
        root=root,
        path=path,
        data_type=data_type,
        raw=raw or _attr(access_el, "Name"),
        absolute=absolute,
    )


_ABS_AREA = {
    "Memory": "M",
    "Input": "I",
    "Output": "Q",
    "PeripheralInput": "PI",
    "PeripheralOutput": "PQ",
    "Counter": "C",
    "Timer": "T",
    "DB": "DB",
}


def _parse_absolute_address(access_el: ET.Element) -> str:
    """Render Siemens AbsoluteAddress / AbsoluteAdress as %M0.5 style."""
    for node in access_el.iter():
        tag = _strip_ns(node.tag)
        if tag not in {"AbsoluteAddress", "AbsoluteAdress"}:
            continue
        area = _ABS_AREA.get(_attr(node, "Area") or "", _attr(node, "Area") or "")
        if not area:
            continue
        typ = (_attr(node, "Type") or "Bit").strip()
        try:
            byte_off = int(_attr(node, "ByteOffset") or "0")
        except ValueError:
            byte_off = 0
        try:
            bit_off = int(_attr(node, "BitOffset") or "0")
        except ValueError:
            bit_off = 0
        if typ.lower() in {"bit", "bool"}:
            return f"%{area}{byte_off}.{bit_off}"
        if typ.lower() in {"byte"}:
            return f"%{area}B{byte_off}"
        if typ.lower() in {"word"}:
            return f"%{area}W{byte_off}"
        if typ.lower() in {"dword"}:
            return f"%{area}D{byte_off}"
        if typ.lower() in {"lword"}:
            return f"%{area}L{byte_off}"
        return f"%{area}{byte_off}.{bit_off}"
    return ""


# ---------------------------------------------------------------------------
# Interface parsing
# ---------------------------------------------------------------------------

def _parse_member(member_el: ET.Element, section: InterfaceSection) -> Variable:
    name = _attr(member_el, "Name")
    data_type = _attr(member_el, "Datatype")
    start_value = ""
    comment = ""
    is_retain = False
    for node in member_el.iter():
        tag = _strip_ns(node.tag)
        if tag == "StartValue":
            start_value = (node.text or "").strip()
        elif tag == "Comment":
            for text_el in node.iter():
                if _strip_ns(text_el.tag) == "Text":
                    comment = (text_el.text or "").strip()
                    break
        elif tag == "Attribute":
            if _attr(node, "Name") == "SetpointAddress" and _attr(node, "Value") == "true":
                is_retain = True
    return Variable(
        name=name,
        section=section,
        data_type=data_type,
        start_value=start_value,
        comment=comment,
        is_retain=is_retain,
    )


def parse_interface(interface_el: ET.Element) -> list[Variable]:
    variables: list[Variable] = []
    for node in interface_el.iter():
        if _strip_ns(node.tag) != "Section":
            continue
        section = _SECTION_MAP.get(_attr(node, "Name"), InterfaceSection.STATIC)
        for member in node:
            if _strip_ns(member.tag) == "Member":
                variables.append(_parse_member(member, section))
    return variables


# ---------------------------------------------------------------------------
# Network / body parsing (LAD, FBD, SCL/STL passthrough)
# ---------------------------------------------------------------------------

def _parse_part(part_el: ET.Element) -> Part:
    part = Part(
        name=_attr(part_el, "Name"),
        part_type=_attr(part_el, "Name"),
        uuid=_attr(part_el, "UId"),
        version=_attr(part_el, "Version"),
    )
    for node in part_el:
        tag = _strip_ns(node.tag)
        if tag == "TemplateValue":
            part.template_values[_attr(node, "Name")] = (node.text or "").strip()
        elif tag == "Equation":
            # CALCULATE box: <Equation>IN1 + IN2 * IN3</Equation>
            part.template_values["Equation"] = (node.text or "").strip()
        elif tag == "Attribute" and _attr(node, "Name") == "Negated":
            part.negated = (node.text or "").strip().lower() == "true"
        elif tag == "Access":
            # Nested access (some call parts embed their instance access)
            access_name = _attr(node, "Name") or f"acc{len(part.accesses)}"
            part.accesses[access_name] = parse_access(node)
        elif tag == "Instance":
            # IEC timer/counter: <Instance Scope=…><Component Name=DB/></Instance>
            comps = [
                _attr(c, "Name")
                for c in node.iter()
                if _strip_ns(c.tag) == "Component" and _attr(c, "Name")
            ]
            if not comps:
                continue
            scope_attr = _attr(node, "Scope") or "GlobalVariable"
            scope = (
                AccessScope.LOCAL
                if scope_attr == "LocalVariable"
                else AccessScope.GLOBAL
            )
            part.accesses["instance"] = Access(
                scope=scope,
                root=comps[0],
                path=tuple(comps[1:]),
                raw=".".join(comps),
            )
            part.template_values["InstanceDB"] = comps[0]
    return part


def _parse_call_el(call_el: ET.Element) -> Part:
    """Openness V17–V20: ``<Call><CallInfo Name=… BlockType=…><Instance/><Parameter/></CallInfo></Call>``."""
    part = Part(
        name="Call",
        part_type="Call",
        uuid=_attr(call_el, "UId") or f"call_{id(call_el)}",
    )
    for node in call_el.iter():
        tag = _strip_ns(node.tag)
        if tag == "CallInfo":
            called = (_attr(node, "Name") or "").strip()
            btype = (_attr(node, "BlockType") or "").strip()
            if called:
                part.template_values["Call"] = called
                part.template_values["calledBlock"] = called
            if btype:
                part.template_values["BlockType"] = btype
        elif tag == "Instance":
            comps = [
                _attr(c, "Name")
                for c in node
                if _strip_ns(c.tag) == "Component" and _attr(c, "Name")
            ]
            if not comps:
                comps = [
                    _attr(c, "Name")
                    for c in node.iter()
                    if _strip_ns(c.tag) == "Component" and _attr(c, "Name")
                ]
            if comps:
                scope_attr = _attr(node, "Scope") or "GlobalVariable"
                if scope_attr == "LocalVariable":
                    scope = AccessScope.LOCAL
                elif scope_attr in {"GlobalVariable", "TypedValue"}:
                    scope = AccessScope.GLOBAL
                else:
                    scope = AccessScope.UNKNOWN
                part.accesses["instance"] = Access(
                    scope=scope,
                    root=comps[0],
                    path=tuple(comps[1:]),
                    raw=".".join(comps),
                )
                part.template_values["InstanceDB"] = comps[0]
        elif tag == "Parameter":
            pname = (_attr(node, "Name") or "").strip()
            if not pname:
                continue
            section = (_attr(node, "Section") or "").strip()
            ptype = (_attr(node, "Type") or "").strip()
            if section:
                part.template_values[f"__sec__{pname}"] = section
            if ptype:
                part.template_values[f"__type__{pname}"] = ptype
            # Embedded Access under Parameter (common in some Openness builds)
            for child in node:
                if _strip_ns(child.tag) == "Access":
                    part.accesses[pname] = parse_access(child)
                    break
                # Some exports nest Access deeper
                for sub in child.iter():
                    if _strip_ns(sub.tag) == "Access" and _attr(sub, "Scope") != "Call":
                        part.accesses[pname] = parse_access(sub)
                        break
    return part


def _parse_wire(wire_el: ET.Element) -> Wire:
    endpoints: list[WireEndpoint] = []
    for node in wire_el:
        tag = _strip_ns(node.tag)
        if tag == "Powerrail":
            endpoints.append(WireEndpoint(kind="powerrail"))
        elif tag == "NameCon":
            endpoints.append(WireEndpoint(kind="namecon", uuid=_attr(node, "UId"), pin=_attr(node, "Name")))
        elif tag == "IdentCon":
            endpoints.append(WireEndpoint(kind="identcon", uuid=_attr(node, "UId")))
        elif tag == "OpenCon":
            endpoints.append(WireEndpoint(kind="opencon", uuid=_attr(node, "UId"), pin=_attr(node, "Name")))
    return Wire(uid=_attr(wire_el, "UId"), endpoints=endpoints)


def _ml_text(parent: ET.Element) -> str:
    """First <Text> content inside a MultilingualText(Item) subtree."""
    for text_el in parent.iter():
        if _strip_ns(text_el.tag) == "Text":
            return (text_el.text or "").strip()
    return ""


def _structured_text_to_scl(st_el: ET.Element) -> str:
    """Reconstruct SCL source from Openness StructuredText token tree.

    NetworkSource may contain ``<StructuredText>`` (SCL networks) instead of
    ``<FlgNet>`` (LAD/FBD). Tokens carry Text/Blank/NewLine; Access nodes are
    operands; Instruction/Parameter form calls.
    """
    chunks: list[str] = []

    def walk(el: ET.Element) -> None:
        tag = _strip_ns(el.tag)
        if tag == "Token":
            chunks.append(_attr(el, "Text"))
            return
        if tag == "Blank":
            try:
                n = max(0, int(_attr(el, "Num") or "1"))
            except ValueError:
                n = 1
            chunks.append(" " * n)
            return
        if tag == "NewLine":
            try:
                n = max(1, int(_attr(el, "Num") or "1"))
            except ValueError:
                n = 1
            chunks.append("\n" * n)
            return
        if tag == "Access":
            # Call-shaped Access embeds Instruction; render children.
            if _attr(el, "Scope") == "Call" or any(
                _strip_ns(child.tag) == "Instruction" for child in el
            ):
                for child in el:
                    walk(child)
                return
            chunks.append(parse_access(el).as_scl())
            return
        if tag == "Instruction":
            chunks.append(_attr(el, "Name"))
            for child in el:
                walk(child)
            return
        if tag == "Parameter":
            name = _attr(el, "Name")
            if name:
                chunks.append(name)
            for child in el:
                walk(child)
            return
        if tag == "ConstantValue":
            chunks.append((el.text or "").strip())
            return
        if tag in {"BooleanAttribute", "Component", "LineComment", "Text"}:
            # Attributes / comments on symbols are reflected via Access.as_scl
            return
        for child in el:
            walk(child)

    for child in st_el:
        walk(child)
    text = "".join(chunks)
    # Normalize trailing whitespace on each line; keep intentional blank lines.
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()


_STL_OUTPUT_PINS = {
    "Q",
    "QU",
    "QD",
    "OUT",
    "OUT1",
    "CV",
    "ET",
    "ENO",
    "RET_VAL",
}


def _instruction_instance_name(instr_el: ET.Element) -> str:
    for node in instr_el:
        if _strip_ns(node.tag) != "Instance":
            continue
        comps = [
            _attr(c, "Name")
            for c in node.iter()
            if _strip_ns(c.tag) == "Component" and _attr(c, "Name")
        ]
        if comps:
            return comps[0]
    return ""


def _stl_call_to_scl(stmt_el: ET.Element) -> str:
    """Rebuild one STL CALL statement as Siemens SCL instance call."""
    for node in stmt_el.iter():
        if _strip_ns(node.tag) != "Instruction":
            continue
        instr = (_attr(node, "Name") or "").strip()
        inst = _instruction_instance_name(node)
        params: list[str] = []
        for child in node:
            if _strip_ns(child.tag) != "Parameter":
                continue
            pname = (_attr(child, "Name") or "").strip()
            if not pname:
                continue
            access_el = None
            for sub in child.iter():
                if _strip_ns(sub.tag) != "Access":
                    continue
                # Skip nested Call wrappers; take operand Access
                if _attr(sub, "Scope") == "Call":
                    continue
                access_el = sub
                break
            if access_el is None:
                continue
            acc = parse_access(access_el)
            op = "=>" if pname.upper() in _STL_OUTPUT_PINS else ":="
            params.append(f"{pname} {op} {acc.as_scl()}")
        callee = f'"{inst}"' if inst else (instr or "(*call*)")
        body = ", ".join(params)
        return f"{callee}({body});" if body else f"{callee}();"
    return ""


def _part_from_stl_call(stmt_el: ET.Element, *, uid: str) -> Part | None:
    """Materialize STL CALL as a Part so KG can emit USES / CALLS."""
    for node in stmt_el.iter():
        if _strip_ns(node.tag) != "Instruction":
            continue
        instr = (_attr(node, "Name") or "").strip() or "Call"
        inst = _instruction_instance_name(node)
        part = Part(
            name=instr,
            part_type=instr,
            uuid=uid or _attr(stmt_el, "UId") or f"stl_{instr}",
        )
        part.template_values["Call"] = instr
        part.template_values["calledBlock"] = instr
        if inst:
            part.template_values["InstanceDB"] = inst
            part.accesses["instance"] = Access(
                scope=AccessScope.GLOBAL,
                root=inst,
                path=(),
                raw=inst,
            )
        for child in node:
            if _strip_ns(child.tag) != "Parameter":
                continue
            pname = (_attr(child, "Name") or "").strip()
            if not pname:
                continue
            for sub in child.iter():
                if _strip_ns(sub.tag) != "Access" or _attr(sub, "Scope") == "Call":
                    continue
                part.accesses[pname] = parse_access(sub)
                break
        return part
    return None


def _statement_list_to_scl(stl_el: ET.Element) -> str:
    """Reconstruct SCL from Openness StatementList (STL network export).

    Mixed LAD blocks sometimes store a network as ``StatementList`` with
    ``StlToken Text=CALL`` + Instruction (e.g. R_TRIG) instead of FlgNet.
    """
    lines: list[str] = []
    for stmt in stl_el:
        if _strip_ns(stmt.tag) != "StlStatement":
            continue
        token = ""
        for child in stmt:
            if _strip_ns(child.tag) == "StlToken":
                token = (_attr(child, "Text") or "").strip().upper()
                break
        if token in {"", "EMPTY_LINE", "COMMENT"}:
            continue
        if token == "CALL":
            line = _stl_call_to_scl(stmt)
            if line:
                lines.append(line)
            continue
        operand = _stl_operand_scl(stmt)
        if token in {"A", "AN", "O", "ON", "=", "S", "R", "CU", "TON"}:
            lines.append(_stl_boolean_line(token, operand))
            continue
        # Best-effort: ignore unsupported rare STL mnemonics
    return "\n".join(ln for ln in lines if ln).strip()


def _stl_operand_scl(stmt_el: ET.Element) -> str:
    for child in stmt_el.iter():
        if _strip_ns(child.tag) != "Access":
            continue
        if _attr(child, "Scope") == "Call":
            continue
        return parse_access(child).as_scl()
    return "(* operand *)"


def _stl_boolean_line(token: str, operand: str) -> str:
    """Common STL ops → folded SCL (A/AN/O/ON/= /S/R/CU/TON)."""
    if token == "A":
        return f"(* STL A *) {operand}"
    if token == "AN":
        return f"(* STL AN *) NOT ({operand})"
    if token == "O":
        return f"(* STL O *) {operand}"
    if token == "ON":
        return f"(* STL ON *) NOT ({operand})"
    if token == "=":
        return f"{operand} := (* RLO *);"
    if token == "S":
        return f"IF (* RLO *) THEN {operand} := TRUE; END_IF;"
    if token == "R":
        return f"IF (* RLO *) THEN {operand} := FALSE; END_IF;"
    if token == "CU":
        return f"{operand}(CU := TRUE);"
    if token == "TON":
        return f"{operand}(IN := TRUE);"
    return f"(* STL {token} {operand} *)"


def _fold_stl_rlo_to_scl(stl_el: ET.Element) -> str:
    """Walk A/AN/O/ON then =/S/R into a single assignment when possible."""
    rlo: list[tuple[str, str]] = []
    lines: list[str] = []

    def rlo_expr() -> str:
        expr = ""
        for tok, op in rlo:
            term = f"NOT ({op})" if tok in {"AN", "ON"} else op
            if not expr:
                expr = term
            elif tok in {"O", "ON"}:
                expr = f"{expr} OR {term}"
            else:
                expr = f"{expr} AND {term}"
        return expr or "TRUE"

    for stmt in stl_el:
        if _strip_ns(stmt.tag) != "StlStatement":
            continue
        token = ""
        for child in stmt:
            if _strip_ns(child.tag) == "StlToken":
                token = (_attr(child, "Text") or "").strip().upper()
                break
        if token in {"", "EMPTY_LINE", "COMMENT"}:
            continue
        if token == "CALL":
            line = _stl_call_to_scl(stmt)
            if line:
                lines.append(line)
            continue
        operand = _stl_operand_scl(stmt)
        if token in {"A", "AN", "O", "ON"}:
            rlo.append((token, operand))
            continue
        if token == "=":
            lines.append(f"{operand} := {rlo_expr()};")
            rlo = []
            continue
        if token == "S":
            lines.append(f"IF {rlo_expr()} THEN {operand} := TRUE; END_IF;")
            rlo = []
            continue
        if token == "R":
            lines.append(f"IF {rlo_expr()} THEN {operand} := FALSE; END_IF;")
            rlo = []
            continue
        if token == "CU":
            lines.append(f"{operand}(CU := {rlo_expr()});")
            rlo = []
            continue
        if token == "TON":
            lines.append(f"{operand}(IN := {rlo_expr()});")
            rlo = []
            continue
    return "\n".join(lines).strip()


def _ingest_statement_list(network: Network, stl_el: ET.Element) -> None:
    """Attach StatementList body as source_text + Call parts."""
    reconstructed = _fold_stl_rlo_to_scl(stl_el) or _statement_list_to_scl(stl_el)
    if reconstructed:
        network.source_text = reconstructed
        if not network.programming_language:
            network.programming_language = "STL"
    for stmt in stl_el:
        if _strip_ns(stmt.tag) != "StlStatement":
            continue
        token = ""
        for child in stmt:
            if _strip_ns(child.tag) == "StlToken":
                token = (_attr(child, "Text") or "").strip().upper()
                break
        if token != "CALL":
            continue
        uid = _attr(stmt, "UId") or f"stl_call_{len(network.parts)}"
        part = _part_from_stl_call(stmt, uid=uid)
        if part is not None:
            network.parts[part.uuid or uid] = part


def parse_network(compile_unit: ET.Element) -> Network:
    network = Network(id=_attr(compile_unit, "UId"))
    # Title/Comment are MultilingualText compositions, not element tags
    for node in compile_unit.iter():
        if _strip_ns(node.tag) != "MultilingualText":
            continue
        comp = _attr(node, "CompositionName")
        if comp == "Title":
            network.title = _ml_text(node)
        elif comp == "Comment":
            text = _ml_text(node)
            if text:
                network.comment = (network.comment + " " + text).strip()
    # programming language: first ProgrammingLanguage inside the unit body
    for node in compile_unit.iter():
        if _strip_ns(node.tag) == "ProgrammingLanguage":
            network.programming_language = (node.text or "").strip()
            break

    flgnet: ET.Element | None = None
    structured: ET.Element | None = None
    statement_list: ET.Element | None = None
    for node in compile_unit.iter():
        tag = _strip_ns(node.tag)
        if tag == "FlgNet" and flgnet is None:
            flgnet = node
        elif tag == "StructuredText" and structured is None:
            structured = node
        elif tag == "StatementList" and statement_list is None:
            statement_list = node

    if flgnet is not None:
        for node in flgnet:
            tag = _strip_ns(node.tag)
            if tag == "StructuredText":
                # Rare: ST embedded under FlgNet
                if structured is None:
                    structured = node
            elif tag == "Parts":
                for part_el in node:
                    part_tag = _strip_ns(part_el.tag)
                    if part_tag == "Call":
                        # Real Openness exports use <Call>…</Call>, not <Part Name="Call">
                        part = _parse_call_el(part_el)
                        network.parts[part.uuid or f"call{len(network.parts)}"] = part
                    elif part_tag == "Part":
                        part = _parse_part(part_el)
                        if part.name in {"LeftRail", "RightRail"}:
                            network.rails[part.name] = part
                        else:
                            network.parts[part.uuid or part.name] = part
                    elif part_tag == "Access":
                        uid = _attr(part_el, "UId")
                        network.access_parts[uid] = parse_access(part_el)
            elif tag == "Wires":
                for wire_el in node:
                    if _strip_ns(wire_el.tag) == "Wire":
                        network.wires.append(_parse_wire(wire_el))

    # SCL / ST networks: NetworkSource → StructuredText (token tree), not FlgNet
    if structured is not None:
        reconstructed = _structured_text_to_scl(structured)
        if reconstructed:
            network.source_text = reconstructed
            if not network.programming_language:
                network.programming_language = "SCL"
        elif (structured.text or "").strip():
            network.source_text = (structured.text or "").strip()

    # STL StatementList (CALL boxes / mixed-language networks)
    if statement_list is not None and not network.parts and not network.source_text:
        _ingest_statement_list(network, statement_list)
    elif statement_list is not None and not network.source_text:
        # FlgNet empty but STL present (or hybrid): still ingest STL body
        _ingest_statement_list(network, statement_list)

    _ingest_graph(network, compile_unit)
    return network


def _ingest_graph(network: Network, compile_unit: ET.Element) -> None:
    """Parse S7-GRAPH steps/transitions into IR (SCL is a commented sequence).

    Official SimaticML may nest ``Sequence/Steps/Transitions`` with Interlock,
    Supervision, and TransitionCondition. Steps/transitions become IR evidence;
    generated SCL stays advisory and is never treated as executable GRAPH.
    """
    steps: list[GraphStep] = []
    transitions: list[GraphTransition] = []
    sequence = None
    for node in compile_unit.iter():
        if _strip_ns(node.tag) == "Sequence":
            sequence = node
            break
    root = sequence if sequence is not None else compile_unit

    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag != "Step":
            continue
        name = _attr(node, "Name") or _child_text_local(node, "Name") or f"Step{len(steps) + 1}"
        number = 0
        try:
            number = int(_attr(node, "Number") or _child_text_local(node, "Number") or "0")
        except ValueError:
            number = 0
        actions: list[str] = []
        interlock = ""
        supervision = ""
        for act in node.iter():
            at = _strip_ns(act.tag)
            if at in {"Action", "Instruction", "Token"}:
                txt = _attr(act, "Text") or (act.text or "").strip()
                if txt:
                    actions.append(txt)
            elif at == "Interlock" and not interlock:
                interlock = (act.text or "").strip() or _attr(act, "Text") or _child_text_local(act, "Text", "Condition")
            elif at == "Supervision" and not supervision:
                supervision = (act.text or "").strip() or _attr(act, "Text") or _child_text_local(act, "Text", "Condition")
        steps.append(
            GraphStep(
                name=name,
                number=number,
                uuid=_attr(node, "UId") or _attr(node, "ID"),
                actions=actions,
                comment=_ml_text(node),
                interlock=interlock,
                supervision=supervision,
                evidence="graph_xml",
            )
        )
    for node in root.iter():
        if _strip_ns(node.tag) != "Transition":
            continue
        name = _attr(node, "Name") or _child_text_local(node, "Name") or f"T{len(transitions) + 1}"
        cond = (
            _attr(node, "Condition")
            or _child_text_local(node, "Condition")
            or _child_text_local(node, "Event")
            or _child_text_local(node, "TransitionCondition")
        )
        if not cond:
            for child in node.iter():
                if _strip_ns(child.tag) in {"TransitionCondition", "Condition", "Event"}:
                    cond = (child.text or "").strip() or _attr(child, "Text")
                    if cond:
                        break
        transitions.append(
            GraphTransition(
                name=name,
                number=len(transitions) + 1,
                uuid=_attr(node, "UId") or _attr(node, "ID"),
                source_step=_attr(node, "From") or _child_text_local(node, "From") or _child_text_local(node, "Source"),
                target_step=_attr(node, "To") or _child_text_local(node, "To") or _child_text_local(node, "Target"),
                condition=cond,
                comment=_ml_text(node),
                evidence="graph_xml",
            )
        )
    if not steps and not transitions:
        return
    network.graph_steps = steps
    network.graph_transitions = transitions
    if not network.programming_language:
        network.programming_language = "GRAPH"
    network.folded = FoldedNetwork(
        network_id=network.id,
        title=network.title,
        evidence="graph_sequence",
        unresolved_parts=[],
        statements=[],
    )
    if network.source_text:
        return
    lines = ["(* GRAPH sequence — advisory, not executable S7-GRAPH *)"]
    for step in steps:
        act = "; ".join(step.actions) if step.actions else ""
        extra = f" // {act}" if act else ""
        lock = f" interlock={step.interlock}" if step.interlock else ""
        superv = f" supervision={step.supervision}" if step.supervision else ""
        lines.append(f"(* Step {step.number or ''} {step.name}{extra}{lock}{superv} *)")
    for tr in transitions:
        lines.append(
            f"(* Transition {tr.name}: {tr.source_step} -[{tr.condition or '?'}]-> {tr.target_step} *)"
        )
    network.source_text = "\n".join(lines)


def _child_text_local(el: ET.Element, *names: str) -> str:
    want = {n.lower() for n in names}
    for child in el:
        if _strip_ns(child.tag).lower() in want and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def _extract_source_text(sw_object: ET.Element) -> str:
    """Best-effort extraction of textual bodies (SCL/STL stored in export)."""
    for node in sw_object.iter():
        if _strip_ns(node.tag) in {"SourceText", "Text"}:
            text = (node.text or "").strip()
            if text and len(text.splitlines()) > 1:
                return text
    return ""


# ---------------------------------------------------------------------------
# Block parsing
# ---------------------------------------------------------------------------

def parse_block_xml(path: Path) -> Block | None:
    tree = ET.parse(path)
    root = tree.getroot()
    doc_type = _detect_document_type(root)
    sw_obj, inferred_type = _find_block_root(root)
    if sw_obj is None:
        return None
    # Fixtures use DocumentType + ObjectSW; real Openness V19 uses typed roots.
    if inferred_type is None and doc_type and not doc_type.startswith("Simatic"):
        return None
    if inferred_type is None and not doc_type and _strip_ns(sw_obj.tag) == "SW.Blocks.ObjectSW":
        return None

    name = _attr(sw_obj, "Name") or path.stem
    attrs: dict[str, str] = {}
    for node in sw_obj.iter():
        tag = _strip_ns(node.tag)
        if tag == "AttributeList":
            for attr_el in node:
                child = _strip_ns(attr_el.tag)
                if child == "Attribute":
                    attrs[_attr(attr_el, "Name")] = (attr_el.text or "").strip()
                elif (attr_el.text or "").strip() or child:
                    attrs.setdefault(child, (attr_el.text or "").strip())
        elif tag in {
            "KnowHowProtection",
            "WriteProtection",
            "IsKnowHowProtected",
            "SetKnowHowProtection",
            "IsFailsafe",
            "Failsafe",
        }:
            attrs.setdefault(tag, (node.text or "").strip() or "true")
        elif tag == "BooleanAttribute":
            n = _attr(node, "Name")
            v = _attr(node, "Value") or (node.text or "").strip() or "true"
            if n:
                attrs[n] = v

    name = _attr(sw_obj, "Name") or attrs.get("Name") or path.stem

    number = 0
    try:
        number = int(attrs.get("Number") or "0")
    except ValueError:
        number = 0
    is_udt = any(_strip_ns(node.tag) == "SW.Types.PlcStruct" for node in root.iter())
    for node in sw_obj.iter():
        if _strip_ns(node.tag) == "Number":
            try:
                number = int((node.text or "0").strip())
            except ValueError:
                number = 0
    block_type = _block_type_from_doc(doc_type, inferred_type, is_udt)

    lang = attrs.get("ProgrammingLanguage") or ""
    if not lang:
        for node in sw_obj.iter():
            if _strip_ns(node.tag) == "ProgrammingLanguage":
                lang = (node.text or "").strip()
                break

    interface: list[Variable] = []
    for node in sw_obj.iter():
        if (
            _strip_ns(node.tag) == "SW.Blocks.InterfaceSection"
            or _strip_ns(node.tag) == "Interface"
            or _attr(node, "CompositionName") == "Interface"
        ):
            interface = parse_interface(node)
            if interface or _strip_ns(node.tag) in {"Interface", "SW.Blocks.InterfaceSection"}:
                break

    networks: list[Network] = []
    for node in sw_obj.iter():
        if _strip_ns(node.tag) == "SW.Blocks.CompileUnit":
            networks.append(parse_network(node))

    header_comment = ""
    for node in sw_obj.iter():
        if (
            _strip_ns(node.tag) == "MultilingualText"
            and _attr(node, "CompositionName") == "Comment"
        ):
            for text_el in node.iter():
                if _strip_ns(text_el.tag) == "Text":
                    header_comment = (text_el.text or "").strip()
                    break
            if header_comment:
                break

    block = Block(
        name=name,
        number=number,
        block_type=block_type,
        programming_language=lang,
        header_comment=header_comment,
        interface=interface,
        networks=networks,
        source_text=_extract_source_text(sw_obj),
        attributes=attrs,
        source_file=str(path),
    )
    from agents.plc.tia.safety import detect_block_safety

    block.is_safety = detect_block_safety(block)
    return block


def parse_tag_table_xml(path: Path) -> TagTable | None:
    tree = ET.parse(path)
    root = tree.getroot()
    doc_type = _detect_document_type(root)
    has_tag_table = any(_strip_ns(n.tag) == "SW.Tags.PlcTagTable" for n in root.iter())
    has_plc_tag = any(_strip_ns(n.tag) == "SW.Tags.PlcTag" for n in root.iter())
    has_constant = any(
        _strip_ns(n.tag) in {"SW.Tags.PlcConstant", "SW.Tags.Constant", "PlcConstant"}
        for n in root.iter()
    )
    if not (has_tag_table or has_plc_tag or has_constant or "TagTable" in doc_type or "Tag" in doc_type):
        return None

    table_name = path.stem
    for node in root.iter():
        if _strip_ns(node.tag) != "SW.Tags.PlcTagTable":
            continue
        for child in node:
            if _strip_ns(child.tag) != "AttributeList":
                continue
            for attr_el in child:
                if _strip_ns(attr_el.tag) == "Name" and (attr_el.text or "").strip():
                    table_name = (attr_el.text or "").strip()
                    break
        if not table_name or table_name == path.stem:
            n = _attr(node, "Name")
            if n:
                table_name = n
        break

    tags: list[Tag] = []
    for node in root.iter():
        if _strip_ns(node.tag) != "SW.Tags.PlcTag":
            continue
        name = _attr(node, "Name")
        data_type = ""
        address = ""
        comment = ""
        for sub in node.iter():
            sub_tag = _strip_ns(sub.tag)
            if sub_tag == "DataTypeName":
                data_type = (sub.text or "").strip()
            elif sub_tag == "LogicalAddress":
                address = (sub.text or "").strip()
            elif sub_tag == "MultilingualText" and _attr(sub, "CompositionName") == "Comment":
                comment = comment or _ml_text(sub)
            elif sub_tag == "Text" and not comment:
                comment = (sub.text or "").strip()
            elif sub_tag == "Name" and not name:
                name = (sub.text or "").strip()
        if name:
            tags.append(Tag(name=name, data_type=data_type, logical_address=address, comment=comment))
    for node in root.iter():
        if _strip_ns(node.tag) not in {"SW.Tags.PlcConstant", "SW.Tags.Constant", "PlcConstant"}:
            continue
        name = _attr(node, "Name") or ""
        data_type = ""
        value = ""
        for sub in node.iter():
            sub_tag = _strip_ns(sub.tag)
            if sub_tag in {"DataTypeName", "DataType"}:
                data_type = (sub.text or "").strip()
            elif sub_tag in {"Value", "StartValue", "ConstantValue"}:
                value = (sub.text or "").strip()
            elif sub_tag == "Name" and not name:
                name = (sub.text or "").strip()
        if name:
            tags.append(
                Tag(
                    name=name,
                    data_type=data_type or "CONSTANT",
                    logical_address=value,
                    comment="constant",
                )
            )
    if not tags and not has_tag_table:
        return None
    return TagTable(name=table_name, tags=tags)


# ---------------------------------------------------------------------------
# Project extraction
# ---------------------------------------------------------------------------

@dataclass
class XmlParseResult:
    """One export XML classified as block, tag table, hardware, surface, skip, or error."""

    kind: str
    rel: str
    block: Block | None = None
    table: TagTable | None = None
    hardware: list[HardwareDevice] | None = None
    payload: object | None = None
    note: str = ""


def parse_export_xml(xml_file: Path, export_path: Path) -> XmlParseResult:
    """Parse a single Openness XML into a block, tag table, hardware, or chapter-6 surface row."""
    try:
        rel = str(xml_file.relative_to(export_path))
    except ValueError:
        rel = str(xml_file)
    try:
        from agents.plc.tia.surface import try_parse_surface

        hit = try_parse_surface(xml_file, export_path, rel)
    except Exception as exc:  # noqa: BLE001 — surface is advisory
        hit = None
        surface_err = f"surface parse skipped in {rel}: {exc}"
    else:
        surface_err = ""
    if hit is not None:
        if hit.kind == "error":
            return XmlParseResult(kind="error", rel=rel, note=hit.note or surface_err)
        if hit.kind == "hardware":
            return XmlParseResult(kind="hardware", rel=rel, hardware=hit.hardware or [])
        if hit.kind != "skip":
            return XmlParseResult(kind=hit.kind, rel=rel, payload=hit.payload, note=hit.note)
    try:
        block = parse_block_xml(xml_file)
        if block is not None:
            return XmlParseResult(kind="block", rel=rel, block=block)
    except ET.ParseError as exc:
        return XmlParseResult(kind="error", rel=rel, note=f"parse error in {rel}: {exc}")
    except Exception as exc:  # noqa: BLE001 — keep pipeline advisory
        return XmlParseResult(kind="error", rel=rel, note=f"block parse failed in {rel}: {exc}")
    try:
        table = parse_tag_table_xml(xml_file)
        if table is not None:
            return XmlParseResult(kind="table", rel=rel, table=table)
    except ET.ParseError as exc:
        return XmlParseResult(kind="error", rel=rel, note=f"tag table parse error in {rel}: {exc}")
    except Exception as exc:  # noqa: BLE001
        return XmlParseResult(kind="error", rel=rel, note=f"tag table parse failed in {rel}: {exc}")
    try:
        from agents.plc.tia.hardware import looks_like_hardware_xml, parse_hardware_xml

        if looks_like_hardware_xml(xml_file):
            devices = parse_hardware_xml(xml_file)
            if devices:
                return XmlParseResult(kind="hardware", rel=rel, hardware=devices)
    except Exception as exc:  # noqa: BLE001 — hardware is advisory
        return XmlParseResult(kind="error", rel=rel, note=f"hardware parse skipped in {rel}: {exc}")
    if surface_err:
        return XmlParseResult(kind="error", rel=rel, note=surface_err)
    return XmlParseResult(kind="skip", rel=rel)


def _merge_hmi(project: PlcProject, device: HmiDevice) -> None:
    existing = next((d for d in project.hmi_devices if d.name == device.name), None)
    if existing is None:
        project.hmi_devices.append(device)
        return
    existing.tag_tables.update(device.tag_tables)
    existing.scripts.extend(device.scripts)
    existing.text_lists.extend(device.text_lists)
    existing.graphic_lists.extend(device.graphic_lists)
    existing.connections.extend(device.connections)
    existing.cycles.extend(getattr(device, "cycles", None) or [])
    existing.screens.extend(device.screens)


def merge_parse_results(project: PlcProject, results: list[XmlParseResult]) -> None:
    """Fold parse results into ``project`` on the calling thread (dict writes)."""
    skipped: list[str] = []
    for item in results:
        if item.kind == "block" and item.block is not None:
            project.add_block(item.block)
        elif item.kind == "table" and item.table is not None:
            project.tag_tables[item.table.name] = item.table
        elif item.kind == "hardware" and item.hardware:
            project.hardware.extend(item.hardware)
        elif item.kind == "watch" and isinstance(item.payload, WatchTable):
            project.watch_tables[item.payload.name] = item.payload
        elif item.kind == "force" and isinstance(item.payload, WatchTable):
            project.force_tables[item.payload.name] = item.payload
        elif item.kind == "to" and isinstance(item.payload, TechnologyObject):
            project.technology_objects.append(item.payload)
        elif item.kind == "alarms" and isinstance(item.payload, AlarmObject):
            project.alarms.append(item.payload)
        elif item.kind == "prodiag" and isinstance(item.payload, AlarmObject):
            project.prodiag.append(item.payload)
        elif item.kind == "cfc" and isinstance(item.payload, CfcChart):
            project.cfc_charts.append(item.payload)
        elif item.kind == "safety" and isinstance(item.payload, SafetyUnitInfo):
            project.safety_units.append(item.payload)
        elif item.kind == "hmi" and isinstance(item.payload, HmiDevice):
            _merge_hmi(project, item.payload)
        elif item.kind == "opcua" and isinstance(item.payload, list):
            project.opcua_nodes.extend(str(n) for n in item.payload if n)
        elif item.kind == "project" and isinstance(item.payload, dict):
            project.project_texts.update({str(k): str(v) for k, v in item.payload.items()})
        elif item.kind == "error" and item.note:
            project.extraction_notes.append(item.note)
            project.parse_gaps.append(
                {
                    "name": Path(item.rel).stem or item.rel,
                    "rel": item.rel,
                    "kind": "block",
                    "status": "failed",
                    "reason": "openness_error",
                    "detail": item.note,
                }
            )
        elif item.kind == "skip":
            skipped.append(item.rel)
            project.parse_gaps.append(
                {
                    "name": Path(item.rel).stem or item.rel,
                    "rel": item.rel,
                    "kind": "block",
                    "status": "skipped",
                    "reason": "unrecognized",
                    "detail": f"unrecognized XML skipped: {item.rel}",
                }
            )
    if skipped:
        preview = ", ".join(skipped[:8])
        more = f" (+{len(skipped) - 8} more)" if len(skipped) > 8 else ""
        project.extraction_notes.append(
            f"unrecognized XML skipped ({len(skipped)}): {preview}{more}"
        )


def _attach_export_manifest(project: PlcProject, export_path: Path) -> None:
    path = export_path / "manifest.json"
    if path.is_file():
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                project.export_manifest = data
        except Exception as exc:  # noqa: BLE001
            project.extraction_notes.append(f"manifest.json unreadable: {exc}")
    from agents.plc.tia.structure import attach_export_journal

    attach_export_journal(project, export_path)


def _has_parsed_surface(project: PlcProject) -> bool:
    return bool(
        project.blocks
        or project.tag_tables
        or project.hardware
        or project.watch_tables
        or project.force_tables
        or project.technology_objects
        or project.alarms
        or project.prodiag
        or project.cfc_charts
        or project.safety_units
        or project.hmi_devices
        or project.opcua_nodes
    )


def extract_project(export_dir: str | Path, *, project_name: str = "") -> PlcProject:
    """Scan an Openness export directory and build PLC-IR.

    Accepts legacy ``Blocks/`` plus official ``plc/<name>/blocks|types|tags|...``,
    ``hardware/``, ``hmi/<name>/``, and ``manifest.json``.
    Independent XML files are parsed on a thread pool; IR merge stays serial.
    """
    from agents.plc.tia.enrich import enrich_project_interfaces

    export_path = Path(export_dir)
    project = PlcProject(name=project_name or export_path.name, source_path=str(export_path))
    if not export_path.exists():
        project.extraction_notes.append(f"export directory not found: {export_path}")
        return project

    xml_files = sorted(p for p in export_path.rglob("*.xml") if p.is_file())
    if not xml_files:
        project.extraction_notes.append("no XML exports found")
        _attach_export_manifest(project, export_path)
        return project

    results = map_parallel(
        lambda xml_file: parse_export_xml(xml_file, export_path),
        xml_files,
        min_items=4,
    )
    merge_parse_results(project, results)
    _attach_export_manifest(project, export_path)

    if not _has_parsed_surface(project):
        project.extraction_notes.append(
            "no PLC blocks or tag tables recognized — check Openness export layout"
        )

    enrich_project_interfaces(project)
    from agents.plc.tia.safety import apply_safety_flags

    apply_safety_flags(project)
    return project
