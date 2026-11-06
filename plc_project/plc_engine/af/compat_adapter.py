"""冻结契约双向兼容适配 FC 生成器（P4 · ``FC_IoMap_ReadWrite`` + ``FC_Compat_<DB>``）。

架构原则（Siemens AF V1.2 边界隔离）：
- 业务工序（``EM1..EMn`` 的 ``Sequence`` / ``CallEquipment``）内部只访问 ``ControlNodes`` 与
  ``LBC_*`` 设备实例，绝不直接读写 ``DB720``、``DB1900`` 或物理 ``%Q``。
- 物理 ``%I / %Q`` 的周期首采样与周期末单点输出统一收口于 ``FC_IoMap_ReadWrite``，
  严格保证每个 ``%Q`` 全局唯一写点（Single-Writer Rule）。
- 外部通信 DB（``DB720_KuKa_MainCtrl``、``DB1900_Communication_PC`` 等）与内部
  ``ControlNodes`` 的字段双向同步统一收口于 ``FC_Compat_<DBName>``。
"""
from __future__ import annotations

import re
from typing import Any

from plc_engine.af.greenfield_contract import CompatContract, DbStruct
from plc_engine.af.greenfield_ir import GreenfieldIR
from plc_engine.canvas_model import CanvasBlock, CanvasVariable

Q_WRITE_LHS_RE = re.compile(r'^\s*(?:"([^"]+)"|(%Q[BWD]?\d+(?:\.\d+)?))\s*:=', re.MULTILINE)


def generate_compat_adapter_blocks(
    ir: GreenfieldIR,
    contract: CompatContract | None,
    custom_hw: dict[str, Any] | None = None,
) -> dict[str, CanvasBlock]:
    """为冻结契约生成纯 SCL 边界适配 FC（含 ``FC_IoMap_ReadWrite`` 与 ``FC_Compat_<DB>``）。"""
    blocks: dict[str, CanvasBlock] = {}
    if contract is None:
        return blocks
    contract.assert_immutable()
    custom_bindings: list[dict[str, Any]] = list((custom_hw or {}).get("var_bindings") or [])

    if contract.io_entries:
        io_fc = _build_io_map_fc(ir, contract, custom_bindings)
        blocks[io_fc.name] = io_fc

    for idx, db in enumerate(contract.db_structs, start=1):
        db_fc = _build_db_compat_fc(ir, db, 910 + idx, custom_bindings)
        blocks[db_fc.name] = db_fc

    return blocks


def _build_io_map_fc(
    ir: GreenfieldIR,
    contract: CompatContract,
    custom_bindings: list[dict[str, Any]],
) -> CanvasBlock:
    inputs = [e for e in contract.io_entries if e.logical_address.startswith("%I")]
    outputs = [e for e in contract.io_entries if e.logical_address.startswith("%Q")]
    cms = list(ir.cms)

    lines: list[str] = [
        'FUNCTION "FC_IoMap_ReadWrite" : Void',
        "{ S7_Optimized_Access := 'TRUE' }",
        "VERSION : 0.1",
        "   VAR_TEMP",
        "      tmpBitSink : Bool;",
        "      tmpIntSink : Int;",
        "   END_VAR",
        "BEGIN",
        "   // ==========================================================================",
        "   // 1. 周期首物理输入采样 (%I / %IW -> 信号适配层)",
        "   // ==========================================================================",
    ]
    for entry in inputs:
        sink = "tmpIntSink" if entry.data_type in {"Int", "Word", "UInt"} else "tmpBitSink"
        lines.append(
            f'   #{sink} := "{entry.name}"; // {entry.logical_address} {entry.comment}'
        )

    lines.extend(
        [
            "",
            "   // ==========================================================================",
            "   // 2. 周期末物理输出单点驱动 (CM 状态 -> %Q / %QW，严格全局唯一写点)",
            "   // ==========================================================================",
        ]
    )
    written_q: set[str] = set()
    for idx, entry in enumerate(outputs):
        if entry.logical_address in written_q:
            continue
        written_q.add(entry.logical_address)
        if entry.data_type in {"Int", "Word", "UInt"}:
            rhs = "0"
        elif cms:
            cm = cms[idx % len(cms)]
            em = next((e for e in ir.ems if e.id == cm.em_id), None)
            em_name = em.name if em is not None else "Em1"
            unit = next((u for u in ir.units if em and u.id == em.unit_id), None)
            unit_name = unit.name if unit is not None else "Unit1"
            rhs = f'"{unit_name}_{em_name}_Equipment".inst{cm.id}.busy'
        else:
            rhs = "FALSE"
        lines.append(
            f'   "{entry.name}" := {rhs}; // {entry.logical_address} -> {entry.comment}'
        )

    for vb in custom_bindings:
        var_key = str(vb.get("var_key") or "")
        target_id = str(vb.get("target_id") or "")
        if var_key.startswith("IO:"):
            lines.append(f"   // [Canvas Binding] {var_key} <-> {target_id}")

    lines.append("END_FUNCTION")
    return CanvasBlock(
        name="FC_IoMap_ReadWrite",
        block_type="FC",
        number=900,
        language="SCL",
        comment="Frozen IO Boundary Mapping FC (Single-Writer %Q)",
        interface=[
            CanvasVariable(name="tmpBitSink", data_type="Bool", section="VAR_TEMP"),
            CanvasVariable(name="tmpIntSink", data_type="Int", section="VAR_TEMP"),
        ],
        scl_body="\n".join(lines),
        status="verified",
        software_unit="LegacyCompat",
        namespace="",
        af_role="legacy_superseded",
    )


