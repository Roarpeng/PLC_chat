"""WP-02 / P0-G：Greenfield 会话模式（F16 地基）离线单测。

全 mock、不连真机：底层 ``openness_session._post`` / ``session_status`` /
``ensure_session_running`` 与 PCEC ``put_change`` 均在模块边界 monkeypatch；
CLI ``openness_cli.openness_cli`` 被监控以确保不触禁用命令。

覆盖契约 §3.1 / UC-05 口径：
  ① /open 只一次、三次增量复用同一句柄；
  ② 不调用 create-project / archive-project / close-project；
  ③ 三次增量调用序列 + PCEC 3 条；
  ④ ExclusiveAccess 失败 fail-closed 且零写入；
  ⑤ tia_unavailable 显式失败、ok=false、非 HTTP 200；
  ⑥ 编译 warning 单列，不影响 compile_ok 判定；
  ⑦ 会话模式开关（默认关闭 / 显式 / 环境变量）与 TiaSessionPort 形状。

**诚实口径**：本文件为 mock / 离线单测，验证接口契约与编排序列。真机
UC-05（3 次 error_count==0 + 项目未重载 + PCEC 三条 + 句柄复用）由主 agent
收口实测，一律 ``pending_real_machine``；**禁止**据此宣称 L2/L4 通过或
「编译零错误」。N9：fidelity_ok 与 compile_ok 严格分离。
"""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from agents.plc.tia import openness_cli
from gateway.app.services.plc import openness_session, tia_delivery
from gateway.app.services.plc.tia_delivery import (
    GF_EXCLUSIVE_ACCESS_DENIED,
    GF_TIA_UNAVAILABLE,
    SESSION_MODE_ENV,
    SessionModeTiaPort,
    TiaSessionPort,
    run_incremental_writebacks,
    session_mode_enabled,
)
from plc_engine import pcec

# 原始记账函数（模块级固定引用），避免同一测试内多次 _mock_env 的 monkeypatch 累积。
_REAL_PUT_CHANGE = pcec.put_change

# 契约 §3.1：所有方法返回的结构化 dict 至少含这 6 个字段。
_REQUIRED_FIELDS = (
    "ok",
    "error_count",
    "warnings",
    "tia_version",
    "project_path",
    "elapsed_ms",
)

_OK_STATUS = {
    "ok": True,
    "available": True,
    "tia_version": "V19",
    "tia_running": False,
    "openness_available": True,
    "reason": "",
}


