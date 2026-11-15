"""Typed fail-closed error codes (PLAN §11 必须阻断的错误与安全边界).

Every code here MUST block the corresponding high-risk delivery path; nothing
may silently downgrade a SafetyError into a warning. The API layer maps
SafetyError to a JSON error response carrying the machine-readable ``code``
so the Web workbench can render the exact blocked reason.
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# PLAN §11 —— 10 个必须阻断的错误码（名称不可改动，测试与前端按此匹配）。
ERROR_CODES: tuple[str, ...] = (
    "DRIFT_DETECTED",          # 在线实际程序与批准工程不一致，冻结变更
    "UNMAPPED_NATIVE_CODE",    # 某逻辑无法映射至工艺 IR；不得自动覆盖
    "AF_PROFILE_MISMATCH",     # 标准库接口/版本不符合锁定 Profile
    "BEHAVIOR_REGRESSION",     # 动作、互锁、模式、恢复逻辑回归失败
    "UNKNOWN_PLC_STATE",       # 现场状态未知；禁止自动宣称可安全下载
    "UNAPPROVED_NATIVE_EDIT",  # 未经审核直接修改源码
    "SAFETY_SCOPE_BLOCKED",    # F/Safety、保护块或安全相关范围需要独立流程
    "RETAIN_DATA_RISK",        # DB 布局、重新初始化或保持值风险，阻断自动上线
    "BUILD_ARTIFACT_MISMATCH", # 工件 ID、校验和与审核记录不一致
    "REOPEN_FAILED",           # 原生工程归档后重新打开失败，不能发布
)


class SafetyError(ValueError):
    """A condition that MUST block delivery (fail-closed, never a warning).

    ``code`` is one of ERROR_CODES; ``http_status`` defaults to 422 and may be
    overridden at the raise site when 409 (state conflict) / 403 (permission)
    / 424 (missing field verification) is semantically closer.
    """

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None,
                 http_status: int = 422) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown safety error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


def register_safety_exception_handler(app: Any) -> None:
    """Wire SafetyError -> JSON {error, code, details} on a FastAPI app."""
    @app.exception_handler(SafetyError)
    async def _safety(_: Request, exc: SafetyError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.message, "code": exc.code, "details": exc.details},
        )
