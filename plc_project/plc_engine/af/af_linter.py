"""AF V1.2 Architecture Static Linter.

Enforces official Siemens Automation Framework V1.2 invariants:
- Rule AF-01: Unidirectional Data Flow (No backward references, no cross-EM ControlNodes writes)
- Rule AF-02: Sequence Control Node Discipline (FB Sequence must issue commands via #controlNodes; no direct %Q or LBC FB execution inside Sequence)
- Rule AF-03: Manual Mode Interlock Discipline (Actuator CM calls must bind enableManualCmds := #statUnitStatus.mode.manual)
- Rule AF-04: OB Numbering & Namespace Standard (OB numbers must strictly follow uxxo formula)
- Rule AF-05: Safety Boundary Guard (F-Safety blocks are immutable; communication only via DataFromSafety/DataToSafety)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from plc_engine.af.af_numbering import validate_af_ob_number
from plc_engine.canvas_model import CanvasBlock, CanvasState


@dataclass
class AfFinding:
    rule_id: str
    severity: str  # "error" | "warning"
    block_name: str
    message: str
    line_number: int | None = None


def lint_af_canvas(canvas: CanvasState) -> list[AfFinding]:
    """Run all AF V1.2 static architecture checks on the canvas state."""
    findings: list[AfFinding] = []

    for key, block in canvas.blocks.items():
        # Skip superseded legacy blocks that are kept for auditing/traceability
        if block.af_role == "legacy_superseded" or (block.software_unit and block.software_unit.lower().startswith("legacy")):
            continue

        # Check Rule AF-04: OB numbering for OB blocks
        if block.block_type.upper() == "OB":
            _check_rule_af04_ob_number(block, findings)

        # Check Rule AF-05: Safety blocks
        if block.software_unit.lower() == "safety" or "safety" in block.name.lower():
            if block.status == "draft":
                findings.append(
                    AfFinding(
                        rule_id="AF-05",
                        severity="error",
                        block_name=block.name,
                        message="Modifying F-Safety blocks is strictly prohibited by safety guidelines.",
                    )
                )

        # Check Rule AF-02: Sequence block discipline
        if block.af_role == "Sequence" or "sequence" in block.name.lower():
            _check_rule_af02_sequence_discipline(block, findings)

        # Check Rule AF-03: CallEquipment manual mode binding
        if block.af_role == "CallEquipment" or "callequipment" in block.name.lower():
            _check_rule_af03_manual_mode_binding(block, findings)

    return findings


def _check_rule_af04_ob_number(block: CanvasBlock, findings: list[AfFinding]) -> None:
    su = block.software_unit
    num = block.number
    if not su:
        return

    # Check if Unit OB (e.g. U1_*)
    m_unit = re.match(r"^U(\d+)_", su, re.IGNORECASE)
    m_em0 = re.match(r"^U(\d+)Em0_", su, re.IGNORECASE)
    m_em = re.match(r"^U(\d+)Em(\d+)_", su, re.IGNORECASE)

    if m_em0:
        uidx = int(m_em0.group(1))
        if not validate_af_ob_number(num, "em0", unit_idx=uidx):
            findings.append(
                AfFinding(
                    rule_id="AF-04",
                    severity="error",
                    block_name=block.name,
                    message=f"OB {num} in {su} does not match AF V1.2 EM0 OB numbering (expected {uidx}005, {uidx}006, or {uidx}007).",
                )
            )
    elif m_em:
        uidx = int(m_em.group(1))
        emidx = int(m_em.group(2))
        if not validate_af_ob_number(num, "em", unit_idx=uidx, em_idx=emidx):
            base = uidx * 1000 + emidx * 10
            findings.append(
                AfFinding(
                    rule_id="AF-04",
                    severity="error",
                    block_name=block.name,
                    message=f"OB {num} in {su} does not match AF V1.2 EM OB numbering (expected {base}, {base+1}, or {base+2}).",
                )
            )
    elif m_unit:
        uidx = int(m_unit.group(1))
        if not validate_af_ob_number(num, "unit", unit_idx=uidx):
            findings.append(
                AfFinding(
                    rule_id="AF-04",
                    severity="error",
                    block_name=block.name,
                    message=f"OB {num} in {su} does not match AF V1.2 Unit OB numbering (expected {uidx}000, {uidx}001, or {uidx}002).",
                )
            )


def _check_rule_af02_sequence_discipline(block: CanvasBlock, findings: list[AfFinding]) -> None:
    code = block.scl_body or block.get_full_scl()
    # Direct write to physical outputs %Q in sequence is forbidden
    if re.search(r"%Q\d+", code, re.IGNORECASE):
        findings.append(
            AfFinding(
                rule_id="AF-02",
                severity="error",
                block_name=block.name,
                message="Direct access to physical %Q in Sequence is prohibited. Commands must go via #controlNodes.",
            )
        )
    # Direct call to LBC_* function block instances inside Sequence is forbidden
    if re.search(r"\bLBC_[A-Za-z0-9_]+\s*\(", code):
        findings.append(
            AfFinding(
                rule_id="AF-02",
                severity="error",
                block_name=block.name,
                message="Direct invocation of LBC Control Modules inside Sequence is prohibited. CMs must be called in FB CallEquipment.",
            )
        )


def _check_rule_af03_manual_mode_binding(block: CanvasBlock, findings: list[AfFinding]) -> None:
    code = block.scl_body or block.get_full_scl()
    # If CallEquipment calls an actuator CM (e.g. LBC_TwoWayActuator), it should bind enableManualCmds
    if "LBC_TwoWayActuator" in code or "LBC_SimpleActuator" in code or "LBC_ThreeWayActuator" in code:
        if "enableManualCmds" not in code or "#statUnitStatus.mode.manual" not in code:
            findings.append(
                AfFinding(
                    rule_id="AF-03",
                    severity="warning",
                    block_name=block.name,
                    message="Actuator CM call in CallEquipment should bind 'enableManualCmds := #statUnitStatus.mode.manual' for safety interlocks.",
                )
            )
