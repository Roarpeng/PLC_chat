"""AF V1.2 OB Numbering Allocator & Namespace Manager.

Strictly adheres to Siemens Automation Framework V1.2 Specification
(Entry ID 109817223, 2024/10, Chapter 6, Section 6.4.3, Tables 6-2 & 6-3, pp. 50-51).

Formula: OB Number = uxxo (4 digits)
  u  = Unit index (1..9)
  xx = EM index (00..99)
  o  = OB Type offset:
       - For Unit (xx=00):
           0 = Startup (u000, e.g. 1000)
           1 = Main    (u001, e.g. 1001)
           2 = ProDiag (u002, e.g. 1002)
       - For EM0 General (xx=00):
           5 = Startup (u005, e.g. 1005)
           6 = Main    (u006, e.g. 1006)
           7 = ProDiag (u007, e.g. 1007)
       - For EM m (xx=01..99):
           0 = Startup (uxx0, e.g. 1010 for EM1, 1020 for EM2)
           1 = Main    (uxx1, e.g. 1011 for EM1, 1021 for EM2)
           2 = ProDiag (uxx2, e.g. 1012 for EM1, 1022 for EM2)

System Level OBs:
  CentralFunctions: Startup=100, Main=1, ProDiag=250
  Safety:           ProDiag=251
  Global:           ProDiag=252
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SYSTEM_OBS: dict[str, dict[str, int]] = {
    "CentralFunctions": {"Startup": 100, "Main": 1, "ProDiag": 250},
    "Safety": {"ProDiag": 251},
    "Global": {"ProDiag": 252},
}


@dataclass(frozen=True)
class AfObNumbers:
    startup: int
    main: int
    prodiag: int


def get_unit_ob_numbers(unit_idx: int) -> AfObNumbers:
    """Calculate OB numbers for a Unit Software Unit (e.g. U1_Unit1)."""
    if not (1 <= unit_idx <= 9):
        raise ValueError(f"unit_idx must be between 1 and 9 in AF V1.2, got {unit_idx}")
    base = unit_idx * 1000
    return AfObNumbers(
        startup=base + 0,  # u000
        main=base + 1,     # u001
        prodiag=base + 2,  # u002
    )


def get_em0_ob_numbers(unit_idx: int) -> AfObNumbers:
    """Calculate OB numbers for EM0 General Software Unit (e.g. U1Em0_General)."""
    if not (1 <= unit_idx <= 9):
        raise ValueError(f"unit_idx must be between 1 and 9 in AF V1.2, got {unit_idx}")
    base = unit_idx * 1000
    return AfObNumbers(
        startup=base + 5,  # u005
        main=base + 6,     # u006
        prodiag=base + 7,  # u007
    )


def get_em_ob_numbers(unit_idx: int, em_idx: int) -> AfObNumbers:
    """Calculate OB numbers for an Equipment Module (EM 1..99)."""
    if not (1 <= unit_idx <= 9):
        raise ValueError(f"unit_idx must be between 1 and 9 in AF V1.2, got {unit_idx}")
    if em_idx == 0:
        return get_em0_ob_numbers(unit_idx)
    if not (1 <= em_idx <= 99):
        raise ValueError(f"em_idx must be between 1 and 99, got {em_idx}")
    base = unit_idx * 1000 + em_idx * 10
    return AfObNumbers(
        startup=base + 0,  # uxx0
        main=base + 1,     # uxx1
        prodiag=base + 2,  # uxx2
    )


def validate_af_ob_number(
    number: int,
    layer: Literal["system", "unit", "em0", "em"],
    unit_idx: int = 1,
    em_idx: int = 0,
) -> bool:
    """Verify whether an OB number matches the AF V1.2 standard for its target."""
    if layer == "unit":
        expected = get_unit_ob_numbers(unit_idx)
        return number in (expected.startup, expected.main, expected.prodiag)
    elif layer == "em0":
        expected = get_em0_ob_numbers(unit_idx)
        return number in (expected.startup, expected.main, expected.prodiag)
    elif layer == "em":
        expected = get_em_ob_numbers(unit_idx, em_idx)
        return number in (expected.startup, expected.main, expected.prodiag)
    elif layer == "system":
        return any(number in obs.values() for obs in SYSTEM_OBS.values())
    return False
