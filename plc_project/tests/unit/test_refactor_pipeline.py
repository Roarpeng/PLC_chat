"""重构流水线编排单测：阶段流转 / result 结构 / 异常收敛（不泄漏线程）/ 端点契约。

约定：单测内不碰真实重构引擎与 Openness——引擎、规则库全部 monkeypatch；
do_compile 场景用「无项目源路径」的画布走诚实 skipped 分支，绝不启动 TIA。
"""

from __future__ import annotations

import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gateway.app.services.plc import refactor_pipeline as rp
from plc_engine.canvas_model import CanvasBlock, CanvasState, create_empty_canvas

# 等待作业终态的轮询上限（秒）
_WAIT_TIMEOUT_S = 10.0


# ---------------------------------------------------------------- 测试桩 ----


def _fake_report(target: str = "U1_DemoLine") -> dict[str, Any]:
    """仿真引擎报告（含 io_retention.details / pending_blocks / degraded 新字段）。"""
    return {
        "status": "success",
        "project_name": "DemoLine",
        "target_unit_name": target,
        "legacy_blocks_count": 2,
        "af_blocks_count": 1,
        "af_blocks_created": ["U1_DemoLine_EM1"],
        "io_retention": {
            "total_ios": 2,
            "retained_ios": 2,
            "percentage": 100.0,
            "details": [
                {
                    "address": "%I0.0",
                    "tag_name": "Start_PB",
                    "data_type": "Bool",
                    "cm_name": "Cyl",
                    "cm_type": "CM",
                    "cm_field": "open",
                    "em_name": "EM1",
                }
            ],
        },
        "pending_blocks": ["MotorCtrl"],
        "degraded": False,
        "lint_findings": [],
    }


def _fake_refactor_ok(canvas: CanvasState, target: str, *args: Any, **kwargs: Any):
    """仿真引擎：接受 self_contained kwarg，画布加一个 AF 新块。"""
    from copy import deepcopy

    new_canvas = deepcopy(canvas)
    new_canvas.blocks["U1_DemoLine_EM1"] = CanvasBlock(
        name="U1_DemoLine_EM1", block_type="FB", scl_body="// AF EM (stub)"
    )
    return new_canvas, _fake_report(target)


def _fake_refactor_degraded(canvas: CanvasState, target: str, *args: Any, **kwargs: Any):
    """仿真引擎完全降级：status=degraded、零 AF 块、旧块原样保留。"""
    from copy import deepcopy

    report = {
        "status": "degraded",
        "target_unit_name": target,
        "af_blocks_created": [],
        "io_retention": {"total_ios": 0, "retained_ios": 0, "percentage": 0.0, "details": []},
        "degraded": True,
        "degrade_reasons": ["no_sequence_block", "no_interlock_detected"],
        "pending_blocks": ["MotorCtrl", "MainDB"],
    }
    return deepcopy(canvas), report


def _fake_refactor_no_kwarg(canvas: CanvasState, target: str, *args: Any, **kwargs: Any):
    """仿真「引擎尚未支持 self_contained」：带 kwarg 即 TypeError。"""
    if kwargs:
        raise TypeError(f"unexpected keyword argument {list(kwargs)}")
    return _fake_refactor_ok(canvas, target)


class _AutofixLike(list):
    """仿真 AutofixPatch：list[dict] 子类 + .diagnostics 属性。"""

    def __init__(self, items: list, diagnostics: list) -> None:
        super().__init__(items)
        self.diagnostics = diagnostics


def _fake_autofix_with_ops(canvas: CanvasState, attributions=None, **kwargs: Any):
    return _AutofixLike(
        [
            {
                "op": "add_variable",
                "block": "MotorCtrl",
                "variable": {"name": "AutoVar", "data_type": "Bool", "section": "VAR"},
            },
            {"op": "clear_errors"},
        ],
        [{"rule": "R1_demo", "message": "诊断提示：示例规则命中"}],
    )


def _fake_autofix_empty(canvas: CanvasState, attributions=None, **kwargs: Any):
    return _AutofixLike([], [])


