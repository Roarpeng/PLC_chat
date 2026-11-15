"""Device catalog + TIA-style hardware configuration -> typed Process Contract.

CM (Control Module) is the software abstraction of a field device. A CM is NOT
always a cylinder: the catalog offers selectable, configurable device types
(cylinder / servo / grippers / motor / sensor / valve island), each with its own
command/feedback ports, parameters, I/O needs and driver sequence. The new-project
wizard collects a TIA-style hardware topology (CPU / rack / IO modules / IO
expansion / field devices / network) and this module lowers it to a contract.
"""
from __future__ import annotations

from typing import Any

DEVICE_TYPES: dict[str, dict[str, Any]] = {
    "cylinder": {
        "label": "气缸", "commands": ["Extend", "Retract"], "feedback": ["Extended", "Retracted"],
        "params": [{"key": "timeout_ms", "label": "动作超时", "default": 3000, "unit": "ms"},
                   {"key": "hold_ms", "label": "保持时间", "default": 2000, "unit": "ms"}],
        "io": {"DI": 2, "DQ": 2, "AI": 0, "AQ": 0}, "conflict": ["Extended", "Retracted"],
    },
    "servo": {
        "label": "伺服轴", "commands": ["Enable", "MoveAbs", "Home"], "feedback": ["Enabled", "InPosition"],
        "params": [{"key": "velocity", "label": "速度", "default": 100, "unit": "mm/s"},
                   {"key": "accel", "label": "加速度", "default": 500, "unit": "mm/s²"},
                   {"key": "target", "label": "目标位置", "default": 0, "unit": "mm"},
                   {"key": "timeout_ms", "label": "定位超时", "default": 5000, "unit": "ms"}],
        "io": {"DI": 0, "DQ": 0, "AI": 0, "AQ": 0}, "conflict": None, "bus": "PROFIdrive",
    },
    "electric_gripper": {
        "label": "电动夹爪", "commands": ["Grip", "Release"], "feedback": ["Gripped", "Released", "PartPresent"],
        "params": [{"key": "force", "label": "夹持力", "default": 50, "unit": "N"},
                   {"key": "stroke", "label": "行程", "default": 40, "unit": "mm"},
                   {"key": "timeout_ms", "label": "动作超时", "default": 2000, "unit": "ms"}],
        "io": {"DI": 3, "DQ": 2, "AI": 1, "AQ": 0}, "conflict": ["Gripped", "Released"],
    },
    "pneumatic_gripper": {
        "label": "气动夹爪", "commands": ["Grip", "Release"], "feedback": ["Gripped", "Open"],
        "params": [{"key": "timeout_ms", "label": "动作超时", "default": 1500, "unit": "ms"}],
        "io": {"DI": 2, "DQ": 1, "AI": 0, "AQ": 0}, "conflict": ["Gripped", "Open"],
    },
    "motor": {
        "label": "电机", "commands": ["Run", "Stop"], "feedback": ["Running", "AtSpeed"],
        "params": [{"key": "speed", "label": "转速", "default": 1500, "unit": "rpm"},
                   {"key": "run_ms", "label": "运行时间", "default": 3000, "unit": "ms"},
                   {"key": "timeout_ms", "label": "启动超时", "default": 2000, "unit": "ms"}],
        "io": {"DI": 2, "DQ": 1, "AI": 1, "AQ": 0}, "conflict": None,
    },
    "sensor": {
        "label": "传感器", "commands": [], "feedback": ["Detected"],
        "params": [{"key": "threshold", "label": "阈值", "default": 1, "unit": ""},
                   {"key": "timeout_ms", "label": "检测超时", "default": 5000, "unit": "ms"}],
        "io": {"DI": 1, "DQ": 0, "AI": 0, "AQ": 0}, "conflict": None,
    },
    "valve_island": {
        "label": "阀岛", "commands": ["Open", "Close"], "feedback": ["Opened", "Closed"],
        "params": [{"key": "timeout_ms", "label": "动作超时", "default": 1000, "unit": "ms"}],
        "io": {"DI": 2, "DQ": 2, "AI": 0, "AQ": 0}, "conflict": ["Opened", "Closed"],
    },
}

