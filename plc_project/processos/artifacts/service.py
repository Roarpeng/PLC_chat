"""PLAN §12 PR 工件服务：从当前项目状态真组装 9 类工件。

``POST /api/processos/projects/{pid}/pr-bundle`` 产出：

- ``design_change.md``：契约名 / revision / profile / 意图摘要（markdown）；
- ``semantic_diff.json``：change_log + 证据护照里真实记录的 patch ops；
- ``impact_report.json``：对最新变更对象调 ImpactReportService 的即时报告；
- ``af_compliance.json``：``store.validate`` 结果；
- ``behavior_test_report.json``：``store.simulate`` 结果；
- ``compile_receipt.json``：最新交付 Job 回执（demo runner 的
  ``evidence_level`` 恒为 ``mocked``，如实透传，绝不写 real）；
- ``source_map.json``：该项目已登记构建的 SourceMap 条目；
- ``native_artifact_manifest.json``：Job 工件清单 + sha256（无则 UNKNOWN）；
- ``handover_snapshot.json``：项目问题单的 handover 上下文聚合。

取不到的字段一律显式 ``UNKNOWN``（PLAN §12：不得编造）。bundle 索引持久化
在 JsonDao namespace ``pr_bundles``。连接纪律：只存 db 路径，每次操作开短命
连接（FastAPI 同步路由跑在线程池线程）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "pr_bundles"
UNKNOWN = "UNKNOWN"

#: PLAN §12 必须提交的 9 类工件（固定文件名，顺序即清单顺序）。
BUNDLE_FILE_NAMES: tuple[str, ...] = (
    "design_change.md",
    "semantic_diff.json",
    "impact_report.json",
    "af_compliance.json",
    "behavior_test_report.json",
    "compile_receipt.json",
    "source_map.json",
    "native_artifact_manifest.json",
    "handover_snapshot.json",
)


def _j(obj: Any) -> str:
    """Canonical JSON text for a bundle file (stable key order, CJK kept)."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)


