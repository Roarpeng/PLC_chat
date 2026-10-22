"""编译作业加固：precheck 门禁 / 取消生效 / 硬超时 / 降级与 allowlist。"""

from __future__ import annotations

import time
from typing import Any

import pytest

from gateway.app.services.plc import compile_jobs as cj
from plc_engine.canvas_model import CanvasState, create_empty_canvas

# 等待 job 终态的轮询上限（秒）
_WAIT_TIMEOUT_S = 5.0


@pytest.fixture(autouse=True)
def _stub_openness(monkeypatch: pytest.MonkeyPatch) -> None:
    """单测里绝不碰真实 Openness：会话打开/保存一律打桩（需要时由用例自行覆盖）。"""
    monkeypatch.setattr(
        "gateway.app.services.plc.openness_session.ensure_project_open",
        lambda project_path, *, plc_name="": {"ok": True},
    )
    monkeypatch.setattr(
        "gateway.app.services.plc.openness_session.save_project",
        lambda project_path="": {"ok": True},
    )


def _wait_terminal(job_id: str, timeout_s: float = _WAIT_TIMEOUT_S) -> dict[str, Any]:
    """轮询直到 job 进入终态（ok/error/cancelled）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        live = cj.get_job(job_id)
        if live and live["status"] in {"ok", "error", "cancelled"}:
            return live
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout_s}s 内进入终态")


def _stage(live: dict[str, Any], name: str) -> dict[str, Any]:
    for st in live["stages"]:
        if st["name"] == name:
            return st
    raise AssertionError(f"缺少阶段 {name}")


def _canvas_with_error() -> CanvasState:
    """含 TODO 占位 + 未配对 IF 的画布（预检必失败）。"""
    c = create_empty_canvas("Demo")
    c.blocks["MotorCtrl"].scl_body = "IF #Start THEN\n    // TODO 待实现\n"
    return c


def _canvas_with_warning_only() -> CanvasState:
    """仅触发 warning（HMI 绑定指向画布外的标签）的画布。"""
    c = create_empty_canvas("Demo")
    c.hmi_widgets["btn_start"].plc_tag = "ExternalDB.StartCmd"
    return c


def _stub_writeback(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """替换真实写回并记录调用；返回调用记录列表（应为空表示未写工程）。"""
    calls: list[dict[str, Any]] = []

    def _fake(canvas: CanvasState, **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        calls.append({"canvas": canvas, "kwargs": kwargs})
        return {"ok": True, "generated": True}, []

    monkeypatch.setattr("plc_engine.canvas_tia_transpiler.execute_canvas_writeback", _fake)
    return calls


def test_precheck_error_blocks_writeback(monkeypatch: pytest.MonkeyPatch):
    """预检 error → job error，写回函数完全不被调用（不碰工程）。"""
    calls = _stub_writeback(monkeypatch)
    job = cj.create_compile_job(_canvas_with_error().to_dict(), project_path="C:/tmp/Demo.ap19")
    live = _wait_terminal(job["id"])

    assert live["status"] == "error"
    assert live["error"] == "precheck_failed"
    assert calls == [], "预检失败时不得调用写回"
    assert _stage(live, "write_plc")["status"] == "error"
    assert "TODO" in _stage(live, "write_plc")["message"]
    # fail-closed：其余阶段全部 skipped
    for name in ("prepare_work", "open_project", "compile_plc", "write_hmi", "compile_hmi", "save"):
        assert _stage(live, name)["status"] == "skipped", name
    # 结果里带 precheck 明细供前端展示
    assert live["result"]["precheck"]["ok"] is False
    assert live["result"]["precheck"]["errors"]
    assert live["precheck"]["errors"]


def test_precheck_warning_continues(monkeypatch: pytest.MonkeyPatch):
    """仅 warning → 不阻断，继续写回，并把 warning 带进结果。"""
    calls = _stub_writeback(monkeypatch)
    job = cj.create_compile_job(
        _canvas_with_warning_only().to_dict(),
        project_path="C:/tmp/Demo.ap19",
        compile_hmi=False,
    )
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    assert len(calls) == 1, "warning 不应阻断写回"
    assert live["precheck"]["ok"] is True
    assert live["precheck"]["warnings"], "warning 必须带进结果"
    assert _stage(live, "write_plc")["status"] == "ok"


def test_cancel_before_write_plc_skips_remaining(monkeypatch: pytest.MonkeyPatch):
    """取消在 write_plc 前生效 → 后续阶段 skipped、job cancelled、不再写工程。"""
    calls = _stub_writeback(monkeypatch)
    holder: list[str] = []

    def _fake_open(project_path: str, *, plc_name: str = "") -> dict[str, Any]:
        # 模拟用户在 open_project 期间点了取消
        if holder:
            cj.cancel_job(holder[0])
        return {"ok": True}

    monkeypatch.setattr("gateway.app.services.plc.openness_session.ensure_project_open", _fake_open)

    def runner(job_id: str, canvas_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        holder.append(job_id)
        return cj.default_compile_runner(job_id, canvas_dict, **kwargs)

    job = cj.create_compile_job(
        _canvas_with_warning_only().to_dict(),
        project_path="C:/tmp/Demo.ap19",
        runner=runner,
    )
    live = _wait_terminal(job["id"])

    assert live["status"] == "cancelled"
    assert calls == [], "取消后不得继续写工程"
    assert _stage(live, "open_project")["status"] == "ok"
    for name in ("write_plc", "compile_plc", "write_hmi", "compile_hmi", "save"):
        assert _stage(live, name)["status"] == "skipped", name


def test_job_timeout_marks_error(monkeypatch: pytest.MonkeyPatch):
    """超过 COMPILE_JOB_TIMEOUT_S → job error / error=timeout，running 阶段标 error。"""
    monkeypatch.setenv("COMPILE_JOB_TIMEOUT_S", "0.3")

    def runner(job_id: str, canvas_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        cj.update_job_stage(job_id, "prepare_work", "ok")
        cj.update_job_stage(job_id, "open_project", "ok")
        cj.update_job_stage(job_id, "write_plc", "running", "写入中…")
        time.sleep(1.0)
        return {"ok": True, "writeback": {"ok": True}}

    job = cj.create_compile_job(create_empty_canvas("Demo").to_dict(), runner=runner)
    live = _wait_terminal(job["id"])

    assert live["status"] == "error"
    assert live["error"] == "timeout"
    assert live["timed_out"] is True
    assert _stage(live, "write_plc")["status"] == "error"
    assert _stage(live, "save")["status"] == "skipped"


def test_open_project_failure_is_skipped_and_degraded(monkeypatch: pytest.MonkeyPatch):
    """open_project 失败 → 阶段 skipped（不是 ok），job 仍继续但 degraded=True。"""

    def _fake_open(project_path: str, *, plc_name: str = "") -> dict[str, Any]:
        raise RuntimeError("no openness session")

    monkeypatch.setattr("gateway.app.services.plc.openness_session.ensure_project_open", _fake_open)
    _stub_writeback(monkeypatch)

    job = cj.create_compile_job(
        create_empty_canvas("Demo").to_dict(),
        project_path="C:/tmp/Demo.ap19",
        compile_hmi=False,
    )
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    stage = _stage(live, "open_project")
    assert stage["status"] == "skipped", "失败不得标 ok"
    assert "no openness session" in stage["message"]
    assert live["degraded"] is True
    assert live["result"]["degraded"] is True


def test_project_path_outside_allowlist_blocked(monkeypatch: pytest.MonkeyPatch):
    """目标工程不在 allowlist 内 → prepare_work error，不写回。"""
    monkeypatch.setenv("PLC_ALLOWED_PROJECT_DIRS", "C:/allowed_projects")
    calls = _stub_writeback(monkeypatch)

    job = cj.create_compile_job(
        create_empty_canvas("Demo").to_dict(),
        project_path="C:/tmp/Outside.ap19",
    )
    live = _wait_terminal(job["id"])

    assert live["status"] == "error"
    assert live["error"] == "path_not_allowed"
    assert calls == []
    assert _stage(live, "prepare_work")["status"] == "error"


def test_missing_job_records_do_not_raise():
    """job 记录被 TTL 清理后，写状态/取消/超时均不得抛 KeyError。"""
    cj.update_job_stage("no-such-job", "write_plc", "ok")
    cj._mark_cancelled("no-such-job", ["write_plc"])
    cj._mark_timeout("no-such-job")
    assert cj.get_job("no-such-job") is None


def test_job_purged_midflight_is_survivable(monkeypatch: pytest.MonkeyPatch):
    """作业运行期间记录被 TTL 清掉时，收尾逻辑走 .get() 判空而非 KeyError。"""
    monkeypatch.setattr(cj, "_TTL_S", 0.0)

    def runner(job_id: str, canvas_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        time.sleep(0.05)
        return {"ok": True, "writeback": {"ok": True}}

    job = cj.create_compile_job(create_empty_canvas("Demo").to_dict(), runner=runner)
    time.sleep(0.4)
    assert cj.get_job(job["id"]) is None


# --- 子进程隔离：超时/取消真杀进程树 ------------------------------------------
#
# 以下用例会真的 spawn Python 子进程（不碰 TIA/Openness exe：runner 是纯 sleep
# 占位）。spawn 按引用 pickle runner，因此这些 runner 必须是**模块级**函数。


def _stuck_openness_runner(job_id: str, canvas_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """占位 runner：模拟卡死在 Openness 调用里（不查取消、睡满才返回）。"""
    cj.update_job_stage(job_id, "prepare_work", "ok", "子进程内就绪")
    cj.update_job_stage(job_id, "write_plc", "running", "模拟卡死的 Openness 调用…")
    time.sleep(60.0)
    return {"ok": True, "writeback": {"ok": True}}


def _quick_ok_runner(job_id: str, canvas_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """占位 runner：立刻成功，验证 bridge 阶段消息与结果回传。"""
    cj.update_job_stage(job_id, "prepare_work", "ok", "子进程阶段消息回传")
    return {
        "ok": True,
        "writeback": {"ok": True},
        "attributions": [],
        "canvas": canvas_dict,
    }


def _cooperative_cancel_runner(job_id: str, canvas_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """占位 runner：轮询取消标记，命中即在阶段边界协作退出（不应被强杀）。"""
    cj.update_job_stage(job_id, "prepare_work", "running", "长任务轮询取消")
    while not cj.is_cancel_requested(job_id):
        time.sleep(0.02)
    cj._mark_cancelled(job_id, list(cj.STAGES[1:]))
    return {
        "ok": False,
        "cancelled": True,
        "writeback": {"ok": False, "cancelled": True},
        "attributions": [],
        "canvas": canvas_dict,
    }


def _wait_child_handle(job_id: str, timeout_s: float = 20.0) -> Any:
    """等子进程句柄注册（spawn 启动需数秒）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        handle = cj._children.get(job_id)
        if handle is not None:
            return handle
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout_s}s 内 spawn 出子进程")


