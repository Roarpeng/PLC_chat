"""TIA Portal / Offline Analyzer bridge for the PLC Agent.

Pipeline (docs/agents/PLC Offline Analyzer Architecture.md):

    .apxx | export dir -> importer -> SimaticML -> PLC-IR -> KG + SCL + report package
"""

from agents.plc.tia.pipeline import (
    analyze_plc_project,
    analyze_tia_exports,
    interpretation_report,
)
from agents.plc.tia.flgnet_fold import attach_folded, fold_project

__all__ = [
    "analyze_plc_project",
    "analyze_tia_exports",
    "interpretation_report",
    "attach_folded",
    "fold_project",
]
