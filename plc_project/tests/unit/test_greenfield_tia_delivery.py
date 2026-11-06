"""Phase 2 最后一公里（§9 P2-4..P2-8）：/deliver-tia 的 XML 补充包、四层静态门禁、
PCEC 账本编排（调用顺序与参数）、结构化编译诊断（P0-A / UC-02）与
TIA 不可用显式失败（UC-03）。

全 mock 不起 TIA：Openness 探测 / 执行均在 ``tia_delivery`` 模块边界 monkeypatch，
真机验收走报告中的手动步骤（本轮不自动编译，一律 ``pending_real_machine``）。
本文件所有 mock 仅验证判定口径与编排，**不构成 L2 证据**。
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc import greenfield_service as svc
from gateway.app.services.plc import tia_delivery
from gateway.app.services.plc.greenfield_session import registry
from plc_engine import pcec

PREFIX = "/api/v1/plc/canvas/greenfield"


@pytest.fixture()
def isolated_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PLC_WORK_DIR 隔离：spec 写盘、staged 包与 PCEC 账本全部落在 tmp_path。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    registry.reset()
    return tmp_path


def _frozen_session(session_id: str) -> object:
    """经 registry 建会话并走完 参考PDF→契约→草稿→校验→确认冻结 全链。"""
    session = registry.get(session_id)
    svc.load_reference_fixture(session, "")
    svc.revalidate(session)
    svc.engineering_summary(session)
    svc.confirm_and_freeze(session, explicit=True)
    return session


# ----------------------------------------------------------------- 门禁 409


def test_deliver_tia_rejected_before_freeze(isolated_work: Path) -> None:
    """FROZEN 前调用 /deliver-tia → 409 GF_GATE_LOCKED（沿用 "generate" 门禁矩阵）。"""
    client = TestClient(app)
    sid = client.get(f"{PREFIX}/state").json()["data"]["session_id"]
    resp = client.post(f"{PREFIX}/deliver-tia", json={"session_id": sid, "mode": "auto"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "GF_GATE_LOCKED"


# ------------------------------------------------------- PCEC 编排（顺序/参数）


def test_pcec_sequence_order_and_params(isolated_work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """new_change→transition(analyzed/validated/approved)→put_change→baseline_matches
    顺序与参数（kind=greenfield_generate、touched=块清单、baseline=project_baseline）。"""
    session = _frozen_session("tia-pcec")
    svc.generate_project_package(session)  # 预生成，deliver 复用 last_delivery

    calls: list[tuple[str, str]] = []
    real = {
        "new_change": pcec.new_change,
        "transition": pcec.transition,
        "put_change": pcec.put_change,
        "baseline_matches": pcec.baseline_matches,
        "project_baseline": pcec.project_baseline,
    }

    def rec_new_change(intent_kind, request, ops, touched_blocks, baseline, **kw):
        calls.append(("new_change", str(intent_kind)))
        captured.update(kind=str(intent_kind), request=str(request), touched=list(touched_blocks), baseline=dict(baseline))
        return real["new_change"](intent_kind, request, ops, touched_blocks, baseline, **kw)

    def rec_transition(change, to_status, **kw):
        calls.append(("transition", str(to_status)))
        return real["transition"](change, to_status, **kw)

    def rec_put_change(change, **kw):
        calls.append(("put_change", str(change.get("status"))))
        return real["put_change"](change, **kw)

    def rec_baseline_matches(change, project_path):
        calls.append(("baseline_matches", str(change.get("change_id"))))
        return real["baseline_matches"](change, project_path)

    def rec_project_baseline(project_path):
        calls.append(("project_baseline", str(project_path)))
        return real["project_baseline"](project_path)

    captured: dict[str, object] = {}
    for name, patched in (
        ("new_change", rec_new_change),
        ("transition", rec_transition),
        ("put_change", rec_put_change),
        ("baseline_matches", rec_baseline_matches),
        ("project_baseline", rec_project_baseline),
    ):
        monkeypatch.setattr(tia_delivery.pcec, name, patched)

    result = tia_delivery.deliver_tia(session, mode="package")

    seq = [f"{name}:{detail}" if name != "baseline_matches" else name for name, detail in calls]
    flat = [name for name, _ in calls]
    # 顺序：project_baseline → new_change → analyzed → validated → approved → put → baseline_matches
    assert flat.index("project_baseline") < flat.index("new_change")
    assert seq.count("transition:analyzed") == 1
    assert seq.count("transition:validated") == 1
    assert seq.count("transition:approved") == 1
    assert flat.index("new_change") < seq.index("transition:analyzed") < seq.index("transition:validated") < seq.index("transition:approved")
    assert seq.index("transition:approved") < seq.index("put_change:approved")
    assert seq.index("put_change:approved") < flat.index("baseline_matches")
    # baseline_matches 之后（package 模式收尾）还有一次 put_change:approved
    assert calls[-1] == ("put_change", "approved")

    # 参数：kind / touched_blocks / baseline
    assert captured["kind"] == "greenfield_generate"
    expected_blocks = [e["name"] for e in session.last_delivery["blocks_manifest"]]
    assert captured["touched"] == expected_blocks
    baseline = captured["baseline"]
    assert str(baseline["project_hash"]).startswith("sha256:")

    # 账本落盘 + 响应
    change_id = result["change_id"]
    stored = pcec.get_change(change_id)
    assert stored is not None and stored["status"] == "approved"
    assert stored["intent"]["kind"] == "greenfield_generate"
    assert result["status"] == "package_only"
    assert result["ok"] is True


def test_baseline_mismatch_fail_closed(isolated_work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """baseline_matches 失败 → 事务 expired + HTTP 409，IR / 阶段 / 事件可观测不变量。"""
    session = _frozen_session("tia-expired")
    svc.generate_project_package(session)
    ir_before = session.ir.ir_sha256()
    stage_before = session.stage

    monkeypatch.setattr(tia_delivery.pcec, "baseline_matches", lambda change, path: False)
    client = TestClient(app)
    resp = client.post(f"{PREFIX}/deliver-tia", json={"session_id": "tia-expired", "mode": "package"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "GF_PCEC_BASELINE_EXPIRED"

    change_id = body["error"]["details"]["change_id"]
    stored = pcec.get_change(change_id)
    assert stored is not None and stored["status"] == "expired"
    assert stored["verification"]["v1_static"] == "fail"

    # fail-closed：IR 与阶段不变，未计一次成功的交付
    assert session.ir.ir_sha256() == ir_before
    assert session.stage is stage_before
    assert session.counters["generations"] == 1  # 仅预生成的那一次
    # 事件消息回流对话流
    assert any(
        m.get("payload", {}).get("status") == "expired" and m.get("role") == "event"
        for m in session.messages
    )


# --------------------------------------- 结构化编译诊断（P0-A / UC-02）


def test_uc02_warning_separated_from_compile_ok() -> None:
    """UC-02：Given 一次含 warning 的编译，Then ``error_count == 0`` 与 warning
    清单分离，``compile_ok`` 不被 warning 污染（warning 单列、禁止并入成功）。"""
    diag = tia_delivery.build_compile_diagnostics(
        {
            "ok": True,
            "compile": {
                "state": "SuccessWithWarnings",
                "errorCount": 0,
                "warnings": ["W1: unused temp var", "W2: implicit cast"],
                "elapsedMs": 321.5,
            },
        },
        static_gate_passed=True,
        tia_version="V19",
        project_path="C:/mock/Greenfield.ap19",
        blocks=["U1_KukaVisionStation_Main", "U1_KukaVisionStation_Startup"],
    )
    assert diag.error_count == 0
    assert diag.warnings == ["W1: unused temp var", "W2: implicit cast"]
    assert diag.compile_ok is True  # warning 单列，未并入成功
    assert diag.status == tia_delivery.COMPILE_STATUS_COMPILED
    assert diag.static_gate_passed is True
    assert diag.tia_unavailable is False
    assert diag.pending_real_machine is False
    # 可复现报告字段（EvidenceBundle）
    assert diag.blocks == ["U1_KukaVisionStation_Main", "U1_KukaVisionStation_Startup"]
    assert diag.elapsed_ms == 321.5
    assert diag.tia_version == "V19"
    assert diag.project_path == "C:/mock/Greenfield.ap19"
    report = diag.to_dict()
    assert report["error_count"] == 0
    assert report["warnings"] == ["W1: unused temp var", "W2: implicit cast"]


def test_uc02_old_warning_state_no_longer_pollutes_success() -> None:
    """回归旧口径：``state`` 含 ``warning`` 但 ``error_count > 0`` 时绝不能判成功。"""
    diag = tia_delivery.build_compile_diagnostics(
        {
            "ok": True,
            "compile": {"state": "SuccessWithWarnings", "errorCount": 1, "warnings": ["W1"]},
        },
        static_gate_passed=True,
        tia_version="V19",
        project_path="C:/mock/Greenfield.ap19",
    )
    assert diag.error_count == 1
    assert diag.warnings == ["W1"]
    assert diag.compile_ok is False


def test_static_gate_interception_blocks_compile_ok() -> None:
    """负例：四层静态门禁任一拦截时，即使 ``error_count == 0`` 也 ``compile_ok == False``。"""
    diag = tia_delivery.evaluate_compile(
        error_count=0,
        static_gate_passed=False,
        warnings=["W1"],
        blocks=["U1_Main"],
        tia_version="V19",
        project_path="C:/mock/Greenfield.ap19",
    )
    assert diag.error_count == 0
    assert diag.static_gate_passed is False
    assert diag.compile_ok is False


def test_tia_unavailable_vs_pending_real_machine_are_distinct() -> None:
    """``tia_unavailable``（探测失败）与 ``pending_real_machine``（真机未跑）显式区分。"""
    unavailable = tia_delivery.unavailable_diagnostics(
        reason="exe 未构建", static_gate_passed=True, tia_version="V19", project_path="p"
    )
    pending = tia_delivery.pending_real_machine_diagnostics(
        static_gate_passed=True, tia_version="V19", project_path="p"
    )
    for diag in (unavailable, pending):
        assert diag.compile_ok is False
        assert diag.error_count == 0
    assert unavailable.status == tia_delivery.COMPILE_STATUS_TIA_UNAVAILABLE
    assert unavailable.tia_unavailable is True
    assert unavailable.pending_real_machine is False
    assert pending.status == tia_delivery.COMPILE_STATUS_PENDING_REAL_MACHINE
    assert pending.pending_real_machine is True
    assert pending.tia_unavailable is False


# ----------------------------------- TIA 不可用显式失败（UC-03 / P0-A）


def test_uc03_tia_unavailable_is_explicit_non_200(
    isolated_work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UC-03：Given TIA 不可用，Then 返回显式非成功状态且**非 HTTP 200**
    （``ok=false`` + 明确 error code），禁止静默降级为 200 成功。"""
    session = _frozen_session("tia-unavailable")
    monkeypatch.setattr(
        tia_delivery,
        "_openness_probe",
        lambda: {"available": False, "reason": "测试模拟：exe 未构建", "exe": ""},
    )
    client = TestClient(app)
    resp = client.post(f"{PREFIX}/deliver-tia", json={"session_id": "tia-unavailable", "mode": "auto"})
    assert resp.status_code != 200
    assert resp.status_code >= 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == tia_delivery.TIA_UNAVAILABLE_ERROR_CODE

    details = body["error"]["details"]
    assert details["tia_unavailable"] is True
    assert details["pending_real_machine"] is False
    assert "人工导入" in details["guidance"]
    diag = details["compile_diagnostics"]
    assert diag["compile_ok"] is False
    assert diag["error_count"] == 0
    assert diag["status"] == tia_delivery.COMPILE_STATUS_TIA_UNAVAILABLE

    # 账本留痕：tia_unavailable 事件 + 事务未被误标 applied
    stored = pcec.get_change(details["change_id"])
    assert stored is not None and stored["status"] == "approved"
    assert any(e.get("event") == "tia_unavailable" for e in stored["events"])
    # 对话流事件存在
    assert any(
        m.get("payload", {}).get("status") == "tia_unavailable" and m.get("kind") == "delivery"
        for m in session.messages
    )


