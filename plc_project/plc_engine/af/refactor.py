"""AF V1.2 Refactoring Engine: Legacy-to-AF Canvas Transformation.

Orchestrates reverse engineering and refactoring of non-standard TIA projects
into official Siemens Automation Framework (AF) V1.2 architecture:
- Generates complete AF V1.2 Software Unit blocks (Units, EMs, CMs, OBs, DBs)
- Marks original legacy blocks as superseded
- Produces architecture comparison reports with 100% I/O retention verification
- Executes AF static architecture linter to guarantee compliance.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from plc_engine.af.af_generator import generate_af_project_blocks
from plc_engine.af.af_linter import lint_af_canvas
from plc_engine.af.af_mapper import LegacyToAfMapper
from plc_engine.canvas_model import CanvasBlock, CanvasState


def refactor_canvas_to_af(
    canvas: CanvasState,
    target_unit_name: str = "U1_Refactored",
) -> tuple[CanvasState, dict[str, Any]]:
    """Refactor a legacy CanvasState into official AF V1.2 architecture.

    Args:
        canvas: The original flat legacy CanvasState.
        target_unit_name: Name of the target AF Unit (e.g. "U1_Assembly").

    Returns:
        tuple[CanvasState, dict[str, Any]]:
            - new_canvas: Updated CanvasState containing AF V1.2 blocks alongside
              superseded legacy blocks.
            - report: Comprehensive architecture transformation report detailing
              block mappings, EM/CM hierarchy, 100% physical I/O retention,
              safety interlocks, and AF linter findings.
    """
    # 1. Execute Legacy-to-AF Mapper analysis
    mapper = LegacyToAfMapper(canvas, target_unit_name=target_unit_name)
    analysis = mapper.analyze()

    # 2. Build AF Project Domain Model
    af_project = mapper.build_af_project(analysis)

    # 3. Generate all AF V1.2 CanvasBlocks
    af_blocks = generate_af_project_blocks(af_project)

    # 4. Enrich CallEquipment blocks with hardware I/O and interlock bindings
    _enrich_callequipment_blocks(af_blocks, analysis)

    # 5. Clone canvas and mark legacy blocks as superseded
    new_canvas = copy.deepcopy(canvas)

    for block in new_canvas.blocks.values():
        block.comment = f"[AF-REFACTORED: Superseded by {target_unit_name}] " + (block.comment or "")
        block.af_role = "legacy_superseded"
        block.software_unit = "Legacy_Superseded"

    # 6. Add all generated AF blocks into the new canvas
    for key, block in af_blocks.items():
        new_canvas.blocks[key] = block

    # 7. Update software unit manifests
    for unit in af_project.units:
        su_name = unit.unit_name
        new_canvas.software_unit_manifests.setdefault(su_name, {"type": "Unit", "unit_idx": unit.unit_idx})
        new_canvas.software_unit_manifests.setdefault(f"U{unit.unit_idx}Em0_General", {"type": "EM0"})
        for em in unit.equipment_modules:
            em_su = f"U{unit.unit_idx}Em{em.em_idx}_{em.name}"
            new_canvas.software_unit_manifests.setdefault(em_su, {"type": "EM", "em_idx": em.em_idx})

    # 8. Run AF static linter on refactored canvas
    findings = lint_af_canvas(new_canvas)

    # 9. Build architecture comparison report
    ems_summary = []
    if analysis.units:
        for em in analysis.units[0].ems:
            ems_summary.append(
                {
                    "em_idx": em.em_idx,
                    "name": em.name,
                    "steps_count": len(em.steps),
                    "cms_count": len(em.control_modules),
                    "cms": [
                        {
                            "name": cm.name,
                            "cm_type": cm.cm_type,
                            "description": cm.description,
                            "io_mapping": cm.io_mapping,
                            "parameters": cm.parameters,
                        }
                        for cm in em.control_modules
                    ],
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "name": s.name,
                            "actions": s.actions,
                            "transition_condition": s.transition_condition,
                            "next_step_id": s.next_step_id,
                        }
                        for s in em.steps
                    ],
                }
            )

    report: dict[str, Any] = {
        "status": "success",
        "project_name": canvas.project_name,
        "target_unit_name": target_unit_name,
        "legacy_blocks_count": len(canvas.blocks),
        "af_blocks_count": len(af_blocks),
        "block_mapping": analysis.block_mapping,
        "ems": ems_summary,
        "io_retention": {
            "total_ios": analysis.total_ios_detected,
            "retained_ios": analysis.retained_ios_count,
            "percentage": analysis.io_retention_rate,
            "details": [
                {
                    "address": m.address,
                    "tag_name": m.tag_name,
                    "data_type": m.data_type,
                    "cm_name": m.cm_name,
                    "cm_type": m.cm_type,
                    "cm_field": m.cm_field,
                    "em_name": m.em_name,
                }
                for m in analysis.io_mappings
            ],
        },
        "interlocks": [
            {
                "name": ic.name,
                "expression": ic.expression,
                "source_block": ic.source_block,
                "associated_cms": ic.associated_cms,
                "description": ic.description,
            }
            for ic in analysis.interlocks_detected
        ],
        "lint_findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "block_name": f.block_name,
                "message": f.message,
            }
            for f in findings
        ],
        "af_blocks_created": sorted(list(af_blocks.keys())),
    }

    return new_canvas, report


def _enrich_callequipment_blocks(
    af_blocks: dict[str, CanvasBlock],
    analysis: Any,
) -> None:
    """Enrich FB CallEquipment SCL body with hardware I/O and safety interlock comments."""
    for key, block in af_blocks.items():
        if block.af_role != "CallEquipment":
            continue

        io_lines = ["\n    // ==========================================", "    // Hardware I/O Binding & Safety Interlocks", "    // =========================================="]
        for m in analysis.io_mappings:
            if m.cm_name:
                io_lines.append(f"    // CM {m.cm_name}.{m.cm_field}: {m.address} ({m.tag_name})")

        interlock_lines = ["    // Active Interlocks:"]
        for ic in analysis.interlocks_detected:
            interlock_lines.append(f"    // - {ic.name}: {ic.expression}")

        binding_doc = "\n".join(io_lines + interlock_lines) + "\n"

        # Insert before END_FUNCTION_BLOCK
        if "END_FUNCTION_BLOCK" in block.scl_body:
            block.scl_body = block.scl_body.replace("END_FUNCTION_BLOCK", f"{binding_doc}\nEND_FUNCTION_BLOCK")


# =====================================================================
# Bug2: Export-time AF restructuring (per staged block, lightweight)
# =====================================================================
#
# 与上方 ``refactor_canvas_to_af`` 的分工:
# - ``refactor_canvas_to_af`` 是全画布"另起炉灶"式重构:新建整套 AF 块并
#   把旧块标记 superseded,其映射器会**改写数据引用**(如 ``"Q_Cyl" := TRUE``
#   → ``#controlNodes.cyl.commands.workPosition := TRUE``),只保留物理 IO
#   百分比,不满足"逐字冻结"约束,不能用于导出写回路径。
# - 下面这一节是导出路径专用的轻量重排:对单个 staged 块的 SCL 做
#   **组织层** AF 化(AF 软件单元标识 + Unit/EM/CM 调用分层标注),
#   数据引用(#变量 / "DB名".成员 / %I %Q 地址)与语句顺序逐字冻结。
#   之所以不动可执行语句本身:SCL 语句顺序敏感,任何重排/改写都会改变
#   行为或数据指向;而接口/块名不动则保证 TIA 侧调用方不受影响。

#: 参与 AF 重排的 af_role(导入 overlay 的通用角色词表子集)。
#: safety(只读)/ global(DB/OB 布局冻结)/ pending/空 一律保持原 SCL。
AF_EXPORT_RESTRUCTURE_ROLES = ("unit", "em", "cm")

#: 数据引用提取:#变量、带引号的 DB/符号名、绝对 IO 地址。
_DATA_REF_RE = re.compile(
    r'#[A-Za-z_][A-Za-z0-9_]*|"[^"]+"|%[IQMW][BWD]?\d+(?:\.\d+)?',
    re.IGNORECASE,
)

# 语句分层识别(EM 步序层 / CM 设备 IO 层 / Unit 层)
_SEQ_LINE_RE = re.compile(r"\bstep\b", re.IGNORECASE)
_IO_ADDR_RE = re.compile(r"%[IQMW][BWD]?", re.IGNORECASE)
_TAG_ASSIGN_RE = re.compile(r'^\s*"[^"\. ]+"\s*:=')  # 整名符号赋值(非 DB 成员)
_LABEL_LINE_RE = re.compile(r"^\s*-?\d+\s*:\s*(?://.*)?$")  # CASE 分支标签,跟随当前层
# 控制流骨架(IF/CASE/FOR/END_*)跟随当前层——切层只由赋值语句驱动,
# 避免横幅在步序体内逐行抖动。
_CTRL_FLOW_RE = re.compile(
    r"^\s*(?:IF|ELSIF|ELSE|END_IF|FOR|TO|BY|WHILE|END_FOR|END_WHILE|CASE|OF|END_CASE|"
    r"REPEAT|UNTIL|END_REPEAT|RETURN|GOTO)\b",
    re.IGNORECASE,
)

_AF_PREFIX_STRIP_RE = re.compile(r"^(?:FB|FC|OB|DB|SFB|SFC)\d*_?", re.IGNORECASE)
_AF_INVALID_CHAR_RE = re.compile(r"[^A-Za-z0-9_]")


def extract_scl_data_references(scl: str) -> list[str]:
    """Extract every data-reference token from SCL text (freeze-check helper).

    Tokens: ``#Var``、``"DB名"/"符号名"``、``%I0.0/%Q0.0/...``。
    """
    return _DATA_REF_RE.findall(scl or "")


def af_software_unit_for_role(block_name: str, af_role: str, ordinal: int = 1) -> str:
    """Derive the AF V1.2 Software Unit name for a staged block.

    - unit → ``U<n>_<Name>``
    - em   → ``U1Em<n>_<Name>``
    - cm   → ``U1Em1CM<nn>_<Name>``
    """
    clean = _AF_INVALID_CHAR_RE.sub("", _AF_PREFIX_STRIP_RE.sub("", str(block_name or "").strip()))
    if not clean:
        clean = "Module"
    n = max(1, int(ordinal))
    role = str(af_role or "").strip().lower()
    if role == "unit":
        return f"U{n}_{clean}"
    if role == "em":
        return f"U1Em{n}_{clean}"
    if role == "cm":
        return f"U1Em1CM{n:02d}_{clean}"
    return clean


def _af_role_banner(af_role: str, af_su: str) -> list[str]:
    """AF identity banner lines (body-legal // comments, quote-free)."""
    role = str(af_role or "").strip().lower()
    if role == "unit":
        call_chain = "OB Main -> CallUnit(U{su}) -> CallEquipment/EMs -> CMs".format(su=af_su)
        layer = "Unit"
    elif role == "em":
        call_chain = "OB Main -> CallUnit(U1) -> CallEquipment({su}) -> Sequence -> CMs".format(su=af_su)
        layer = "Equipment Module"
    else:  # cm
        call_chain = "OB Main -> CallUnit(U1) -> CallEquipment(U1Em1) -> CM({su})".format(su=af_su)
        layer = "Control Module"
    return [
        "    // ==============================================================",
        f"    // AF V1.2 Software Unit : {af_su}   (af_role = {role})",
        f"    // AF Layer              : {layer}",
        f"    // AF Call Structure     : {call_chain}",
        "    // --------------------------------------------------------------",
        "    // DATA REFERENCES FROZEN / 数据引用冻结:",
        "    //   原始 DB 名 / 符号名 / %I %Q 地址 / #变量 在下方逐字保留",
        "    //   且语句顺序不变;仅代码组织结构重排为 AF Unit/EM/CM 分层。",
        "    // AF ControlNodes 桥接说明(追加式,不改原始 DB 偏移):",
        f"    //   {af_su}_ControlNodes 为 AF 接口 DB(块号追加),原 DB 不动。",
        "    // ==============================================================",
    ]


_LAYER_BANNERS = {
    "sequence": "    // --- [AF Sequence | EM 步序层] 以下为原始语句(逐字、原顺序) ---",
    "cm": "    // --- [AF CallEquipment -> CM | 设备 IO 控制层] 以下为原始语句(逐字、原顺序) ---",
    "unit": "    // --- [AF CallUnit | Unit 模式/状态层] 以下为原始语句(逐字、原顺序) ---",
}


def _classify_body_line(line: str) -> str:
    """Classify a body statement into an AF layer without touching it.

    只有赋值语句(``:=``)驱动切层;注释/空行/CASE 标签/控制流骨架跟随
    当前层,保证节标稳定不抖动。
    """
    s = line.strip()
    if (
        not s
        or s.startswith("//")
        or _LABEL_LINE_RE.match(s)
        or _CTRL_FLOW_RE.match(s)
        or ":=" not in s
    ):
        return ""
    if _SEQ_LINE_RE.search(s):
        return "sequence"
    if _IO_ADDR_RE.search(s) or _TAG_ASSIGN_RE.match(s):
        return "cm"
    return "unit"


def restructure_staged_scl_to_af(scl: str, af_role: str, af_software_unit: str) -> str:
    """Restructure one staged legacy SCL into AF Unit/EM/CM organization.

    只做组织层重排,可执行语句逐字逐序保留:

    1. AF 软件单元横幅(身份/命名空间/调用层级/ControlNodes 桥接说明);
    2. 函数体按 AF 调用分层(Unit/Sequence/CM)加节标——语句不移动、不改写,
       仅在"语句性质切换处"插入 ``// ---`` 节标;
    3. 冻结校验:原 SCL 的全部数据引用 token(#变量/"名字"/%地址)必须
       逐字出现在重排结果中,且带引号的符号名集合完全一致;任一不满足
       则原样返回 ``scl``(宁可不出 AF 结构,绝不带着丢引用的重排版进 TIA)。

    DB/UDT 或无法定位 BEGIN..END_ 结构的文本同样原样返回。
    """
    if not scl or not str(af_role or "").strip().lower() in AF_EXPORT_RESTRUCTURE_ROLES:
        return scl
    head = scl.lstrip()
    if head.startswith("DATA_BLOCK") or head.startswith("TYPE"):
        return scl  # DB/UDT 布局冻结,不做任何改写

    lines = scl.splitlines()
    end_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip()
            in ("END_FUNCTION_BLOCK", "END_ORGANIZATION_BLOCK", "END_FUNCTION")
        ),
        -1,
    )
    begin_idx = -1
    if end_idx > 0:
        begin_idx = max(
            (i for i in range(end_idx) if lines[i].strip() == "BEGIN"),
            default=-1,
        )
    if begin_idx < 0:
        return scl

    out: list[str] = lines[: begin_idx + 1]
    out.extend(_af_role_banner(str(af_role).strip().lower(), af_software_unit))

    current_layer = ""
    for ln in lines[begin_idx + 1 : end_idx]:
        layer = _classify_body_line(ln)
        if layer and layer != current_layer:
            out.append(_LAYER_BANNERS[layer])
            current_layer = layer
        out.append(ln)

    out.extend(lines[end_idx:])
    new_scl = "\n".join(out)
    if scl.endswith("\n"):
        new_scl += "\n"

    # ---- 数据引用冻结校验(运行时兜底,测试另有独立断言) ----
    orig_refs = set(extract_scl_data_references(scl))
    new_refs = set(extract_scl_data_references(new_scl))
    if not orig_refs <= new_refs:
        return scl
    orig_quoted = {t for t in orig_refs if t.startswith('"')}
    new_quoted = {t for t in new_refs if t.startswith('"')}
    if orig_quoted != new_quoted:
        return scl
    return new_scl
