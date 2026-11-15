"""PLAN §5.2 · 自动修复边界 (repair proposal boundary)."""
from processos.repair.service import (
    ALLOWED_CATEGORIES,
    FORBIDDEN_CATEGORIES,
    RepairBoundaryService,
    register_routes,
)

__all__ = [
    "ALLOWED_CATEGORIES",
    "FORBIDDEN_CATEGORIES",
    "RepairBoundaryService",
    "register_routes",
]
