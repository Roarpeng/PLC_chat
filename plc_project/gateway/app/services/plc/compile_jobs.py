"""Async canvas compile jobs with staged progress (PLC + HMI).

Jobs are stored in-memory (same process as gateway). Frontend polls
``GET /api/v1/plc/canvas/compile-jobs/{id}``.

Execution has two modes:

- in-thread (default): the runner runs on ``_pool``; ``future.result(timeout=)``
  can only *detect* a timeout, it cannot stop a runner blocked inside an
  Openness call — the worker thread keeps the Openness handle until Openness
  itself returns, permanently leaking a pool slot.
- subprocess (``PLC_COMPILE_JOB_SUBPROCESS=1``): the runner runs in a spawned
  child process. Timeout/cancel kills the whole child process tree, so the
  Openness sidecar (and the TIA instance it started) dies with it and the pool
  slot is reclaimed. Stage/cancel/result travel over a Pipe + shared Event.

进程级 kill 的边界（诚实声明）：

- 只有**一次性 CLI 路径**（``RESEARCHOS_TIA_SESSION=0``，默认）才杀得干净：
  ``agents.plc.tia.openness_cli.openness_cli()`` 用 ``subprocess.run`` 把
  TiaOpenness.Server.exe 拉起为编译子进程的孙进程，``taskkill /F /T`` 连树杀掉
  后，TIA 持有的 .apXX 工程锁随进程消亡而释放。
- 常驻会话模式（``RESEARCHOS_TIA_SESSION=1``，当前未启用）：TIA 实例属于
  会话服务进程，不属于编译子进程树——杀编译子进程**释放不了**会话持有的工程
  锁。在「写入/编译也走会话 API 且会话自带可中断语义」落地前，不要为它会话
  模式强杀而改架构（services.toml 已默认关闭会话）。
- Openness worker 模式（非 Windows 本机 + ``RESEARCHOS_OPENNESS_WORKER_URL``）：
  exe 跑在 worker 服务进程树里，网关侧 kill 够不着，超时只能打标记（worker 内
  的 ``_OPENNESS_LOCK`` 会被卡住的线程持有）。

工程文件损坏缓解：写回链路（``agents.plc.tia.writeback.execute_writeback``）
在任何 Openness 写入**之前**先做写前备份（``writeback_safety.backup_target``，
备份失败 fail-closed 不写）。强杀只发生在硬超时（默认 1500s）或取消宽限
（默认 15s）到期之后；若怀疑杀在写入中途导致工程损坏，用
``writeback_safety.restore_from_backup`` 从写前备份还原（超时/取消消息里会
给出提示）。
"""

from __future__ import annotations

import atexit
import multiprocessing
import os
import signal
import subprocess
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from copy import deepcopy
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import CanvasState, attribute_compiler_errors

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="compile-job")
_TTL_S = 3600.0

# 子进程句柄（单独存放：_jobs 会被 deepcopy 出去，不能放 Process 对象）
_children: dict[str, "_ChildHandle"] = {}

# 作业总超时（秒）：环境变量 COMPILE_JOB_TIMEOUT_S 可配，<=0 表示不限制
_DEFAULT_JOB_TIMEOUT_S = 900.0
_TIMEOUT_ENV = "COMPILE_JOB_TIMEOUT_S"
# 允许写回的工程目录 allowlist（os.pathsep 分隔；Windows 下为 ';'）
_ALLOWED_DIRS_ENV = "PLC_ALLOWED_PROJECT_DIRS"
# 预检错误在 write_plc 阶段 message 里最多展示的条数
_PRECHECK_MSG_LIMIT = 5

