"""Transpiles Canvas state into 1:1 Siemens TIA Portal SCL sources and SimaticML bundles.

Executes writeback and compiler closed-loop feedback into Canvas nodes.
"""

from __future__ import annotations

import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from agents.plc.tia.writeback import execute_writeback
from plc_engine.af.refactor import (
    AF_EXPORT_RESTRUCTURE_ROLES,
    af_software_unit_for_role,
    restructure_staged_scl_to_af,
)
from plc_engine.canvas_model import CanvasState, attribute_compiler_errors


def precheck_canvas_for_writeback(canvas: CanvasState) -> dict[str, Any]:
    """写回前的本地 SCL 预检门禁（复用 plc_engine.scl_precheck 的规则）。

    归一化返回 {ok, errors, warnings, findings, summary}：
    - ok=False（存在 error 级问题）→ 调用方必须 fail-closed，不得写 TIA；
    - 仅 warning 不阻断，但要带进结果供前端展示。
    """
    from plc_engine.scl_precheck import precheck_canvas

    report = precheck_canvas(canvas)
    findings = list(report.get("findings") or [])
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
        "summary": f"本地预检：{len(errors)} 个错误 / {len(warnings)} 个警告",
    }


def preview_canvas_scl(canvas: CanvasState) -> dict[str, str]:
    """Render full SCL source code for all blocks in Canvas."""
    scl_map: dict[str, str] = {}
    for name, block in canvas.blocks.items():
        scl_map[name] = block.get_full_scl()
    return scl_map


def preview_canvas_tags_xml(canvas: CanvasState) -> str:
    """Render Siemens standard SimaticML XML for PLC and HMI tags."""
    doc = ET.Element("Document")
    doc.set("xmlns", "http://www.siemens.com/automation/Openness/SW/Interface/v4")
    eng = ET.SubElement(doc, "Engineering")
    eng.set("version", "V17")

    tag_table = ET.SubElement(doc, "SW.Tags.PlcTagTable")
    tag_table.set("ID", "0")
    tag_table.set("CompositionName", "TagTables")

    attr_list = ET.SubElement(tag_table, "AttributeList")
    name_el = ET.SubElement(attr_list, "Name")
    name_el.text = f"{canvas.project_name}_CanvasTags"

    obj_list = ET.SubElement(tag_table, "ObjectList")

    tag_id = 10
    for tag_name, tag in canvas.tags.items():
        plc_tag = ET.SubElement(obj_list, "SW.Tags.PlcTag")
        plc_tag.set("ID", str(tag_id))
        plc_tag.set("CompositionName", "Tags")

        t_attrs = ET.SubElement(plc_tag, "AttributeList")
        dt_el = ET.SubElement(t_attrs, "DataTypeName")
        dt_el.text = tag.data_type
        addr_el = ET.SubElement(t_attrs, "LogicalAddress")
        addr_el.text = tag.logical_address
        t_name_el = ET.SubElement(t_attrs, "Name")
        t_name_el.text = tag_name

        if tag.comment:
            cmt_list = ET.SubElement(plc_tag, "ObjectList")
            ml_text = ET.SubElement(cmt_list, "MultilingualText")
            ml_text.set("ID", str(tag_id + 1))
            ml_text.set("CompositionName", "Comment")
            ml_items = ET.SubElement(ml_text, "ObjectList")
            ml_item = ET.SubElement(ml_items, "MultilingualTextItem")
            ml_item.set("ID", str(tag_id + 2))
            ml_item.set("CompositionName", "Items")
            item_attrs = ET.SubElement(ml_item, "AttributeList")
            culture_el = ET.SubElement(item_attrs, "Culture")
            culture_el.text = "zh-CN"
            text_el = ET.SubElement(item_attrs, "Text")
            text_el.text = tag.comment
            tag_id += 3
        else:
            tag_id += 1

    return ET.tostring(doc, encoding="utf-8", xml_declaration=True).decode("utf-8")


