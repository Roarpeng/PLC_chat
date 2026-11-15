"""Siemens AF target semantics — roles, ports and the six structural rules.

The process contract is framework-neutral; once a Siemens AF target is chosen,
every deliverable block must satisfy these rules (blueprint §4). AF is a forced
*target*, not the user's interaction language.
"""
from __future__ import annotations

from dataclasses import dataclass

AF_ROLES = ("unit", "em_sequence", "cm_driver", "instance_db", "main")

#: The six non-bypassable structural rules (blueprint §4.2).
STRUCTURAL_RULES = (
    "UNIT_MANAGES_MODE_STATE",
    "SEQUENCE_VIA_CONTROLNODES_NOT_DIRECT_IO",
    "LOCKED_TEMPLATE_CALL_ORDER",
    "SINGLE_WRITER_ARBITRATION",
    "INSTANCE_DB_FROM_TEMPLATE",
    "VERSION_LOCKED_TOGETHER",
)


@dataclass(frozen=True)
class AfPortContract:
    """Standard CM command/feedback/status interface (from a verified template)."""

    commands: tuple[str, ...]
    feedback: tuple[str, ...]
    status: tuple[str, ...] = ("Busy", "Done", "Error")


def cm_port_contract(commands, feedback) -> AfPortContract:
    return AfPortContract(commands=tuple(commands), feedback=tuple(feedback))


def sequence_block_name(em_id: str) -> str:
    return f"FB_{em_id}_SEQ"


def driver_block_name(cm_id: str) -> str:
    return f"FB_{cm_id}_DRV"


def unit_block_name(unit_id: str) -> str:
    return f"FB_{unit_id}_UNIT"


def instance_db_name(block: str) -> str:
    return f"i{block}"


def assert_no_direct_io(action_target: str) -> None:
    """Sequence actions must target a CM command, never a physical %Q/%I."""
    if action_target.startswith("%") or "." in action_target and action_target[0] in "QI":
        raise ValueError(f"direct physical I/O write forbidden from sequence: {action_target}")