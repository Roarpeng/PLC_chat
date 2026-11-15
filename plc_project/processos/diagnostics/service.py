"""PLAN §1 L-loop · DiagnosticsLocateService（编译诊断定位 + 编译范围建议）。

**locate**（诊断 → 语义对象，修错闭环 L 环）：
- 每条诊断 ``{block, line?, message}`` 经 ``trace.sourcemap`` 按 ``block_name``
  反查（扫描全部 build 的条目，同一块多 build 时**优先最新 build**——最新 =
  条目在 registry 中的最后插入位置所在 build，绝不按字典序猜）；
- 带行号且落在某条目 ``scl_line_range`` 内 → 精确到 step/CM 条目；
- 无行号且该块在最新 build 只有一个条目 → 该条目（CM 驱动块常为此形态）；
- 无行号且该块承载多个语义对象 → **块级歧义**：``located="block_ambiguous"``，
  ``semantic_object_id=None``、``display_name="UNKNOWN"``，附带 ``candidates``
  供人工判断——不猜；
- 块名完全不在 SourceMap（手写原生代码/未知块）→ ``unmapped`` +
  ``error_code="UNMAPPED_NATIVE_CODE"``（§11 语义：不可映射不猜）；
- 行号给了解析不成整数 → 视为无行号（不虚构行定位），仅保留原始输入。

``proposals``：同批诊断交给 ``RepairBoundaryService.propose``（白名单映射在其
内部保守完成），原样附在响应供 UI 呈现候选修复；``must_return_to_review``
恒真、``auto_applied`` 恒空由 repair 服务保证。

**compile_scope**（§5/FastWriteback 对应的范围建议）：
- 触及 invariants / interface / io / resources（接口面）或结构性
  ``add``/``remove`` → ``mode="full"`` + 原因（调用方接口与实例 DB 需重新解析，
  增量不安全）；
- 其余（step/em/cm 参数类 set）→ ``mode="incremental"`` + 经 SourceMap 反查的
  受影响块清单；ops 映射不出任何块 → fail-closed 回 full（证明不了范围就不
  声称增量）；
- **规则诚实**：生成器当前总是全量编译——``note`` 明写「当前交付链为全量编译；
  增量范围由 FastWriteback 分级编译承接（见 C# 侧）」，不冒充已增量。

Persistence：``db`` 给定时每次 locate 快照写入 namespace ``"diag_locates"``
（短命连接 + RLock）；``db=None`` 纯内存（no-db 应用不触碰默认 SQLite 路径）。
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import uuid
from typing import Any

from processos.repair.service import RepairBoundaryService
from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "diag_locates"

#: 条目无 scl 行区间时的诚实文案（块级定位，行号永不虚构）。
BLOCK_LEVEL_TEXT = "块级定位（无行号）"

#: §11 语义：块名映射不回 SourceMap（原生手写代码/未知块）时的机器码。
UNMAPPED_NATIVE_CODE = "UNMAPPED_NATIVE_CODE"

#: 范围建议的诚实注脚：本服务只给建议，交付链当前是全量编译。
FULL_COMPILE_NOTE = ("当前交付链为全量编译；增量范围由 FastWriteback 分级编译承接"
                     "（见 C# 侧）")

#: op 路径触及这些段 → 接口/IO/不变量变更，增量编译不安全 → full。
#: （按叶子字段匹配；``/resources/<id>/name`` 之类的非接口字段不算，结构性
#: add/remove 由 _STRUCTURAL_OPS 单独覆盖。）
_INTERFACE_TOKENS = ("invariants", "interface", "io_bindings", "io", "resource_ids",
                     "commands", "feedback", "status")

#: 结构性 op（增删节点改变调用结构/接口面）→ full。
_STRUCTURAL_OPS = ("add", "remove")


def _norm_line(raw: Any) -> int | None:
    """行号归一：非负整数才可用，其余（缺失/非数字/0）视为无行号。"""
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


class DiagnosticsLocateService:
    """locate：诊断→对象（SourceMap 反查）；compile_scope：ops→建议编译范围。"""

    def __init__(self, trace: Any, repair: RepairBoundaryService | None,
                 db: Any = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "DiagnosticsLocateService 需要数据库路径（或 None 走纯内存），"
                "不接受常驻连接：FastAPI 同步路由在线程池线程中使用会触发 "
                "sqlite 跨线程错误")
        self._trace = trace
        self._repair = repair
        #: db=None -> 纯内存（no-db 应用不触碰默认 SQLite 路径）。
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()
        self._mem: list[dict[str, Any]] = []

    # ---------- 内部：SourceMap 反查（最新 build 优先） ----------

    def _all_entries(self) -> list[Any]:
        try:
            return list(self._trace.sourcemap.all_entries())
        except AttributeError:
            return []

    def _entries_latest_build_first(self, entries: list[Any]) -> list[Any]:
        """按所属 build 的「最后插入位置」降序排（最新 build 的条目排前面）。"""
        last_pos: dict[str, int] = {}
        for idx, e in enumerate(entries):
            last_pos[e.release_build_id] = idx
        return sorted(entries, key=lambda e: -last_pos[e.release_build_id])

    def _entries_for_block(self, block: str) -> list[Any]:
        return [e for e in self._all_entries() if e.block_name == block]

    def _entries_for_object(self, object_id: str) -> list[Any]:
        try:
            resolve = self._trace.sourcemap.resolve
        except AttributeError:
            return []
        return self._entries_latest_build_first(list(resolve(object_id)))

    def _display_name(self, semantic_object_id: str | None) -> str:
        """display_name 经 registry.get 取；取不到 → 显式 UNKNOWN（不猜）。"""
        if not semantic_object_id:
            return "UNKNOWN"
        try:
            obj = self._trace.registry.get(semantic_object_id)
        except AttributeError:
            obj = None
        return (getattr(obj, "display_name", "") or "UNKNOWN") if obj else "UNKNOWN"

    def _mapping_from_entry(self, index: int, entry: Any, block: str, line: int | None,
                            message: str, located: str) -> dict[str, Any]:
        rng = entry.scl_line_range
        return {
            "index": index,
            "block": block,
            "line": line,
            "message": message,
            "semantic_object_id": entry.semantic_object_id or None,
            "behavior_step_id": entry.behavior_step_id or None,
            "source_map_id": entry.source_map_id,
            "display_name": self._display_name(entry.semantic_object_id),
            "scl_line_range": list(rng) if rng else None,
            "scl_location": (f"行 {rng[0]}–{rng[1]}" if rng else BLOCK_LEVEL_TEXT),
            "release_build_id": entry.release_build_id,
            "block_kind": entry.block_kind,
            "instance_db": entry.instance_db,
            "ownership": entry.ownership,
            "located": located,  # line | block | block_ambiguous
        }

    # ---------- locate（L 环主入口） ----------

    def locate(self, project_id: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
        """批量诊断 → {mappings, unmapped, proposals}（详见模块 docstring）。"""
        mappings: list[dict[str, Any]] = []
        unmapped: list[dict[str, Any]] = []
        for index, diagnostic in enumerate(diagnostics or []):
            if not isinstance(diagnostic, dict):
                diagnostic = {"message": str(diagnostic)}
            block = str(diagnostic.get("block", "") or "").strip()
            line = _norm_line(diagnostic.get("line"))
            message = str(diagnostic.get("message", "") or "")
            entries = self._entries_latest_build_first(self._entries_for_block(block))
            hit = self._resolve_entry(entries, line)
            if isinstance(hit, dict):  # block_ambiguous aggregate
                mappings.append({
                    "index": index, "block": block, "line": line, "message": message,
                    "semantic_object_id": None, "behavior_step_id": None,
                    "source_map_id": None, "display_name": "UNKNOWN",
                    "scl_line_range": None, "scl_location": BLOCK_LEVEL_TEXT,
                    "release_build_id": hit["release_build_id"],
                    "block_kind": hit["block_kind"], "instance_db": "",
                    "ownership": hit["ownership"], "located": "block_ambiguous",
                    "candidates": hit["candidates"],
                })
                continue
            if hit is None:
                unmapped.append({
                    "index": index, "block": block, "line": line, "message": message,
                    "error_code": UNMAPPED_NATIVE_CODE,
                    "reason": "块名不在 SourceMap（手写原生代码/未知块）："
                              "不可映射不猜（PLAN §11）",
                })
                continue
            located = "line" if (line is not None and hit.scl_line_range) else "block"
            mappings.append(self._mapping_from_entry(index, hit, block, line, message, located))
        proposals: dict[str, Any] | None = None
        if self._repair is not None:
            proposals = self._repair.propose(project_id, list(diagnostics or []))
        result: dict[str, Any] = {
            "project_id": project_id,
            "mappings": mappings,
            "unmapped": unmapped,
            "proposals": proposals,
            "created_at": utcnow(),
        }
        self._persist_locate(project_id, result)
        return result

    def _resolve_entry(self, entries: list[Any],
                       line: int | None) -> Any | None:
        """最新 build 优先：行号命中区间 → 该条目；无行号唯一条目 → 该条目。

        返回 ``None``（无条目）、SourceMapEntry 或 ``dict``（块级歧义聚合，
        ``candidates`` 列全该块在最新 build 的条目）。
        """
        if not entries:
            return None
        latest_build = entries[0].release_build_id
        build_entries = [e for e in entries if e.release_build_id == latest_build]
        if line is not None:
            for e in build_entries:  # spans of distinct nodes do not overlap
                rng = e.scl_line_range
                if rng and rng[0] <= line <= rng[1]:
                    return e
            # 行号不落任何区间 → 退块级聚合（不猜到邻近区间）
        if len(build_entries) == 1:
            return build_entries[0]
        return {
            "release_build_id": latest_build,
            "block_kind": build_entries[0].block_kind,
            "ownership": build_entries[0].ownership,
            "candidates": [{
                "source_map_id": e.source_map_id,
                "semantic_object_id": e.semantic_object_id or None,
                "behavior_step_id": e.behavior_step_id or None,
                "display_name": self._display_name(e.semantic_object_id),
                "scl_line_range": list(e.scl_line_range) if e.scl_line_range else None,
                "scl_location": (f"行 {e.scl_line_range[0]}–{e.scl_line_range[1]}"
                                 if e.scl_line_range else BLOCK_LEVEL_TEXT),
            } for e in build_entries],
        }

    # ---------- compile_scope（§5/FastWriteback 范围建议） ----------

    def compile_scope(self, project_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
        """ops → {mode, affected_blocks, reason, note}（建议范围，非已执行）。"""
        clean_ops = [o for o in (ops or []) if isinstance(o, dict)]
        if not clean_ops:
            return {
                "project_id": project_id, "mode": "full", "affected_blocks": [],
                "reason": "未提供变更操作：默认全量编译（fail-closed，不猜范围）",
                "note": FULL_COMPILE_NOTE, "ops_analyzed": 0,
            }

        interface_reasons: list[str] = []
        affected: list[str] = []
        seen_blocks: set[str] = set()
        unresolved: list[str] = []
        ids_map: dict[str, str] = dict(self._ids_for(project_id))
        for op in clean_ops:
            path = str(op.get("path") or op.get("target") or "")
            op_name = str(op.get("op", "") or "").strip().lower()
            tokens = {t.lower() for t in path.split("/") if t}
            touched = sorted(tokens & set(_INTERFACE_TOKENS))
            if touched:
                interface_reasons.append(
                    f"op '{op_name or '?'}' 触及 {'/'.join(touched)}（接口/IO/不变量面）")
            if op_name in _STRUCTURAL_OPS:
                interface_reasons.append(
                    f"结构性 op '{op_name}'：增删节点改变调用结构/接口面")
            # 受影响块照常反查（full 模式下也给出，作为上下文信息）
            mapped_any = False
            for token in (t for t in path.split("/") if t):
                oid = ids_map.get(token)
                if not oid:
                    continue
                mapped_any = True
                for entry in self._entries_for_object(oid):
                    if entry.block_name not in seen_blocks:
                        seen_blocks.add(entry.block_name)
                        affected.append(entry.block_name)
            if not mapped_any:
                unresolved.append(path or f"<op:{op_name or 'unknown'}>")

        if interface_reasons:
            return {
                "project_id": project_id, "mode": "full",
                "affected_blocks": affected,
                "reason": "涉及 OB/接口/IO/不变量变更，增量编译不安全（调用方接口与"
                          "实例 DB 需重新解析）：" + "；".join(interface_reasons),
                "note": FULL_COMPILE_NOTE, "ops_analyzed": len(clean_ops),
                "unresolved_targets": unresolved,
            }
        if not affected:
            return {
                "project_id": project_id, "mode": "full", "affected_blocks": [],
                "reason": "变更目标无法经 SourceMap 映射到受影响块（UNKNOWN）："
                          "证明不了增量范围就不声称增量，回退全量"
                          + (f"；未解析目标：{', '.join(unresolved)}" if unresolved else ""),
                "note": FULL_COMPILE_NOTE, "ops_analyzed": len(clean_ops),
                "unresolved_targets": unresolved,
            }
        return {
            "project_id": project_id, "mode": "incremental",
            "affected_blocks": affected,
            "reason": "无 OB/接口/IO/不变量变更：建议仅增量编译受影响块"
                      "（incremental_blocks）",
            "note": FULL_COMPILE_NOTE, "ops_analyzed": len(clean_ops),
            "unresolved_targets": unresolved,
        }

    def _ids_for(self, project_id: str) -> dict[str, str]:
        try:
            return dict(self._trace.ids_for(project_id))
        except AttributeError:
            return {}

    # ---------- persistence（namespace "diag_locates"，短命连接 + RLock） ----------

    def locates_for(self, project_id: str) -> list[dict[str, Any]]:
        """项目历史 locate 快照（含 mappings/unmapped/proposals）。"""
        if self._db is None:
            with self._lock:
                rows = list(self._mem)
        else:
            with contextlib.closing(open_db(self._db)) as conn:
                rows = JsonDao(conn, NAMESPACE).list_by_kind("diag_locate")
        out = [{k: v for k, v in r.items() if k not in ("id", "kind")}
               for r in rows if r.get("project_id") == project_id]
        out.sort(key=lambda r: (r.get("created_at") or "", r.get("locate_id") or ""))
        return out

    def _persist_locate(self, project_id: str, result: dict[str, Any]) -> None:
        locate_id = "dl_" + uuid.uuid4().hex[:8]
        snapshot = {"locate_id": locate_id, **result}
        if self._db is None:
            with self._lock:
                self._mem.append(snapshot)
            return
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            JsonDao(conn, NAMESPACE).put(locate_id, "diag_locate", snapshot)
