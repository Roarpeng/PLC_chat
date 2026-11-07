"""批次 3 · Agent R · UC-18 编排函数纯离线单测。

只验证 ``compile_feedback_heal`` / ``_locate_compile_errors`` / ``_build_fix_proposal``
的编排结构与诚实口径（warning 单列、pending_real_machine 不静默消除、不臆造数字）。
**recompile 回调用确定性 dict 构造响应，仅为结构验证；不连真机、不构成 L2/L4 证据、
不宣称「编译零错误」**——真机三段 errorCount 见 evidence/uc18_compile_feedback_real.json。
"""
from __future__ import annotations

from gateway.app.services.plc.tia_delivery import (
    COMPILE_STATUS_COMPILED,
    COMPILE_STATUS_PENDING_REAL_MACHINE,
    CompileDiagnostics,
    _build_fix_proposal,
    _locate_compile_errors,
    compile_feedback_heal,
)


def _failed(error_count: int = 2, reason: str = "") -> dict:
    return CompileDiagnostics(
        error_count=error_count,
        static_gate_passed=True,
        compile_ok=error_count == 0,
        reason=reason,
    ).to_dict()


def _clean_compile_raw(error_count: int = 0, warnings: list[str] | None = None) -> dict:
    return {
        "ok": True,
        "compile": {
            "ok": True, "apiAvailable": True, "state": "Success",
            "errorCount": error_count, "warningCount": len(warnings or []),
            "warnings": list(warnings or []),
            "message": f"Compile State=Success errors={error_count}",
        },
    }


def test_no_recompile_marks_pending_real_machine_not_success() -> None:
    """未提供复编译回调：after_fix 显式 pending_real_machine，heal_ok=False，不冒充真机。"""
    r = compile_feedback_heal(before=_failed(0), failed=_failed(2, "OB 引用缺失"))
    assert r["after_fix"]["status"] == COMPILE_STATUS_PENDING_REAL_MACHINE
    assert r["after_fix"]["pending_real_machine"] is True
    assert r["after_fix"]["compile_ok"] is False
    assert r["heal_ok"] is False
    assert "禁止" in r["after_fix"]["note"]


def test_three_phase_diagnostics_with_clean_recompile() -> None:
    """三段诊断结构齐全：注入前 0 / 失败 >0 / 修正后 0，heal_ok=True。"""
    before = CompileDiagnostics(
        error_count=0, static_gate_passed=True, compile_ok=True,
    ).to_dict()
    r = compile_feedback_heal(
        before=before,
        failed=_failed(2, "R_OB_CallFault 引用不存在实例 DB"),
        recompile=lambda: _clean_compile_raw(0),
        fix_hint="去除缺失实例 DB 的 Call 依赖",
        ledger_ref="evidence/uc18_compile_feedback_real.json#heal",
        static_gate_passed=True,
        tia_version="V19",
        project_path="C:/Temp/gf_real_*/proj/CanvasE2E.ap19",
    )
    assert r["before_injection"]["error_count"] == 0
    assert r["failed"]["error_count"] == 2
    assert r["after_fix"]["error_count"] == 0
    assert r["after_fix"]["status"] == COMPILE_STATUS_COMPILED
    assert r["heal_ok"] is True
    assert r["ledger_ref"].startswith("evidence/")
    assert r["recompile_raw_return"]["compile"]["errorCount"] == 0


def test_warning_is_single_column_not_merged_into_success() -> None:
    """含 warning 但 errorCount=0 的复编译：warning 单列、compile_ok 仍 True（N9/P0-A）。"""
    r = compile_feedback_heal(
        before=_failed(0),
        failed=_failed(1, "语法错误"),
        recompile=lambda: _clean_compile_raw(0, warnings=["变量未使用"]),
    )
    assert r["after_fix"]["warnings"] == ["变量未使用"]
    assert r["after_fix"]["error_count"] == 0
    assert r["after_fix"]["compile_ok"] is True
    assert r["heal_ok"] is True
    assert "warning" in r["warning_separation"]


def test_recompile_still_failing_marks_heal_not_ok() -> None:
    """复编译仍 errorCount>0：heal_ok=False，不美化、不静默。"""
    r = compile_feedback_heal(
        before=_failed(0),
        failed=_failed(2, "占位实例 DB 缺失"),
        recompile=lambda: _clean_compile_raw(3),
    )
    assert r["after_fix"]["error_count"] == 3
    assert r["after_fix"]["compile_ok"] is False
    assert r["heal_ok"] is False


def test_locate_compile_errors_extracts_line_and_block() -> None:
    """错误定位：从失败诊断的 reason / blocks 中抽取行号与 OB/DB 块名，只读不臆造。"""
    located = _locate_compile_errors({
        "error_count": 2,
        "blocks": ["R_OB_CallFault"],
        "reason": "R_OB_CallFault 行 14: 占位实例 DB R_NoSuchInstDB 不存在",
        "warnings": [],
    })
    assert located["error_count"] == 2
    assert located["line_numbers"] == [14]
    assert "R_OB_CallFault" in located["blocks"]
    assert located["locatable"] is True


def test_build_fix_proposal_is_reproducible_and_non_mutating() -> None:
    """修正建议含可复现命令与步骤，且声明不改冻结模块、不代跑编译。"""
    located = {
        "error_count": 2, "blocks": ["R_OB_CallFault"], "line_numbers": [14],
        "reason": "占位实例 DB 不存在", "warnings": [], "locatable": True,
    }
    p = _build_fix_proposal(located, "去除缺失实例 DB 的 Call")
    assert "compile-plc" in p["reproducible_command"]
    assert p["target_lines"] == [14]
    assert p["target_blocks"] == ["R_OB_CallFault"]
    assert p["fix_hint"] == "去除缺失实例 DB 的 Call"
    assert "不改冻结模块" in p["note"]


def test_honest_note_states_numbers_come_from_real_returns() -> None:
    """诚实口径声明：三段数值来自真实原始返回，编排函数本身不产生数字。"""
    r = compile_feedback_heal(
        before=_failed(0), failed=_failed(2), recompile=lambda: _clean_compile_raw(0),
    )
    assert "真实" in r["honest_note"]
    assert r["schema"] == "gf-uc18-compile-feedback-v1"
