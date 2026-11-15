"""FC-16/17 · Online diff capture + field TIA modification recovery.

Compares a captured field PLC block manifest (B3, the online state) against
the approved built baseline (B2) and reports a three-way view against the
design IR (B1). Without any baseline the service refuses to guess:
``b2_vs_b3="UNKNOWN"`` + error_code ``UNKNOWN_PLC_STATE`` and stays frozen
(fail-closed, PLAN §11).

Field blocks that exist neither in the SourceMap nor in the B2 manifest are
*unmapped native code*: they are preserved as read-only
``MANAGED_NATIVE_OVERRIDE`` records (controlled black boxes) and are never
reverse-engineered or auto-overwritten. 本服务绝不写回/覆盖任何原工程文件。
"""
from __future__ import annotations

import contextlib
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from typing import Any, Iterable

from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "field_overrides"

OVERRIDE_NOTE = "不可反向解析的现场代码作为受控黑盒保留，不得自动覆盖"
UNKNOWN_BASELINE_NOTE = (
    "无 B2 基准（baseline_provider 与 b2_manifest 均未提供）——现场状态未知，"
    "fail-closed 冻结变更，不做任何猜测（UNKNOWN_PLC_STATE）"
)

_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


def _norm_sha(value: Any) -> str:
    """Normalize 'sha256:<hex>' / '<hex>' to bare lowercase hex for comparison."""
    s = str(value).strip()
    if s.lower().startswith("sha256:"):
        s = s[len("sha256:"):]
    return s.lower()


def _sourcemap_block_names(sourcemap: Any) -> set[str]:
    """Inventory of mapped block names from trace_provider.sourcemap."""
    names: set[str] = set()
    if sourcemap is None:
        return names
    entries: Iterable[Any]
    if hasattr(sourcemap, "all_entries"):
        entries = sourcemap.all_entries()
    else:
        raw = getattr(sourcemap, "entries", None)
        if raw is None:
            raw = getattr(sourcemap, "_entries", None) or {}
        entries = raw.values() if isinstance(raw, dict) else raw
    for e in entries:
        if hasattr(e, "block_name"):
            names.add(e.block_name)
        elif isinstance(e, dict) and e.get("block_name"):
            names.add(e["block_name"])
    return {n for n in names if n}


def _manifest_blocks(manifest: Any) -> dict[str, str]:
    """Extract {block_name: sha256} from a B2 manifest payload."""
    if not isinstance(manifest, dict):
        raise ValueError("b2_manifest 必须是对象")
    block_manifest = manifest.get("block_manifest")
    if isinstance(block_manifest, dict) and "blocks" in block_manifest and isinstance(block_manifest["blocks"], dict):
        block_manifest = block_manifest["blocks"]
    if not isinstance(block_manifest, dict):
        raise ValueError("b2_manifest.block_manifest 缺失或不是映射")
    out: dict[str, str] = {}
    for name, sha in block_manifest.items():
        if not str(name).strip():
            raise ValueError("b2_manifest.block_manifest 含空 block_name")
        out[str(name)] = _norm_sha(sha)
    return out