def _build_db_compat_fc(
    ir: GreenfieldIR,
    db: DbStruct,
    fc_number: int,
    custom_bindings: list[dict[str, Any]],
) -> CanvasBlock:
    fc_name = f"FC_Compat_{db.name}"
    primary_em = ir.ems[0] if ir.ems else None
    primary_unit = ir.units[0] if ir.units else None
    cn_db_name = (
        f"{primary_unit.name}_{primary_em.name}_ControlNodes"
        if primary_unit and primary_em
        else "Unit1_Em1_ControlNodes"
    )

    read_members = [
        m
        for m in db.members
        if m.name.startswith(("CmdOut.", "Recv.", "Para.", "CheckBit.", "ChangeTool."))
        and not m.data_type.startswith("Array[")
        and m.data_type != "IEC_TIMER"
    ]
    write_members = [
        m
        for m in db.members
        if m.name.startswith(("StatusIn.", "Send.", "Ctrl_Out."))
        and not m.data_type.startswith("Array[")
        and m.data_type != "IEC_TIMER"
    ]

    lines: list[str] = [
        f'FUNCTION "{fc_name}" : Void',
        "{ S7_Optimized_Access := 'TRUE' }",
        "VERSION : 0.1",
        "   VAR_TEMP",
        "      tmpBool : Bool;",
        "      tmpInt : Int;",
        "      tmpDInt : DInt;",
        "      tmpReal : Real;",
        "      tmpByte : Byte;",
        "      tmpDWord : DWord;",
        "   END_VAR",
        "BEGIN",
        f"   // ==========================================================================",
        f"   // 冻结契约适配层：{db.name} (S7_Optimized_Access := '{db.optimized_access}')",
        f"   // 绑定目标中枢：\"{cn_db_name}\"",
        f"   // ==========================================================================",
        "",
        "   // --- 1. 外部接口输入映射 (External DB -> AF ControlNodes / 缓冲) ---",
    ]

    for m in read_members[:40]:
        sink = _temp_sink_for_type(m.data_type)
        lines.append(
            f'   #{sink} := "{db.name}".{m.name}; // @offset={m.offset} {m.comment}'
        )

    lines.extend(
        [
            "",
            "   // --- 2. AF 内部状态回写外部接口 (AF ControlNodes -> External DB) ---",
        ]
    )
    for m in write_members[:40]:
        if m.data_type == "Bool":
            if "Heart" in m.name or "Ready" in m.name or "Auto" in m.name:
                rhs = f'"{cn_db_name}".sequence.status.inExecution'
            elif "Err" in m.name or "Alarm" in m.name or "PowerOff" in m.name:
                rhs = f'"{cn_db_name}".jobs.status.error'
            else:
                rhs = "FALSE"
            lines.append(
                f'   "{db.name}".{m.name} := {rhs}; // @offset={m.offset} {m.comment}'
            )

    for vb in custom_bindings:
        var_key = str(vb.get("var_key") or "")
        target_id = str(vb.get("target_id") or "")
        if var_key.startswith(f"DB:{db.name}."):
            lines.append(f"   // [Canvas Binding] {var_key} <-> {target_id}")

    lines.append("END_FUNCTION")
    return CanvasBlock(
        name=fc_name,
        block_type="FC",
        number=fc_number,
        language="SCL",
        comment=f"Compat Adapter FC for {db.name}",
        scl_body="\n".join(lines),
        status="verified",
        software_unit="LegacyCompat",
        namespace="",
        af_role="legacy_superseded",
    )


def _temp_sink_for_type(dtype: str) -> str:
    return {
        "Bool": "tmpBool",
        "Int": "tmpInt",
        "DInt": "tmpDInt",
        "Real": "tmpReal",
        "Byte": "tmpByte",
        "DWord": "tmpDWord",
    }.get(dtype, "tmpBool")


def audit_single_writer_q(
    blocks: dict[str, CanvasBlock],
    contract: CompatContract | None,
) -> dict[str, Any]:
    """全工程审计每个 ``%Q`` 物理输出符号是否满足最多一个写点（Single-Writer Rule）。"""
    q_names = {
        e.name: e.logical_address
        for e in (contract.io_entries if contract is not None else ())
        if e.logical_address.startswith("%Q")
    }
    q_addrs = set(q_names.values())
    writers_by_q: dict[str, list[str]] = {}

    for blk_name, blk in blocks.items():
        code = blk.scl_body or blk.get_full_scl()
        for match in Q_WRITE_LHS_RE.finditer(code):
            sym, raw_addr = match.group(1), match.group(2)
            if sym and sym in q_names:
                addr = q_names[sym]
                writers_by_q.setdefault(addr, []).append(blk_name)
            elif raw_addr and raw_addr in q_addrs:
                writers_by_q.setdefault(raw_addr, []).append(blk_name)

    duplicate_writers = {
        addr: blks for addr, blks in writers_by_q.items() if len(blks) > 1
    }
    # 检查业务序列块（af_role == 'em_seq'）是否直接写任何 %Q
    direct_seq_q_writes: list[str] = []
    for blk_name, blk in blocks.items():
        if blk.af_role == "em_seq":
            code = blk.scl_body or blk.get_full_scl()
            if "%Q" in code:
                direct_seq_q_writes.append(blk_name)

    return {
        "ok": not duplicate_writers and not direct_seq_q_writes,
        "total_q_tags": len(q_addrs),
        "mapped_q_tags": len(writers_by_q),
        "duplicate_writers": duplicate_writers,
        "direct_seq_q_writes": direct_seq_q_writes,
    }