# ---------------------------------------------------------------- 助手 ----


@pytest.fixture(autouse=True)
def _clean_registry():
    """隔离模块级作业注册表；清理测试产出的临时交付包。"""
    rp._jobs.clear()
    yield
    for job in list(rp._jobs.values()):
        pkg_path = str(job.get("package_path") or "")
        if pkg_path and Path(pkg_path).exists():
            Path(pkg_path).unlink(missing_ok=True)
            pkg_dir = Path(pkg_path).with_suffix("")
            if pkg_dir.is_dir():
                shutil.rmtree(pkg_dir, ignore_errors=True)
    rp._jobs.clear()


def _wait_terminal(job_id: str, timeout_s: float = _WAIT_TIMEOUT_S) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        live = rp.get_refactor_pipeline_job(job_id)
        if live and live["status"] in {"ok", "error", "cancelled"}:
            return live
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout_s}s 内进入终态")


def _stage(live: dict[str, Any], name: str) -> dict[str, Any]:
    for st in live["stages"]:
        if st["name"] == name:
            return st
    raise AssertionError(f"缺少阶段 {name}")


def _canvas_dict() -> dict[str, Any]:
    return create_empty_canvas("DemoLine").to_dict()


# ---------------------------------------------------------------- 编排单测 ----


def test_pipeline_no_compile_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    """do_compile=false：五阶段固定流转，compile/fix_loop skipped，result 结构齐备。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_ok)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_empty)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), project_name="DemoLine", do_compile=False, auto_fix=True)
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    assert [s["name"] for s in live["stages"]] == rp.STAGES
    assert _stage(live, "refactor")["status"] == "ok"
    assert _stage(live, "auto_fix")["status"] == "skipped"  # 无规则可用 → skipped
    assert _stage(live, "compile")["status"] == "skipped"
    assert _stage(live, "fix_loop")["status"] == "skipped"
    assert _stage(live, "package")["status"] == "ok"

    result = live["result"]
    assert set(result.keys()) == {"canvas", "report", "compile", "equivalence", "package", "warnings"}
    # report 原样透传（含引擎新字段）
    assert result["report"]["pending_blocks"] == ["MotorCtrl"]
    assert result["report"]["degraded"] is False
    assert result["canvas"]["blocks"]["U1_DemoLine_EM1"]["scl_body"].startswith("// AF EM")
    # compile：未请求 → 诚实 skipped_reason，不伪造 0 错误
    assert result["compile"] == {
        "compiled": False,
        "skipped_reason": "未请求编译验证（do_compile=false）",
        "errors": [],
        "warnings_count": 0,
    }
    assert result["package"]["file_count"] >= 3
    assert result["package"]["size_bytes"] > 0
    assert isinstance(result["warnings"], list)
    # 交付包 zip 已落盘并被作业记录
    assert live["package_path"] and Path(live["package_path"]).is_file()
    with zipfile.ZipFile(live["package_path"]) as zf:
        assert "refactor_report.json" in zf.namelist()


def test_pipeline_view_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET 视图契约：{id, status, stage, stages:[{name,status,detail?}], result?}。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_ok)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_empty)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=False, auto_fix=False)
    _wait_terminal(job["id"])

    view = rp.refactor_job_view(job["id"])
    assert view is not None
    assert view["id"] == job["id"]
    assert view["status"] == "ok"
    assert view["stage"] == "package"
    assert [s["name"] for s in view["stages"]] == ["refactor", "auto_fix", "compile", "fix_loop", "package"]
    for st in view["stages"]:
        assert st["status"] in {"pending", "running", "ok", "skipped", "error"}
    assert "result" in view
    assert rp.refactor_job_view("no-such-job") is None


def test_refactor_self_contained_fallback_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎未支持 self_contained kwarg：TypeError 降级调用 + 记 warning。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_no_kwarg)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_empty)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=False, auto_fix=False)
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    assert _stage(live, "refactor")["status"] == "ok"
    assert any(w.startswith("引擎未支持自举模式") for w in live["result"]["warnings"])


def test_autofix_applied_and_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """规则补丁应用成功：应用数统计 + diagnostics 转入 warnings 前列 + 画布生效。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_ok)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_with_ops)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=False, auto_fix=True)
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    stage = _stage(live, "auto_fix")
    assert stage["status"] == "ok"
    assert "1 条" in stage["detail"]  # clear_errors 不计入应用数
    warnings = live["result"]["warnings"]
    assert warnings and "诊断提示" in warnings[0]  # diagnostics 在 warnings 前列
    motor = live["result"]["canvas"]["blocks"]["MotorCtrl"]
    assert any(v["name"] == "AutoVar" for v in motor["interface"])