class FieldModificationService:
    """Recover field TIA modifications as a three-way diff + frozen-drift verdict.

    ``trace_provider``: anything with ``.sourcemap`` (TraceabilityService).
    ``baseline_provider``: duck-typed ``.latest_b2(project_id)`` ->
    ``{"block_manifest": {...}, "archive_sha256": ...}`` (baselines module,
    injected at integration time).
    """

    def __init__(self, trace_provider: Any, baseline_provider: Any = None,
                 db: str | Any | None = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "FieldModificationService 需要数据库路径（或 None 走 PROCESSOS_DB/默认值），"
                "不接受常驻连接：FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误"
            )
        self.trace_provider = trace_provider
        self.baseline_provider = baseline_provider
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()

    def close(self) -> None:
        """No-op: operations use short-lived connections (no persistent handles)."""

    @contextlib.contextmanager
    def _session(self) -> Iterator[JsonDao]:
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            yield JsonDao(conn, NAMESPACE)

    # ---- FC-17 core ----

    def recover(self, project_id: str, field_state: dict[str, Any], *,
                captured_at: str | None = None, source: str = "MANUAL_UPLOAD",
                b2_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        captured = captured_at or utcnow()
        field_blocks = self._normalize_field_state(field_state)
        design_blocks = _sourcemap_block_names(getattr(self.trace_provider, "sourcemap", None))
        b2_blocks = self._resolve_baseline(project_id, b2_manifest)

        result: dict[str, Any] = {
            "project_id": project_id,
            "captured_at": captured,
            "source": source,
            "b2_vs_b3": "UNKNOWN",
            "drift_detected": None,
            "changed_blocks": [],
            "three_way": {"native_changed": [], "field_changed": [],
                          "design_changed": [], "unknown": ["b2_baseline", "design_baseline_b1"]},
            "unmapped_native_code": [],
            "managed_native_overrides": [],
            "frozen": True,
            "error_code": "UNKNOWN_PLC_STATE",
            "note": UNKNOWN_BASELINE_NOTE,
        }
        if b2_blocks is None:
            return result  # 无任何基准：不猜（fail-closed）

        changed: list[dict[str, Any]] = []
        unmapped: list[str] = []
        native_changed: list[str] = []
        field_changed: list[str] = []
        for name in sorted(set(field_blocks) | set(b2_blocks)):
            in_field, in_b2 = name in field_blocks, name in b2_blocks
            if in_field and not in_b2:
                if name in design_blocks:
                    # 设计已知块，但批准基线里没有：现场相对 B2 的新增。
                    changed.append({"block_name": name, "b2_sha256": None,
                                    "field_sha256": field_blocks[name], "reason": "missing_from_b2"})
                    field_changed.append(name)
                else:
                    # 现场新增、SourceMap 与 B2 manifest 都没有：unmapped native code。
                    unmapped.append(name)
            elif in_b2 and not in_field:
                changed.append({"block_name": name, "b2_sha256": b2_blocks[name],
                                "field_sha256": None, "reason": "missing_from_field"})
                native_changed.append(name)
            elif field_blocks[name] != b2_blocks[name]:
                changed.append({"block_name": name, "b2_sha256": b2_blocks[name],
                                "field_sha256": field_blocks[name], "reason": "content_differs"})
                native_changed.append(name)
                field_changed.append(name)

        drift = bool(changed or unmapped)
        overrides = [self._record_override(project_id, name) for name in unmapped]
        result.update({
            "b2_vs_b3": "DRIFT" if drift else "MATCH",
            "drift_detected": drift,
            "changed_blocks": changed,
            "three_way": {
                "native_changed": native_changed,   # B2 vs B3 可观测差异
                "field_changed": field_changed,     # 现场侧相对 B2 的新增/修改
                "design_changed": [],               # 本服务无 B1（设计 IR）视角，留空
                "unknown": ["design_baseline_b1"],  # 显式声明未知视角，不猜测
            },
            "unmapped_native_code": unmapped,
            "managed_native_overrides": overrides,
            "frozen": drift,       # MATCH 之外一律冻结（fail-closed）
            "error_code": "DRIFT_DETECTED" if drift else None,
            "note": "" if not drift else "检测到现场漂移：变更已冻结（DRIFT_DETECTED），需人工走变更流程",
        })
        return result

    # ---- managed native overrides (read-only registry) ----

    def overrides_for(self, project_id: str) -> list[dict[str, Any]]:
        with self._session() as dao:
            rows = dao.list_by_kind("managed_native_override")
        out = [self._strip(r) for r in rows if r.get("project_id") == project_id]
        out.sort(key=lambda r: (r.get("created_at") or "", r.get("override_id") or ""))
        return out

    def get_override(self, override_id: str) -> dict[str, Any] | None:
        with self._session() as dao:
            row = dao.get(override_id)
        return self._strip(row) if row is not None else None

    # ---- internals ----

    def _record_override(self, project_id: str, block_name: str) -> dict[str, Any]:
        override_id = "mno_" + uuid.uuid4().hex[:8]
        body = {
            "override_id": override_id,
            "project_id": project_id,
            "block_name": block_name,
            "ownership": "MANAGED_NATIVE_OVERRIDE",
            "protected_by": "EXPLICIT_OWNERSHIP",
            "note": OVERRIDE_NOTE,
            "created_at": utcnow(),
        }
        with self._session() as dao:
            dao.put(override_id, "managed_native_override", body)
        return dict(body)

    def _resolve_baseline(self, project_id: str,
                          b2_manifest: dict[str, Any] | None) -> dict[str, str] | None:
        if b2_manifest is not None:
            return _manifest_blocks(b2_manifest)  # 显式 body 优先；格式错误 -> ValueError(422)
        latest = self._latest_b2_from_provider(project_id)
        if latest is None:
            return None
        try:
            return _manifest_blocks(latest)
        except ValueError:
            return None  # provider 数据 malformed：不崩，按未知处理（fail-closed）

    def _latest_b2_from_provider(self, project_id: str) -> dict[str, Any] | None:
        """Duck-typed B2 fetch: prefers ``latest_b2(pid)``, adapts to the real
        ``BaselineService`` (``baselines(pid)`` + kind=="B2" records) otherwise.
        Provider failures degrade to unknown (fail-closed), never to a guess."""
        bp = self.baseline_provider
        if bp is None:
            return None
        try:
            if hasattr(bp, "latest_b2"):
                latest = bp.latest_b2(project_id)
                return latest if latest is None else dict(latest)
            if hasattr(bp, "baselines"):
                records = [r for r in bp.baselines(project_id)
                           if str(r.get("kind", "")).upper() == "B2"
                           or str(r.get("baseline_id", "")).startswith("B2:")]
                if not records:
                    return None
                rec = max(records, key=lambda r: r.get("seq", 0))
                return {"block_manifest": rec.get("block_manifest") or {},
                        "archive_sha256": rec.get("archive_sha256", "")}
        except Exception:
            return None  # provider 故障 -> 未知基准（fail-closed）
        return None

    @staticmethod
    def _normalize_field_state(field_state: Any) -> dict[str, str]:
        if not isinstance(field_state, dict) or not isinstance(field_state.get("blocks"), list):
            raise ValueError("field_state 必须是 {blocks: [{block_name, content_sha256}]}")
        out: dict[str, str] = {}
        for i, blk in enumerate(field_state["blocks"]):
            if not isinstance(blk, dict):
                raise ValueError(f"field_state.blocks[{i}] 必须是对象")
            name = blk.get("block_name")
            sha = blk.get("content_sha256")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"field_state.blocks[{i}].block_name 必须是非空字符串")
            if not isinstance(sha, str) or not _SHA256_RE.match(sha.strip()):
                raise ValueError(f"field_state.blocks[{i}].content_sha256 必须是 64 位 sha256 十六进制")
            out[name.strip()] = _norm_sha(sha)
        return out

    @staticmethod
    def _strip(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k not in ("id", "kind")}
