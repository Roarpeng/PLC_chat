"""Greenfield 物理硬件拓扑推导与内外部变量目录聚合器（P2）。

职责：
1. 从 ``CompatContract``（IO 表 + 标准访问 DB 块）与 ``GreenfieldIR`` 自动推导物理硬件拓扑：
   - ``PLC_CPU``（S7-1500 CPU）
   - ``DI_MODULE`` / ``DO_MODULE`` / ``AI_MODULE`` / ``AO_MODULE``（按 ``%I/%Q/%IW/%QW`` 字节/字地址聚类）
   - ``ROBOT_KUKA``（识别 ``DB720_KuKa_MainCtrl`` 等机器人接口 DB，Profinet 连接）
   - ``HOST_PC``（识别 ``DB1900_Communication_PC`` 等上位机通信 DB，TCP/IP 连接）
2. 将 ``GFCm`` 设备模块挂载到对应物理硬件节点，并支持前端在拓扑画布上手工改挂或新增硬件节点。
3. 聚合右侧变量面板所需的『外部锁定变量（IO + DB）』与『内部生成变量（ControlNodes + CM 五信号 + Step）』。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from plc_engine.af.greenfield_contract import CompatContract
from plc_engine.af.greenfield_ir import GreenfieldIR

BIT_IO_RE = re.compile(r"^%([IQ])(\d+)\.(\d+)$")
WORD_IO_RE = re.compile(r"^%([IQ])([BWD])(\d+)$")


@dataclass
class GFHwNode:
    """物理硬件拓扑节点。"""

    id: str
    kind: str  # PLC_CPU | DI_MODULE | DO_MODULE | AI_MODULE | AO_MODULE | ROBOT_KUKA | HOST_PC | HMI_PANEL
    label: str
    slot: str = ""
    protocol: str = "Backplane"  # Backplane | Profinet | TCP_IP
    address_range: str = ""
    mounted_cm_ids: list[str] = field(default_factory=list)
    tag_count: int = 0
    tags_preview: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "slot": self.slot,
            "protocol": self.protocol,
            "address_range": self.address_range,
            "mounted_cm_ids": list(self.mounted_cm_ids),
            "tag_count": self.tag_count,
            "tags_preview": list(self.tags_preview),
        }


@dataclass
class GFNetLink:
    """物理硬件总线/网络连接线。"""

    id: str
    src_hw_id: str
    dst_hw_id: str
    protocol: str = "Backplane"
    label: str = "背板总线"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "src_hw_id": self.src_hw_id,
            "dst_hw_id": self.dst_hw_id,
            "protocol": self.protocol,
            "label": self.label,
        }


def derive_hardware_topology(
    ir: GreenfieldIR | None,
    contract: CompatContract | None,
    custom_hw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据当前会话契约与 IR 派生完整物理拓扑与变量绑定目录。"""
    custom = custom_hw or {}
    custom_mounts: dict[str, str] = dict(custom.get("cm_mounts") or {})
    custom_var_bindings: list[dict[str, Any]] = list(custom.get("var_bindings") or [])
    extra_nodes: list[dict[str, Any]] = list(custom.get("extra_nodes") or [])

    nodes: list[GFHwNode] = []
    links: list[GFNetLink] = []

    cpu_label = "S7-1500 CPU 1516F-3 PN/DP"
    if ir is not None and ir.project.name:
        cpu_label = f"PLC CPU · {ir.project.name} ({ir.project.tia_version})"
    cpu_node = GFHwNode(
        id="HW_CPU",
        kind="PLC_CPU",
        label=cpu_label,
        slot="Rack 0 / Slot 1",
        protocol="Backplane",
        address_range="OB1 / AF V1.2 Standard",
    )
    nodes.append(cpu_node)

    di_groups: dict[int, list[dict[str, Any]]] = {}
    do_groups: dict[int, list[dict[str, Any]]] = {}
    ai_entries: list[dict[str, Any]] = []
    ao_entries: list[dict[str, Any]] = []
    addr_to_hw: dict[str, str] = {}

    io_entries = list(contract.io_entries) if contract is not None else []
    for entry in io_entries:
        addr = entry.logical_address
        item = {
            "name": entry.name,
            "logical_address": addr,
            "data_type": entry.data_type,
            "comment": entry.comment,
        }
        m_bit = BIT_IO_RE.match(addr)
        if m_bit:
            direction, byte_no = m_bit.group(1), int(m_bit.group(2))
            if direction == "I":
                di_groups.setdefault(byte_no, []).append(item)
                addr_to_hw[addr] = f"HW_DI_{byte_no}"
            else:
                do_groups.setdefault(byte_no, []).append(item)
                addr_to_hw[addr] = f"HW_DO_{byte_no}"
            continue
        m_word = WORD_IO_RE.match(addr)
        if m_word:
            direction = m_word.group(1)
            if direction == "I":
                ai_entries.append(item)
                addr_to_hw[addr] = "HW_AI_0"
            else:
                ao_entries.append(item)
                addr_to_hw[addr] = "HW_AO_0"

    slot_idx = 2
    for byte_no in sorted(di_groups):
        items = di_groups[byte_no]
        hw_id = f"HW_DI_{byte_no}"
        nodes.append(
            GFHwNode(
                id=hw_id,
                kind="DI_MODULE",
                label=f"DI 8x24VDC (%IB{byte_no})",
                slot=f"Rack 0 / Slot {slot_idx}",
                protocol="Backplane",
                address_range=f"%I{byte_no}.0 .. %I{byte_no}.7",
                tag_count=len(items),
                tags_preview=items[:8],
            )
        )
        links.append(
            GFNetLink(
                id=f"LINK_CPU_{hw_id}",
                src_hw_id="HW_CPU",
                dst_hw_id=hw_id,
                protocol="Backplane",
                label="背板 DI",
            )
        )
        slot_idx += 1

    for byte_no in sorted(do_groups):
        items = do_groups[byte_no]
        hw_id = f"HW_DO_{byte_no}"
        nodes.append(
            GFHwNode(
                id=hw_id,
                kind="DO_MODULE",
                label=f"DQ 8x24VDC (%QB{byte_no})",
                slot=f"Rack 0 / Slot {slot_idx}",
                protocol="Backplane",
                address_range=f"%Q{byte_no}.0 .. %Q{byte_no}.7",
                tag_count=len(items),
                tags_preview=items[:8],
            )
        )
        links.append(
            GFNetLink(
                id=f"LINK_CPU_{hw_id}",
                src_hw_id="HW_CPU",
                dst_hw_id=hw_id,
                protocol="Backplane",
                label="背板 DQ",
            )
        )
        slot_idx += 1

    if ai_entries:
        hw_id = "HW_AI_0"
        addrs = ", ".join(e["logical_address"] for e in ai_entries)
        nodes.append(
            GFHwNode(
                id=hw_id,
                kind="AI_MODULE",
                label=f"AI 模拟量输入 ({addrs})",
                slot=f"Rack 0 / Slot {slot_idx}",
                protocol="Backplane",
                address_range=addrs,
                tag_count=len(ai_entries),
                tags_preview=ai_entries[:8],
            )
        )
        links.append(
            GFNetLink(
                id=f"LINK_CPU_{hw_id}",
                src_hw_id="HW_CPU",
                dst_hw_id=hw_id,
                protocol="Backplane",
                label="背板 AI",
            )
        )
        slot_idx += 1

    if ao_entries:
        hw_id = "HW_AO_0"
        addrs = ", ".join(e["logical_address"] for e in ao_entries)
        nodes.append(
            GFHwNode(
                id=hw_id,
                kind="AO_MODULE",
                label=f"AQ 模拟量输出 ({addrs})",
                slot=f"Rack 0 / Slot {slot_idx}",
                protocol="Backplane",
                address_range=addrs,
                tag_count=len(ao_entries),
                tags_preview=ao_entries[:8],
            )
        )
        links.append(
            GFNetLink(
                id=f"LINK_CPU_{hw_id}",
                src_hw_id="HW_CPU",
                dst_hw_id=hw_id,
                protocol="Backplane",
                label="背板 AQ",
            )
        )
        slot_idx += 1

    # 若尚未上传 IO 表，提供默认 DI/DO 槽位以便新建工程画布直接展示物理拓扑
    if not io_entries:
        for default_id, kind, label, rng in (
            ("HW_DI_0", "DI_MODULE", "DI 16x24VDC (默认输入槽)", "%I0.0 .. %I1.7"),
            ("HW_DO_0", "DO_MODULE", "DQ 16x24VDC (默认输出槽)", "%Q0.0 .. %Q1.7"),
        ):
            nodes.append(
                GFHwNode(
                    id=default_id,
                    kind=kind,
                    label=label,
                    slot=f"Rack 0 / Slot {slot_idx}",
                    protocol="Backplane",
                    address_range=rng,
                    tag_count=0,
                )
            )
            links.append(
                GFNetLink(
                    id=f"LINK_CPU_{default_id}",
                    src_hw_id="HW_CPU",
                    dst_hw_id=default_id,
                    protocol="Backplane",
                    label="背板总线",
                )
            )
            slot_idx += 1

    db_to_hw: dict[str, str] = {}
    db_structs = list(contract.db_structs) if contract is not None else []
    for db in db_structs:
        upper_name = db.name.upper()
        if "KUKA" in upper_name or "720" in upper_name or "ROBOT" in upper_name:
            hw_id = "HW_KUKA"
            kind = "ROBOT_KUKA"
            label = f"KUKA 机器人控制器 ({db.name})"
            protocol = "Profinet"
            slot = "Profinet IO / DB720"
            net_label = "Profinet (DB720 映射)"
        elif "PC" in upper_name or "1900" in upper_name or "COMM" in upper_name:
            hw_id = "HW_PC"
            kind = "HOST_PC"
            label = f"上位机 PC ({db.name})"
            protocol = "TCP_IP"
            slot = "Ethernet / DB1900"
            net_label = "TCP/IP (DB1900 映射)"
        else:
            hw_id = f"HW_DB_{db.name}"
            kind = "HMI_PANEL"
            label = f"外部接口伙伴 ({db.name})"
            protocol = "Profinet"
            slot = f"External / {db.name}"
            net_label = f"接口映射 ({db.name})"

        db_to_hw[db.name] = hw_id
        max_off = max((m.offset for m in db.members), default=0)
        preview = [
            {
                "name": f"{db.name}.{m.name}",
                "data_type": m.data_type,
                "offset": m.offset,
                "comment": m.comment,
            }
            for m in db.members[:8]
        ]
        nodes.append(
            GFHwNode(
                id=hw_id,
                kind=kind,
                label=label,
                slot=slot,
                protocol=protocol,
                address_range=f"{db.name} (0 .. {max_off}B, StdAccess={db.optimized_access == 'FALSE'})",
                tag_count=len(db.members),
                tags_preview=preview,
            )
        )
        links.append(
            GFNetLink(
                id=f"LINK_CPU_{hw_id}",
                src_hw_id="HW_CPU",
                dst_hw_id=hw_id,
                protocol=protocol,
                label=net_label,
            )
        )

    for raw_extra in extra_nodes:
        ex_id = str(raw_extra.get("id") or "")
        if not ex_id or any(n.id == ex_id for n in nodes):
            continue
        protocol = str(raw_extra.get("protocol") or "Profinet")
        nodes.append(
            GFHwNode(
                id=ex_id,
                kind=str(raw_extra.get("kind") or "HMI_PANEL"),
                label=str(raw_extra.get("label") or ex_id),
                slot=str(raw_extra.get("slot") or "External"),
                protocol=protocol,
                address_range=str(raw_extra.get("address_range") or ""),
            )
        )
        links.append(
            GFNetLink(
                id=f"LINK_CPU_{ex_id}",
                src_hw_id="HW_CPU",
                dst_hw_id=ex_id,
                protocol=protocol,
                label=protocol,
            )
        )

    node_by_id = {n.id: n for n in nodes}
    do_hw_ids = [n.id for n in nodes if n.kind in {"DO_MODULE", "ROBOT_KUKA", "HOST_PC"}] or ["HW_CPU"]

    if ir is not None:
        for idx, cm in enumerate(ir.cms):
            target_hw = custom_mounts.get(cm.id) or str(cm.parameters.get("hw_node_id") or "")
            if not target_hw or target_hw not in node_by_id:
                label_upper = (cm.business_label + " " + cm.cm_type).upper()
                if ("KUKA" in label_upper or "机器人" in label_upper) and "HW_KUKA" in node_by_id:
                    target_hw = "HW_KUKA"
                elif ("PC" in label_upper or "上位机" in label_upper) and "HW_PC" in node_by_id:
                    target_hw = "HW_PC"
                else:
                    target_hw = do_hw_ids[idx % len(do_hw_ids)]
            if target_hw in node_by_id and cm.id not in node_by_id[target_hw].mounted_cm_ids:
                node_by_id[target_hw].mounted_cm_ids.append(cm.id)

    variable_catalog = build_variable_catalog(
        ir=ir,
        contract=contract,
        addr_to_hw=addr_to_hw,
        db_to_hw=db_to_hw,
        custom_var_bindings=custom_var_bindings,
    )

    return {
        "nodes": [n.to_dict() for n in nodes],
        "links": [l.to_dict() for l in links],
        "variable_catalog": variable_catalog,
        "custom_var_bindings": custom_var_bindings,
        # 前端可编辑性标记：哪些挂载/节点是用户手工指定的（可卸载/可移除），
        # 其余为自动推导（重置/卸载后回到默认）。
        "custom_cm_mounts": dict(custom_mounts),
        "custom_node_ids": [str(n.get("id") or "") for n in extra_nodes],
    }


