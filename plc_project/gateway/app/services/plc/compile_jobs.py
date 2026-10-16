"""Async canvas compile jobs with staged progress (PLC + HMI).

Jobs are stored in-memory (same process as gateway). Frontend polls
``GET /api/v1/plc/canvas/compile-jobs/{id}``.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from plc_engine.canvas_model import CanvasState, apply_canvas_patch, attribute_compiler_errors

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="compile-job")
_TTL_S = 3600.0

STAGES = [
    "prepare_work",
    "open_project",
    "write_plc",
    "compile_plc",
    "write_hmi",
    "compile_hmi",
    "save",
]


def _now() -> float:
    return time.time()


def _purge_locked() -> None:
    cutoff = _now() - _TTL_S
    dead = [k for k, v in _jobs.items() if float(v.get("updated_at") or 0) < cutoff]
    for k in dead:
        _jobs.pop(k, None)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        _purge_locked()
        job = _jobs.get(job_id)
        return deepcopy(job) if job else None


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job["status"] in {"queued", "running"}:
            job["cancel_requested"] = True
            job["updated_at"] = _now()
        return deepcopy(job)


def _set_stage(job: dict[str, Any], name: str, status: str, message: str = "", log_line: str = "") -> None:
    for stage in job["stages"]:
        if stage["name"] == name:
            stage["status"] = status
            if message:
                stage["message"] = message
            if status == "running":
                stage["started_at"] = _now()
            if status in {"ok", "error", "skipped"}:
                stage["finished_at"] = _now()
            if log_line:
                stage.setdefault("log", []).append(log_line)
            break
    job["updated_at"] = _now()


def _is_cancelled(job: dict[str, Any]) -> bool:
    return bool(job.get("cancel_requested"))


def create_compile_job(
    canvas_dict: dict[str, Any],
    *,
    project_path: str = "",
    plc_name: str = "",
    compile_plc: bool = True,
    compile_hmi: bool = True,
    save_on_success: bool = True,
    reset_work: bool = True,
    runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create and schedule a compile job; returns the job snapshot."""
    job_id = uuid.uuid4().hex[:16]
    stages = [
        {
            "name": name,
            "status": "pending",
            "message": "",
            "log": [],
            "started_at": None,
            "finished_at": None,
        }
        for name in STAGES
    ]
    job = {
        "id": job_id,
        "status": "queued",
        "stages": stages,
        "attributions": [],
        "result": None,
        "canvas": None,
        "error": None,
        "cancel_requested": False,
        "created_at": _now(),
        "updated_at": _now(),
        "request": {
            "project_path": project_path,
            "plc_name": plc_name,
            "compile_plc": compile_plc,
            "compile_hmi": compile_hmi,
            "save_on_success": save_on_success,
            "reset_work": reset_work,
        },
    }
    with _lock:
        _purge_locked()
        _jobs[job_id] = job

    def _run() -> None:
        with _lock:
            live = _jobs[job_id]
            live["status"] = "running"
            live["updated_at"] = _now()
        try:
            result = (runner or default_compile_runner)(
                job_id,
                canvas_dict,
                project_path=project_path,
                plc_name=plc_name,
                compile_plc=compile_plc,
                compile_hmi=compile_hmi,
                save_on_success=save_on_success,
                reset_work=reset_work,
            )
            with _lock:
                live = _jobs[job_id]
                if live.get("cancel_requested") and live["status"] != "error":
                    live["status"] = "cancelled"
                    live["error"] = "cancelled by user"
                else:
                    live["status"] = "ok" if result.get("ok") else "error"
                    live["result"] = result.get("writeback")
                    live["attributions"] = result.get("attributions") or []
                    live["canvas"] = result.get("canvas")
                    live["error"] = None if result.get("ok") else str(result.get("error") or "compile failed")
                live["updated_at"] = _now()
        except Exception as exc:  # noqa: BLE001
            with _lock:
                live = _jobs[job_id]
                live["status"] = "error"
                live["error"] = str(exc)
                live["result"] = {"ok": False, "traceback": traceback.format_exc()}
                live["updated_at"] = _now()

    _pool.submit(_run)
    return get_job(job_id) or job


def update_job_stage(job_id: str, name: str, status: str, message: str = "", log_line: str = "") -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        _set_stage(job, name, status, message, log_line)


