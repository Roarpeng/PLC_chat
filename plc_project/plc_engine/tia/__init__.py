"""[已弃用 / 兼容占位包] 本包不含任何解析实现，仅为历史导入路径保留兼容重导出。

权威实现：``agents/plc/tia``（SimaticML 解析、PLC-IR、SCL 转换、知识图谱、Review 规则）。
新功能禁止添加在本包；新代码请直接依赖 ``agents.plc.tia``。

TIA Portal / Offline Analyzer bridge for the PLC Agent.

Pipeline (docs/agents/PLC Offline Analyzer Architecture.md):

    .apxx | export dir -> importer -> SimaticML -> PLC-IR -> KG + SCL + report package
"""

from agents.plc.tia.flgnet_fold import attach_folded, fold_project
from agents.plc.tia.pipeline import (
    analyze_plc_project,
    analyze_tia_exports,
    interpretation_report,
)

__all__ = [
    "analyze_plc_project",
    "analyze_tia_exports",
    "attach_folded",
    "fold_project",
    "interpretation_report",
]