def build_variable_catalog(
    *,
    ir: GreenfieldIR | None,
    contract: CompatContract | None,
    addr_to_hw: dict[str, str],
    db_to_hw: dict[str, str],
    custom_var_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建右侧变量面板所需的『外部锁定变量 + 内部生成变量』完整目录。"""
    bound_by_ref: dict[str, list[str]] = {}
    if ir is not None:
        ref_raw_map = {r.id: r.raw_ref for r in ir.compat_refs}
        for b in ir.io_bindings:
            raw_ref = ref_raw_map.get(b.compat_ref_id, b.compat_ref_id)
            if raw_ref and b.cm_id:
                bound_by_ref.setdefault(raw_ref, []).append(b.cm_id)
            if b.field_path and b.cm_id:
                bound_by_ref.setdefault(b.field_path, []).append(b.cm_id)

    for vb in custom_var_bindings:
        var_key = str(vb.get("var_key") or "")
        target_id = str(vb.get("target_id") or "")
        if var_key and target_id:
            bound_by_ref.setdefault(var_key, []).append(target_id)

    external_io: list[dict[str, Any]] = []
    if contract is not None:
        for entry in contract.io_entries:
            addr = entry.logical_address
            direction = "IN" if addr.startswith("%I") else "OUT"
            targets = sorted(set(bound_by_ref.get(addr, []) + bound_by_ref.get(entry.name, [])))
            external_io.append(
                {
                    "key": f"IO:{entry.name}",
                    "name": entry.name,
                    "logical_address": addr,
                    "data_type": entry.data_type,
                    "direction": direction,
                    "comment": entry.comment,
                    "hw_node_id": addr_to_hw.get(addr, "HW_CPU"),
                    "locked": True,
                    "bound_targets": targets,
                }
            )

    external_db: list[dict[str, Any]] = []
    if contract is not None:
        for db in contract.db_structs:
            hw_id = db_to_hw.get(db.name, "HW_CPU")
            for m in db.members:
                full_symbol = f'"{db.name}".{m.name}'
                dot_key = f"{db.name}.{m.name}"
                targets = sorted(
                    set(
                        bound_by_ref.get(full_symbol, [])
                        + bound_by_ref.get(dot_key, [])
                        + bound_by_ref.get(m.name, [])
                    )
                )
                external_db.append(
                    {
                        "key": f"DB:{dot_key}",
                        "db_name": db.name,
                        "name": m.name,
                        "full_symbol": full_symbol,
                        "data_type": m.data_type,
                        "offset": m.offset,
                        "initial_value": m.initial_value,
                        "comment": m.comment,
                        "hw_node_id": hw_id,
                        "locked": True,
                        "bound_targets": targets,
                    }
                )

    internal_vars: list[dict[str, Any]] = []
    if ir is not None:
        for cn in ir.control_nodes:
            for cmd in cn.commands:
                internal_vars.append(
                    {
                        "key": f"CN:{cn.id}.commands.{cmd}",
                        "group": "ControlNodes",
                        "owner_id": cn.id,
                        "em_id": cn.em_id,
                        "name": f"{cn.namespace_prefix}ControlNodes.commands.{cmd}",
                        "data_type": "Bool",
                        "role": "COMMAND",
                        "locked": False,
                    }
                )
            for st in cn.status:
                dtype = "DInt" if "step" in st.lower() else "Bool"
                internal_vars.append(
                    {
                        "key": f"CN:{cn.id}.status.{st}",
                        "group": "ControlNodes",
                        "owner_id": cn.id,
                        "em_id": cn.em_id,
                        "name": f"{cn.namespace_prefix}ControlNodes.status.{st}",
                        "data_type": dtype,
                        "role": "STATUS",
                        "locked": False,
                    }
                )
        for cm in ir.cms:
            for sig in ("enable", "busy", "done", "error", "errorID"):
                dtype = "Word" if sig == "errorID" else "Bool"
                internal_vars.append(
                    {
                        "key": f"CM:{cm.id}.{sig}",
                        "group": "CM_PLCOpen",
                        "owner_id": cm.id,
                        "em_id": cm.em_id,
                        "name": f"inst{cm.id}.{sig}",
                        "data_type": dtype,
                        "role": "PLCOPEN_5",
                        "locked": False,
                    }
                )

    return {
        "external_io": external_io,
        "external_db": external_db,
        "internal_vars": internal_vars,
        "counts": {
            "external_io": len(external_io),
            "external_db": len(external_db),
            "internal_vars": len(internal_vars),
        },
    }