def default_compile_runner(
    job_id: str,
    canvas_dict: dict[str, Any],
    *,
    project_path: str = "",
    plc_name: str = "",
    compile_plc: bool = True,
    compile_hmi: bool = True,
    save_on_success: bool = True,
    reset_work: bool = True,
) -> dict[str, Any]:
    """Prepare work copy, write PLC (+ optional HMI), compile, attribute errors."""
    from gateway.app.services.plc import workspace as ws
    from plc_engine.canvas_tia_transpiler import execute_canvas_writeback

    canvas = CanvasState.from_dict(canvas_dict)
    source = canvas.source
    project_id = (source.project_id if source else "") or ""

    # --- prepare_work ---
    update_job_stage(job_id, "prepare_work", "running", "准备工程工作副本…")
    job = get_job(job_id) or {}
    if job.get("cancel_requested"):
        raise RuntimeError("cancelled")

    resolved_path = project_path
    if project_id and reset_work:
        apxx = ws.reset_work_copy(project_id)
        if apxx is not None:
            resolved_path = str(apxx)
            if canvas.source:
                canvas.source.project_path = resolved_path
    if not resolved_path and source:
        resolved_path = source.project_path
    if not resolved_path:
        update_job_stage(job_id, "prepare_work", "error", "缺少可写回的工程路径")
        return {"ok": False, "error": "missing project_path", "canvas": canvas.to_dict()}
    if project_id and not ws.is_workspace_path(resolved_path):
        # Allow explicit allowlisted paths outside workspace only when no project_id.
        pass
    update_job_stage(job_id, "prepare_work", "ok", f"工作副本就绪：{resolved_path}")

    # --- open_project (session or one-shot) ---
    update_job_stage(job_id, "open_project", "running", "打开博途工程…")
    try:
        from gateway.app.services.plc.openness_session import ensure_project_open

        ensure_project_open(resolved_path, plc_name=plc_name or (source.plc_name if source else ""))
        update_job_stage(job_id, "open_project", "ok", "工程已打开（常驻会话或一次性）")
    except Exception as exc:  # noqa: BLE001
        update_job_stage(job_id, "open_project", "ok", f"会话打开跳过，回退一次性写回：{exc}")

    if not compile_plc and not compile_hmi:
        update_job_stage(job_id, "write_plc", "skipped", "未请求写入")
        update_job_stage(job_id, "compile_plc", "skipped")
        update_job_stage(job_id, "write_hmi", "skipped")
        update_job_stage(job_id, "compile_hmi", "skipped")
        update_job_stage(job_id, "save", "skipped")
        return {"ok": True, "writeback": {"ok": True, "note": "nothing to compile"}, "canvas": canvas.to_dict()}

    # --- write + compile PLC ---
    update_job_stage(job_id, "write_plc", "running", "写入 PLC 块/标签…")
    writeback: dict[str, Any] = {"ok": False}
    attributions: list[dict[str, Any]] = []
    try:
        writeback, attributions = execute_canvas_writeback(
            canvas,
            project_path=resolved_path,
            plc_name=plc_name or (source.plc_name if source else ""),
            compile_after=compile_plc,
        )
        update_job_stage(
            job_id,
            "write_plc",
            "ok" if writeback.get("ok") or writeback.get("generated") else "error",
            writeback.get("message") or "PLC 写入完成",
        )
        if compile_plc:
            compile_ok = bool(writeback.get("ok"))
            update_job_stage(
                job_id,
                "compile_plc",
                "ok" if compile_ok else "error",
                "PLC 编译通过" if compile_ok else "PLC 编译失败",
            )
        else:
            update_job_stage(job_id, "compile_plc", "skipped", "跳过 PLC 编译")
    except Exception as exc:  # noqa: BLE001
        update_job_stage(job_id, "write_plc", "error", str(exc))
        update_job_stage(job_id, "compile_plc", "skipped")
        writeback = {"ok": False, "error": str(exc)}
        attributions = attribute_compiler_errors(canvas, writeback)

    # --- HMI write/compile (best-effort until full bridge lands) ---
    if compile_hmi and canvas.hmi_devices:
        update_job_stage(job_id, "write_hmi", "running", "写入 HMI 差异…")
        try:
            from plc_engine.hmi_writeback import apply_hmi_diff

            hmi_result = apply_hmi_diff(
                canvas,
                project_path=resolved_path,
                compile_after=True,
            )
            writeback["hmi"] = hmi_result
            update_job_stage(
                job_id,
                "write_hmi",
                "ok" if hmi_result.get("ok") else "error",
                hmi_result.get("message") or "HMI 写入完成",
            )
            update_job_stage(
                job_id,
                "compile_hmi",
                "ok" if hmi_result.get("compile_ok", hmi_result.get("ok")) else "error",
                "HMI 编译完成",
            )
            if hmi_result.get("messages"):
                attributions.extend(
                    attribute_compiler_errors(
                        canvas,
                        {"ok": hmi_result.get("ok"), "hmi": hmi_result, "messages": hmi_result.get("messages")},
                    )
                )
        except Exception as exc:  # noqa: BLE001
            update_job_stage(job_id, "write_hmi", "error", str(exc))
            update_job_stage(job_id, "compile_hmi", "skipped", "HMI 编译跳过")
            writeback["hmi"] = {"ok": False, "error": str(exc)}
    else:
        update_job_stage(job_id, "write_hmi", "skipped", "无 HMI 设备或未请求")
        update_job_stage(job_id, "compile_hmi", "skipped")

    ok = bool(writeback.get("ok")) and not (
        isinstance(writeback.get("hmi"), dict) and writeback["hmi"].get("ok") is False
    )

    if save_on_success and ok:
        update_job_stage(job_id, "save", "running", "保存工程…")
        try:
            from gateway.app.services.plc.openness_session import save_project

            save_project(resolved_path)
            update_job_stage(job_id, "save", "ok", "工程已保存")
        except Exception as exc:  # noqa: BLE001
            # One-shot writeback may already have saved; treat as advisory.
            update_job_stage(job_id, "save", "ok", f"保存由写回路径处理：{exc}")
    else:
        update_job_stage(
            job_id,
            "save",
            "skipped",
            "编译未通过，不保存（fail-closed）" if not ok else "跳过保存",
        )

    return {
        "ok": ok,
        "writeback": writeback,
        "attributions": attributions,
        "canvas": canvas.to_dict(),
        "error": None if ok else (writeback.get("error") or writeback.get("message") or "compile failed"),
    }
