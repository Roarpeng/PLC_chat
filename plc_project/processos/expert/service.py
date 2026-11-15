"""PLAN §3.2 B · 专家模式：受控 SCL 修改 (ExpertSclService + routes).

工程师可以提出代码级变更，但系统绝不直接改写工程。两条受控分支：

1. **SEMANTIC_CANDIDATE（可解析分支）** —— 保守解析器只认 ``<param> := <value>;``
   形式的常量参数赋值（如 ``ExtendTimeout := T#5000ms;``）。全部语句可解析且能
   确定性映射到工艺 IR 时，生成结构化候选 Patch 并在**副本**上试应用
   （``processos.contract.patch.apply_patch`` 自带深拷贝，原件不变）。返回
   ``{mode: "SEMANTIC_CANDIDATE", patch, requires_approval: true, ir_written: false}``
   —— **不落盘、不走审批门禁不算通过**，必须经既有 Patch 审批链路。
   解析/映射/应用任何一步失败 → 按黑盒处理（fail-closed，不猜）。

2. **MANAGED_NATIVE_OVERRIDE（黑盒分支）** —— 不能被语义理解的 diff 以受控黑盒
   保留：scl_diff 原文、块名、原因、提交人全部入档，``ownership:"MANAGED_NATIVE_OVERRIDE"``
   + ``protected_by:"EXPLICIT_OWNERSHIP"``，禁止 AI 重生成/自动覆盖（PLAN §0.6）。

安全边界（PLAN §3.2/§11）：SourceMap 条目 ownership ∈ {OFFICIAL_LIBRARY,
MANAGED_NATIVE_OVERRIDE} 或块属性/命名标记 protected/F-Safety（``F_`` 前缀块名、
``block_kind`` 或 symbol_refs 含 F_SAFETY/PROTECTED）→ ``SafetyError``
``SAFETY_SCOPE_BLOCKED``(403)，官方库/安全块禁止自动写入。

Persistence：``db`` 给定时写 namespace ``"scl_overrides"``（短命连接 + RLock）；
``db=None`` 纯内存（no-db 应用绝不触碰默认 SQLite 路径）。审计经 ``self.audit``
（rbac.AuditLog duck-type，无则跳过不炸；有但写入失败则抛出——审计不可静默丢失）。
"""
from __future__ import annotations

import contextlib
import re
import sqlite3
import threading
import uuid
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request

from processos.contract import Patch, PatchOp, RevisionConflict, apply_patch
from processos.contract.patch import PatchError
from processos.rbac import Actor, require_role
from processos.safety.errors import SafetyError, register_safety_exception_handler
from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "scl_overrides"

#: ownership 一旦是官方库或既有黑盒覆盖，AI/自动写入一律禁止（显式所有权保护）。
_BLOCKED_OWNERSHIPS = frozenset({"OFFICIAL_LIBRARY", "MANAGED_NATIVE_OVERRIDE"})

_BLACKBOX_NOTE = "未被 Canvas 语义理解，禁止 AI 重生成/自动覆盖"

# 保守解析器：仅识别常量参数赋值 "<ident> := <value>;"。
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=\s*(.+?)\s*$")
_TIME_RE = re.compile(r"^T#(\d{1,9})(ms|s)$", re.IGNORECASE)
_INT_RE = re.compile(r"^-?\d{1,12}$")

# Module-level gate: with ``from __future__ import annotations`` route hints
# resolve through __globals__ only — dependencies must not live in a closure.
_SCL_CHANGE_GATE = require_role(action="changeset.propose")

_ROUTES_FLAG = "_expert_scl_routes_registered"


def _parse_scl_value(text: str) -> Any:
    """Deterministically parse one SCL constant literal, else ``None``.

    只认 ``T#5000ms``/``T#2s`` 时间字面量、十进制整数、TRUE/FALSE 与双引号字符串；
    其它（表达式、标识符引用、浮点、括号…）一律 ``None`` → 黑盒分支。
    """
    t = text.strip()
    m = _TIME_RE.match(t)
    if m:
        return int(m.group(1)) * (1 if m.group(2).lower() == "ms" else 1000)
    if _INT_RE.match(t):
        return int(t)
    if t.upper() == "TRUE":
        return True
    if t.upper() == "FALSE":
        return False
    if len(t) >= 2 and t.startswith('"') and t.endswith('"'):
        return t[1:-1]
    return None


