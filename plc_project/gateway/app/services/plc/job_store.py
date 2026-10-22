"""In-memory PLC job records, progress entries, and export helpers."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from gateway.app.services import store as mem


def _now() -> datetime:
    return datetime.now(UTC)


def _job_id() -> str:
    return f"plc_{uuid4().hex[:16]}"
def create_job_record(
    *,
    source_type: str,
    source_path: str,
    project_name: str,
    created_by: str,
    upload_filename: str | None = None,
) -> dict[str, Any]:
    now = _now()
    job = {
        "id": _job_id(),
        "status": "queued",
        "source_type": source_type,
        "source_path": source_path,
        "upload_filename": (upload_filename or "").strip() or None,
        "project_name": project_name,
        "created_by": created_by,
        "summary": {},
        "extraction_notes": [],
        "logic_graph": {"nodes": [], "edges": []},
        "knowledge_graph": {"nodes": [], "edges": []},
        "scl_sources": {},
        "folded_logic": {},
        "report": "",
        "graph_publish": None,
        "blocks": [],
        "structure": {},
        "chat": [],
        "engineer_understanding": None,
        "device_card_annotations": {},
        "export_dir": None,
        "export_ready": False,
        "project_path": None,
        "openness_export_dir": None,
        "changeset": None,
        "writeback": None,
        "optimize_plan": "",
        "scl_files": {},
        "scl_diffs": [],
        "scl_skipped": [],
        "source_xmls": [],
        "progress": [],
        "timings": {},
        "coverage": {},
        "hardware": [],
        "tag_tables": [],
        "brief_ready": False,
        "ingest_phase": "queued",
        "body_pull_queue": [],
        "block_stubs": [],
        "device_cards": [],
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    with mem.store._lock:
        mem.store.plc_jobs[job["id"]] = job
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    return mem.store.plc_jobs.get(job_id)


def delete_job(job_id: str) -> bool:
    """Remove a PLC job from the in-memory store. Returns True if it existed."""
    with mem.store._lock:
        return mem.store.plc_jobs.pop(job_id, None) is not None


def query_job_graph(job: dict[str, Any], op: str, **params: Any) -> dict[str, Any]:
    """Run a deterministic query against a PLC job's knowledge graph."""
    from agents.plc.tia.graph_query import query

    return query(job.get("knowledge_graph") or {}, op, **params)


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    jobs = list(mem.store.plc_jobs.values())
    jobs.sort(key=lambda j: j.get("created_at") or _now(), reverse=True)
    return jobs[: max(1, min(limit, 100))]
def _append_progress(
    job: dict[str, Any],
    step: str,
    title: str,
    *,
    detail: str = "",
    status: str = "done",
    duration_ms: int | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "step": step,
        "title": title,
        "detail": detail,
        "status": status,
        "at": _now().isoformat(),
    }
    if duration_ms is not None:
        entry["duration_ms"] = int(duration_ms)
    job.setdefault("progress", []).append(entry)
    job["updated_at"] = _now()
    return entry


def _start_progress(
    job: dict[str, Any],
    step: str,
    title: str,
    *,
    detail: str = "",
) -> dict[str, Any]:
    import time

    entry = _append_progress(job, step, title, detail=detail, status="running")
    entry["_t0"] = time.monotonic()
    return entry


def _finish_progress(
    job: dict[str, Any],
    *,
    detail: str | None = None,
    status: str = "done",
) -> int:
    import time

    progress = job.get("progress") or []
    if not progress:
        return 0
    entry = progress[-1]
    t0 = entry.pop("_t0", None)
    duration_ms = int((time.monotonic() - t0) * 1000) if isinstance(t0, (int, float)) else 0
    entry["duration_ms"] = duration_ms
    entry["status"] = status
    entry["at"] = _now().isoformat()
    if detail is not None:
        entry["detail"] = detail
    job["updated_at"] = _now()
    return duration_ms
def analyze_job(job: dict[str, Any], *, block_name: str | None = None) -> dict[str, Any]:
    """Run deterministic, evidence-gated PLC analysis without any LLM call."""
    from agents.plc.tia.analyst import analyze_block, analyze_project
    from agents.plc.tia.review import run_review

    result = analyze_block(job, block_name) if block_name else analyze_project(job)
    result["review"] = run_review(job)
    return result


def build_export_zip(job: dict[str, Any]) -> bytes:
    export_dir = job.get("export_dir")
    if not export_dir or not Path(export_dir).is_dir():
        raise FileNotFoundError("Export package not ready")
    buf = io.BytesIO()
    root = Path(export_dir)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(root)))
        # Also include logic graph snapshot
        zf.writestr(
            "ui_snapshots/logic_graph.json",
            json.dumps(job.get("logic_graph") or {}, ensure_ascii=False, indent=2),
        )
    return buf.getvalue()


def append_chat_turn(
    job: dict[str, Any],
    *,
    role: str,
    content: str,
    block_name: str | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> None:
    job.setdefault("chat", []).append(
        {
            "role": role,
            "content": content,
            "block_name": block_name,
            "citations": list(citations or []),
            "created_at": _now(),
        }
    )
    job["updated_at"] = _now()
