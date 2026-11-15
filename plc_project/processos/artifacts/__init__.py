"""FC-11/§12 · PR 工件组装（design change → handover snapshot）。

从当前项目状态真组装 PLAN §12 要求的 9 类 PR 工件；取不到的字段显式
标 ``UNKNOWN``，mock 证据如实标注，绝不伪装成真实编译。
"""
from __future__ import annotations

from .service import BUNDLE_FILE_NAMES, PrBundleService, register_routes

__all__ = ["PrBundleService", "BUNDLE_FILE_NAMES", "register_routes"]