def _parse_assignments(scl_diff: str) -> list[tuple[str, str, Any]] | None:
    """Parse every statement as a constant assignment, else ``None``.

    任意一条语句不是 ``<param> := <value>;``（含控制语句、注释、表达式）→ 整个
    diff 不可确定性解析 → ``None``（黑盒）。空片段跳过；纯空白 diff 由调用方校验。
    """
    out: list[tuple[str, str, Any]] = []
    for raw in scl_diff.split(";"):
        piece = raw.strip()
        if not piece:
            continue
        m = _ASSIGN_RE.match(piece)
        if not m:
            return None
        param, value_text = m.group(1), m.group(2)
        parsed = _parse_scl_value(value_text)
        if parsed is None:
            return None
        out.append((param, value_text, parsed))
    return out or None


def _is_safety_scope_blocked(entries: list[Any]) -> bool:
    """官方库 / F-Safety / 保护块的保守判定（PLAN §3.2/§11）。

    SourceMap 条目没有独立的属性字典，标记按以下确定性信号扫描：ownership、
    ``block_kind``、块名 ``F_`` 前缀（Fail-Safe 块命名约定）、symbol_refs 关键词。
    误伤（把普通块当安全块）只会走独立流程，不会放行危险写入——fail-closed。
    """
    for e in entries:
        if getattr(e, "ownership", "") in _BLOCKED_OWNERSHIPS:
            return True
        kind = str(getattr(e, "block_kind", "") or "").upper()
        # 普通块型是 FB/FC/DB/OB/UDT——任何 F_ 前缀的块型都是 Fail-Safe 域。
        if kind.startswith("F_") or "F_SAFETY" in kind or "PROTECTED" in kind:
            return True
        if str(getattr(e, "block_name", "") or "").upper().startswith("F_"):
            return True
        refs = " ".join(str(r) for r in (getattr(e, "symbol_refs", None) or [])).upper()
        if "F_SAFETY" in refs or "PROTECTED" in refs:
            return True
    return False


