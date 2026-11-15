"""Import Agent (L) — TIA 块导出解析、保真度分级与工位/执行器认领映射。

Routes live in ``processos.api.import_routes`` (mounted by the main agent);
this package owns the parsing/claim/baseline-check service itself.
"""
from __future__ import annotations

from .service import FIDELITIES, ImportParseService, ParseError

__all__ = ["FIDELITIES", "ImportParseService", "ParseError"]