def _mock_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    open_resp: dict | None = None,
    fwb_resp: dict | None = None,
    compile_resp: dict | None = None,
    status: dict | None = None,
) -> SimpleNamespace:
    """搭建隔离 mock 环境：PCEC 落 tmp_path，HTTP / CLI / 记账全部可观测。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    ap = tmp_path / "Greenfield.ap19"
    ap.write_bytes(b"mock ap19 (temp copy)")
    scl = tmp_path / "AF_bundle.scl"
    scl.write_text("// mock mega-source", encoding="utf-8")

    posts: list[dict] = []
    writes: list[str] = []
    cli_calls: list[tuple] = []

    def fake_post(path: str, body: dict, timeout_s: float = 120.0) -> dict:
        posts.append({"path": path, "body": dict(body)})
        if path == "/open":
            return open_resp if open_resp is not None else {
                "ok": True, "project": {"ok": True}, "path": body.get("project"),
            }
        if path == "/fast-writeback":
            return fwb_resp if fwb_resp is not None else {
                "ok": True, "success": True, "exclusiveAccessUsed": True,
                "writtenBlockCount": 1, "errors": [], "elapsedMilliseconds": 12,
            }
        if path == "/compile-plc":
            return compile_resp if compile_resp is not None else {
                "ok": True, "scope": "full_software",
                "compile": {"state": "Success", "errorCount": 0, "warnings": [], "elapsedMs": 42.0},
            }
        if path == "/save":
            return {"ok": True}
        if path == "/close":
            return {"ok": True}
        return {"ok": False, "error": f"unexpected path {path}"}

    monkeypatch.setattr(openness_session, "ensure_session_running", lambda: True)
    monkeypatch.setattr(
        openness_session, "session_status",
        lambda: status if status is not None else dict(_OK_STATUS),
    )
    monkeypatch.setattr(openness_session, "_post", fake_post)

    # CLI 命令监控：会话模式不得触发 create-project / archive-project / close-project。
    monkeypatch.setattr(
        openness_cli, "openness_cli",
        lambda *args, **kw: cli_calls.append(args) or {"ok": True},
    )

    def rec_put(change: dict, **kw) -> dict:
        writes.append(str(change.get("change_id") or ""))
        return _REAL_PUT_CHANGE(change, **kw)

    monkeypatch.setattr(tia_delivery.pcec, "put_change", rec_put)

    return SimpleNamespace(
        ap=str(ap), scl=str(scl), posts=posts, writes=writes, cli_calls=cli_calls,
    )


def _increments(ap: str, scl: str) -> list[dict]:
    """UC-05 三次增量：① 改 EM 步序 ② 新增 CM ③ 改交互连线（均块级覆盖）。"""
    return [
        {"ap_path": ap, "overwrite": True, "blocks": [{"name": "U1_EM1_Step", "scl_path": scl}]},
        {"ap_path": ap, "overwrite": True, "blocks": [{"name": "U1_CM2_New", "scl_path": scl}]},
        {"ap_path": ap, "overwrite": True, "blocks": [{"name": "U1_Link1", "scl_path": scl}]},
    ]


def _paths(ctx: SimpleNamespace) -> list[str]:
    return [p["path"] for p in ctx.posts]


def _fwb_bodies(ctx: SimpleNamespace) -> list[dict]:
    return [p["body"] for p in ctx.posts if p["path"] == "/fast-writeback"]


# --------------------------------------------------------------------- ① 句柄


def test_open_once_and_three_increments_reuse_same_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """① /open 只调用一次；三次增量复用同一 session_handle。"""
    ctx = _mock_env(monkeypatch, tmp_path)
    port = SessionModeTiaPort(tia_version="V19")
    result = run_incremental_writebacks(port, _increments(ctx.ap, ctx.scl), ap_path=ctx.ap)

    assert result["ok"] is True
    assert _paths(ctx).count("/open") == 1, "连续增量不得重复 /open"
    assert port._open_count == 1
    assert result["session_handle"] == port.session_handle
    assert result["sequence"].count(("open_project", 0)) == 1

    # 同一路径再次 open 直接复用句柄，不再 POST /open。
    again = port.open_project(ctx.ap)
    assert again["reused"] is True
    assert again["session_handle"] == port.session_handle
    assert _paths(ctx).count("/open") == 1


# ------------------------------------------------------------- ② 禁用命令


def test_session_mode_never_calls_create_archive_close_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """② 会话模式只走 /open /fast-writeback /compile-plc /save，
    不调用 create-project / archive-project / close-project（CLI 与 HTTP 均不触）。"""
    ctx = _mock_env(monkeypatch, tmp_path)
    port = SessionModeTiaPort()
    result = run_incremental_writebacks(port, _increments(ctx.ap, ctx.scl), ap_path=ctx.ap)
    assert result["ok"] is True

    paths = _paths(ctx)
    assert "/open" in paths
    assert set(paths) <= {"/open", "/fast-writeback", "/compile-plc", "/save"}
    for forbidden in ("create-project", "archive-project", "close-project",
                      "create_project", "archive_project", "reload"):
        assert all(forbidden not in p for p in paths), f"会话模式触发了禁用路径 {forbidden}"
    # CLI 层同样零禁用命令（create-project 等一次性 CLI 完全不被调用）。
    assert not ctx.cli_calls, f"会话模式触发了 CLI 命令：{ctx.cli_calls}"


# -------------------------------------------------- ③ 三次增量序列 + PCEC 3 条


def test_three_increments_sequence_and_pcec_three_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """③ 三次增量调用序列固定，每次成功增量写 1 条 PCEC（共 3 条），
    且 fast-writeback 均带 overwrite:true（不归档 / 不重载 / 不新建）。"""
    ctx = _mock_env(monkeypatch, tmp_path)
    port = SessionModeTiaPort()
    result = run_incremental_writebacks(port, _increments(ctx.ap, ctx.scl), ap_path=ctx.ap)

    seq = [name for name, _ in result["sequence"]]
    assert seq == ["open_project"] + [
        "fast_writeback", "compile_plc", "save_project", "pcec",
    ] * 3
    assert result["increment_count"] == 3
    assert result["pcec_records"] == 3
    assert len(ctx.writes) == 3
    assert len(set(ctx.writes)) == 3  # 三条独立事务

    # 账本可读且 kind 正确（沿用 sanctioned pcec 记账路径）。
    for cid in ctx.writes:
        stored = pcec.get_change(cid)
        assert stored is not None
        assert stored["intent"]["kind"] == "greenfield_incremental"

    # overwrite:true 接通、会话路由调用次数与不重载语义。
    bodies = _fwb_bodies(ctx)
    assert len(bodies) == 3
    assert all(b.get("overwrite") is True for b in bodies)
    assert _paths(ctx).count("/fast-writeback") == 3
    assert _paths(ctx).count("/compile-plc") == 3
    assert _paths(ctx).count("/save") == 3
    assert result["mode"] == "incremental"
    assert result["pending_real_machine"] is True  # 真机项诚实标注


# --------------------------------------------- ④ ExclusiveAccess fail-closed


def test_exclusive_access_denied_fail_closed_zero_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """④ ExclusiveAccess 获取失败 → fail-closed：调用方阻止写入、零 PCEC、零副作用。"""
    denied = {
        "ok": False,
        "error": {
            "code": "exclusive_access_unavailable",
            "message": "TiaPortal.ExclusiveAccess(string) denied / file lock held",
        },
    }
    # 场景 A：/open 阶段即失败 → 连 fast-writeback 都不应发生。
    ctx_a = _mock_env(monkeypatch, tmp_path / "a", open_resp=denied)
    port_a = SessionModeTiaPort()
    res_a = run_incremental_writebacks(port_a, _increments(ctx_a.ap, ctx_a.scl), ap_path=ctx_a.ap)
    assert res_a["ok"] is False
    assert res_a["code"] == GF_EXCLUSIVE_ACCESS_DENIED
    assert res_a["http_status"] != 200
    assert res_a["increment_count"] == 0
    assert res_a["pcec_records"] == 0
    assert not ctx_a.writes
    assert "/fast-writeback" not in _paths(ctx_a)  # 零写入
    assert "/save" not in _paths(ctx_a)
    for field in _REQUIRED_FIELDS:
        assert field in port_a.open_project(ctx_a.ap)

    # 场景 B：/open 正常、/fast-writeback 阶段失败 → 零 compile / 零 save / 零 PCEC。
    fwb_denied = {
        "ok": False, "success": False, "exclusiveAccessUsed": False,
        "exclusiveAccessSkipReason": "exclusive_access_unavailable: reflection failed",
        "error": {"code": "exclusive_access_unavailable", "message": "denied"},
    }
    ctx_b = _mock_env(monkeypatch, tmp_path / "b", fwb_resp=fwb_denied)
    port_b = SessionModeTiaPort()
    res_b = run_incremental_writebacks(port_b, _increments(ctx_b.ap, ctx_b.scl), ap_path=ctx_b.ap)
    assert res_b["ok"] is False
    assert res_b["code"] == GF_EXCLUSIVE_ACCESS_DENIED
    assert res_b["pcec_records"] == 0
    assert not ctx_b.writes
    assert "/compile-plc" not in _paths(ctx_b)
    assert "/save" not in _paths(ctx_b)


# ------------------------------------------- ⑤ tia_unavailable 非 200


def test_tia_unavailable_explicit_non_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑤ tia_unavailable 显式失败：ok=false、code=GF_TIA_UNAVAILABLE、
    http_status!=200，绝不包装成 ok=true 或 HTTP 200；零写入。"""
    unavailable = {
        "ok": False, "available": False, "tia_version": "", "tia_running": False,
        "openness_available": False, "reason": "mock: TIA / Openness 不可用",
    }
    ctx = _mock_env(monkeypatch, tmp_path, status=unavailable)
    port = SessionModeTiaPort()

    opened = port.open_project(ctx.ap)
    assert opened["ok"] is False
    assert opened["code"] == GF_TIA_UNAVAILABLE
    assert opened["http_status"] != 200
    assert opened["http_status"] == 503
    for field in _REQUIRED_FIELDS:
        assert field in opened
    # 探测失败时根本不发 /open，更不触 /save。
    assert "/open" not in _paths(ctx)

    result = run_incremental_writebacks(port, _increments(ctx.ap, ctx.scl), ap_path=ctx.ap)
    assert result["ok"] is False
    assert result["code"] == GF_TIA_UNAVAILABLE
    assert result["http_status"] != 200
    assert result["pcec_records"] == 0
    assert not ctx.writes
    assert all(p not in ("/fast-writeback", "/save") for p in _paths(ctx))