def _wait_stage(job_id: str, name: str, status: str, timeout_s: float = 20.0) -> dict[str, Any]:
    """等某个阶段进入给定状态（证明子进程真的跑起来了再触发超时/取消）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        live = cj.get_job(job_id)
        if live and _stage(live, name)["status"] == status:
            return live
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 的阶段 {name} 未进入 {status}")


def _wait_dead(proc: Any, timeout_s: float = 15.0) -> None:
    """等进程真正死亡（kill 后 join 有短暂窗口）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not proc.is_alive():
            return
        proc.join(0.05)
    raise AssertionError("子进程未被杀掉，进程级 kill 失效")


def test_use_child_process_gating(monkeypatch: pytest.MonkeyPatch):
    """开关语义：内置 runner 由 PLC_COMPILE_JOB_SUBPROCESS 决定；注入 runner 只在
    PLC_COMPILE_JOB_SUBPROCESS_ALL=1 且可 pickle（模块级）时才进子进程。"""
    monkeypatch.delenv("PLC_COMPILE_JOB_SUBPROCESS", raising=False)
    monkeypatch.delenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", raising=False)
    assert cj._use_child_process(None) is False

    monkeypatch.setenv("PLC_COMPILE_JOB_SUBPROCESS", "1")
    assert cj._use_child_process(None) is True

    def _local_runner(job_id: str, canvas: dict[str, Any], **kw: Any) -> dict[str, Any]:
        return {"ok": True}

    assert cj._use_child_process(_local_runner) is False

    monkeypatch.setenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", "1")
    assert cj._use_child_process(_quick_ok_runner) is True
    assert cj._use_child_process(_local_runner) is False