def canvas_to_tia_bundle(
    canvas: CanvasState,
    output_dir: str | Path,
    af_refactor: bool = True,
) -> Path:
    """Create a fully compliant Openness writeback import bundle from Canvas state.

    ``af_refactor=True``(默认)时,对 af_role∈{unit,em,cm} 的待写回块执行
    AF V1.2 架构重排(见 plc_engine.af.refactor.restructure_staged_scl_to_af):
    staged SCL 重排为 Unit/EM/CM 结构,数据引用逐字冻结;传 False 可整体
    关闭(全部块按原始 SCL 原样导出)。
    """
    bundle_path = Path(output_dir).resolve()
    bundle_path.mkdir(parents=True, exist_ok=True)

    # 1. External sources folder (.scl)
    ext_dir = bundle_path / "external_sources"
    ext_dir.mkdir(parents=True, exist_ok=True)

    staged_scls: list[dict[str, Any]] = []
    skipped_protected: list[str] = []
    scl_map = preview_canvas_scl(canvas)
    # 3.5 AF 架构重构的角色序号(决定 U<n>_/U1Em<n>_/U1Em1CM<nn>_ 命名)
    af_ordinals: dict[str, int] = {role: 0 for role in AF_EXPORT_RESTRUCTURE_ROLES}
    for block_key, scl_content in scl_map.items():
        block = canvas.blocks.get(block_key)
        # Bug1 硬防护(必须先于 synced 判断):know-how/加密块的保护与 status
        # 无关 —— 体从未离开过 TIA,画布上只有接口,哪怕被改成 draft 也绝不
        # 写回,否则翻译空壳会覆盖 TIA 原始块。原块原样保留在 TIA 工程中,
        # 跳过名单写入 bundle manifest(skipped_protected.json)。
        if block is not None and bool(getattr(block, "protected", False)):
            skipped_protected.append(block.name or block_key)
            continue
        # 只重写真正被改动过的块。画布刚从工程导入时所有块都是 synced，
        # 此时若全量重写，会把 89 个块全部用规则翻译结果覆盖原工程
        # （真实工程 HR001 实测：编译错误从 0 涨到 1007）。未改动的块
        # 必须保持 TIA 里的原样，这是最小破坏原则。
        if block is not None and str(getattr(block, "status", "")) == "synced":
            continue
        # 3.5 AF 架构重构:导入只做了 af_role 标注(元数据),导出时必须把
        # 非 AF 块的 staged SCL 重排为 AF Unit/EM/CM 结构(非破坏式,可关):
        # - 仅 af_role ∈ {unit, em, cm} 的 draft 块参与;safety(只读)、
        #   global(DB/OB 布局冻结)、pending/空角色 → 保持原 SCL;
        # - 数据引用冻结:DB 名/变量名/%I %Q 地址/符号表逐字保留,只改
        #   代码组织结构(AF 软件单元标识 + 调用分层标注);
        # - 非破坏式:重排结果只写入 staged 文件,画布块本体不被改动。
        af_role_txt = str(getattr(block, "af_role", "") or "").strip() if block is not None else ""
        af_role_key = af_role_txt.lower()
        af_su = ""
        if af_refactor and af_role_key in AF_EXPORT_RESTRUCTURE_ROLES:
            af_ordinals[af_role_key] += 1
            af_su = af_software_unit_for_role(
                block.name if block is not None else block_key,
                af_role_key,
                af_ordinals[af_role_key],
            )
            scl_content = restructure_staged_scl_to_af(scl_content, af_role_key, af_su)
        su = block.software_unit if block else ""
        bname = block.name if block else block_key
        safe_file_name = f"{su}_{bname}.scl" if su else f"{bname}.scl"
        scl_file = ext_dir / safe_file_name
        # TIA External Source 只认 UTF-8 带 BOM(无 BOM 且含非 ASCII 中文注释时
        # CreateFromFile 直接报 Unable to open the file —— 真机 HR001 复现)
        scl_file.write_text(scl_content, encoding="utf-8-sig")
        staged_scls.append({
            "path": str(scl_file),
            "software_unit": su,
            "block_name": bname,
            # AF 元数据(追加字段;writeback 只消费 path/software_unit/block_name)
            "af_role": af_role_txt,
            "af_software_unit": af_su,
        })

    # 2. Tag Table XML — 只有存在 draft 标签才回写（导入的 synced 标签不动，
    #    与块的最小破坏原则一致）
    staged_xmls: list[str] = []
    if any(getattr(t, "status", "") == "draft" for t in canvas.tags.values()):
        tags_xml_file = bundle_path / "CanvasTags.xml"
        tags_xml_file.write_text(preview_canvas_tags_xml(canvas), encoding="utf-8")
        staged_xmls.append(str(tags_xml_file))

    # 3. Write manifest files
    (bundle_path / "staged_scls.json").write_text(json.dumps(staged_scls, indent=2), encoding="utf-8")
    (bundle_path / "staged_xmls.json").write_text(json.dumps(staged_xmls, indent=2), encoding="utf-8")
    # Bug1:know-how/加密块跳过名单(原样保留在 TIA 中,供前端/审计展示)
    (bundle_path / "skipped_protected.json").write_text(
        json.dumps(skipped_protected, indent=2), encoding="utf-8"
    )

    return bundle_path


def execute_canvas_writeback(
    canvas: CanvasState,
    project_path: str | Path,
    plc_name: str = "",
    compile_after: bool = True,
    temp_bundle_parent: str | Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute 1:1 writeback from Canvas to TIA Portal and attribute compiler results.

    Returns:
        (writeback_result, error_attributions)
    """
    if temp_bundle_parent:
        bundle_dir = canvas_to_tia_bundle(canvas, Path(temp_bundle_parent) / "canvas_bundle")
    else:
        temp_dir = tempfile.mkdtemp(prefix="canvas_writeback_")
        bundle_dir = canvas_to_tia_bundle(canvas, Path(temp_dir) / "bundle")

    # Run writeback via HostGateway or Worker
    writeback_result = execute_writeback(
        project_path=project_path,
        bundle_dir=bundle_dir,
        plc_name=plc_name,
        compile_after=compile_after,
    )

    # Compile feedback attribution
    attributions = attribute_compiler_errors(canvas, writeback_result)

    if writeback_result.get("ok"):
        # Everything succeeded! Mark all canvas blocks as synced
        for block in canvas.blocks.values():
            block.status = "synced"
            block.errors = []
            for net in block.networks:
                net.status = "synced"
                net.errors = []
        for widget in canvas.hmi_widgets.values():
            widget.status = "synced"
            widget.errors = []
        for tag in canvas.tags.values():
            tag.status = "synced"

    return writeback_result, attributions
