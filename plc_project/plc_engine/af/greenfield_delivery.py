"""Greenfield Phase 2 标准 AF V1.2 博途工程交付器（P4 · 实现 ``DeliveryPort``）。

严格遵循：
- 仅接受已确认并冻结的 ``FrozenSpec``（``stage == FROZEN`` 且 ``spec_hash`` 非空），未冻结调用抛 ``GateLockedError``。
- 生成 100% 驱动与逻辑解耦的 Siemens AF V1.2 标准工程包（UDT + LAF/LBC 标准库 + Unit/EM0/EM1..n
  + 冻结标准访问 DB720/DB1900 + ``FC_Compat_*`` + ``FC_IoMap_ReadWrite`` + 113 IO 变量表 CSV/XML
  + ``io_retention_matrix.csv`` + 架构留痕 Markdown）。
- 全量通过 ``lint_af_canvas`` 静态架构规则校验与 ``%Q`` 全局唯一写点审计。
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from plc_engine.af.af_generator import generate_af_project_blocks
from plc_engine.af.af_linter import lint_af_canvas
from plc_engine.af.compat_adapter import (
    audit_single_writer_q,
    generate_compat_adapter_blocks,
)
from plc_engine.af.compat_emit import (
    emit_compat_db_blocks,
    emit_io_retention_matrix_csv,
    emit_io_tags_csv,
    emit_io_tags_xml,
    verify_compat_emission_integrity,
)
from plc_engine.af.greenfield_contract import CompatContract
from plc_engine.af.greenfield_ir import GreenfieldIR, sha256_prefixed
from plc_engine.af.greenfield_ports import DeliveryPort, GateLockedError
from plc_engine.af.greenfield_spec import FrozenSpec
from plc_engine.af.greenfield_views import project_views, render_export_md, render_step_flowchart
from plc_engine.canvas_model import CanvasBlock, CanvasState


def _folder_for_block(block: CanvasBlock) -> str:
    role = (block.af_role or "").lower()
    btype = (block.block_type or "").upper()
    if btype == "UDT" or role == "udt":
        return "00_Types_UDT"
    if block.name.startswith(("LAF_", "LBC_")):
        return "01_AF_Standard_Library"
    if role == "legacy_superseded" or block.software_unit == "LegacyCompat":
        return "90_Compat_Frozen_Boundary"
    if role.startswith("unit"):
        return "10_Unit_Supervision"
    if role.startswith("em0"):
        return "20_EM0_General"
    return "30_Equipment_Modules"


class AfGreenfieldDelivery(DeliveryPort):
    """标准 AF V1.2 博途工程包内存交付实现。"""

    def assert_pcec_gate(self, spec: FrozenSpec) -> None:
        if spec is None or not spec.spec_hash or not spec.ir_snapshot:
            raise GateLockedError(
                "规格尚未确认冻结，禁止执行博途工程生成（G1/G2 门禁）",
                code="GF_GATE_LOCKED",
            )
        if spec.recompute_hash() != spec.spec_hash:
            raise GateLockedError(
                "冻结规格哈希不一致，拒绝生成",
                code="GF_SPEC_TAMPERED",
            )

    def deliver(
        self,
        spec: FrozenSpec,
        *,
        contract: CompatContract | None = None,
        custom_hw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.assert_pcec_gate(spec)
        if contract is not None:
            contract.assert_immutable()

        ir = GreenfieldIR.from_dict(spec.ir_snapshot)
        if ir.ir_sha256() != spec.ir_sha256:
            raise GateLockedError(
                "冻结规格 IR 哈希不匹配，拒绝生成",
                code="GF_SPEC_TAMPERED",
            )
        views = project_views(ir)
        af_project = ir.to_af_project()
        af_blocks = generate_af_project_blocks(
            af_project,
            self_contained=True,
            af_io_drive=False,
        )
        compat_dbs = emit_compat_db_blocks(contract)
        compat_fcs = generate_compat_adapter_blocks(ir, contract, custom_hw)

        all_blocks: dict[str, CanvasBlock] = {}
        all_blocks.update(af_blocks)
        all_blocks.update(compat_dbs)
        all_blocks.update(compat_fcs)

        canvas = CanvasState(project_name=af_project.name, blocks=all_blocks)
        findings = lint_af_canvas(canvas)
        errors = [f for f in findings if f.severity == "ERROR"]
        single_writer = audit_single_writer_q(all_blocks, contract)
        compat_integrity = verify_compat_emission_integrity(contract, compat_dbs)

        io_csv = emit_io_tags_csv(contract)
        io_xml = emit_io_tags_xml(contract, table_name="PLC_IO")
        retention_csv = emit_io_retention_matrix_csv(contract, ir, custom_hw)
        step_flow = render_step_flowchart(ir)
        trace_md = render_export_md(
            ir,
            views,
            title=f"{af_project.name} · AF V1.2 工程规格与三视图留痕",
            frozen_note=f"冻结版本：{spec.version_label} · spec_hash={spec.spec_hash}",
        )
        trace_md += f"\n## 视图四 · 步序流程图 (Step Flowchart)\n\n```mermaid\n{step_flow['mermaid']}\n```\n"

        blocks_manifest: list[dict[str, Any]] = []
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(all_blocks):
                blk = all_blocks[name]
                folder = _folder_for_block(blk)
                scl_text = blk.scl_body if blk.block_type in {"DB", "UDT"} and blk.scl_body else blk.get_full_scl()
                rel_path = f"blocks/{folder}/{blk.name}.scl"
                zf.writestr(rel_path, scl_text.encode("utf-8"))
                blocks_manifest.append(
                    {
                        "name": blk.name,
                        "block_type": blk.block_type,
                        "number": blk.number,
                        "af_role": blk.af_role,
                        "folder": folder,
                        "path": rel_path,
                        "sha256": sha256_prefixed(scl_text),
                    }
                )

            zf.writestr("plc_tags/PLCTags_Frozen.csv", io_csv.encode("utf-8-sig"))
            zf.writestr("plc_tags/PLCTags_Frozen.xml", io_xml.encode("utf-8"))
            zf.writestr("audit/io_retention_matrix.csv", retention_csv.encode("utf-8-sig"))
            zf.writestr("docs/architecture_spec.md", trace_md.encode("utf-8"))

            verification_report = {
                "ok": len(errors) == 0 and single_writer["ok"] and compat_integrity["ok"],
                "project_name": af_project.name,
                "af_profile": ir.project.af_profile,
                "tia_version": ir.project.tia_version,
                "spec_version": spec.version_label,
                "spec_hash": spec.spec_hash,
                "contract_hashes": [spec.contract_sha] if spec.contract_sha else [],
                "linter_error_count": len(errors),
                "linter_warning_count": len([f for f in findings if f.severity != "ERROR"]),
                "linter_findings": [f.to_dict() for f in findings],
                "single_writer_audit": single_writer,
                "compat_integrity": compat_integrity,
            }
            zf.writestr(
                "audit/af_verification_report.json",
                json.dumps(verification_report, ensure_ascii=False, indent=2).encode("utf-8"),
            )

            manifest = {
                "project_name": af_project.name,
                "spec_version": spec.version_label,
                "spec_hash": spec.spec_hash,
                "block_count": len(blocks_manifest),
                "blocks": blocks_manifest,
                "verification": verification_report,
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )

        zip_bytes = zip_buf.getvalue()
        return {
            "ok": len(errors) == 0 and single_writer["ok"] and compat_integrity["ok"],
            "project_name": af_project.name,
            "spec_version": spec.version_label,
            "spec_hash": spec.spec_hash,
            "block_count": len(blocks_manifest),
            "blocks_manifest": blocks_manifest,
            "verification": verification_report,
            "zip_filename": f"{af_project.name}_{spec.version_label}_AF_TIA_Package.zip",
            "zip_sha256": sha256_prefixed(zip_bytes.hex()),
            "zip_size_bytes": len(zip_bytes),
            "zip_bytes": zip_bytes,
        }
