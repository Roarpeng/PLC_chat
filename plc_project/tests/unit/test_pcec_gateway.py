"""PCEC 网关接入（契约 docs/19-pcec-contract.md §4 · 并行线 B）。

线 A（``plc_engine/pcec.py``）尚未交付时，这里按契约 §3 的**固定签名**构造
fake 模块注入 ``sys.modules``，验证网关侧完整链路：

- confirm-writeback 确认即建事务（new_change → 预检 v1_static → approval →
  approved → 账本），change_id 随作业/响应下发；
- 编译作业收敛回写事务（ok → applied + rollback；error → failed + 诊断摘要）；
- 写回前基线门禁（baseline_matches=False → 事务 expired + 作业 fail-closed）；
- 事务任何异常只 warning，绝不阻塞写回主流程；
- GET /canvas/changes 与 GET /canvas/changes/{id}。
"""

from __future__ import annotations

import hashlib
import re
import sys
import threading
import time
import types
import uuid
from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import create_app
from gateway.app.services.plc import compile_jobs as cj
from plc_engine.canvas_model import create_empty_canvas

_WAIT_TIMEOUT_S = 5.0
_CHANGE_ID_RE = re.compile(r"^chg-[0-9a-f]{12}$")


# ---------------------------------------------------------------------------
# 契约 §3 签名的 fake pcec（内存账本 + 契约 §2 状态机）
# ---------------------------------------------------------------------------