CPU_CATALOG = [
    {"series": "S7-1500", "order_no": "6ES7511-1AK02-0AB0", "firmware": "V2.9", "label": "CPU 1511-1 PN"},
    {"series": "S7-1500", "order_no": "6ES7516-3AN02-0AB0", "firmware": "V2.9", "label": "CPU 1516-3 PN/DP"},
    {"series": "S7-1200", "order_no": "6ES7214-1AG40-0XB0", "firmware": "V4.5", "label": "CPU 1214C DC/DC/DC"},
    {"series": "ET200SP", "order_no": "6ES7155-6AU01-0BN0", "firmware": "V4.2", "label": "IM 155-6 PN ST"},
]

IO_MODULES = [
    {"type": "DI", "points": 8, "order_no": "6ES7221-1BH32-0XB0", "label": "DI 8×24VDC"},
    {"type": "DQ", "points": 8, "order_no": "6ES7222-1BH32-0XB0", "label": "DQ 8×24VDC"},
    {"type": "AI", "points": 4, "order_no": "6ES7231-4HD32-0XB0", "label": "AI 4×13bit"},
    {"type": "AQ", "points": 2, "order_no": "6ES7232-4HB32-0XB0", "label": "AQ 2×14bit"},
]


def _step(id: str, name: str, **kw: Any) -> dict[str, Any]:
    base = {"id": id, "name": name, "entry": [], "cyclic": [], "exit": [], "guard": "",
            "duration_ms": 0, "timeout_ms": 0, "next": "", "failure_target": "", "is_fault": False, "reset_guard": ""}
    base.update(kw)
    return base


def _act(cmd: str, val: bool = True) -> dict[str, Any]:
    return {"command": cmd, "value": val}