# 子进程隔离开关：=1 时把内置 runner 放进子进程（超时可真杀）
_SUBPROCESS_ENV = "PLC_COMPILE_JOB_SUBPROCESS"
# 连显式注入的 runner 也放进子进程 —— 仅供单测注入假阻塞任务，生产不要开
_SUBPROCESS_ALL_ENV = "PLC_COMPILE_JOB_SUBPROCESS_ALL"
# 父进程读子进程事件的轮询间隔（秒）
_CHILD_POLL_S = 0.2
# 子进程退出/被杀后的等待上限（秒）
_CHILD_JOIN_S = 5.0
# 取消后给子进程的协作退出宽限（秒），到期仍活着就强杀
_CANCEL_GRACE_S = 15.0
# taskkill / killpg 的兜底超时（秒）
_TREE_KILL_TIMEOUT_S = 30.0

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


def job_timeout_seconds() -> float:
    """作业硬超时（秒）。env COMPILE_JOB_TIMEOUT_S；<=0 表示不限制。"""
    raw = os.getenv(_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_JOB_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_JOB_TIMEOUT_S
    return value if value > 0 else 0.0


def allowed_project_dirs() -> list[Path]:
    """允许写回的工程目录 allowlist；未配置时返回空（回落到工作区校验）。"""
    raw = os.getenv(_ALLOWED_DIRS_ENV, "").strip()
    if not raw:
        return []
    return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]