def test_compile_skipped_without_project_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """do_compile=true 但画布无项目源：compile 诚实 skipped（不启动 Openness），流水线继续。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_ok)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_empty)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=True, auto_fix=False)
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    assert _stage(live, "compile")["status"] == "skipped"
    assert "项目源路径" in _stage(live, "compile")["detail"]
    assert _stage(live, "fix_loop")["status"] == "skipped"
    assert _stage(live, "package")["status"] == "ok"
    assert live["result"]["compile"]["compiled"] is False
    assert "项目源路径" in live["result"]["compile"]["skipped_reason"]


def test_engine_exception_marks_error_and_pool_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎异常：作业收敛 error、后续阶段 skipped；线程池线程正常归还（后续作业仍可完成）。"""

    def _boom(canvas, target, *args, **kwargs):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _boom)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=False, auto_fix=False)
    live = _wait_terminal(job["id"])

    assert live["status"] == "error"
    assert "engine exploded" in (live["error"] or "")
    assert _stage(live, "refactor")["status"] == "error"
    for name in ("auto_fix", "compile", "fix_loop", "package"):
        assert _stage(live, name)["status"] == "skipped"
    assert live["result"] is None
    assert not live["package_path"]

    # 线程未泄漏：同一个池再跑一个正常作业，照常收敛 ok
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_ok)
    job2 = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=False, auto_fix=False)
    live2 = _wait_terminal(job2["id"])
    assert live2["status"] == "ok"


def test_engine_degraded_skips_middle_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎完全降级：auto_fix/compile/fix_loop 三段 skipped，package 照常，整体 ok。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_degraded)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_with_ops)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), project_name="DemoLine", do_compile=True, auto_fix=True)
    live = _wait_terminal(job["id"])

    assert live["status"] == "ok"
    assert _stage(live, "refactor")["status"] == "ok"
    for name in ("auto_fix", "compile", "fix_loop"):
        stage = _stage(live, name)
        assert stage["status"] == "skipped"
        assert stage["detail"] == rp.DEGRADED_SKIP_REASON
    assert _stage(live, "package")["status"] == "ok"

    result = live["result"]
    assert result["compile"]["compiled"] is False
    assert result["compile"]["skipped_reason"] == rp.DEGRADED_SKIP_REASON
    # 降级证据转入 warnings
    assert any("no_sequence_block" in w for w in result["warnings"])
    assert any("待人工确认块" in w for w in result["warnings"])
    # 交付收据如实呈现（未编译不伪造 0 错误）
    with zipfile.ZipFile(live["package_path"]) as zf:
        import json as _json

        receipt = _json.loads(zf.read("compile_receipt.json").decode("utf-8"))
    assert receipt["compiled"] is False
    assert rp.DEGRADED_SKIP_REASON in receipt["reason"]


def test_cancel_between_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """取消请求在阶段边界生效：作业 cancelled、剩余阶段 skipped。"""
    started = threading.Event()

    def _slow_refactor(canvas, target, *args, **kwargs):
        started.set()
        time.sleep(0.05)
        return _fake_refactor_ok(canvas, target)

    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _slow_refactor)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_empty)

    job = rp.create_refactor_pipeline_job(_canvas_dict(), do_compile=False, auto_fix=False)
    assert started.wait(_WAIT_TIMEOUT_S)
    cancelled = rp.cancel_refactor_pipeline_job(job["id"])
    assert cancelled is not None
    live = _wait_terminal(job["id"])
    assert live["status"] == "cancelled"
    assert live["package_path"] == ""