def _build_fake_pcec() -> types.ModuleType:
    mod = types.ModuleType("plc_engine.pcec")
    lock = threading.Lock()
    ledger: dict[str, dict[str, Any]] = {}
    # 注入开关：按用例制造 pcec 侧异常/基线漂移
    state: dict[str, Any] = {"baseline_override": {}}

    class PcecTransitionError(Exception):
        """契约 §2：非法迁移必须抛的异常。"""

    # 契约 §2 状态机（终态不可再迁移；applied → rolled_back 例外）
    legal = {
        "proposed": {"analyzed"},
        "analyzed": {"validated", "rejected", "expired"},
        "validated": {"approved", "failed", "expired"},
        "approved": {"applied", "failed", "expired"},
        "applied": {"rolled_back"},
        "failed": set(),
        "expired": set(),
        "rejected": set(),
        "rolled_back": set(),
    }

    mod.VERSION = "0.1-fake"
    mod.PcecTransitionError = PcecTransitionError
    mod.LEDGER = ledger
    mod.STATE = state

    def project_baseline(project_path: Any, settings: Any | None = None) -> dict[str, Any]:
        key = str(project_path)
        override = state["baseline_override"].get(key)
        digest = override or ("sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32])
        return {"project_hash": digest, "tia_version": "V19-test", "parser_version": mod.VERSION}

    def new_change(
        intent_kind: str,
        request: str,
        ops: list,
        touched_blocks: list,
        baseline: dict,
    ) -> dict[str, Any]:
        now = time.time()
        cid = "chg-" + uuid.uuid4().hex[:12]
        return {
            "change_id": cid,
            "created_at": now,
            "updated_at": now,
            "project_baseline": deepcopy(baseline),
            "intent": {"kind": intent_kind, "request": request, "summary": request[:60]},
            "ops": list(ops or []),
            "touched_blocks": list(touched_blocks or []),
            "preconditions": [],
            "impact": {},
            "verification": {
                "v0_parsed": "pending",
                "v1_static": "pending",
                "v2_tia_compile": "pending",
                "v3_behavior": "pending",
                "detail": {},
            },
            "approval": {},
            "rollback": {"backup_path": "", "backup_hash": "", "restore_verified": False},
            "status": "proposed",
            "events": [{"ts": now, "event": "created"}],
        }

    def transition(change: dict, to_status: str, *, event: str = "", **patch: Any) -> dict:
        if to_status not in legal.get(str(change.get("status")), set()):
            raise PcecTransitionError(
                f"illegal transition {change.get('status')} -> {to_status}"
            )
        chg = deepcopy(change)
        chg["status"] = to_status
        chg["updated_at"] = time.time()
        chg.setdefault("events", []).append({"ts": chg["updated_at"], "event": event or to_status})
        for key, value in patch.items():
            chg[key] = deepcopy(value)
        return chg

    def baseline_matches(change: dict, project_path: Any, settings: Any | None = None) -> bool:
        return (
            (change.get("project_baseline") or {}).get("project_hash")
            == project_baseline(project_path)["project_hash"]
        )

    def put_change(change: dict, settings: Any | None = None) -> dict:
        with lock:
            ledger[str(change["change_id"])] = deepcopy(change)
        return deepcopy(change)

    def get_change(change_id: str, settings: Any | None = None) -> dict | None:
        with lock:
            chg = ledger.get(str(change_id))
            return deepcopy(chg) if chg else None

    def list_changes(settings: Any | None = None) -> list[dict]:
        with lock:
            metas = [
                {
                    "change_id": c["change_id"],
                    "kind": c["intent"]["kind"],
                    "summary": c["intent"]["summary"],
                    "status": c["status"],
                    "updated_at": c["updated_at"],
                    "touched": len(c["touched_blocks"]),
                }
                for c in ledger.values()
            ]
        metas.sort(key=lambda m: -float(m["updated_at"]))
        return metas

    def changes_root(settings: Any | None = None) -> Any:
        import tempfile
        from pathlib import Path

        return Path(tempfile.gettempdir()) / "researchos_plc_test_changes"

    mod.project_baseline = project_baseline
    mod.new_change = new_change
    mod.transition = transition
    mod.baseline_matches = baseline_matches
    mod.put_change = put_change
    mod.get_change = get_change
    mod.list_changes = list_changes
    mod.changes_root = changes_root
    return mod


@pytest.fixture
def fake_pcec(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """按契约签名伪造 plc_engine.pcec（线 A 未交付也可测网关全链）。"""
    import plc_engine

    mod = _build_fake_pcec()
    monkeypatch.setitem(sys.modules, "plc_engine.pcec", mod)
    monkeypatch.setattr(plc_engine, "pcec", mod, raising=False)
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离环境开关：不许子进程模式/allowlist 干扰，也不残留 fake 模块。"""
    monkeypatch.delenv("PLC_COMPILE_JOB_SUBPROCESS", raising=False)
    monkeypatch.delenv("PLC_COMPILE_JOB_SUBPROCESS_ALL", raising=False)
    monkeypatch.delenv("PLC_ALLOWED_PROJECT_DIRS", raising=False)
    # 兜底：上个用例若真实装过 pcec（线 A 交付后），恢复前先摘除
    monkeypatch.setitem(sys.modules, "plc_engine.pcec", None)
    # 单测里绝不碰真实 Openness
    monkeypatch.setattr(
        "gateway.app.services.plc.openness_session.ensure_project_open",
        lambda project_path, *, plc_name="": {"ok": True},
    )
    monkeypatch.setattr(
        "gateway.app.services.plc.openness_session.save_project",
        lambda project_path="": {"ok": True},
    )


def _wait_terminal(job_id: str, timeout_s: float = _WAIT_TIMEOUT_S) -> dict[str, Any]:
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


def _stub_writeback(
    monkeypatch: pytest.MonkeyPatch,
    result: dict[str, Any] | None = None,
    attributions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """替换真实写回并记录调用；返回调用记录列表。"""
    calls: list[dict[str, Any]] = []
    payload = result if result is not None else {
        "ok": True,
        "generated": True,
        "backup_path": "D:/bak/demo.pre-write.zip",
        "backup_hash": "sha256:deadbeef",
    }

    def _fake(canvas: Any, **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        calls.append(kwargs)
        return deepcopy(payload), deepcopy(list(attributions or []))

    monkeypatch.setattr("plc_engine.canvas_tia_transpiler.execute_canvas_writeback", _fake)
    return calls


def _canvas_no_hmi(project_name: str = "Demo"):
    """无 HMI 设备的画布：confirm 端点据此把 compile_hmi 关掉（测试只关心 PLC 链）。"""
    canvas = create_empty_canvas(project_name)
    canvas.hmi_devices = []
    return canvas


# ---------------------------------------------------------------------------
# 1. 完整链：confirm → 建事务 → 作业收敛 → 账本 applied → 变更 API
# ---------------------------------------------------------------------------


def test_confirm_to_applied_full_chain(fake_pcec, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_writeback(monkeypatch)  # ok + backup_path/backup_hash
    client = TestClient(create_app())

    resp = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": _canvas_no_hmi().to_dict(),
            "project_path": "C:/tmp/Demo.ap19",
            "plc_name": "PLC_1",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["async"] is True
    change_id = data["change_id"]
    assert change_id and _CHANGE_ID_RE.match(change_id), "确认响应必须带 change_id"
    job_id = data["job"]["id"]
    assert data["job"]["change_id"] == change_id, "作业记录携带 change_id"

    live = _wait_terminal(job_id)
    assert live["status"] == "ok"
    assert live["change_id"] == change_id
    assert len(calls) == 1, "写回主流程照常执行"

    # 账本：proposed → … → approved → applied，V0/V1/V2 全 pass，rollback 证据齐全
    chg = fake_pcec.get_change(change_id)
    assert chg is not None
    assert chg["status"] == "applied"
    assert chg["intent"]["kind"] == "writeback"
    assert sorted(chg["touched_blocks"]) == ["MainDB", "MotorCtrl"]
    ver = chg["verification"]
    assert ver["v0_parsed"] == "pass"
    assert ver["v1_static"] == "pass"
    assert ver["v2_tia_compile"] == "pass"
    assert ver["detail"]["compile_job_id"] == job_id
    assert chg["rollback"]["backup_path"] == "D:/bak/demo.pre-write.zip"
    assert chg["rollback"]["backup_hash"] == "sha256:deadbeef"
    assert chg["approval"]["reviewer"]
    events = [e["event"] for e in chg["events"]]
    assert "created" in events and "approved" in events and "applied" in events

    # 变更 API：meta 列表 + 单条完整事务 + 未知 404
    r_list = client.get("/api/v1/plc/canvas/changes")
    assert r_list.status_code == 200
    metas = r_list.json()["data"]
    assert any(m.get("change_id") == change_id for m in metas)

    r_one = client.get(f"/api/v1/plc/canvas/changes/{change_id}")
    assert r_one.status_code == 200
    assert r_one.json()["data"]["status"] == "applied"

    r_404 = client.get("/api/v1/plc/canvas/changes/chg-ffffffffffff")
    assert r_404.status_code == 404
    assert r_404.json()["detail"]["code"] == "PLC_CHANGE_NOT_FOUND"


def test_sync_confirm_settles_change(fake_pcec, monkeypatch: pytest.MonkeyPatch) -> None:
    """sync=true 分支：确认建事务 + 写回后直接落账 applied。"""
    _stub_writeback(monkeypatch)
    client = TestClient(create_app())

    resp = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": _canvas_no_hmi().to_dict(),
            "project_path": "C:/tmp/Demo.ap19",
            "sync": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["async"] is False
    change_id = data["change_id"]
    assert change_id

    chg = fake_pcec.get_change(change_id)
    assert chg is not None
    assert chg["status"] == "applied"
    assert chg["verification"]["v2_tia_compile"] == "pass"
    assert chg["rollback"]["backup_path"] == "D:/bak/demo.pre-write.zip"


# ---------------------------------------------------------------------------
# 2. 基线门禁：baseline_matches=False → 事务 expired + 作业 fail-closed
# ---------------------------------------------------------------------------


def test_baseline_mismatch_expires_and_fail_closes(
    fake_pcec, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_writeback(monkeypatch)
    canvas = create_empty_canvas("Demo")
    change_id = cj.open_writeback_change(canvas, project_path="C:/tmp/B.ap19")
    assert change_id, "预检通过的画布应成功建事务"

    # 模拟确认之后、写回之前工程被人改过（基线漂移）
    fake_pcec.STATE["baseline_override"]["C:/tmp/B.ap19"] = "sha256:changed-elsewhere"

    job = cj.create_compile_job(
        canvas.to_dict(),
        project_path="C:/tmp/B.ap19",
        compile_hmi=False,
        change_id=change_id,
    )
    live = _wait_terminal(job["id"])

    assert live["status"] == "error"
    assert live["error"] == "baseline_expired"
    assert calls == [], "基线失配必须 fail-closed，绝不写工程"
    stage = _stage(live, "write_plc")
    assert stage["status"] == "error"
    assert "工程基线已变化" in stage["message"]
    assert "变更过期拒绝" in stage["message"]
    for name in ("compile_plc", "write_hmi", "compile_hmi", "save"):
        assert _stage(live, name)["status"] == "skipped", name

    chg = fake_pcec.get_change(change_id)
    assert chg is not None
    assert chg["status"] == "expired"
    assert chg["verification"]["detail"]["baseline_mismatch"] is True


# ---------------------------------------------------------------------------
# 3. 兜底：pcec 缺席/抛错绝不阻塞写回主流程
# ---------------------------------------------------------------------------


def test_pcec_module_missing_confirm_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """线 A 未交付（import 失败）→ 不建账、不拦写回、变更 API 空列表/404。"""
    calls = _stub_writeback(monkeypatch)
    client = TestClient(create_app())

    resp = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": _canvas_no_hmi().to_dict(),
            "project_path": "C:/tmp/Demo.ap19",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["change_id"] == ""
    live = _wait_terminal(data["job"]["id"])
    assert live["status"] == "ok"
    assert len(calls) == 1, "pcec 缺席不得影响写回"

    r_list = client.get("/api/v1/plc/canvas/changes")
    assert r_list.status_code == 200
    assert r_list.json()["data"] == []
    r_one = client.get("/api/v1/plc/canvas/changes/chg-aaaaaaaaaaaa")
    assert r_one.status_code == 404


def test_pcec_exception_never_blocks_writeback(fake_pcec, monkeypatch: pytest.MonkeyPatch) -> None:
    """建事务抛错 → confirm 仍 200、change_id 为空、作业照常收敛 ok。"""
    original_new_change = fake_pcec.new_change

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("pcec ledger exploded")

    monkeypatch.setattr(fake_pcec, "new_change", _boom)

    calls = _stub_writeback(monkeypatch)
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": _canvas_no_hmi().to_dict(),
            "project_path": "C:/tmp/Demo.ap19",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["change_id"] == "", "事务失败必须静默降级，不报错"
    live = _wait_terminal(data["job"]["id"])
    assert live["status"] == "ok"
    assert len(calls) == 1

    # 收敛阶段 transition 抛错 → 账本停在 approved，但作业终态不受影响
    monkeypatch.setattr(fake_pcec, "new_change", original_new_change)
    change_id = cj.open_writeback_change(create_empty_canvas("Demo"), project_path="C:/tmp/C.ap19")
    assert change_id

    def _boom_transition(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("pcec transition exploded")

    monkeypatch.setattr(fake_pcec, "transition", _boom_transition)
    job = cj.create_compile_job(
        create_empty_canvas("Demo").to_dict(),
        project_path="C:/tmp/C.ap19",
        compile_hmi=False,
        change_id=change_id,
    )
    live2 = _wait_terminal(job["id"])
    assert live2["status"] == "ok", "记账失败不得影响作业终态"
    chg = fake_pcec.get_change(change_id)
    assert chg is not None and chg["status"] == "approved", "账本保持建账后的合法状态"


# ---------------------------------------------------------------------------
# 4. 收敛失败路径：error → failed + 诊断摘要（≤20 条，复用归因）
# ---------------------------------------------------------------------------


def test_compile_failure_marks_change_failed_with_diagnostics(
    fake_pcec, monkeypatch: pytest.MonkeyPatch
) -> None:
    attributions = [
        {
            "target_type": "block",
            "target_id": f"B{i:02d}",
            "severity": "error",
            "message": f"compile error {i}",
            "source": "compile",
        }
        for i in range(25)
    ]
    _stub_writeback(
        monkeypatch,
        result={"ok": False, "error": "compile failed", "message": "PLC 编译失败"},
        attributions=attributions,
    )

    canvas = create_empty_canvas("Demo")
    change_id = cj.open_writeback_change(canvas, project_path="C:/tmp/F.ap19")
    assert change_id

    job = cj.create_compile_job(
        canvas.to_dict(),
        project_path="C:/tmp/F.ap19",
        compile_hmi=False,
        change_id=change_id,
    )
    live = _wait_terminal(job["id"])
    assert live["status"] == "error"

    chg = fake_pcec.get_change(change_id)
    assert chg is not None
    assert chg["status"] == "failed"
    assert chg["verification"]["v2_tia_compile"] == "fail"
    detail = chg["verification"]["detail"]
    assert detail["compile_job_id"] == job["id"]
    assert detail["error_count"] == 25
    assert len(detail["diagnostics"]) == 20, "诊断摘要最多 20 条"
    assert detail["diagnostics"][0]["target_id"] == "B00"
    assert detail["diagnostics"][19]["target_id"] == "B19"


def test_precheck_failure_marks_change_rejected(fake_pcec, monkeypatch: pytest.MonkeyPatch) -> None:
    """确认时预检失败 → 事务 rejected（v1_static=fail）；作业 fail-closed 后
    收敛不得把终态 rejected 改写成 failed（终态不可迁移）。"""
    calls = _stub_writeback(monkeypatch)
    canvas = create_empty_canvas("Demo")
    canvas.blocks["MotorCtrl"].scl_body = "IF #Start THEN\n    // TODO 待实现\n"

    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={"canvas": canvas.to_dict(), "project_path": "C:/tmp/P.ap19"},
    )
    assert resp.status_code == 200
    change_id = resp.json()["data"]["change_id"]
    assert change_id, "预检失败也要建账（rejected 是合法终态）"

    chg = fake_pcec.get_change(change_id)
    assert chg is not None
    assert chg["status"] == "rejected"
    assert chg["verification"]["v1_static"] == "fail"

    live = _wait_terminal(resp.json()["data"]["job"]["id"])
    assert live["status"] == "error"
    assert live["error"] == "precheck_failed"
    assert calls == []

    # 收敛时已是终态（rejected）→ 不再迁移，账本保持 rejected
    chg2 = fake_pcec.get_change(change_id)
    assert chg2 is not None and chg2["status"] == "rejected"
