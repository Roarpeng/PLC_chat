"""PLAN §5.2 · 自动修复边界：允许提议什么、禁止自动什么 (RepairBoundaryService).

**允许自动提议**（确定性编译问题，且只能作为**候选变更**回流审查/验证链路）：
块/实例 DB 名称冲突、缺少显式调用、库接口不匹配、类型不一致、合法 XML。

**禁止自动**（PLAN §5.2 原文七类）：删除互锁、绕过安全许可、把超时改大以消除
故障、改变动作优先级、忽略故障位、静默重置 DB、修改 F-Safety 逻辑。编译失败时
不得只屏蔽报错而宣称修好。

Fail-closed：类别表**精确匹配**，未知类别默认 FORBIDDEN（``"unknown fix category"``）；
诊断文本只在保守白名单内映射，其余只登记（forbidden_seen）不提议。
``propose()`` 的 ``auto_applied`` **恒为空** —— 本服务没有自动应用修复的代码路径，
一切候选修复必须经人工审查与既有验证链路（§5.2）。

Persistence：``db`` 给定时把每次 propose 快照写入 namespace ``"repair_proposals"``
（短命连接 + RLock）；``db=None`` 纯内存（no-db 应用不触碰默认 SQLite 路径）。
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import uuid
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request

from processos.rbac import Actor, require_role
from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "repair_proposals"

#: 允许自动「提议」的确定性编译问题类别（精确匹配；仍需人工审查）。
ALLOWED_CATEGORIES: tuple[str, ...] = (
    "BLOCK_NAME_CONFLICT",
    "MISSING_EXPLICIT_CALL",
    "LIBRARY_INTERFACE_MISMATCH",
    "TYPE_INCONSISTENT",
    "INVALID_XML",
)

#: 禁止自动修复的类别（PLAN §5.2 原文七类；精确匹配）。
FORBIDDEN_CATEGORIES: tuple[str, ...] = (
    "DELETE_INTERLOCK",
    "BYPASS_SAFETY_PERMIT",
    "INCREASE_TIMEOUT_TO_CLEAR_FAULT",
    "CHANGE_ACTION_PRIORITY",
    "IGNORE_FAULT_BITS",
    "SILENT_DB_RESET",
    "MODIFY_F_SAFETY",
)

_UNKNOWN_CATEGORY_REASON = "unknown fix category"

_FORBIDDEN_REASONS: dict[str, str] = {
    "DELETE_INTERLOCK": "禁止自动删除互锁（PLAN §5.2）",
    "BYPASS_SAFETY_PERMIT": "禁止自动绕过安全许可（PLAN §5.2）",
    "INCREASE_TIMEOUT_TO_CLEAR_FAULT":
        "禁止把超时改大来消除故障：超时是运行行为变化，必须先查明工艺依据并走审核（PLAN §5.2/§10）",
    "CHANGE_ACTION_PRIORITY": "禁止自动改变动作优先级（PLAN §5.2）",
    "IGNORE_FAULT_BITS": "禁止忽略/屏蔽故障位（PLAN §5.2）",
    "SILENT_DB_RESET": "禁止静默重置 DB（PLAN §5.2）",
    "MODIFY_F_SAFETY": "禁止修改 F-Safety 逻辑（PLAN §5.2/§11 SAFETY_SCOPE_BLOCKED）",
}

_ALLOWED_REASONS: dict[str, str] = {
    c: "确定性编译问题，可作为候选变更回流审查（PLAN §5.2）" for c in ALLOWED_CATEGORIES
}

#: 候选修复动作提示（只描述方向，绝不代表已执行）。
_ACTION_HINTS: dict[str, str] = {
    "BLOCK_NAME_CONFLICT": "重命名冲突块/实例 DB 并更新全部引用（候选变更，需人工审查）",
    "MISSING_EXPLICIT_CALL": "补上缺失的显式块调用并纳入调用顺序（候选变更，需人工审查）",
    "LIBRARY_INTERFACE_MISMATCH": "对齐锁定的库接口/版本参数（候选变更，需人工审查）",
    "TYPE_INCONSISTENT": "修正类型不一致的变量/接口声明（候选变更，需人工审查）",
    "INVALID_XML": "修正非法 XML 生成为合法结构（候选变更，需人工审查）",
}

#: 诊断文本 → 类别的保守白名单（子串匹配，小写比较；其余不映射）。
_DIAGNOSTIC_MAP: tuple[tuple[str, str], ...] = (
    ("name conflict", "BLOCK_NAME_CONFLICT"),
    ("not called", "MISSING_EXPLICIT_CALL"),
    ("type mismatch", "TYPE_INCONSISTENT"),
    ("invalid xml", "INVALID_XML"),
    ("library interface mismatch", "LIBRARY_INTERFACE_MISMATCH"),
)

_NO_CATEGORY_REASON = ("诊断不在保守白名单内：无可确定的自动修复类别，只登记不提议"
                       "（PLAN §5.2：编译失败时不得只屏蔽报错而宣称修好）")

# Module-level gate (postponed annotations resolve through __globals__ only).
_REPAIR_PROPOSE_GATE = require_role(action="changeset.propose")

_ROUTES_FLAG = "_repair_boundary_routes_registered"


def _resolve_diagnostic_category(diagnostic: dict[str, Any]) -> str | None:
    """诊断 → 候选修复类别（保守白名单）。

    显式 ``diagnostic["category"]`` 只在命中已知类别表时采用（未知值不猜）；
    否则对 code+message 做白名单子串扫描。映射不出 → ``None``（只登记不提议）。
    """
    explicit = str(diagnostic.get("category", "") or "").strip()
    if explicit in ALLOWED_CATEGORIES or explicit in FORBIDDEN_CATEGORIES:
        return explicit
    text = " ".join([str(diagnostic.get("code", "") or ""),
                     str(diagnostic.get("message", "") or "")]).lower()
    for needle, category in _DIAGNOSTIC_MAP:
        if needle in text:
            return category
    return None


class RepairBoundaryService:
    """§5.2 修复边界：classify 单项判定；propose 批量产出候选（永不自动应用）。"""

    def __init__(self, db: Any = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "RepairBoundaryService 需要数据库路径（或 None 走纯内存），不接受常驻连接："
                "FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误")
        #: db=None -> 纯内存（no-db 应用不触碰默认 SQLite 路径）。
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()
        self._mem: list[dict[str, Any]] = []

    # ---------- 单项判定 ----------

    def classify(self, proposed_fix: dict[str, Any]) -> dict[str, Any]:
        """判定一个拟议修复是否允许自动提议。

        ``proposed_fix = {category, description?, touches?}``；类别表精确匹配：
        ALLOWED → ``{"allowed": True, reason}``；FORBIDDEN → ``{"allowed": False,
        类别专属 reason}``；未知/缺失 → ``{"allowed": False, "unknown fix
        category"}``（fail-closed）。``description``/诊断文本**不影响**类别判定
        ——「编译通过」之类的话术不能把禁改项洗白。
        """
        category = str((proposed_fix or {}).get("category", "") or "").strip()
        if category in ALLOWED_CATEGORIES:
            return {"allowed": True, "category": category,
                    "reason": _ALLOWED_REASONS[category]}
        if category in FORBIDDEN_CATEGORIES:
            return {"allowed": False, "category": category,
                    "reason": _FORBIDDEN_REASONS[category]}
        return {"allowed": False, "category": category or None,
                "reason": _UNKNOWN_CATEGORY_REASON}

    # ---------- 批量提议 ----------

    def propose(self, project_id: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
        """从编译诊断产出候选修复提案（PLAN §5.2）。

        - 白名单映射成功的 ALLOWED 类别 → ``proposals[]``，每条
          ``must_return_to_review=True``：候选修复必须回到审查/验证链路；
        - FORBIDDEN 类别（显式给出或映射）与映射不出的诊断 → ``forbidden_seen[]``
          只登记，绝不提议；
        - ``auto_applied`` 恒为空：本服务不存在自动应用路径。
        """
        proposals: list[dict[str, Any]] = []
        forbidden_seen: list[dict[str, Any]] = []
        for diagnostic in diagnostics or []:
            if not isinstance(diagnostic, dict):
                forbidden_seen.append(
                    {"diagnostic": diagnostic, "category": None, "reason": _NO_CATEGORY_REASON})
                continue
            category = _resolve_diagnostic_category(diagnostic)
            if category is None:
                forbidden_seen.append({"diagnostic": dict(diagnostic), "category": None,
                                       "reason": _NO_CATEGORY_REASON})
                continue
            verdict = self.classify({"category": category})
            if verdict["allowed"]:
                proposals.append({
                    "diagnostic": dict(diagnostic),
                    "fix": {"category": category, "action": _ACTION_HINTS[category]},
                    "allowed": True,
                    # §5.2：所有修复以候选变更回到审查/验证链路——恒真。
                    "must_return_to_review": True,
                })
            else:
                forbidden_seen.append({"diagnostic": dict(diagnostic), "category": category,
                                       "reason": verdict["reason"]})
        result: dict[str, Any] = {
            "project_id": project_id,
            "proposals": proposals,
            "forbidden_seen": forbidden_seen,
            "auto_applied": [],  # 永远为空：没有自动应用修复的代码路径
            "note": "全部候选修复必须回流人工审查/验证链路（PLAN §5.2）；auto_applied 恒空。",
            "created_at": utcnow(),
        }
        self._persist_snapshot(project_id, result)
        return result

    def proposals_for(self, project_id: str) -> list[dict[str, Any]]:
        """项目历史 propose 快照（审查侧可见的登记轨迹）。"""
        if self._db is None:
            with self._lock:
                rows = list(self._mem)
        else:
            with contextlib.closing(open_db(self._db)) as conn:
                rows = JsonDao(conn, NAMESPACE).list_by_kind("repair_proposal")
        out = [{k: v for k, v in r.items() if k not in ("id", "kind")}
               for r in rows if r.get("project_id") == project_id]
        out.sort(key=lambda r: (r.get("created_at") or "", r.get("proposal_id") or ""))
        return out

    # ---------- persistence ----------

    def _persist_snapshot(self, project_id: str, result: dict[str, Any]) -> None:
        proposal_id = "rp_" + uuid.uuid4().hex[:8]
        snapshot = {"proposal_id": proposal_id, **result}
        if self._db is None:
            with self._lock:
                self._mem.append(snapshot)
            return
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            JsonDao(conn, NAMESPACE).put(proposal_id, "repair_proposal", snapshot)


# ---------- HTTP layer ----------

def register_routes(app: FastAPI) -> None:
    """幂等挂载修复边界路由。

    - POST /api/processos/projects/{pid}/repair-proposals
      （RBAC changeset.propose：FieldEngineer/Admin——提出候选变更的动作）。
    """
    if getattr(app.state, "repair_boundary", None) is None:
        app.state.repair_boundary = RepairBoundaryService()
    service: RepairBoundaryService = app.state.repair_boundary
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)

    @app.post("/api/processos/projects/{pid}/repair-proposals")
    def create_repair_proposals(request: Request, pid: str, body: dict[str, Any],
                                actor: Annotated[Actor, Depends(_REPAIR_PROPOSE_GATE)]
                                ) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is not None and pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        diagnostics = body.get("diagnostics")
        if not isinstance(diagnostics, list):
            raise HTTPException(status_code=422,
                                detail="missing required field: diagnostics (list)")
        return service.propose(pid, diagnostics)
