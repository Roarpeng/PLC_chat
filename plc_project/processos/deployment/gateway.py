"""FC-18 · SiteDeploymentGateway — fail-closed site deployment precheck/execute.

PLAN §5.3 明确：**不存在网页“一键自动上线”路径**。本模块刻意如此实现：

1. ``precheck`` 只做条件核验并落库（现场授权窗口、在线比较、数据保持
   评估、双人复核、回退计划、投产记录/B3 证据），不触发任何下载动作；
2. ``execute`` 必须引用已通过的服务端 precheck、必须 ``confirm=True``
   （人工明确确认），且必须由部署方显式注入真实执行后端——默认
   ``execution_backend=None`` 时以 501 SAFETY_SCOPE_BLOCKED 拒绝执行，
   现场部署保持人工流程（下载 TIA 工程 + 现场授权部署）。
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from typing import Any

from processos.safety.errors import SafetyError
from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "deployment"

NO_ONE_CLICK_NOTE = "本网关不提供网页一键自动上线（PLAN 5.3）；执行需人工确认 + 真实执行后端。"


class PrecheckNotFound(KeyError):
    """Raised by execute() when the referenced precheck_id does not exist (-> 404)."""


class SiteDeploymentGateway:
    """Controlled precheck/execute gateway persisted in namespace ``deployment``.

    ``execution_backend``: optional real backend (duck-typed ``execute(precheck)
    -> receipt dict``). Production default is None — refusal, never a fake run.
    ``commissioning``: optional CommissioningLedger (app.state.commissioning)
    used as the 投产记录 evidence source. ``baseline_provider``: optional
    duck-typed ``plc_state_known(project_id, build_id) -> bool|None`` used when
    no commissioning ledger is wired.
    """

    def __init__(self, execution_backend: Any = None, *,
                 baseline_provider: Any = None,
                 commissioning: Any = None,
                 db: str | Any | None = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "SiteDeploymentGateway 需要数据库路径（或 None 走 PROCESSOS_DB/默认值），"
                "不接受常驻连接：FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误"
            )
        self.execution_backend = execution_backend
        self.baseline_provider = baseline_provider
        self.commissioning = commissioning
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()

    def close(self) -> None:
        """No-op: operations use short-lived connections (no persistent handles)."""

    @contextlib.contextmanager
    def _session(self) -> Iterator[JsonDao]:
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            yield JsonDao(conn, NAMESPACE)

    # ---- FC-18 step 1: precheck (no side effects beyond persistence) ----

    def precheck(self, project_id: str, build_id: str, device_id: str, window: str, *,
                 online_compare: dict[str, Any] | None = None,
                 retain_assessment: dict[str, Any] | None = None,
                 second_person: str | None = None,
                 rollback_plan: dict[str, Any] | None = None,
                 authorized_window: bool = False) -> dict[str, Any]:
        satisfied: list[str] = []
        missing: list[str] = []
        blocked_by: list[str] = []

        def check(condition: str, ok: bool, blocked_code: str | None = None) -> None:
            if ok:
                satisfied.append(condition)
                return
            missing.append(condition)
            if blocked_code:
                blocked_by.append(blocked_code)

        check("AUTHORIZED_WINDOW", bool(authorized_window))
        # 无在线比较 -> 现场 PLC 状态未知（§11 UNKNOWN_PLC_STATE，fail-closed）。
        check("ONLINE_COMPARE", online_compare is not None, blocked_code="UNKNOWN_PLC_STATE")
        check("RETAIN_ASSESSMENT", retain_assessment is not None, blocked_code="RETAIN_DATA_RISK")
        check("SECOND_PERSON", bool(second_person and str(second_person).strip()))
        check("ROLLBACK_PLAN", rollback_plan is not None)
        build_ok, build_blocked = self._commissioning_state(project_id, build_id)
        check("COMMISSIONING_RECORD", build_ok, blocked_code=build_blocked)

        precheck_id = "dgp_" + uuid.uuid4().hex[:8]
        body: dict[str, Any] = {
            "precheck_id": precheck_id,
            "project_id": project_id,
            "build_id": build_id,
            "device_id": device_id,
            "window": window,
            "authorized_window": bool(authorized_window),
            "satisfied": satisfied,
            "missing": missing,
            "blocked_by": list(dict.fromkeys(blocked_by)),
            "ready": not missing and not blocked_by,
            "one_click_online": False,
            "note": NO_ONE_CLICK_NOTE,
            "created_at": utcnow(),
        }
        with self._session() as dao:
            dao.put(precheck_id, "precheck", body)
        return dict(body)

    def get_precheck(self, precheck_id: str) -> dict[str, Any] | None:
        with self._session() as dao:
            row = dao.get(precheck_id)
        return self._strip(row) if row is not None else None

    # ---- FC-18 step 2: execute (human-confirmed, backend-gated) ----

    def execute(self, precheck_id: str, *, confirm: bool = False, actor: str = "") -> dict[str, Any]:
        pc = self.get_precheck(precheck_id)
        if pc is None:
            raise PrecheckNotFound(precheck_id)
        if confirm is not True:
            raise SafetyError(
                "SAFETY_SCOPE_BLOCKED", "需要人工明确确认（confirm=True）方可执行现场部署",
                http_status=403,
            )
        if not pc.get("ready"):
            raise SafetyError(
                "SAFETY_SCOPE_BLOCKED", "预检未通过，禁止执行现场部署",
                details={"missing": pc.get("missing", []), "blocked_by": pc.get("blocked_by", [])},
                http_status=403,
            )
        if self.execution_backend is None:
            raise SafetyError(
                "SAFETY_SCOPE_BLOCKED",
                "未配置真实执行后端——现场部署保持人工流程（下载 TIA 工程 + 现场授权部署）",
                http_status=501,
            )
        receipt = self.execution_backend.execute(pc)  # 真实后端由部署方注入；无 mock 伪装
        executed: dict[str, Any] = {
            "precheck_id": precheck_id,
            "actor": actor,
            "backend": getattr(self.execution_backend, "name", type(self.execution_backend).__name__),
            "result": receipt,
            "one_click_online": False,
            "note": NO_ONE_CLICK_NOTE,
            "executed_at": utcnow(),
        }
        with self._session() as dao:
            dao.put(precheck_id + "::exec", "execution", executed)
        return dict(executed)

    def executions_for(self, precheck_id: str) -> list[dict[str, Any]]:
        with self._session() as dao:
            rows = dao.list_by_kind("execution")
        out = [self._strip(r) for r in rows if r.get("precheck_id") == precheck_id]
        out.sort(key=lambda r: (r.get("executed_at") or "", r.get("precheck_id") or ""))
        return out

    # ---- internals ----

    def _commissioning_state(self, project_id: str, build_id: str) -> tuple[bool, str | None]:
        """投产记录/B3 证据核验：True=有 COMMISSIONED 记录；否则给出阻断码。

        commissioning 台账可用：无该 build 的 COMMISSIONED 记录 -> DRIFT_DETECTED。
        baseline_provider 可用：用其 plc_state_known（None -> 状态未知）。
        两者皆无：状态未知 -> UNKNOWN_PLC_STATE（不猜，§11）。
        """
        comm = self.commissioning
        if comm is not None and hasattr(comm, "records_for"):
            records = [r for r in comm.records_for(project_id)
                       if r.get("build_id") == build_id]
            if any(r.get("result") == "COMMISSIONED" for r in records):
                return True, None
            return False, "DRIFT_DETECTED"  # 无对应投产记录（或未 COMMISSIONED）
        known = self._plc_state_from_provider(project_id, build_id)
        if known is True:
            return True, None
        # provider 的 False = 无 FIELD_VERIFIED 的 B3（现场状态未证实）——按未知处理，
        # 不虚构 DRIFT_DETECTED（那是“已证实不一致”，只能由投产台账缺失等得出）。
        return False, "UNKNOWN_PLC_STATE"

    def _plc_state_from_provider(self, project_id: str, build_id: str) -> bool | None:
        """Duck-typed ``plc_state_known``; tolerates both (pid, build_id) and
        the real BaselineService's (pid)-only signature. Provider failure ->
        None (unknown, fail-closed)."""
        bp = self.baseline_provider
        if bp is None or not hasattr(bp, "plc_state_known"):
            return None
        try:
            try:
                return bp.plc_state_known(project_id, build_id)
            except TypeError:
                return bp.plc_state_known(project_id)
        except Exception:
            return None

    @staticmethod
    def _strip(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k not in ("id", "kind")}
