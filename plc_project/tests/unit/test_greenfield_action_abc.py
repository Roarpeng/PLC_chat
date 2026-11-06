"""WP-06 / Action A·B·C 产品化 + D11 硬门禁（F9 / F16 完整版 / F20 服务端）单测。

覆盖：UC-17（fidelity_ok=false 时 B 被拒）、UC-19（确认前零副作用）、
UC-12（D10 反向保护阻止、禁止先覆盖再提示）、UC-13（失败导入回滚）、
§13.5 八步顺序、增量响应字段、会话复用 / 归属冲突（D9）、compile_ok 口径、
旧端点兼容（D11 只挂新增端点，不挂 /generate /deliver-tia）。

**诚实口径（契约 §0.4 / §6）**：本文件全部为 mock / 离线单测，验证服务端编排、
门禁与数据结构；真机 L2（编译零错误）/ L4（三次增量不重载）一律
``pending_real_machine``，由主 agent 收口实测，**禁止**据此宣称 L2/L4 通过或
「编译零错误」。N9：``fidelity_ok`` 与 ``compile_ok`` 严格分离；warning 单列。
``xml_package_unverified`` 保持 True。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc import greenfield_service as svc
from gateway.app.services.plc.greenfield_session import GreenfieldSession, registry
from plc_engine.af.spec_diff import canonical_hash

PREFIX = "/api/v1/plc/canvas/greenfield"
ZERO_COUNTERS = {"ops": 0, "disk_writes": 0, "writebacks": 0, "generations": 0}


# ---------------------------------------------------------------------------
# 契约 §3.1 TiaSessionPort 的 mock 实现（全离线，不连真机）。
# ---------------------------------------------------------------------------
class _MockPort:
    def __init__(
        self,
        *,
        open_ok: bool = True,
        fwb_ok: bool = True,
        compile_error_count: int = 0,
        compile_warnings: list[str] | None = None,
        compile_ok_flag: bool = True,
        save_ok: bool = True,
        tia_unavailable: bool = False,
    ) -> None:
        self.calls: list[tuple] = []
        self.open_count = 0
        self.open_ok = open_ok
        self.fwb_ok = fwb_ok
        self.compile_error_count = compile_error_count
        self.compile_warnings = list(compile_warnings or [])
        self.compile_ok_flag = compile_ok_flag
        self.save_ok = save_ok
        self.tia_unavailable = tia_unavailable

    def _base(self, **extra):
        out = {
            "ok": True, "error_count": 0, "warnings": [],
            "tia_version": "V19", "project_path": "", "elapsed_ms": 1.0,
        }
        out.update(extra)
        return out

    def open_project(self, ap_path: str) -> dict:
        self.calls.append(("open_project", ap_path))
        if self.tia_unavailable:
            return self._base(ok=False, code=svc.GF_TIA_UNAVAILABLE,
                              tia_unavailable=True, reason="mock: TIA / Openness 不可用")
        if not self.open_ok:
            return self._base(ok=False, code=svc.GF_TIA_EXEC_ERROR, reason="mock open fail")
        self.open_count += 1
        return self._base(session_handle=f"mock-h{self.open_count}",
                          reused=self.open_count > 1, project_path=ap_path)

    def fast_writeback(self, blocks, *, overwrite: bool = True) -> dict:
        self.calls.append(("fast_writeback", list(blocks), overwrite))
        if not self.fwb_ok:
            return self._base(ok=False, error="mock write fail", error_count=1)
        return self._base(writtenBlockCount=len(blocks))

    def compile_plc(self) -> dict:
        self.calls.append(("compile_plc",))
        return self._base(
            ok=self.compile_ok_flag,
            error_count=self.compile_error_count,
            warnings=list(self.compile_warnings),
            reason="" if self.compile_ok_flag else "mock compile error",
        )

    def save_project(self) -> dict:
        self.calls.append(("save_project",))
        return self._base(ok=self.save_ok)

    def close(self) -> dict:
        self.calls.append(("close",))
        return self._base()


def _method_names(port: _MockPort) -> list[str]:
    return [c[0] for c in port.calls]


# ---------------------------------------------------------------------------
# 会话与差异清单 helpers
# ---------------------------------------------------------------------------
def _frozen(monkeypatch: pytest.MonkeyPatch, tmp_path, sid: str = "act") -> GreenfieldSession:
    """构造已 FROZEN 会话（冻结规格落 tmp_path，避免污染真实工作目录）。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    s = GreenfieldSession(session_id=sid)
    svc.draft_from_prompt(s, "")
    svc.revalidate(s)
    svc.engineering_summary(s)
    svc.confirm_and_freeze(s, explicit=True)
    return s