def test_subprocess_success_roundtrip(monkeypatch: pytest.MonkeyPatch):
    """子进程模式正常路径：阶段消息经 bridge 回传父进程，结果落回 job。"""
    monkeypatch.setenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", "1")
    job = cj.create_compile_job(create_empty_canvas("Demo").to_dict(), runner=_quick_ok_runner)
    handle = _wait_child_handle(job["id"])
    live = _wait_terminal(job["id"], timeout_s=25.0)

    assert live["status"] == "ok"
    assert _stage(live, "prepare_work")["status"] == "ok"
    assert _stage(live, "prepare_work")["message"] == "子进程阶段消息回传"
    # 子进程正常退出
    _wait_dead(handle.proc)
    assert handle.proc.exitcode == 0


def test_subprocess_timeout_kills_child_tree(monkeypatch: pytest.MonkeyPatch):
    """超时 → taskkill 整个子进程树：job timed_out/error=timeout，被杀进程不残留，
    写入阶段消息带 restore_from_backup 提示，后续作业不被卡。"""
    monkeypatch.setenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", "1")
    # 必须大于子进程 spawn+启动耗时（Windows 下 1-3s），确保先卡进 write_plc 再触发超时
    monkeypatch.setenv("COMPILE_JOB_TIMEOUT_S", "5")

    stuck1 = cj.create_compile_job(create_empty_canvas("A").to_dict(), runner=_stuck_openness_runner)
    stuck2 = cj.create_compile_job(create_empty_canvas("B").to_dict(), runner=_stuck_openness_runner)
    handles = [_wait_child_handle(stuck1["id"]), _wait_child_handle(stuck2["id"])]
    _wait_stage(stuck1["id"], "write_plc", "running")
    _wait_stage(stuck2["id"], "write_plc", "running")

    live1 = _wait_terminal(stuck1["id"], timeout_s=25.0)
    live2 = _wait_terminal(stuck2["id"], timeout_s=25.0)

    for live in (live1, live2):
        assert live["status"] == "error"
        assert live["error"] == "timeout"
        assert live["timed_out"] is True
        assert _stage(live, "write_plc")["status"] == "error"
        assert "restore_from_backup" in _stage(live, "write_plc")["message"]
        assert _stage(live, "save")["status"] == "skipped"

    # 进程真死（非零退出码 = 被 taskkill 强杀），句柄清理
    for handle in handles:
        _wait_dead(handle.proc)
        assert handle.proc.exitcode != 0

    # 池槽位已回收：被杀作业之后新作业能立刻跑完，不受残留进程影响
    follow = cj.create_compile_job(create_empty_canvas("C").to_dict(), runner=_quick_ok_runner)
    follow_live = _wait_terminal(follow["id"], timeout_s=25.0)
    assert follow_live["status"] == "ok"


