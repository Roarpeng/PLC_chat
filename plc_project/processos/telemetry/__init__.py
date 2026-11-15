"""FC-15/16/17 · 现场遥测与现场修改回收子包（PLAN §6.4 / §5.3）。

只读遥测（含手工降级证据）+ 在线差异采集 + 现场 TIA 修改三方比对回收。
已采集事件原件只读不覆盖；无基准时明确 UNKNOWN，不猜测。
"""
from __future__ import annotations

from processos.telemetry.fieldmods import FieldModificationService, OVERRIDE_NOTE
from processos.telemetry.routes import register_routes
from processos.telemetry.service import (
    DEFAULT_QUALITY,
    EVIDENCE_BY_SOURCE,
    SOURCES,
    TelemetryService,
)

__all__ = [
    "TelemetryService",
    "FieldModificationService",
    "register_routes",
    "SOURCES",
    "EVIDENCE_BY_SOURCE",
    "DEFAULT_QUALITY",
    "OVERRIDE_NOTE",
]