class PrBundleService:
    """Assemble the 9 PLAN §12 artifacts from the live project state."""

    def __init__(self, store: Any, trace: Any, impact: Any = None,
                 db: str | Any | None = None,
                 patch_history: dict[str, list[dict[str, Any]]] | None = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "PrBundleService 需要数据库路径（或 None 走 PROCESSOS_DB/默认值），"
                "不接受常驻连接：FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误"
            )
        self._store = store
        self._trace = trace
        self._impact = impact
        self._patch_history = patch_history  # live app.state dict (may be None)
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()

    @contextlib.contextmanager
    def _session(self) -> Iterator[JsonDao]:
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            yield JsonDao(conn, NAMESPACE)

    # ---- artifact builders (each returns the file TEXT) ----------------------

    def _patch_history_for(self, project_id: str) -> list[dict[str, Any]]:
        """Real patch records kept by the API layer ({rev, request_id, ops}).

        Not durable across restarts — when absent the semantic diff says so
        explicitly (UNKNOWN), never a reconstruction.
        """
        history = (self._patch_history or {}).get(project_id) or []
        return list(history)

    def _latest_patch_ops(self, project_id: str) -> list[dict[str, Any]]:
        history = self._patch_history_for(project_id)
        return list(history[-1].get("ops") or []) if history else []

    def _subject_object_id(self, project_id: str) -> str | None:
        """Latest-change subject: prefer the contract's first CM object."""
        ids = self._trace.ids_for(project_id)
        for key in sorted(ids):
            if key.startswith("CM_"):
                return ids[key]
        for key in sorted(ids):
            if key.startswith("EM_"):
                return ids[key]
        return None

    def _build_impact(self, project_id: str, state: Any) -> dict[str, Any]:
        ops = self._latest_patch_ops(project_id)
        subject = self._subject_object_id(project_id)
        if self._impact is None:
            return {"impact_report": UNKNOWN,
                    "reason": "no impact service wired (UNKNOWN)", "project_id": project_id}
        if subject is None and not ops:
            return {"impact_report": UNKNOWN,
                    "reason": "no analyzable subject or patch ops (UNKNOWN)",
                    "project_id": project_id}
        return self._impact.build(
            project_id,
            object_id=subject,
            patch_ops=ops or None,
            reason="PR bundle：对最新变更对象复核影响面（候选分析，不构成上线许可）",
        )

    def _build_compile_receipt(self, state: Any) -> dict[str, Any]:
        jobs = list(state.jobs.values())
        if not jobs:
            return {"job_id": UNKNOWN, "evidence_level": UNKNOWN,
                    "note": "no delivery job recorded for this project"}
        job = jobs[-1]  # latest delivery job
        receipt = {
            "job_id": job.get("id", UNKNOWN),
            "status": job.get("status", UNKNOWN),
            "chain_state": job.get("chain_state", UNKNOWN),
            # demo runner 证据等级如实透传（mocked）；缺失按 UNKNOWN，绝不写 real。
            "evidence_level": job.get("evidence_level") or UNKNOWN,
            "ob_main_included": job.get("ob_main_included", UNKNOWN),
            "events": job.get("events", []),
            "diagnostics": job.get("diagnostics", []),
        }
        if receipt["evidence_level"] == "mocked":
            receipt["note"] = ("demo runner 回执：mocked 证据等级，未发生真实 TIA 编译；"
                               "BUILD_VERIFIED 不代表现场部署")
        return receipt

    def _build_source_map(self, project_id: str) -> dict[str, Any]:
        builds = [o for o in self._trace.registry.by_kind("build")
                  if (o.attributes or {}).get("project") == project_id]
        entries: list[dict[str, Any]] = []
        for b in builds:
            entries.extend(e.to_dict() for e in self._trace.sourcemap.for_build(b.display_name))
        return {
            "project_id": project_id,
            "builds": [b.display_name for b in builds] or [UNKNOWN],
            "source_map": entries,
            "note": "" if entries else "no SourceMap entries recorded (UNKNOWN)",
        }

    def _build_native_manifest(self, state: Any) -> dict[str, Any]:
        jobs = list(state.jobs.values())
        job = jobs[-1] if jobs else None
        if job is None:
            return {"manifest_sha256": UNKNOWN, "artifact": UNKNOWN,
                    "note": "no delivery job / artifact recorded"}
        artifact = job.get("artifact")
        return {
            "manifest_sha256": job.get("manifest_sha256") or UNKNOWN,
            "workspace_dir": job.get("workspace_dir", UNKNOWN),
            "artifact": artifact if artifact is not None else UNKNOWN,
            "note": "" if artifact is not None else "job produced no artifact (UNKNOWN)",
        }

    def _build_handover_snapshot(self, project_id: str) -> dict[str, Any]:
        ids_values = set(self._trace.ids_for(project_id).values())
        incidents = [i for i in self._trace.incidents.all_incidents()
                     if i.object_id in ids_values]
        if not incidents:
            return {"project_id": project_id, "incidents": [],
                    "handover_context": UNKNOWN,
                    "note": "no incident references this project's objects (UNKNOWN)"}
        return {
            "project_id": project_id,
            "incidents": [
                {"incident_id": i.incident_id, "triage": i.triage, "handover": i.handover}
                for i in incidents
            ],
            "handover_context": self._trace.handover(incidents[0].incident_id),
        }

    def _build_design_change_md(self, state: Any, impact: dict[str, Any]) -> str:
        contract = state.contract
        lines = [
            f"# 设计变更 · {contract.name}",
            "",
            f"- 契约：`{contract.id}` · revision **{state.revision}** · profile `{state.profile_id}`",
            f"- 意图摘要：{impact.get('subject', {}).get('reason') or 'UNKNOWN（无记录的变更理由）'}",
            "",
            "## 变更历史（change_log）",
        ]
        if state.change_log:
            for c in state.change_log:
                lines.append(f"- rev {c.get('rev')} · request `{c.get('request_id')}` · source {c.get('source')}")
        else:
            lines.append("- 无记录变更（UNKNOWN）")
        lines += [
            "",
            "## 风险与未知项（来自 impact 报告）",
            f"- 状态保持风险：{impact.get('state_retention_risk', UNKNOWN)}",
            f"- 在线加载影响：{impact.get('online_load_impact', UNKNOWN)}",
            f"- 未知字段：{', '.join(impact.get('unknown_fields') or []) or '无'}",
            f"- 高风险交付阻断：{'是' if impact.get('blocked_high_risk_delivery') else '否'}",
            "",
            "> 编译通过 ≠ 可上线；本工件是候选变更说明，不构成部署许可。",
        ]
        return "\n".join(lines)

    # ---- bundle assembly ------------------------------------------------------

    def build(self, project_id: str) -> dict[str, Any]:
        state = self._store._get(project_id)  # raises NotFound -> 404 at route
        impact = self._build_impact(project_id, state)
        patch_history = self._patch_history_for(project_id)
        files: dict[str, str] = {
            "design_change.md": self._build_design_change_md(state, impact),
            "semantic_diff.json": _j({
                "project_id": project_id,
                "revision": state.revision,
                "change_log": state.change_log,
                "patches": patch_history,
                "latest_patch_ops": patch_history[-1].get("ops") if patch_history else UNKNOWN,
                "note": "" if state.change_log else "no recorded changes (UNKNOWN)",
            }),
            "impact_report.json": _j(impact),
            "af_compliance.json": _j(self._store.validate(project_id)),
            "behavior_test_report.json": _j(self._store.simulate(project_id)),
            "compile_receipt.json": _j(self._build_compile_receipt(state)),
            "source_map.json": _j(self._build_source_map(project_id)),
            "native_artifact_manifest.json": _j(self._build_native_manifest(state)),
            "handover_snapshot.json": _j(self._build_handover_snapshot(project_id)),
        }
        bundle_id = "prb_" + uuid.uuid4().hex[:8]
        generated_at = utcnow()
        record = {
            "bundle_id": bundle_id,
            "project_id": project_id,
            "revision": state.revision,
            "generated_at": generated_at,
            "files": files,
            "file_digests": {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                             for name, text in files.items()},
        }
        with self._session() as dao:
            dao.put(bundle_id, "bundle", record)
        return record

    def get(self, bundle_id: str) -> dict[str, Any] | None:
        with self._session() as dao:
            row = dao.get(bundle_id)
        if row is None:
            return None
        return {k: v for k, v in row.items() if k not in ("id", "kind")}


_ROUTES_FLAG = "_pr_bundle_routes_registered"


def register_routes(app: FastAPI) -> None:
    """Idempotently mount the PR-bundle routes."""
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)

    def service_of(request: Request) -> PrBundleService:
        svc = getattr(request.app.state, "pr_bundles", None)
        if svc is None:
            svc = PrBundleService(
                store=getattr(request.app.state, "store", None),
                trace=getattr(request.app.state, "trace", None),
                impact=getattr(request.app.state, "impact", None),
                db=getattr(request.app.state, "db_path", None),
                patch_history=getattr(request.app.state, "patch_history", None),
            )
            request.app.state.pr_bundles = svc
        return svc

    @app.post("/api/processos/projects/{pid}/pr-bundle")
    def create_pr_bundle(request: Request, pid: str) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is None or pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        bundle = service_of(request).build(pid)
        return bundle

    @app.get("/api/processos/pr-bundles/{bundle_id}")
    def get_pr_bundle(request: Request, bundle_id: str) -> dict[str, Any]:
        bundle = service_of(request).get(bundle_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail=f"unknown pr bundle {bundle_id}")
        return bundle
