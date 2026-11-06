"""Phase 2 最后一公里（§9 P2-4..P2-8）：/deliver-tia 的 XML 补充包、四层静态门禁、
PCEC 账本编排（调用顺序与参数）与 Openness 优雅降级。

全 mock 不起 TIA：Openness 探测 / 执行均在 ``tia_delivery`` 模块边界 monkeypatch，
真机验收走报告中的手动步骤（本轮不自动编译）。
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


# --------------------------------------------------------- Openness 优雅降级


def test_openness_unavailable_degrades(isolated_work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """worker/CLI 不可用 → HTTP 200 + status=tia_unavailable + 人工导入指引；
    事务保持 approved 并标注事件；ZIP 交付不受影响。"""
    session = _frozen_session("tia-degrade")
    monkeypatch.setattr(
        tia_delivery,
        "_openness_probe",
        lambda: {"available": False, "reason": "测试模拟：exe 未构建", "exe": ""},
    )
    client = TestClient(app)
    resp = client.post(f"{PREFIX}/deliver-tia", json={"session_id": "tia-degrade", "mode": "auto"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["status"] == "tia_unavailable"
    assert data["openness"]["status"] == "tia_unavailable"
    assert "人工导入" in data["guidance"]
    assert data["change_id"]

    stored = pcec.get_change(data["change_id"])
    assert stored is not None and stored["status"] == "approved"
    assert any(e.get("event") == "tia_unavailable" for e in stored["events"])
    # 事件消息存在（对话流）
    assert any(
        m.get("payload", {}).get("status") == "tia_unavailable" and m.get("kind") == "delivery"
        for m in session.messages
    )
    # 交付计数 + ZIP 已产出
    assert session.counters["generations"] >= 1
    assert data["package"]["zip_size_bytes"] > 0


def test_openness_mocked_success_applies_change(isolated_work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Openness 通道 mock 成功（编译零错误）→ 事务 applied、V2=pass、事件回流。"""
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
