"""FC-18 · 受控部署网关子包（PLAN §5.3：无网页一键自动上线）。

SiteDeploymentGateway 只做服务端预检落库 + 人工确认 + 真实后端门禁的
execute；默认无执行后端，现场部署保持人工流程。
"""
from __future__ import annotations

from processos.deployment.gateway import NO_ONE_CLICK_NOTE, PrecheckNotFound, SiteDeploymentGateway
from processos.deployment.routes import register_routes

__all__ = ["SiteDeploymentGateway", "PrecheckNotFound", "register_routes", "NO_ONE_CLICK_NOTE"]
