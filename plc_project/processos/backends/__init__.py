"""Compiler backends: Process Contract IR -> framework-specific project IR."""
from __future__ import annotations

from .siemens_af import SiemensAfBackend, lower

__all__ = ["SiemensAfBackend", "lower"]