def _is_relative_to(target: Path, parent: Path) -> bool:
    try:
        target.relative_to(parent.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def is_allowed_project_path(path: str | Path, *, project_id: str = "") -> bool:
    """allowlist 校验：目标工程路径必须落在允许目录（或工作区）内。

    - 配置了 PLC_ALLOWED_PROJECT_DIRS：必须在其中任一目录内；
    - 未配置但有 project_id：必须写回工作区副本，避免污染原始工程；
    - 未配置且无 project_id（显式传入路径）：放行。
    """
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return False
    dirs = allowed_project_dirs()
    if dirs:
        return any(_is_relative_to(target, d) for d in dirs)
    if project_id:
        from gateway.app.services.plc import workspace as ws

        return ws.is_workspace_path(target)
    return True


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
            handle = _children.get(job_id)
            if handle is not None:
                # 子进程模式下还要跨进程把取消信号送过去，让阶段边界的守卫能命中
                handle.cancel.set()
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


def is_cancel_requested(job_id: str) -> bool:
    """读取实时 job 的取消标记（job 已被 TTL 清理时视为未取消）。

    子进程模式下改读父进程设置的共享 Event —— 子进程的 ``_jobs`` 是空的。
    """
    if _bridge is not None:
        return _bridge.is_cancelled()
    job = get_job(job_id)
    return _is_cancelled(job) if job else False


def _mark_remaining_skipped(job_id: str, names: list[str], reason: str) -> None:
    """把给定阶段标成 skipped（用于前置校验失败等场景）。"""
    if _bridge is not None:
        _bridge.skipped(names, reason)
        return
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for name in names:
            _set_stage(job, name, "skipped", reason)
        job["updated_at"] = _now()


def _mark_cancelled(job_id: str, names: list[str]) -> None:
    """取消落地：当前及后续阶段标 skipped，job 标 cancelled。"""
    if _bridge is not None:
        _bridge.cancelled(names)
        return
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for name in names:
            _set_stage(job, name, "skipped", "已取消，未执行")
        job["status"] = "cancelled"
        job["error"] = "cancelled by user"
        job["updated_at"] = _now()


def _cancel_guard(job_id: str, remaining: list[str]) -> bool:
    """阶段边界取消检查。

    命中则把 remaining 中的阶段标 skipped、job 标 cancelled 并返回 True，
    调用方应立即 return，不再继续写工程。
    """
    if not is_cancel_requested(job_id):
        return False
    _mark_cancelled(job_id, remaining)
    return True


def _mark_timeout(job_id: str, *, killed_process: bool = False) -> None:
    """硬超时落地：job error/timeout，当前 running 阶段 error，未执行阶段 skipped。

    ``killed_process=True`` 表示编译子进程树已被强杀（一次性 CLI 路径下 Openness
    exe 一并死亡，TIA 工程锁应已释放）；消息里附上写前备份还原提示。
    """
    timeout_s = job_timeout_seconds()
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["status"] != "running":
            return
        job["timed_out"] = True
        # 线程模式下这是「尽力通知」worker 线程在阶段边界自查退出（无法强制中断
        # Openness 调用）；子进程模式下进程已被杀，这里只是标记。
        job["cancel_requested"] = True
        job["status"] = "error"
        job["error"] = "timeout"
        for stage in list(job["stages"]):
            if stage["status"] == "running":
                msg = f"阶段执行超时（>{timeout_s:.0f}s）"
                if killed_process:
                    msg += "；已强制结束编译子进程及 Openness CLI，工程锁应已释放。若怀疑工程损坏，可用写前备份还原（restore_from_backup）"
                _set_stage(job, stage["name"], "error", msg)
            elif stage["status"] in {"pending", "queued"}:
                _set_stage(job, stage["name"], "skipped", "作业超时，阶段未执行")
        job["updated_at"] = _now()


# --- 子进程隔离：超时能真杀的那条路 -----------------------------------------


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _use_child_process(runner: Callable[..., dict[str, Any]] | None) -> bool:
    """是否把 runner 放进子进程。

    - runner is None（内置 default_compile_runner）：由 PLC_COMPILE_JOB_SUBPROCESS 开关；
    - runner 被显式注入：默认仍走线程（保持既有语义/单测打桩），只有
      PLC_COMPILE_JOB_SUBPROCESS_ALL=1 时才进子进程，且必须是模块级函数（能按引用 pickle）。
    """
    if runner is None:
        return _env_flag(_SUBPROCESS_ENV)
    if not _env_flag(_SUBPROCESS_ALL_ENV):
        return False
    return "<locals>" not in getattr(runner, "__qualname__", "<locals>")


_bridge: _ChildBridge | None = None


class _ChildBridge:
    """子进程侧的事件出口：把阶段/取消/结果写回父进程的连接。

    父进程侧 ``_bridge`` 恒为 None，所有写状态函数照旧直接改 ``_jobs``。
    """

    __slots__ = ("_conn", "_cancel")

    def __init__(self, conn: Any, cancel: Any) -> None:
        self._conn = conn
        self._cancel = cancel

    def _send(self, message: tuple[Any, ...]) -> None:
        try:
            self._conn.send(message)
        except (OSError, ValueError, BrokenPipeError):  # 父进程已放弃读取
            pass

    def stage(self, name: str, status: str, message: str = "", log_line: str = "") -> None:
        self._send(("stage", name, status, message, log_line))

    def cancelled(self, names: list[str]) -> None:
        self._send(("cancel", list(names)))

    def skipped(self, names: list[str], reason: str) -> None:
        self._send(("skip", list(names), reason))

    def result(self, payload: dict[str, Any]) -> None:
        self._send(("result", payload))

    def failure(self, message: str, tb: str) -> None:
        self._send(("failure", message, tb))

    def is_cancelled(self) -> bool:
        return bool(self._cancel.is_set())


class _ChildHandle:
    """父进程持有的子进程句柄（进程 + 取消信号）。"""

    __slots__ = ("proc", "cancel")

    def __init__(self, proc: Any, cancel: Any) -> None:
        self.proc = proc
        self.cancel = cancel


def _child_entry(conn: Any, cancel: Any, job_id: str, payload: dict[str, Any]) -> None:
    """子进程入口：在独立解释器里跑 runner，只通过 conn 与父进程通信。"""
    global _bridge
    _bridge = _ChildBridge(conn, cancel)
    runner = payload.get("runner") or default_compile_runner
    try:
        result = runner(job_id, payload["canvas"], **payload["kwargs"])
    except Exception as exc:  # noqa: BLE001 - 异常要连同栈一起回传父进程
        _bridge.failure(str(exc), traceback.format_exc())
        return
    _bridge.result(result)


def _kill_process_tree(pid: int) -> None:
    """尽力杀掉 pid 及其子孙进程。

    Windows 用 ``taskkill /F /T``：一次性 CLI 拉起的 TiaOpenness.Server.exe（以及它
    启动的 TIA 实例）都是本进程的子孙，只有整树杀掉才不会留下占着工程的孤儿。
    POSIX 下退化为进程组 kill（仅当子进程不在父进程组内时，避免自杀）。
    """
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=_TREE_KILL_TIMEOUT_S,
                check=False,
            )
        elif os.getpgid(pid) != os.getpgrp():
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001 - 进程可能已退出，杀不掉不应影响作业收尾
        pass