# ---------------------------------------------------------------- 端点契约 ----


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
    monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(tmp_path.resolve()))
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


_AUTH = {"X-API-Key": "ros_ak_test_key"}


def test_endpoint_post_poll_download(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """POST 建作业 → GET 轮询 → GET package 下载 zip（完整契约链路）。"""
    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _fake_refactor_ok)
    monkeypatch.setattr("plc_engine.canvas_model.generate_canvas_autofix_patch", _fake_autofix_empty)

    resp = client.post(
        "/api/v1/plc/canvas/refactor-pipeline",
        json={"canvas": _canvas_dict(), "project_name": "DemoLine", "do_compile": False, "auto_fix": True},
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    job_id = payload["data"]["job_id"]
    assert isinstance(job_id, str) and job_id

    deadline = time.time() + _WAIT_TIMEOUT_S
    view: dict[str, Any] = {}
    while time.time() < deadline:
        poll = client.get(f"/api/v1/plc/canvas/refactor-pipeline/{job_id}", headers=_AUTH)
        assert poll.status_code == 200
        view = poll.json()["data"]
        if view["status"] in {"ok", "error", "cancelled"}:
            break
        time.sleep(0.02)
    assert view["status"] == "ok", view
    assert view["result"]["compile"]["compiled"] is False

    pkg = client.get(f"/api/v1/plc/canvas/refactor-pipeline/{job_id}/package", headers=_AUTH)
    assert pkg.status_code == 200, pkg.text
    assert pkg.content[:2] == b"PK"
    assert pkg.headers["content-type"].startswith("application/zip")

    zap_resp = client.get(f"/api/v1/plc/canvas/refactor-pipeline/{job_id}/zap", headers=_AUTH)
    assert zap_resp.status_code == 200, zap_resp.text
    assert zap_resp.content[:2] == b"PK"
    assert "attachment" in zap_resp.headers["content-disposition"]


def test_endpoint_404_unknown_job(client: TestClient) -> None:
    """不存在的作业：GET 与 package 均 404。"""
    assert client.get("/api/v1/plc/canvas/refactor-pipeline/none", headers=_AUTH).status_code == 404
    assert (
        client.get("/api/v1/plc/canvas/refactor-pipeline/none/package", headers=_AUTH).status_code == 404
    )


def test_endpoint_package_not_ready_on_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """失败作业无交付包：package 404（PACKAGE_NOT_READY）。"""

    def _boom(canvas, target, *args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr("plc_engine.af.refactor.refactor_canvas_to_af", _boom)
    resp = client.post(
        "/api/v1/plc/canvas/refactor-pipeline",
        json={"canvas": _canvas_dict(), "do_compile": False, "auto_fix": False},
        headers=_AUTH,
    )
    job_id = resp.json()["data"]["job_id"]
    deadline = time.time() + _WAIT_TIMEOUT_S
    while time.time() < deadline:
        view = client.get(f"/api/v1/plc/canvas/refactor-pipeline/{job_id}", headers=_AUTH).json()["data"]
        if view["status"] == "error":
            break
        time.sleep(0.02)
    assert view["status"] == "error"

    pkg = client.get(f"/api/v1/plc/canvas/refactor-pipeline/{job_id}/package", headers=_AUTH)
    assert pkg.status_code == 404
    assert pkg.json()["detail"]["code"] == "PACKAGE_NOT_READY"


def test_endpoint_canvas_required(client: TestClient) -> None:
    """缺 canvas → 400 CANVAS_REQUIRED。"""
    resp = client.post("/api/v1/plc/canvas/refactor-pipeline", json={}, headers=_AUTH)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "CANVAS_REQUIRED"


def test_compile_write_scope_excludes_superseded_draft() -> None:
    """写集裁剪：只留 AF 家族——superseded/pending 移出(TIA 保留原件)。"""
    canvas = create_empty_canvas("DemoLine")
    superseded = CanvasBlock(name="FB720_KuKa_MainCtrl", block_type="FB", scl_body="// TODO[x] 翻译占位")
    superseded.status = "draft"
    superseded.af_role = "legacy_superseded"
    pending = CanvasBlock(name="FC2100_Modbus", block_type="FC", scl_body="// 原 SCL")
    pending.status = "draft"
    pending.af_role = "af_pending_manual"
    af_block = CanvasBlock(name="Sequence", block_type="FB", scl_body="// AF 自举块")
    af_block.status = "draft"
    af_block.af_role = "Sequence"
    canvas.blocks["FB720_KuKa_MainCtrl"] = superseded
    canvas.blocks["FC2100_Modbus"] = pending
    canvas.blocks["U1_DemoLine::Sequence"] = af_block

    scoped, excluded = rp._compile_write_scope(canvas)

    assert "FB720_KuKa_MainCtrl" in excluded
    assert "FC2100_Modbus" in excluded
    assert scoped.blocks["FB720_KuKa_MainCtrl"].status == "synced"
    assert scoped.blocks["FC2100_Modbus"].status == "synced"
    assert scoped.blocks["U1_DemoLine::Sequence"].status == "draft"
    # 原画布不被裁剪污染（交付画布仍保留取代块的 draft 状态）
    assert canvas.blocks["FB720_KuKa_MainCtrl"].status == "draft"


def test_compile_write_scope_excludes_todo_pending() -> None:
    """pending 块(含/不含 TODO)一律移出写集——TIA 保留原件,不写翻译体。"""
    canvas = create_empty_canvas("DemoLine")
    todo_pending = CanvasBlock(name="FB1142_TypeChangePrompt", block_type="FB", scl_body="// TODO[x] 未翻译元素")
    todo_pending.status = "draft"
    todo_pending.af_role = "af_pending_manual"
    clean_pending = CanvasBlock(name="FB1080_Component", block_type="FB", scl_body="#a := TRUE;")
    clean_pending.status = "draft"
    clean_pending.af_role = "af_pending_manual"
    canvas.blocks["FB1142_TypeChangePrompt"] = todo_pending
    canvas.blocks["FB1080_Component"] = clean_pending

    scoped, excluded = rp._compile_write_scope(canvas)

    assert "FB1142_TypeChangePrompt" in excluded
    assert "FB1080_Component" in excluded
    assert scoped.blocks["FB1142_TypeChangePrompt"].status == "synced"
    assert scoped.blocks["FB1080_Component"].status == "synced"


def test_compile_write_scope_keeps_af_family() -> None:
    """AF 家族块(含 :: 键与各 AF 角色)保留 draft——交付=原件+AF 覆盖层。"""
    canvas = create_empty_canvas("DemoLine")
    af1 = CanvasBlock(name="Sequence", block_type="FB", scl_body='FUNCTION_BLOCK "U1Em1_Seq" END_FUNCTION_BLOCK')
    af1.status = "draft"
    af1.af_role = "Sequence"
    af2 = CanvasBlock(name="CallEquipment_DB", block_type="DB", scl_body='DATA_BLOCK "U1_CE_DB" END_DATA_BLOCK')
    af2.status = "draft"
    af2.af_role = "CallEquipment_DB"
    canvas.blocks["U1Em1_Seq::Sequence"] = af1
    canvas.blocks["U1_CE::CallEquipment_DB"] = af2

    scoped, excluded = rp._compile_write_scope(canvas)
    # blank 画布自带的默认块(无 AF 角色)会被移出——只断言 AF 家族保留
    assert "U1Em1_Seq::Sequence" not in excluded
    assert "U1_CE::CallEquipment_DB" not in excluded
    assert scoped.blocks["U1Em1_Seq::Sequence"].status == "draft"
    assert scoped.blocks["U1_CE::CallEquipment_DB"].status == "draft"