class ExpertSclService:
    """专家模式受控 SCL 修改：语义候选 or 受控黑盒，绝不直接写工程。"""

    def __init__(self, store: Any, trace: Any, db: Any = None, *, audit: Any = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "ExpertSclService 需要数据库路径（或 None 走纯内存），不接受常驻连接："
                "FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误")
        self._store = store
        self._trace = trace
        #: db=None -> 纯内存（no-db 应用不触碰默认 SQLite 路径）。
        self._db: str | None = None if db is None else str(db)
        #: rbac.AuditLog duck-type；None -> 跳过审计（无 rbac 环境不炸）。
        self.audit = audit
        self._lock = threading.RLock()
        self._mem: list[dict[str, Any]] = []

    # ---------- public API ----------

    def submit(self, project_id: str, *, block_name: str, scl_diff: str,
               reason: str, actor: Actor | str) -> dict[str, Any]:
        """提交一次专家模式 SCL 变更（SEMANTIC_CANDIDATE 或 MANAGED_NATIVE_OVERRIDE）。

        校验失败抛 ``ValueError``（路由映射 422）；官方库/F-Safety/保护块抛
        ``SafetyError("SAFETY_SCOPE_BLOCKED", ..., 403)``。语义候选**不落盘**：
        ``ir_written=False``，落盘必须经既有 Patch 审批门禁。
        """
        # 纯字符串 actor：角色未知就记 UNKNOWN，不伪造（路由层传入真实 Actor）。
        actor_obj = actor if isinstance(actor, Actor) \
            else Actor(actor_id=str(actor or ""), role="UNKNOWN")
        block_name = str(block_name or "").strip()
        reason = str(reason or "").strip()
        if not block_name:
            raise ValueError("block_name 不能为空")
        if not reason:
            raise ValueError("reason 不能为空（专家模式必须保留变更原因）")
        if not str(actor_obj.actor_id or "").strip():
            raise ValueError("actor 不能为空")
        if not isinstance(scl_diff, str) or not scl_diff.strip():
            raise ValueError("scl_diff 必须是非空文本")

        sourcemap = getattr(self._trace, "sourcemap", None)
        if sourcemap is None:
            raise ValueError("trace/sourcemap 不可用，无法验证块身份")
        entries = [e for e in sourcemap.all_entries() if e.block_name == block_name]
        if not entries:
            raise ValueError(f"块 {block_name!r} 不存在于任何已记录 build 的 SourceMap")

        if _is_safety_scope_blocked(entries):
            self._audit(actor_obj, "expert.scl.submit", f"{project_id}/{block_name}",
                        result="SAFETY_SCOPE_BLOCKED",
                        extra={"block_name": block_name,
                               "ownership": sorted({str(e.ownership) for e in entries})})
            raise SafetyError(
                "SAFETY_SCOPE_BLOCKED",
                "官方库/安全块禁止自动写入（独立流程，PLAN §3.2/§11）",
                details={"block_name": block_name,
                         "ownership": sorted({str(e.ownership) for e in entries})},
                http_status=403,
            )

        semantic = self._try_semantic_candidate(project_id, block_name, scl_diff, entries)
        if semantic is not None:
            self._audit(actor_obj, "expert.scl.submit", f"{project_id}/{block_name}",
                        extra={"mode": "SEMANTIC_CANDIDATE", "block_name": block_name,
                               "requires_approval": True, "ir_written": False})
            return semantic

        override = self._record_override(project_id, block_name, scl_diff, reason, actor_obj)
        self._audit(actor_obj, "expert.scl.submit", f"{project_id}/{block_name}",
                    extra={"mode": "MANAGED_NATIVE_OVERRIDE", "block_name": block_name,
                           "override_id": override["override_id"],
                           "semantic_understood": False})
        return {"mode": "MANAGED_NATIVE_OVERRIDE", "override": override}

    def overrides_for(self, project_id: str) -> list[dict[str, Any]]:
        """某项目的全部受控黑盒覆盖（含 scl_diff 原文），按时间排序。"""
        if self._db is None:
            with self._lock:
                rows = list(self._mem)
        else:
            with contextlib.closing(open_db(self._db)) as conn:
                rows = JsonDao(conn, NAMESPACE).list_by_kind("scl_override")
        out = [{k: v for k, v in r.items() if k not in ("id", "kind")}
               for r in rows if r.get("project_id") == project_id]
        out.sort(key=lambda r: (r.get("created_at") or "", r.get("override_id") or ""))
        return out

    # ---------- semantic candidate branch ----------

    def _try_semantic_candidate(self, project_id: str, block_name: str, scl_diff: str,
                                entries: list[Any]) -> dict[str, Any] | None:
        """可解析分支：全部语句可确定性映射时返回候选结果，否则 ``None``（黑盒）。

        Patch 只在 ``apply_patch`` 的内部深拷贝上试应用；应用失败按黑盒处理
        （PLAN §3.2：不能解析或不允许 AI 重生成的部分以 MANAGED_NATIVE_OVERRIDE 隔离）。
        """
        try:
            if self._store is None:
                return None
            state = self._store._get(project_id)
            contract = state.contract
            assignments = _parse_assignments(scl_diff)
            if assignments is None:
                return None
            mapped = self._map_to_patch_ops(contract, block_name, assignments, entries)
            if mapped is None:
                return None
            patch_ops, semantic_ops = mapped
            patch = Patch(base_revision=state.revision, ops=patch_ops,
                          request_id="scl_" + uuid.uuid4().hex[:8], source="expert_scl")
            apply_patch(contract, patch, state.revision)  # 副本试应用；原件不变
        except (PatchError, RevisionConflict, ValueError, KeyError, TypeError):
            return None
        return {
            "mode": "SEMANTIC_CANDIDATE",
            "block_name": block_name,
            "semantic_ops": semantic_ops,
            "patch": patch.to_dict(),
            # 必须走既有 approve 门禁；本服务绝不落盘工程。
            "requires_approval": True,
            "ir_written": False,
        }

    def _map_to_patch_ops(self, contract: Any, block_name: str,
                          assignments: list[tuple[str, str, Any]],
                          entries: list[Any]) -> tuple[list[PatchOp], list[dict[str, Any]]] | None:
        """把解析出的赋值确定性映射为 Patch ops；任一条映射不了 → ``None``。

        规则（保守白名单，二者必居其一，否则黑盒）：
        - ``<X>Timeout`` → 块绑定（SourceMap.behavior_step_id）的 step ``S_<X>`` 的
          ``timeout_ms``（例：ExtendTimeout → S_EXTEND.timeout_ms）；
        - 其它参数 → 块绑定的 CM（registry kind=af_cm，attributes.cm=资源 id）的
          ``/resources/{cm}/params/{param}``。
        """
        registry = getattr(self._trace, "registry", None)
        cm_ids: list[str] = []
        for e in entries:
            obj = registry.get(e.semantic_object_id) if registry and e.semantic_object_id else None
            if obj is not None and obj.kind == "af_cm":
                rid = str(obj.attributes.get("cm", "") or "")
                if rid and contract.resource(rid) is not None:
                    cm_ids.append(rid)
        patch_ops: list[PatchOp] = []
        semantic_ops: list[dict[str, Any]] = []
        for param, raw, value in assignments:
            op: PatchOp | None = None
            if param.lower().endswith("timeout"):
                base = param[:-len("timeout")].rstrip("_")
                step_id = "S_" + base.upper() if base else ""
                if step_id and any(e.behavior_step_id == step_id for e in entries):
                    owner = next((o for o in contract.operations if o.step(step_id)), None)
                    if owner is not None:
                        op = PatchOp(op="set",
                                     path=f"/operations/{owner.id}/steps/{step_id}/timeout_ms",
                                     value=value)
            if op is None and cm_ids:
                op = PatchOp(op="set", path=f"/resources/{cm_ids[0]}/params/{param}",
                             value=value)
            if op is None:
                return None  # 无法确定性映射 → 黑盒，不猜
            patch_ops.append(op)
            semantic_ops.append({"op": "set_param", "block": block_name,
                                 "param": param, "value": raw})
        return patch_ops, semantic_ops

    # ---------- black box branch + persistence ----------

    def _record_override(self, project_id: str, block_name: str, scl_diff: str,
                         reason: str, actor: Actor) -> dict[str, Any]:
        override: dict[str, Any] = {
            "override_id": "mno_" + uuid.uuid4().hex[:8],
            "project_id": project_id,
            "block_name": block_name,
            "scl_diff": scl_diff,  # 原文保留，逐字节不改动
            "reason": reason,
            "actor": actor.actor_id,
            "ownership": "MANAGED_NATIVE_OVERRIDE",
            "protected_by": "EXPLICIT_OWNERSHIP",
            "semantic_understood": False,
            "note": _BLACKBOX_NOTE,
            "created_at": utcnow(),
        }
        if self._db is None:
            with self._lock:
                self._mem.append(dict(override))
        else:
            with self._lock, contextlib.closing(open_db(self._db)) as conn:
                JsonDao(conn, NAMESPACE).put(override["override_id"], "scl_override", override)
        return override

    def _audit(self, actor: Actor, action: str, target: str, *,
               result: str = "OK", extra: dict[str, Any] | None = None) -> None:
        log = getattr(self, "audit", None)
        if log is None:
            return  # 无 rbac 环境则跳过（不炸）；审计存在但写失败则向上抛（不可静默丢）。
        log.record(actor, action, target, result=result, extra=extra or {})