def _kill_child(proc: Any) -> None:
    """真杀子进程：先杀树（防止孙进程变孤儿），再兜底 terminate/kill。"""
    pid = proc.pid
    if pid:
        _kill_process_tree(pid)
    for action in (proc.terminate, proc.kill):
        if not proc.is_alive():
            break
        try:
            action()
        except (OSError, ValueError):  # 已退出
            break
        proc.join(_CHILD_JOIN_S)


def _kill_all_children() -> None:
    """解释器退出前清掉仍在跑的编译子进程（非 daemon 子进程否则会卡住关停）。"""
    with _lock:
        handles = list(_children.values())
    for handle in handles:
        _kill_child(handle.proc)


atexit.register(_kill_all_children)


def _mark_cancelled_after_kill(job_id: str) -> None:
    """子进程被强杀后的取消落地：未结束阶段标 skipped，job 标 cancelled。

    强杀发生在取消宽限（``_CANCEL_GRACE_S``）到期之后——runner 多半卡在
    Openness 写入中途。写入阶段被强杀的消息附上写前备份还原提示。
    """
    write_stages = {"write_plc", "compile_plc", "write_hmi", "compile_hmi", "save"}
    hint = "；子进程已强制结束，若怀疑工程损坏，可用写前备份还原（restore_from_backup）"
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for stage in job["stages"]:
            if stage.get("status") in {"pending", "queued", "running"}:
                msg = "已取消，未执行"
                if stage.get("status") == "running" and stage["name"] in write_stages:
                    msg += hint
                _set_stage(job, stage["name"], "skipped", msg)
        job["status"] = "cancelled"
        job["error"] = "cancelled by user"
        job["updated_at"] = _now()


def _child_crash_result(exitcode: int | None) -> dict[str, Any]:
    """子进程没给结果就没了（被外部杀掉/崩溃）时的 fail-closed 结果。"""
    message = f"编译子进程异常退出（exitcode={exitcode}）"
    return {
        "ok": False,
        "error": message,
        "writeback": {"ok": False, "error": message},
        "attributions": [],
        "canvas": None,
        "degraded": False,
        "precheck": None,
    }


def _apply_child_message(job_id: str, message: tuple[Any, ...]) -> tuple[dict[str, Any] | None, bool]:
    """把子进程事件落到父进程的 job 上；返回 (result, 是否结束)。"""
    kind = message[0]
    if kind == "stage":
        update_job_stage(job_id, *message[1:])
    elif kind == "cancel":
        _mark_cancelled(job_id, message[1])
    elif kind == "skip":
        _mark_remaining_skipped(job_id, message[1], message[2])
    elif kind == "result":
        return message[1], True
    elif kind == "failure":
        return {
            "ok": False,
            "error": str(message[1]),
            "writeback": {"ok": False, "error": str(message[1]), "traceback": str(message[2])},
            "attributions": [],
            "canvas": None,
            "degraded": False,
            "precheck": None,
        }, True
    return None, False