def _sequence(kind: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    """Each command is pulsed within ONE step (entry set, exit clear) so the
    single-writer invariant holds; the device mechanically latches between steps."""
    to = int(p.get("timeout_ms", 3000))
    hold = int(p.get("hold_ms", p.get("run_ms", 2000)))
    if kind == "servo":
        return [
            _step("S_WAIT", "等待启动", guard="Start AND SafetyPermit", next="S_ENABLE"),
            _step("S_ENABLE", "使能", entry=[_act("Enable")], exit=[_act("Enable", False)], guard="Enabled", timeout_ms=to, failure_target="S_FAULT", next="S_MOVE"),
            _step("S_MOVE", "定位", entry=[_act("MoveAbs")], exit=[_act("MoveAbs", False)], guard="InPosition", timeout_ms=to, failure_target="S_FAULT", next="S_DONE"),
            _step("S_DONE", "完成", next="S_WAIT"),
            _step("S_FAULT", "故障保持", is_fault=True, reset_guard="Reset AND InPosition", next="S_WAIT"),
        ]
    if kind in ("electric_gripper", "pneumatic_gripper"):
        rel_fb = "Released" if kind == "electric_gripper" else "Open"
        return [
            _step("S_WAIT", "等待启动", guard="Start AND SafetyPermit", next="S_GRIP"),
            _step("S_GRIP", "夹紧", entry=[_act("Grip")], exit=[_act("Grip", False)], guard="Gripped", timeout_ms=to, failure_target="S_FAULT", next="S_HOLD"),
            _step("S_HOLD", "保持", duration_ms=hold, next="S_RELEASE"),
            _step("S_RELEASE", "松开", entry=[_act("Release")], exit=[_act("Release", False)], guard=rel_fb, timeout_ms=to, failure_target="S_FAULT", next="S_DONE"),
            _step("S_DONE", "完成", next="S_WAIT"),
            _step("S_FAULT", "故障保持", is_fault=True, reset_guard=f"Reset AND {rel_fb}", next="S_WAIT"),
        ]
    if kind == "motor":
        return [
            _step("S_WAIT", "等待启动", guard="Start AND SafetyPermit", next="S_RUN"),
            _step("S_RUN", "启动", entry=[_act("Run")], exit=[_act("Run", False)], guard="Running", timeout_ms=to, failure_target="S_FAULT", next="S_HOLD"),
            _step("S_HOLD", "运行", duration_ms=hold, next="S_STOP"),
            _step("S_STOP", "停止", entry=[_act("Stop")], exit=[_act("Stop", False)], guard="NOT Running", timeout_ms=to, failure_target="S_FAULT", next="S_DONE"),
            _step("S_DONE", "完成", next="S_WAIT"),
            _step("S_FAULT", "故障保持", is_fault=True, reset_guard="Reset AND NOT Running", next="S_WAIT"),
        ]
    if kind == "sensor":
        return [
            _step("S_WAIT", "等待启动", guard="Start AND SafetyPermit", next="S_DETECT"),
            _step("S_DETECT", "检测", guard="Detected", timeout_ms=to, failure_target="S_FAULT", next="S_DONE"),
            _step("S_DONE", "完成", next="S_WAIT"),
            _step("S_FAULT", "故障保持", is_fault=True, reset_guard="Reset AND NOT Detected", next="S_WAIT"),
        ]
    if kind == "valve_island":
        return [
            _step("S_WAIT", "等待启动", guard="Start AND SafetyPermit", next="S_OPEN"),
            _step("S_OPEN", "打开", entry=[_act("Open")], exit=[_act("Open", False)], guard="Opened", timeout_ms=to, failure_target="S_FAULT", next="S_HOLD"),
            _step("S_HOLD", "保持", duration_ms=hold, next="S_CLOSE"),
            _step("S_CLOSE", "关闭", entry=[_act("Close")], exit=[_act("Close", False)], guard="Closed", timeout_ms=to, failure_target="S_FAULT", next="S_DONE"),
            _step("S_DONE", "完成", next="S_WAIT"),
            _step("S_FAULT", "故障保持", is_fault=True, reset_guard="Reset AND Closed", next="S_WAIT"),
        ]
    return [
        _step("S_WAIT", "等待启动", guard="Start AND SafetyPermit", next="S_EXTEND"),
        _step("S_EXTEND", "伸出", entry=[_act("Extend")], exit=[_act("Extend", False)], guard="Extended", timeout_ms=to, failure_target="S_FAULT", next="S_HOLD"),
        _step("S_HOLD", "保持", duration_ms=hold, next="S_RETRACT"),
        _step("S_RETRACT", "缩回", entry=[_act("Retract")], exit=[_act("Retract", False)], guard="Retracted", timeout_ms=to, failure_target="S_FAULT", next="S_DONE"),
        _step("S_DONE", "完成", next="S_WAIT"),
        _step("S_FAULT", "故障保持", is_fault=True, reset_guard="Reset AND Retracted AND NOT Extended", next="S_WAIT"),
    ]


def _fb_event(guard: str) -> tuple[str, bool]:
    """Feedback (signal, value) needed to satisfy a step guard."""
    if guard.startswith("NOT "):
        return guard[4:].strip(), False
    return guard.strip(), True


def _scenarios(kind: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Device-appropriate scenarios compatible with the scan-cycle runner."""
    act = [s for s in steps if s.get("guard") and not s["is_fault"] and s["id"] != "S_WAIT"]
    hold = next((s["duration_ms"] for s in steps if s["id"] == "S_HOLD"), 0)
    t2 = 500 + hold + 600
    conflict = DEVICE_TYPES[kind].get("conflict")

    def ev(t: int, sig: str, val: bool) -> dict[str, Any]:
        return {"t_ms": t, "signal": sig, "value": val}

    first_sig, first_val = _fb_event(act[0]["guard"]) if act else ("Detected", True)
    normal = [ev(0, "Start", True), ev(100, "Start", False), ev(500, first_sig, first_val)]
    if len(act) > 1:
        sec_sig, sec_val = _fb_event(act[1]["guard"])
        normal.append(ev(t2, sec_sig, sec_val))
        if first_val and sec_sig != first_sig:
            normal.append(ev(t2, first_sig, False))

    to = act[0]["timeout_ms"] if act else 3000
    reset_events: list[dict[str, Any]] = []
    for term in steps[-1]["reset_guard"].split("AND"):
        term = term.strip()
        if term in ("Reset", ""):
            continue
        sig, val = _fb_event(term)
        reset_events.append(ev(to + 900, sig, val))

    sc = [
        {"id": "normal_cycle", "name": "正常循环", "kind": "normal", "description": "反馈依序到位",
         "inputs": normal, "expect": {"completed": True, "fault": False}},
        {"id": "extend_timeout", "name": "动作超时", "kind": "fault", "description": "无反馈触发超时",
         "inputs": [ev(0, "Start", True), ev(100, "Start", False)], "expect": {"fault": True, "fault_reason": "TIMEOUT"}},
        {"id": "permit_loss", "name": "许可丢失", "kind": "fault", "description": "动作中许可撤销",
         "inputs": [ev(0, "Start", True), ev(100, "Start", False), ev(300, "SafetyPermit", False)],
         "expect": {"fault": True, "fault_reason": "PERMIT_LOST"}},
        {"id": "fault_reset", "name": "故障复位", "kind": "normal", "description": "超时后安全复位",
         "inputs": [ev(0, "Start", True), ev(100, "Start", False)] + reset_events + [ev(to + 1000, "Reset", True), ev(to + 1100, "Reset", False)],
         "expect": {"reset_ok": True}},
    ]
    if conflict:
        sc.append({"id": "conflicting_feedback", "name": "矛盾反馈", "kind": "fault", "description": "互斥反馈同时有效",
                   "inputs": [ev(0, "Start", True), ev(100, "Start", False), ev(600, conflict[0], True), ev(600, conflict[1], True)],
                   "expect": {"fault": True, "fault_reason": "FEEDBACK_FAULT"}})
    return sc


def build_contract_from_hardware(config: dict[str, Any]) -> dict[str, Any]:
    """Lower a TIA-style hardware topology into a typed Process Contract."""
    devices = config.get("devices") or [{"type": "cylinder", "name": "夹紧气缸", "params": {}}]
    resources = []
    operations = []
    invariants = []
    for i, dev in enumerate(devices):
        kind = dev.get("type", "cylinder")
        spec = DEVICE_TYPES.get(kind, DEVICE_TYPES["cylinder"])
        rid = dev.get("id") or f"CM_{i + 1:02d}"
        params = {p["key"]: p["default"] for p in spec["params"]}
        params.update(dev.get("params") or {})
        resources.append({
            "id": rid, "name": dev.get("name") or spec["label"], "kind": kind,
            "commands": list(spec["commands"]), "feedback": list(spec["feedback"]),
            "status": ["Busy", "Done", "Error"], "exclusive": True,
            "io_bindings": {fb: "unbound" for fb in spec["feedback"]}, "params": params,
        })
        steps = _sequence(kind, params)
        for s in steps:
            for a in s["entry"] + s["exit"]:
                a["target"] = rid
        em = dev.get("em") or f"EM_{i + 1:02d}"
        operations.append({
            "id": f"OP_{em}", "name": dev.get("name") or spec["label"], "unit": config.get("unit", "U_ASSEMBLY"),
            "em": em, "resource_ids": [rid], "preconditions": ["unit.auto_permit", "air.ok", "guard.closed"],
            "steps": steps, "acceptance": ["normal_cycle", "extend_timeout", "fault_reset"],
        })
        if spec.get("conflict"):
            c = spec["conflict"]
            invariants.append({"id": f"INV_{rid}", "expr": f"NOT ({c[0]} AND {c[1]})", "scope": rid, "severity": "error"})

    primary_kind = devices[0].get("type", "cylinder")
    scenarios = _scenarios(primary_kind, operations[0]["steps"])
    return {
        "id": config.get("id", "PRJ_HW"), "name": config.get("name", "新建项目") + "工艺契约",
        "target_framework": "siemens-af-basic@unverified", "unit": config.get("unit", "U_ASSEMBLY"),
        "schema": "process-contract/1.0", "resources": resources, "operations": operations,
        "invariants": invariants,
        "open_questions": [{"id": "Q_SAFETY_STOP", "question": "全局安全许可撤销时设备应保持还是退回？须现场工程决策。",
                            "affects": [operations[0]["id"]], "severity": "blocking", "resolution": None, "resolved_by": None}],
        "scenarios": scenarios,
        "provenance": {"origin": "hardware-config", "confirmed_by": None,
                       "evidence_refs": [f"CPU:{config.get('cpu', {}).get('order_no', '')}"]},
        "hardware": {"cpu": config.get("cpu"), "io_modules": config.get("io_modules", []),
                     "expansion": config.get("expansion", []), "network": config.get("network", {})},
    }


def catalog_payload() -> dict[str, Any]:
    return {"device_types": DEVICE_TYPES, "cpus": CPU_CATALOG, "io_modules": IO_MODULES}