# ---------- HTTP layer ----------

def register_routes(app: FastAPI) -> None:
    """幂等挂载专家模式路由（POST 受 RBAC changeset.propose 保护）。

    - POST /api/processos/projects/{pid}/scl-changes   FieldEngineer/Admin
    - GET  /api/processos/projects/{pid}/scl-overrides 任意角色（只读）
    """
    if getattr(app.state, "expert_scl", None) is None:
        app.state.expert_scl = ExpertSclService(
            getattr(app.state, "store", None), getattr(app.state, "trace", None))
    service: ExpertSclService = app.state.expert_scl
    if getattr(service, "audit", None) is None:
        service.audit = getattr(app.state, "audit", None)  # rbac 先挂载则可用
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)
    register_safety_exception_handler(app)

    def require_project(request: Request, pid: str) -> None:
        store = getattr(request.app.state, "store", None)
        if store is None or pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")

    @app.post("/api/processos/projects/{pid}/scl-changes")
    def submit_scl_change(request: Request, pid: str, body: dict[str, Any],
                          actor: Annotated[Actor, Depends(_SCL_CHANGE_GATE)]) -> dict[str, Any]:
        require_project(request, pid)
        for field in ("block_name", "scl_diff", "reason"):
            if field not in body:
                raise HTTPException(status_code=422, detail=f"missing required field: {field}")
        try:
            return service.submit(pid, block_name=str(body["block_name"]),
                                  scl_diff=body["scl_diff"], reason=str(body["reason"]),
                                  actor=actor)
        except SafetyError:
            raise  # {error, code, details}，403 SAFETY_SCOPE_BLOCKED 绝不降级
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/processos/projects/{pid}/scl-overrides")
    def list_scl_overrides(request: Request, pid: str) -> dict[str, Any]:
        require_project(request, pid)
        return {"project_id": pid, "overrides": service.overrides_for(pid)}