def _run_child_job(
    job_id: str,
    runner: Callable[..., dict[str, Any]] | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """在子进程里跑 runner，超时/取消到期就杀掉整个进程树。

    返回 runner 结果；返回 None 表示终态（timeout/cancelled）已由本函数落地，
    调用方不要再写 job。
    """
    ctx = multiprocessing.get_context("spawn")
    conn_r, conn_w = ctx.Pipe(duplex=False)
    cancel = ctx.Event()
    proc = ctx.Process(
        target=_child_entry,
        args=(conn_w, cancel, job_id, payload),
        name=f"compile-child-{job_id}",
    )
    proc.start()
    conn_w.close()  # 写端只留给子进程

    with _lock:
        live = _jobs.get(job_id)
        if live is None:  # 记录已被 TTL 清理，立刻收掉刚起的进程
            _kill_child(proc)
            conn_r.close()
            return None
        _children[job_id] = _ChildHandle(proc, cancel)

    timeout_s = job_timeout_seconds()
    deadline = _now() + timeout_s if timeout_s > 0 else None
    cancel_deadline: float | None = None
    result: dict[str, Any] | None = None
    eof = False
    try:
        while True:
            if not eof:
                while conn_r.poll(_CHILD_POLL_S if proc.is_alive() else 0.0):
                    try:
                        message = conn_r.recv()
                    except (EOFError, OSError):
                        eof = True
                        break
                    result, done = _apply_child_message(job_id, message)
                    if done:
                        return result
            if not proc.is_alive():
                return result if result is not None else _child_crash_result(proc.exitcode)
            if deadline is not None and _now() >= deadline:
                _kill_child(proc)
                _mark_timeout(job_id, killed_process=True)
                return None
            if is_cancel_requested(job_id):
                if cancel_deadline is None:
                    cancel_deadline = _now() + _CANCEL_GRACE_S
                elif _now() >= cancel_deadline:
                    _kill_child(proc)
                    _mark_cancelled_after_kill(job_id)
                    return None
            if eof:  # 管道已断但进程还在：退化为低频轮询，别把 CPU 打满
                time.sleep(_CHILD_POLL_S)
    finally:
        conn_r.close()
        proc.join(_CHILD_JOIN_S)
        if proc.is_alive():
            _kill_child(proc)
        with _lock:
            _children.pop(job_id, None)


def _watch_timeout(job_id: str, future: Future, *, child: bool = False) -> None:
    """守护线程：`future.result(timeout=...)` 到期即判超时。

    线程模式下这只能“判定”超时并标记 job，杀不掉仍在跑的 worker 线程；
    子进程模式下由 ``_run_child_job`` 自己在到点时杀进程树并以
    ``killed_process=True`` 落地超时（消息含强杀/还原提示），看门狗不再抢先把
    job 标成无 kill 信息的旧文案 —— 它只在 ``_run_child_job`` 自身异常卡死时兜底。
    """
    timeout_s = job_timeout_seconds()
    if timeout_s <= 0:
        return

    def _watch() -> None:
        try:
            future.result(timeout=timeout_s)
        except FuturesTimeoutError:
            if not child:
                _mark_timeout(job_id)
        except Exception:  # noqa: BLE001 - runner 内部已把异常写进 job
            return

    threading.Thread(target=_watch, name=f"compile-watchdog-{job_id}", daemon=True).start()


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
        "degraded": False,
        "timed_out": False,
        "precheck": None,
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
            live = _jobs.get(job_id)
            if live is None:  # 记录已被 TTL 清理
                return
            live["status"] = "running"
            live["updated_at"] = _now()
        child_payload: dict[str, Any] | None = None
        if use_child:
            # 子进程隔离：runner（含其拉起的 Openness exe）整树可杀，
            # 超时/取消不再是「只打标记」。kwargs 必须可 pickle。
            child_payload = {
                "runner": runner,  # None → 子进程里用 default_compile_runner
                "canvas": canvas_dict,
                "kwargs": {
                    "project_path": project_path,
                    "plc_name": plc_name,
                    "compile_plc": compile_plc,
                    "compile_hmi": compile_hmi,
                    "save_on_success": save_on_success,
                    "reset_work": reset_work,
                },
            }
        try:
            if child_payload is not None:
                result = _run_child_job(job_id, runner, child_payload)
            else:
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
        except Exception as exc:  # noqa: BLE001
            with _lock:
                live = _jobs.get(job_id)
                if live is None:
                    return
                if live.get("timed_out"):
                    # 已判定超时，保留 timeout 结论（worker 线程仍在跑，无法强杀）
                    live["updated_at"] = _now()
                    return
                if live.get("cancel_requested"):
                    live["status"] = "cancelled"
                    live["error"] = "cancelled by user"
                else:
                    live["status"] = "error"
                    live["error"] = str(exc)
                    live["result"] = {"ok": False, "traceback": traceback.format_exc()}
                live["updated_at"] = _now()
            return

        if result is None:
            # 子进程模式终态（超时被杀 → timed_out；取消被杀 → cancelled）
            # 已由 _run_child_job 落地，这里不得再写 job 覆盖结论。
            return

        with _lock:
            live = _jobs.get(job_id)
            if live is None:
                return
            if live.get("timed_out"):
                # 同上：不覆盖超时结论
                live["updated_at"] = _now()
                return
            live["result"] = result.get("writeback")
            live["attributions"] = result.get("attributions") or []
            live["canvas"] = result.get("canvas")
            live["degraded"] = bool(result.get("degraded"))
            live["precheck"] = result.get("precheck")
            if result.get("cancelled") or (live.get("cancel_requested") and live["status"] != "error"):
                live["status"] = "cancelled"
                live["error"] = "cancelled by user"
            else:
                live["status"] = "ok" if result.get("ok") else "error"
                live["error"] = None if result.get("ok") else str(result.get("error") or "compile failed")
            live["updated_at"] = _now()

    use_child = _use_child_process(runner)

    _watch_timeout(job_id, _pool.submit(_run), child=use_child)
    return get_job(job_id) or job


def update_job_stage(job_id: str, name: str, status: str, message: str = "", log_line: str = "") -> None:
    if _bridge is not None:
        # 子进程侧：_jobs 是空的，阶段更新必须经 bridge 发回父进程落地，
        # 否则 default_compile_runner 里的 update_job_stage 会被静默丢弃。
        _bridge.stage(name, status, message, log_line)
        return
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        _set_stage(job, name, status, message, log_line)


def _cancelled_result(
    canvas: CanvasState,
    *,
    degraded: bool = False,
    writeback: dict[str, Any] | None = None,
    attributions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """取消后的统一返回：ok=False 且带 cancelled 标记，不再继续写工程。"""
    return {
        "ok": False,
        "cancelled": True,
        "error": "cancelled by user",
        "writeback": writeback if writeback is not None else {"ok": False, "cancelled": True},
        "attributions": attributions or [],
        "canvas": canvas.to_dict(),
        "degraded": degraded,
    }


def _precheck_failure_result(job_id: str, canvas: CanvasState, report: dict[str, Any]) -> dict[str, Any]:
    """预检失败：标记阶段并给出 fail-closed 结果（不准备工作副本、不打开工程、不写 TIA）。"""
    errors = list(report.get("errors") or [])
    head = "；".join(
        f"[{e.get('target_type')}:{e.get('target_id')}] {e.get('message')}"
        for e in errors[:_PRECHECK_MSG_LIMIT]
    )
    more = f" …共 {len(errors)} 条" if len(errors) > _PRECHECK_MSG_LIMIT else ""
    message = f"本地预检失败，未写入 TIA：{head}{more}"

    # 在画布上标红出错的块，便于前端定位
    for finding in errors:
        if finding.get("target_type") != "block":
            continue
        block = canvas.blocks.get(str(finding.get("target_id")))
        if block is None:
            continue
        block.status = "error"
        text = str(finding.get("message") or "")
        if text and text not in block.errors:
            block.errors.append(text)

    update_job_stage(job_id, "prepare_work", "skipped", "预检失败，未准备工作副本（fail-closed）")
    update_job_stage(job_id, "open_project", "skipped", "预检失败，未打开工程")
    update_job_stage(job_id, "write_plc", "error", message)
    update_job_stage(job_id, "compile_plc", "skipped", "预检失败，跳过 PLC 编译")
    update_job_stage(job_id, "write_hmi", "skipped", "预检失败，跳过 HMI 写入")
    update_job_stage(job_id, "compile_hmi", "skipped", "预检失败，跳过 HMI 编译")
    update_job_stage(job_id, "save", "skipped", "预检失败，不保存")
    return {
        "ok": False,
        "error": "precheck_failed",
        "writeback": {"ok": False, "error": "precheck_failed", "message": message, "precheck": report},
        "attributions": [
            {
                "target_type": f.get("target_type"),
                "target_id": f.get("target_id"),
                "severity": f.get("severity") or "error",
                "message": f.get("message") or "",
                "source": "precheck",
            }
            for f in (report.get("findings") or [])
        ],
        "canvas": canvas.to_dict(),
        "precheck": report,
        "degraded": False,
    }


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
    from plc_engine.canvas_tia_transpiler import (
        execute_canvas_writeback,
        precheck_canvas_for_writeback,
    )

    canvas = CanvasState.from_dict(canvas_dict)
    source = canvas.source
    project_id = (source.project_id if source else "") or ""

    # --- precheck 门禁（fail-closed）---
    # 前置到 prepare_work 之前：预检有 error 时不准备工作副本、不打开工程、不写 TIA。
    # 只预检「待写回」的块：画布刚导入、用户什么都没改时（全部 synced）不会写任何
    # 内容进 TIA，此时若拿全部块的 TODO 去拦，会让"导入→编译验证"这条最基本的
    # 路径直接不可用（真实工程 HR001 实测就是这个症状）。
    pending_blocks = {
        name: blk
        for name, blk in canvas.blocks.items()
        if str(getattr(blk, "status", "")) != "synced"
    }
    if pending_blocks:
        precheck_target = CanvasState(
            project_name=canvas.project_name,
            blocks=pending_blocks,
            hmi_widgets=canvas.hmi_widgets,
            tags=canvas.tags,
            source=canvas.source,
        )
        pre = precheck_canvas_for_writeback(precheck_target)
        pre["pending_blocks"] = len(pending_blocks)
    else:
        pre = {
            "ok": True,
            "errors": [],
            "warnings": [],
            "findings": [],
            "summary": "无待写回块（画布与工程一致），跳过预检直接编译",
            "pending_blocks": 0,
        }
    if pre.get("errors"):
        return _precheck_failure_result(job_id, canvas, pre)

    # --- prepare_work ---
    update_job_stage(job_id, "prepare_work", "running", "准备工程工作副本…")
    if _cancel_guard(job_id, list(STAGES)):
        return _cancelled_result(canvas)

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
        _mark_remaining_skipped(job_id, list(STAGES[1:]), "缺少工程路径，未执行")
        return {"ok": False, "error": "missing project_path", "canvas": canvas.to_dict()}
    if not is_allowed_project_path(resolved_path, project_id=project_id):
        # allowlist 校验：非允许目录内的工程一律不写回
        reason = f"工程路径不在允许目录内：{resolved_path}"
        update_job_stage(job_id, "prepare_work", "error", reason)
        _mark_remaining_skipped(job_id, list(STAGES[1:]), "路径校验失败，未执行")
        return {"ok": False, "error": "path_not_allowed", "canvas": canvas.to_dict()}
    update_job_stage(job_id, "prepare_work", "ok", f"工作副本就绪：{resolved_path}")

    # --- open_project (session or one-shot) ---
    if _cancel_guard(job_id, list(STAGES[1:])):
        return _cancelled_result(canvas)
    degraded = False
    update_job_stage(job_id, "open_project", "running", "打开博途工程…")
    try:
        from gateway.app.services.plc.openness_session import (
            ensure_project_open,
            session_enabled,
        )

        opened = ensure_project_open(
            resolved_path, plc_name=plc_name or (source.plc_name if source else "")
        )
        # ensure_project_open 在会话不可用时返回 {"ok": False} 而不抛异常，
        # 必须显式检查返回值，否则会把「没打开」误报成「已打开」。
        if isinstance(opened, dict) and opened.get("ok"):
            update_job_stage(job_id, "open_project", "ok", "工程已在常驻会话中打开")
        elif not session_enabled():
            # 常驻会话被显式关闭：一次性写回是既定模式，不算降级
            update_job_stage(job_id, "open_project", "skipped", "常驻会话已禁用，使用一次性写回")
        else:
            degraded = True
            reason = str((opened or {}).get("error") or "session unavailable")
            update_job_stage(job_id, "open_project", "skipped", f"常驻会话不可用，回退一次性写回：{reason}")
    except Exception as exc:  # noqa: BLE001
        degraded = True
        update_job_stage(job_id, "open_project", "skipped", f"会话打开失败，回退一次性写回：{exc}")

    if not compile_plc and not compile_hmi:
        update_job_stage(job_id, "write_plc", "skipped", "未请求写入")
        update_job_stage(job_id, "compile_plc", "skipped")
        update_job_stage(job_id, "write_hmi", "skipped")
        update_job_stage(job_id, "compile_hmi", "skipped")
        update_job_stage(job_id, "save", "skipped")
        return {
            "ok": True,
            "writeback": {"ok": True, "note": "nothing to compile"},
            "canvas": canvas.to_dict(),
            "precheck": pre,
            "degraded": degraded,
        }

    # --- write + compile PLC ---
    if _cancel_guard(job_id, list(STAGES[2:])):
        return _cancelled_result(canvas, degraded=degraded)
    update_job_stage(job_id, "write_plc", "running", "写入 PLC 块/标签…")
    writeback: dict[str, Any] = {"ok": False}
    attributions: list[dict[str, Any]] = []
    try:
        if pending_blocks:
            writeback, attributions = execute_canvas_writeback(
                canvas,
                project_path=resolved_path,
                plc_name=plc_name or (source.plc_name if source else ""),
                compile_after=compile_plc,
            )
        else:
            # 没有待写回的块：只做编译验证，绝不重写工程。
            # 这条路径对应「导入工程 → 直接点编译看能不能过」，是用户最常用的场景。
            update_job_stage(job_id, "write_plc", "skipped", "无待写回块（画布与工程一致），跳过写入")
            if compile_plc:
                from agents.plc.tia.openness_cli import compile_plc_via_openness_cli

                cres = compile_plc_via_openness_cli(
                    resolved_path,
                    plc_name=plc_name or (source.plc_name if source else ""),
                )
                writeback = {
                    "ok": bool(cres.get("ok")),
                    "compile": cres,
                    "note": "compile_only_no_writeback",
                    "message": cres.get("message") or ("PLC 编译通过" if cres.get("ok") else "PLC 编译失败"),
                }
            else:
                writeback = {"ok": True, "note": "compile skipped by request"}
        wb_ok = bool(writeback.get("ok") or writeback.get("generated"))
        if wb_ok:
            stage_msg = writeback.get("message") or "PLC 写入完成"
        else:
            # 失败时不要把默认文案当成结果——优先展示归因到的具体块与错误
            first = attributions[0] if attributions else None
            stage_msg = (
                str(first.get("message"))[:300]
                if isinstance(first, dict) and first.get("message")
                else (writeback.get("message") or "PLC 写入失败：博图未返回具体原因")
            )
        update_job_stage(
            job_id,
            "write_plc",
            "ok" if wb_ok else "error",
            stage_msg,
        )
        if compile_plc:
            # compile_plc 阶段边界：命中取消则不再写工程
            if _cancel_guard(job_id, list(STAGES[3:])):
                return _cancelled_result(canvas, degraded=degraded, writeback=writeback, attributions=attributions)
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
        if _cancel_guard(job_id, list(STAGES[4:])):
            return _cancelled_result(canvas, degraded=degraded, writeback=writeback, attributions=attributions)
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
        if _cancel_guard(job_id, list(STAGES[6:])):
            return _cancelled_result(canvas, degraded=degraded, writeback=writeback, attributions=attributions)
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

    writeback["degraded"] = degraded
    return {
        "ok": ok,
        "writeback": writeback,
        "attributions": attributions,
        "canvas": canvas.to_dict(),
        "precheck": pre,
        "degraded": degraded,
        "error": None if ok else (writeback.get("error") or writeback.get("message") or "compile failed"),
    }