def test_tia_unavailable_raises_explicit_error_at_service_layer(
    isolated_work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """service 层同样是显式失败（抛 ``GateLockedError``），不返回静默成功的 dict。"""
    session = _frozen_session("tia-unavailable-svc")
    monkeypatch.setattr(
        tia_delivery,
        "_openness_probe",
        lambda: {"available": False, "reason": "mock", "exe": ""},
    )
    with pytest.raises(tia_delivery.GateLockedError) as excinfo:
        tia_delivery.deliver_tia(session, mode="auto")
    assert excinfo.value.code == tia_delivery.TIA_UNAVAILABLE_ERROR_CODE
    assert excinfo.value.details["compile_diagnostics"]["compile_ok"] is False


def test_package_mode_reports_pending_real_machine(isolated_work: Path) -> None:
    """package 模式（离线可推进部分）：真机未跑，``pending_real_machine=True``，
    结构化报告字段齐全；``xml_package_unverified`` 保持 True（本批次无真机导入验证）。"""
    session = _frozen_session("tia-package-pending")
    result = tia_delivery.deliver_tia(session, mode="package")
    assert result["status"] == "package_only"
    diag = result["compile_diagnostics"]
    assert diag["status"] == tia_delivery.COMPILE_STATUS_PENDING_REAL_MACHINE
    assert diag["pending_real_machine"] is True
    assert diag["tia_unavailable"] is False
    assert diag["compile_ok"] is False
    assert result["pending_real_machine"] is True
    assert result["l2_status"] == "pending_real_machine"
    assert result["xml_package_unverified"] is True
    for key in (
        "error_count",
        "warnings",
        "blocks",
        "elapsed_ms",
        "tia_version",
        "project_path",
        "static_gate_passed",
        "compile_ok",
    ):
        assert key in diag
    assert diag["blocks"]


def test_openness_mocked_success_applies_change(isolated_work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Openness 通道 mock 成功（``error_count == 0``）→ 事务 applied、V2=pass、事件回流。

    注意：mock 仅验证编排与结构化判定口径，**不构成 L2 证据**；本批次真机
    结论一律 ``pending_real_machine``，禁止以离线单测宣称「编译零错误」。
    """
    session = _frozen_session("tia-auto")
    monkeypatch.setattr(
        tia_delivery,
        "_openness_probe",
        lambda: {"available": True, "reason": "", "exe": "mock.exe", "status": {"ok": True}},
    )
    monkeypatch.setattr(
        tia_delivery,
        "_run_openness_import_compile",
        lambda **kw: {
            "status": "compile_ok",
            "steps": [{"step": "create-project", "ok": True, "detail": "mock"}],
            "compile": {"ok": True, "compile": {"state": "Success", "errorCount": 0}},
            "project_path": "C:/mock/Greenfield.ap19",
        },
    )
    client = TestClient(app)
    resp = client.post(f"{PREFIX}/deliver-tia", json={"session_id": "tia-auto", "mode": "auto"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "delivered_applied"
    assert data["openness"]["project_path"] == "C:/mock/Greenfield.ap19"

    stored = pcec.get_change(data["change_id"])
    assert stored["status"] == "applied"
    assert stored["verification"]["v2_tia_compile"] == "pass"
    assert any(
        m.get("payload", {}).get("status") == "compile_ok" for m in session.messages
    )
    # P0-A 结构化诊断随回执归档；离线批次仍标 pending_real_machine（不宣称 L2 通过）
    diag = data["compile_diagnostics"]
    assert diag["compile_ok"] is True
    assert diag["error_count"] == 0
    assert diag["static_gate_passed"] is True
    assert diag["status"] == tia_delivery.COMPILE_STATUS_COMPILED
    assert data["l2_status"] == "pending_real_machine"
    assert data["l2_note"]


# ------------------------------------------------------------ XML 补充包内容


def test_xml_supplement_package_contents(isolated_work: Path) -> None:
    """ZIP 含 OB SimaticML XML（OB 号来自 IR ob_numbers、调用 Unit FB 实例 DB）、
    folders.json 文件夹清单与 manifest 的 xml_package_unverified 诚实标注。"""
    session = _frozen_session("tia-xml")
    result = tia_delivery.deliver_tia(session, mode="package")

    zf = zipfile.ZipFile(io.BytesIO(result["zip_bytes"]))
    names = set(zf.namelist())
    # SCL 工程包原样保留
    assert "manifest.json" in names
    assert any(n.startswith("blocks/") for n in names)
    assert "plc_tags/PLCTags_Frozen.xml" in names
    # XML 补充包
    assert "xml_supplement/ob/U1_KukaVisionStation_Main.xml" in names
    assert "xml_supplement/ob/U1_KukaVisionStation_Startup.xml" in names
    assert "xml_supplement/folders.json" in names
    assert "xml_supplement/manifest.json" in names
    assert "tia_delivery.json" in names

    # OB 号从 IR ob_numbers 取（Unit U1 main=1001 / startup=1000）
    main_xml = zf.read("xml_supplement/ob/U1_KukaVisionStation_Main.xml").decode("utf-8-sig")
    assert "<Number>1001</Number>" in main_xml
    assert "<SecondaryType>ProgramCycle</SecondaryType>" in main_xml
    assert '<CallInfo Name="U1_KukaVisionStation_CallUnit" BlockType="FB">' in main_xml
    assert '<Component Name="U1_KukaVisionStation_CallUnit_DB" />' in main_xml
    startup_xml = zf.read("xml_supplement/ob/U1_KukaVisionStation_Startup.xml").decode("utf-8-sig")
    assert "<Number>1000</Number>" in startup_xml
    assert "<SecondaryType>Startup</SecondaryType>" in startup_xml

    # ProDiag（SecondaryType 未真机确证）被跳过并记录原因
    supplement_manifest = json.loads(zf.read("xml_supplement/manifest.json").decode("utf-8"))
    assert supplement_manifest["xml_package_unverified"] is True
    assert supplement_manifest["ob_count"] >= 2
    assert any("ProDiag" in str(s.get("reason")) for s in supplement_manifest["skipped_obs"])
    skipped_names = {s["name"] for s in supplement_manifest["skipped_obs"]}
    assert not any(f"xml_supplement/ob/{n}.xml" in names for n in skipped_names)

    # folders.json：文档化文件夹清单
    folders = json.loads(zf.read("xml_supplement/folders.json").decode("utf-8"))
    assert set(folders["folders"]).issuperset({"90_Compat_Frozen_Boundary"})
    assert "文件夹" in folders["note"]

    # IR ob_numbers 交叉核对：生成的 OB 号 ⊆ 合法域（IR ob_numbers ∪ AF V1.2 公式）
    ir = session.specs[-1].ir_snapshot
    from plc_engine.af.greenfield_ir import GreenfieldIR

    legal = set(tia_delivery.expected_ob_numbers(GreenfieldIR.from_dict(ir)).values())
    assert legal
    for ob in supplement_manifest["generated_obs"]:
        assert ob["number"] in legal


def test_static_gates_report_and_fail_closed(isolated_work: Path) -> None:
    """四层静态门禁按序出现在报告里；参考实例全绿（af_linter→scl_precheck→
    writeback_linter→mega_source）。"""
    session = _frozen_session("tia-gates")
    svc.generate_project_package(session)
    gates = tia_delivery.run_static_gates(session.last_delivery)
    assert gates["ok"] is True
    assert [s["name"] for s in gates["stages"]] == [
        "af_linter.lint_af_canvas",
        "scl_precheck.precheck_canvas",
        "writeback_linter.lint_bundle",
        "mega_source.bundle (via writeback_pipeline.build_plan)",
    ]
    assert gates["artifact_count"] > 0
    # OB 不进外部源批次（BR-3），artifact 数 = 块总数 - OB 数
    total = len(session.last_delivery["blocks_manifest"])
    ob_count = sum(
        1 for e in session.last_delivery["blocks_manifest"] if e["block_type"] == "OB"
    )
    assert gates["artifact_count"] == total - ob_count