def _with_action_a(monkeypatch, tmp_path, sid: str = "act") -> GreenfieldSession:
    s = _frozen(monkeypatch, tmp_path, sid)
    svc.run_action_a(s)  # 生成 last_delivery + fidelity_ok=true
    return s


def _snapshot(s: GreenfieldSession) -> dict[str, str]:
    """与「上次生成物」一致的 TIA 侧块哈希快照（离线演练 mock）。"""
    return {e["source_id"]: e["sha256"] for e in s.last_delivery["blocks_manifest"]}


def _diff(base: int = 1, target: int = 2, sids=("SID_X",)) -> dict:
    return {
        "base_spec_version": base,
        "target_spec_version": target,
        "changed": [{"source_id": x, "kind": "em", "payload": {}} for x in sids],
        "added": [],
        "removed": [],
        "changed_source_ids": list(sids),
    }


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset()
    yield
    registry.reset()


def _http_frozen(client: TestClient, monkeypatch, tmp_path) -> str:
    """经 HTTP 完成 FROZEN，返回 session_id。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    sid = client.get(f"{PREFIX}/state").json()["data"]["session_id"]
    assert client.post(f"{PREFIX}/draft", json={"session_id": sid, "prompt": ""}).status_code == 200
    assert client.post(f"{PREFIX}/validate", json={"session_id": sid}).status_code == 200
    assert client.post(f"{PREFIX}/engineering-summary", json={"session_id": sid}).status_code == 200
    cf = client.post(f"{PREFIX}/confirm", json={"session_id": sid, "explicit": True})
    assert cf.status_code == 200, cf.json()
    return sid


# ---------------------------------------------------------------------------
# Action A：EvidenceBundle 可离线校验、不写 TIA、返回 fidelity_ok
# ---------------------------------------------------------------------------
def test_action_a_produces_offline_verifiable_evidence_bundle(monkeypatch, tmp_path) -> None:
    s = _frozen(monkeypatch, tmp_path, "a-evidence")
    a = svc.run_action_a(s)

    assert a["ok"] is True and a["action"] == "A" and a["mode"] == "full"
    assert a["fidelity_ok"] is True                 # L1 离线逻辑等价
    assert a["tia_written"] is False               # 不写 TIA
    assert a["compile_ok"] is None                 # N9：A 不产出编译结论
    assert a["xml_package_unverified"] is True
    assert a["pending_real_machine"] is True

    eb = a["evidence_bundle"]
    for key in (
        "spec", "ir_snapshot", "views", "edge_list", "static_gate",
        "artifact_hashes", "zip_entry_hashes", "fidelity_report", "package",
        "bundle_sha256", "baseline_manifest", "source_id_map",
    ):
        assert key in eb, f"EvidenceBundle 缺 {key}"
    assert eb["offline_verifiable"] is True
    assert eb["fidelity_report"]["fidelity_ok"] is True
    assert eb["compile_ok"] is None
    assert "flow" in eb["views"]                  # 四视图
    assert eb["package"]["zip_sha256"]
    assert eb["package"]["zip_entry_count"] > 0
    # bundle_sha256 可离线复算（第三方仅凭证据包即可校验）
    body = {k: v for k, v in eb.items() if k not in ("bundle_sha256", "package_zip_base64")}
    assert canonical_hash(body) == eb["bundle_sha256"] == a["evidence_bundle_sha256"]
    # A 的结论寄存会话，供 UC-17 的 B 前置读取
    assert s.last_fidelity_report["fidelity_ok"] is True
    assert s.last_fidelity_ok is True


def test_action_a_over_http_returns_fidelity_ok(monkeypatch, tmp_path) -> None:
    client = TestClient(app)
    sid = _http_frozen(client, monkeypatch, tmp_path)
    resp = client.post(f"{PREFIX}/action-a", json={"session_id": sid})
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["fidelity_ok"] is True
    assert data["tia_written"] is False
    assert data["evidence_bundle"]["offline_verifiable"] is True


# ---------------------------------------------------------------------------
# UC-17：Action B 以 A 的 fidelity_ok == true 为前提
# ---------------------------------------------------------------------------
def test_uc17_action_b_rejected_when_action_a_fidelity_false(monkeypatch, tmp_path) -> None:
    # 走真实负例：注入不一致 TIA 侧快照 → A 的 fidelity_ok=false
    s = _frozen(monkeypatch, tmp_path, "uc17-real")
    a_bad = svc.run_action_a(s, tia_side_snapshot={"BAD_SID": "sha256:hand_edited"})
    assert a_bad["fidelity_ok"] is False

    b = svc.run_action_b(s, confirmed=True)
    assert b["blocked"] is True
    assert b["code"] == svc.ACTION_B_FIDELITY_FAILED
    assert "fidelity_ok" in b["reason"] and "UC-17" in b["reason"]
    assert b["fidelity_ok"] is False
    assert b["prerequisite"] == "fidelity_ok == true"
    assert b["zero_side_effects"] is True
    assert s.action_b_done is False


def test_uc17_action_b_rejected_with_explicit_false_report(monkeypatch, tmp_path) -> None:
    s = _frozen(monkeypatch, tmp_path, "uc17-explicit")
    b = svc.run_action_b(s, confirmed=True, fidelity_report={"fidelity_ok": False})
    assert b["blocked"] is True and b["code"] == svc.ACTION_B_FIDELITY_FAILED
    assert b["zero_side_effects"] is True

    # 亦覆盖「从未跑过 A」：无 fidelity 报告同样拒绝
    s2 = GreenfieldSession(session_id="uc17-no-a")
    b2 = svc.run_action_b(s2, confirmed=True)
    assert b2["blocked"] is True and b2["code"] == svc.ACTION_B_FIDELITY_FAILED


# ---------------------------------------------------------------------------
# UC-19：D11 服务端 fail-closed，确认前零副作用（ops/disk_writes/writebacks/generations 恒 0）
# ---------------------------------------------------------------------------
def test_uc19_confirm_gate_zero_side_effects_service() -> None:
    # 全新会话：计数器本就全 0，未确认时 B / C 均不得产生任何副作用
    sb = GreenfieldSession(session_id="uc19-b")
    sc = GreenfieldSession(session_id="uc19-c")
    rb = svc.run_action_b(sb, confirmed=False)
    rc = svc.run_action_c(sc, confirmed=False)

    for r in (rb, rc):
        assert r["blocked"] is True
        assert r["code"] == svc.ACTION_CONFIRM_REQUIRED
        assert r["side_effect_counters"] == ZERO_COUNTERS
        assert r["zero_side_effects"] is True
    assert sb.counters == ZERO_COUNTERS
    assert sc.counters == ZERO_COUNTERS
    assert not sc.incremental_ledger               # 零账本
    assert sc.action_session_handle == ""          # 连 open 都不做


def test_uc19_confirm_gate_zero_side_effects_http() -> None:
    client = TestClient(app)
    sid = client.get(f"{PREFIX}/state").json()["data"]["session_id"]
    for ep in ("/action-b", "/action-c"):
        resp = client.post(f"{PREFIX}{ep}", json={"session_id": sid, "confirmed": False})
        assert resp.status_code == 409, resp.json()
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == svc.ACTION_CONFIRM_REQUIRED
        details = body["error"]["details"]
        assert details["zero_side_effects"] is True
        assert details["side_effect_counters"] == ZERO_COUNTERS
    state = client.get(f"{PREFIX}/state?session_id={sid}").json()["data"]
    assert state["counters"] == ZERO_COUNTERS


def test_d11_gate_not_attached_to_legacy_generate_and_deliver_tia(monkeypatch, tmp_path) -> None:
    """任务 5：D11 只挂新增 /action-b /action-c；旧端点默认行为不变（不传 confirmed 仍 200）。"""
    client = TestClient(app)
    sid = _http_frozen(client, monkeypatch, tmp_path)
    gen = client.post(f"{PREFIX}/generate", json={"session_id": sid})   # 无 confirmed
    assert gen.status_code == 200, gen.json()
    assert gen.json()["data"]["delivery"]["ok"] is True
    dt = client.post(f"{PREFIX}/deliver-tia", json={"session_id": sid, "mode": "package"})
    assert dt.status_code == 200, dt.json()
    assert dt.json()["ok"] is True


# ---------------------------------------------------------------------------
# UC-12 / D10：反向保护阻止，禁止「先覆盖再提示」，tia_side_drift > 0 fail-closed
# ---------------------------------------------------------------------------
def test_uc12_d10_reverse_guard_blocks_before_any_write(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "uc12")
    port = _MockPort()
    snap = _snapshot(s)

    # 情形 A：TIA 侧多出一个手工块（无关块被改）→ drift > 0
    drifted = dict(snap)
    drifted["HAND_EDITED_BLOCK"] = "sha256:xxx"
    c = svc.run_action_c(s, confirmed=True, port=port, diff=_diff(), tia_side_snapshot=drifted)
    assert c["blocked"] is True
    assert c["code"] == svc.ACTION_C_REVERSE_GUARD_BLOCKED
    assert c["tia_side_drift"] >= 1
    assert c["reverse_protection"]["allowed"] is False
    assert c["zero_side_effects"] is True
    # 禁止先覆盖再提示：步骤 3 即被阻止，任何写入方法都未被调用
    assert "fast_writeback" not in _method_names(port)
    assert "compile_plc" not in _method_names(port)
    assert "save_project" not in _method_names(port)
    assert c["step_order"] == ["session_reuse", "spec_diff", "reverse_guard"]
    assert "禁止覆盖" in c["reason"] or "先覆盖再提示" in c["reason"]

    # 情形 B：已有块哈希被手工改动 → 同样 fail-closed
    changed = dict(snap)
    changed[next(iter(snap))] = "sha256:HAND_EDITED"
    c2 = svc.run_action_c(s, confirmed=True, port=_MockPort(), diff=_diff(), tia_side_snapshot=changed)
    assert c2["blocked"] is True and c2["code"] == svc.ACTION_C_REVERSE_GUARD_BLOCKED
    assert c2["tia_side_drift"] >= 1


def test_action_c_reverse_guard_unavailable_fail_closed(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "rg-unavail")
    c = svc.run_action_c(s, confirmed=True, port=_MockPort(), diff=_diff(), tia_side_snapshot=None)
    assert c["blocked"] is True
    assert c["code"] == svc.ACTION_C_REVERSE_GUARD_UNAVAILABLE
    assert c["reverse_protection"]["allowed"] is False
    assert c["zero_side_effects"] is True


# ---------------------------------------------------------------------------
# §13.5 八步顺序 + 不归档 / 不重载 / 不新建
# ---------------------------------------------------------------------------
def test_action_c_eight_steps_in_order(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "eight")
    port = _MockPort()
    c = svc.run_action_c(
        s, confirmed=True, port=port, diff=_diff(),
        tia_side_snapshot=_snapshot(s), static_gate_passed=True,
    )
    assert c["ok"] is True and len(c["steps"]) == 8
    assert c["step_order"] == list(svc.ACTION_C_STEPS)
    assert c["rolled_back"] is False
    assert c["compile_ok"] is True

    names = _method_names(port)
    assert names.index("fast_writeback") < names.index("compile_plc") < names.index("save_project")
    for forbidden in ("archive", "reload", "create_project", "close"):
        assert forbidden not in names
    assert c["archived"] is False and c["reloaded"] is False and c["project_recreated"] is False
    # 块级覆盖带 overwrite=true
    fwb = [x for x in port.calls if x[0] == "fast_writeback"][0]
    assert fwb[2] is True
    assert c["compile_diagnostics"]["l2_status"] == "pending_real_machine"  # 不宣称 L2 通过


# ---------------------------------------------------------------------------
# UC-13：失败导入回滚到调用前状态，且备份可恢复
# ---------------------------------------------------------------------------
def test_uc13_rollback_on_compile_failure(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "rollback-compile")
    before = dict(s.counters)
    port = _MockPort(compile_error_count=1)
    c = svc.run_action_c(
        s, confirmed=True, port=port, diff=_diff(),
        tia_side_snapshot=_snapshot(s), static_gate_passed=True,
    )
    assert c["blocked"] is True
    assert c["code"] == svc.ACTION_C_ROLLBACK
    assert c["rolled_back"] is True
    assert c["backup_restorable"] is True
    assert c["state_restored"] is True
    assert s.counters == before
    assert c["side_effect_counters"] == before
    assert c["backup"]["pre_state"]["counters"] == before
    assert c["backup"]["backup_sha256"]
    assert "save_project" not in _method_names(port)   # 编译失败不保存
    assert s.counters["writebacks"] == before["writebacks"]
    assert len(s.incremental_ledger) == 0              # 失败不写账本


def test_uc13_rollback_on_writeback_failure(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "rollback-fwb")
    before = dict(s.counters)
    port = _MockPort(fwb_ok=False)
    c = svc.run_action_c(
        s, confirmed=True, port=port, diff=_diff(),
        tia_side_snapshot=_snapshot(s), static_gate_passed=True,
    )
    assert c["rolled_back"] is True and c["state_restored"] is True
    assert s.counters == before
    names = _method_names(port)
    assert "fast_writeback" in names
    assert "compile_plc" not in names and "save_project" not in names


# ---------------------------------------------------------------------------
# 增量响应字段齐全（任务 8）+ OB 偏差显式留痕（禁止静默）
# ---------------------------------------------------------------------------
def test_action_c_incremental_response_fields_complete(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "fields")
    c = svc.run_action_c(
        s, confirmed=True, port=_MockPort(), diff=_diff(),
        tia_side_snapshot=_snapshot(s), static_gate_passed=True,
    )
    for field in (
        "mode", "base_spec_version", "changed_source_ids",
        "reverse_protection", "tia_side_drift", "ob_number_deviations",
    ):
        assert field in c, f"增量响应缺字段 {field}"
    assert c["mode"] == "incremental"
    assert c["base_spec_version"] == 1
    assert c["changed_source_ids"] == ["SID_X"]
    assert c["reverse_protection"]["status"] == "evaluated"
    assert c["reverse_protection"]["allowed"] is True
    assert c["tia_side_drift"] == 0
    assert isinstance(c["ob_number_deviations"], list)   # 即使为空也显式留痕，禁止静默
    assert "ob_number_deviations_note" in c
    fr = c["fidelity_report"]
    assert fr["mode"] == "incremental"
    assert fr["base_spec_version"] == 1
    assert c["pcec_ledger_entries"] == 1                 # 每次成功增量 1 条账本
    assert c["compile_diagnostics"]["l2_status"] == "pending_real_machine"
    assert c["xml_package_unverified"] is True


# ---------------------------------------------------------------------------
# D9：会话复用（不重复 /open）+ 会话归属冲突提示
# ---------------------------------------------------------------------------
def test_action_c_session_reuse_no_second_open(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "reuse")
    port = _MockPort()
    snap = _snapshot(s)
    c1 = svc.run_action_c(s, confirmed=True, port=port, diff=_diff(),
                          tia_side_snapshot=snap, static_gate_passed=True)
    c2 = svc.run_action_c(s, confirmed=True, port=port, diff=_diff(2, 3),
                          tia_side_snapshot=snap, static_gate_passed=True)
    assert c1["session_reused"] is False
    assert c2["session_reused"] is True
    assert port.open_count == 1
    assert len([x for x in port.calls if x[0] == "open_project"]) == 1
    assert c2["pcec_ledger_entries"] == 2               # 两次成功增量 = 2 条账本


def test_action_c_session_ownership_conflict_hint(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "ownership")
    c = svc.run_action_c(
        s, confirmed=True, port=_MockPort(), diff=_diff(),
        tia_side_snapshot=_snapshot(s), tia_owned_by_ui=True,
    )
    assert c["blocked"] is True
    assert c["code"] == svc.ACTION_C_SESSION_OWNERSHIP_CONFLICT
    assert "关闭用户 UI" in c["reason"] and "只读观察" in c["reason"]
    assert c["session_conflict_hint"] == "关闭用户 UI 或转只读观察"
    assert c["zero_side_effects"] is True


# ---------------------------------------------------------------------------
# Action B：首次写入编排、compile_ok 判定（warning 单列 / error 不保存）、tia_unavailable 非 200
# ---------------------------------------------------------------------------
def test_action_b_first_write_sequence_and_warning_single(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "b-seq")
    port = _MockPort(compile_warnings=["W1: unused", "W2: implicit cast"])
    b = svc.run_action_b(s, confirmed=True, port=port, static_gate_passed=True)
    assert b["ok"] is True and b["action"] == "B"
    assert b["step_order"] == ["open_project", "fast_writeback", "compile_plc", "save_project"]
    assert b["compile_ok"] is True                       # warning 不并入成功
    diag = b["compile_diagnostics"]
    assert diag["error_count"] == 0
    assert diag["warnings"] == ["W1: unused", "W2: implicit cast"]
    assert diag["static_gate_passed"] is True
    assert diag["l2_status"] == "pending_real_machine"  # 真机 L2 仍 pending
    assert s.action_b_done is True and s.action_b_compile_ok is True
    assert s.action_session_handle and s.action_c_open_count == 1  # 供 C 复用


def test_action_b_compile_error_does_not_save_and_rolls_back(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "b-err")
    port = _MockPort(compile_error_count=1)
    b = svc.run_action_b(s, confirmed=True, port=port, static_gate_passed=True)
    assert b["blocked"] is True
    assert b["code"] == svc.ACTION_B_COMPILE_FAILED
    assert b["compile_diagnostics"]["compile_ok"] is False
    assert "save_project" not in _method_names(port)
    assert s.counters["writebacks"] == 0                # 已回滚计数
    assert s.action_b_done is False


def test_action_b_tia_unavailable_explicit_non_200(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "b-unavail")
    b = svc.run_action_b(s, confirmed=True, port=_MockPort(tia_unavailable=True))
    assert b["blocked"] is True
    assert b["code"] == svc.GF_TIA_UNAVAILABLE
    assert b["http_status"] == 503                     # 显式非 200
    assert b["zero_side_effects"] is True


def test_action_b_offline_port_is_pending_not_claimed_compile_ok(monkeypatch, tmp_path) -> None:
    s = _with_action_a(monkeypatch, tmp_path, "b-offline")
    b = svc.run_action_b(s, confirmed=True)            # 无 port（未并线）
    assert b["ok"] is True
    assert b["tia_written"] is False
    assert b["compile_ok"] is False                     # 禁止宣称编译零错误
    assert b["compile_diagnostics"]["status"] == "pending_real_machine"
    assert b["compile_diagnostics"]["l2_status"] == "pending_real_machine"
    assert b["xml_package_unverified"] is True


# ---------------------------------------------------------------------------
# 旧端点仍可用（存量测试依赖，任务 1）
# ---------------------------------------------------------------------------
def test_legacy_endpoints_still_available(monkeypatch, tmp_path) -> None:
    client = TestClient(app)
    sid = _http_frozen(client, monkeypatch, tmp_path)
    gen = client.post(f"{PREFIX}/generate", json={"session_id": sid})
    assert gen.status_code == 200 and gen.json()["data"]["delivery"]["ok"] is True
    dl = client.get(f"{PREFIX}/download-package?session_id={sid}")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"
    dt = client.post(f"{PREFIX}/deliver-tia", json={"session_id": sid, "mode": "package"})
    assert dt.status_code == 200 and dt.json()["ok"] is True
    cd = client.post(f"{PREFIX}/confirm-diff",
                     json={"session_id": sid, "diff_id": "D1", "confirmed": False})
    assert cd.status_code == 200 and cd.json()["data"]["zero_side_effects"] is True