# --------------------------------------- ⑥ warning 不污染 compile_ok


def test_compile_warning_does_not_pollute_compile_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑥ 会话模式 compile_plc 复用 CompileDiagnostics：warning 单列、
    error_count==0 ∧ static_gate_passed ⇒ compile_ok=True；warning 不并入成功。"""
    with_warnings = {
        "ok": True, "scope": "full_software",
        "compile": {
            "state": "SuccessWithWarnings", "errorCount": 0,
            "warnings": ["W1: unused temp var", "W2: implicit cast"],
            "elapsedMs": 7.5,
        },
    }
    ctx = _mock_env(monkeypatch, tmp_path, compile_resp=with_warnings)
    port = SessionModeTiaPort()
    port.open_project(ctx.ap)

    comp = port.compile_plc()
    assert comp["ok"] is True
    assert comp["error_count"] == 0
    assert comp["compile_ok"] is True
    assert comp["warnings"] == ["W1: unused temp var", "W2: implicit cast"]
    assert comp["compile_diagnostics"]["compile_ok"] is True
    assert comp["compile_diagnostics"]["warnings"] == ["W1: unused temp var", "W2: implicit cast"]

    # 三次增量全过，PCEC 仍为 3 条（warning 不阻挡、也不伪装成编译失败）。
    result = run_incremental_writebacks(port, _increments(ctx.ap, ctx.scl), ap_path=ctx.ap)
    assert result["ok"] is True
    assert result["pcec_records"] == 3

    # 负例：含 warning 但 error_count>0 时绝不能判成功（旧口径回归）。
    diag = tia_delivery.build_compile_diagnostics(
        {"ok": True, "compile": {"state": "SuccessWithWarnings", "errorCount": 1, "warnings": ["W1"]}},
        static_gate_passed=True, tia_version="V19", project_path=ctx.ap,
    )
    assert diag.compile_ok is False
    assert diag.warnings == ["W1"]


# --------------------------- ⑧ deliver_tia 会话模式分支执行体（接线证据）


def test_run_session_mode_import_compile_uses_session_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """deliver_tia 的 session_mode 分支执行体只走 4 条会话路由，产出结构化
    compile_ok 诊断，不 create-project / 不归档 / 不重载 / 不新建。"""
    ctx = _mock_env(monkeypatch, tmp_path)
    run = tia_delivery._run_session_mode_import_compile(
        project_name="GF",
        package_dir=tmp_path,
        workspace=tmp_path,
        planned_text="// mock mega-source",
        supplement={"ob_files": []},
        tia_version="V19",
    )
    assert run["status"] == "compile_ok"
    assert run["diagnostics"]["compile_ok"] is True
    paths = _paths(ctx)
    for route in ("/open", "/fast-writeback", "/compile-plc", "/save"):
        assert route in paths
    assert set(paths) <= {"/open", "/fast-writeback", "/compile-plc", "/save"}
    assert [s["step"] for s in run["steps"]] == [
        "/open", "/fast-writeback", "/compile-plc", "/save",
    ]


# --------------------------------- ⑦ 开关与 Protocol 形状（默认兼容）


def test_session_mode_switch_and_port_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑦ 会话模式默认关闭（向后兼容）；显式参数 / 环境变量可开启；
    SessionModeTiaPort 满足契约 §3.1 的 TiaSessionPort 形状。"""
    monkeypatch.delenv(SESSION_MODE_ENV, raising=False)
    assert session_mode_enabled() is False
    assert session_mode_enabled(None) is False
    assert session_mode_enabled(True) is True
    assert session_mode_enabled(False) is False
    monkeypatch.setenv(SESSION_MODE_ENV, "1")
    assert session_mode_enabled() is True
    monkeypatch.setenv(SESSION_MODE_ENV, "0")
    assert session_mode_enabled() is False

    port = SessionModeTiaPort()
    assert isinstance(port, TiaSessionPort)
    for method in ("open_project", "fast_writeback", "compile_plc", "save_project", "close"):
        assert callable(getattr(port, method))