def test_subprocess_cancel_grace_kills_stuck_child(monkeypatch: pytest.MonkeyPatch):
    """取消后宽限期内仍卡死 → 强杀进程树，job cancelled、进程不残留。"""
    monkeypatch.setenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", "1")
    monkeypatch.setenv("COMPILE_JOB_TIMEOUT_S", "60")  # 别让超时先触发
    monkeypatch.setattr(cj, "_CANCEL_GRACE_S", 1.0)

    job = cj.create_compile_job(create_empty_canvas("Demo").to_dict(), runner=_stuck_openness_runner)
    handle = _wait_child_handle(job["id"])
    _wait_stage(job["id"], "write_plc", "running")

    cj.cancel_job(job["id"])
    live = _wait_terminal(job["id"], timeout_s=25.0)

    assert live["status"] == "cancelled"
    assert live["error"] == "cancelled by user"
    # 卡在写入阶段被强杀：消息带还原提示
    assert "restore_from_backup" in _stage(live, "write_plc")["message"]
    _wait_dead(handle.proc)
    assert handle.proc.exitcode != 0


def test_subprocess_cancel_cooperative_no_kill(monkeypatch: pytest.MonkeyPatch):
    """取消时子进程在阶段边界自查退出：不需要强杀，exitcode==0。"""
    monkeypatch.setenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", "1")
    monkeypatch.setenv("COMPILE_JOB_TIMEOUT_S", "60")
    monkeypatch.setattr(cj, "_CANCEL_GRACE_S", 10.0)  # 宽限足够长，协作退出应先发生

    job = cj.create_compile_job(create_empty_canvas("Demo").to_dict(), runner=_cooperative_cancel_runner)
    handle = _wait_child_handle(job["id"])
    _wait_stage(job["id"], "prepare_work", "running")

    cj.cancel_job(job["id"])
    live = _wait_terminal(job["id"], timeout_s=25.0)

    assert live["status"] == "cancelled"
    assert live["error"] == "cancelled by user"
    for name in ("open_project", "write_plc", "compile_plc", "write_hmi", "compile_hmi", "save"):
        assert _stage(live, name)["status"] == "skipped", name
    # 协作退出（未强杀）：进程自行结束
    _wait_dead(handle.proc)
    assert handle.proc.exitcode == 0
