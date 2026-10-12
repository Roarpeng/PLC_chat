"""Canonical Siemens LAD/FBD Part names used by fold / SCL / KG."""

from __future__ import annotations

from agents.plc.tia.ir import Part

# Openness exports mix IEC names (CTU) and LAD box names (CtU).
PART_ALIASES: dict[str, str] = {
    "CtU": "CTU",
    "CtD": "CTD",
    "CtUD": "CTUD",
    "CTU": "CTU",
    "CTD": "CTD",
    "CTUD": "CTUD",
    "SetCoil": "Set",
    "ResetCoil": "Reset",
    "SCoil": "Set",
    "RCoil": "Reset",
    "Set": "Set",
    "Reset": "Reset",
    "TONR": "TONR",
    "TON_R": "TONR",
    "Conv": "Convert",
    "Convert": "Convert",
    "Round": "Round",
    "Mux": "Mux",
    "Demux": "Demux",
    "JumpUnconditional": "Jump",
    "Jump": "Jump",
    "Label": "Label",
    "Ret": "Return",
    "Return": "Return",
    "SR": "SR",
    "RS": "RS",
}

COMPARE_OPS = {
    "Eq": "=",
    "Ne": "<>",
    "Gt": ">",
    "Ge": ">=",
    "Lt": "<",
    "Le": "<=",
}

CONTACT_PARTS = {"Contact", "NegContact", "NotContact", "ContactNeg"}
COIL_PARTS = {"Coil", "NegCoil", "Set", "Reset", "Save"}
MOVE_PARTS = {"Move", "Assign", "Move_Bool", "Move_Word", "Move_DWord", "Move_Real"}
COUNTER_PARTS = {"CTU", "CTD", "CTUD"}
TIMER_PARTS = {"TON", "TOF", "TP", "TONR"}
# LAD coil-form timers: <Part Name="CoilTON"> with operand=instance DB, value=PT.
COIL_TIMER_KINDS = {"CoilTON": "TON", "CoilTOF": "TOF", "CoilTP": "TP"}
EDGE_TRIG_PARTS = {"R_TRIG", "F_TRIG", "P_TRIG"}
LATCH_PARTS = {"SR", "RS"}
CONVERT_PARTS = {"Convert", "Round"}
MUX_PARTS = {"Mux", "Demux"}
JUMP_PARTS = {"Jump", "Label", "Return"}
CALL_PARTS = {"Call", "CallPart"}
BOX_PARTS = COUNTER_PARTS | TIMER_PARTS | EDGE_TRIG_PARTS | LATCH_PARTS
BRANCH_PARTS = CONTACT_PARTS | set(COMPARE_OPS)
# FBD boolean gates (Siemens instruction names) and inline RLO negation wedge.
GATE_AND_PARTS = {"&"}
GATE_OR_PARTS = {"O"}
RLO_NOT_PARTS = {"Not"}
# Edge contacts: ---|P|--- / ---|N|--- (operand = edge memory bit).
EDGE_CONTACT_PARTS = {"PBox": "P", "NBox": "N"}
# Math / system-function boxes that fold into value assignments.
MATH_BINARY_OPS = {
    "Add": "+",
    "Sub": "-",
    "Mul": "*",
    "Div": "/",
    "Mod": "MOD",
    "Pow": "**",
    "Expt": "**",
    "Min": "MIN",
    "Max": "MAX",
    "AndWord": "AND",
    "OrWord": "OR",
    "XorWord": "XOR",
}
MATH_UNARY_FUNCS = {
    "Sin": "SIN",
    "Cos": "COS",
    "Tan": "TAN",
    "Asin": "ASIN",
    "Acos": "ACOS",
    "Atan": "ATAN",
    "Sqrt": "SQRT",
    "Sqr": "SQR",
    "Ln": "LN",
    "Log": "LOG",
    "Exp": "EXP",
    "Abs": "ABS",
    "Neg": "-",
    "Ceil": "CEIL",
    "Floor": "FLOOR",
    "Trunc": "TRUNC",
    "Swap": "SWAP",
}
CALC_PARTS = {"Calc"}
SYS_TIME_PARTS = {"RD_SYS_T", "RD_LOC_T", "WR_SYS_T", "WR_LOC_T"}
TIME_CONV_PARTS = {"T_CONV"}


def canon_part(name: str) -> str:
    key = (name or "").strip()
    if not key:
        return ""
    if key in PART_ALIASES:
        return PART_ALIASES[key]
    return PART_ALIASES.get(key.upper(), key)


def format_todo(part: Part) -> str:
    """Structured leftover: never silent-drop; always name the Siemens Part."""
    pins: list[str] = []
    for pin, acc in (part.accesses or {}).items():
        pins.append(f"{pin}={acc.as_scl()}")
    templates = [f"{k}={v}" for k, v in (part.template_values or {}).items() if not str(k).startswith("__")]
    pin_txt = ",".join(pins) if pins else "-"
    tpl_txt = ",".join(templates) if templates else "-"
    return (
        f"(* TODO[{part.name or 'unknown'}] uid={part.uuid or '-'} "
        f"pins={{{pin_txt}}} templates={{{tpl_txt}}} *)"
    )
