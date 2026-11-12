"""QA 独立验收 · T01–T04 自建边界用例（严过关 / 第 2 层独立验证）。

纪律：
  * 本文件只放在 ``tests/qa_v2/``，**不修改任何源码**，不启动 TIA Portal；
  * 所有链均为注入式 fake worker / offline，绝不写 V19 real 台账；
  * ``TestSourceDefectsFoundByQA`` 中的用例按 PRD / 设计条款写**期望行为**，
    当前实现不满足时会真实 FAILED，作为「源码 Bug → Engineer」的证据，
    不使用 xfail 掩盖。

依据：PRD 6.2 / 6.4 / 7.6 / 7.9，设计 §4.3 / §6.4 / §9.3 / §9.9，
蓝图 §07 A1–A7 / §12 G0–G7，任务包 TASK-00B/01A/01B/03A/03B。
"""
from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.approval_v2 import ApprovalGate
from gateway.app.services.plc.artifact_store_v2 import (
    ArtifactJobMismatchError,
    ArtifactStore,
)
from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.engineering_service_v2 import EngineeringServiceV2
from gateway.app.services.plc.tia_delivery_v2 import (
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    execute_chain,
)
from gateway.app.services.plc.workspace_v2 import WorkspaceStore, get_store
from plc_engine.canonical import compute_file_sha256
from plc_engine.components.driver_spec import FieldSource
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import CompileReceipt, NativeTiaArtifact
from plc_engine.engineering_ir.patch import (
    PatchConflictError,
    SemanticValidationError,
    apply_patch_atomic,
    make_patch,
)
from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.guard_ast import GuardAST, GuardValidationError
from plc_engine.process.scl_lowering import CompilerService, assert_deterministic
from tests.v2_fixtures import (
    build_store,
    build_valid_demo_ir,
    make_fake_openness_worker,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _active_step(frame: Any) -> str:
    """TraceFrame 可能是 dataclass 或 dict，统一取 active_step。"""
    return str(frame["active_step"] if isinstance(frame, dict) else frame.active_step)


def _s2_frame_count(trace: list[Any]) -> int:
    return sum(1 for frame in trace if _active_step(frame) == "S2")


def _prepared_job(tmp_path, *, real_machine: bool = False):
    """构造：有效工程 → 冻结 ChangeSet → 人工批准 → 202 QUEUED job。"""
    store = build_store(tmp_path)
    changeset = EngineeringServiceV2.freeze_changeset(store, "prj_demo", base_revision=0)
    baseline = store.get_project("prj_demo").baseline_hash
    ApprovalGate(store).approve(
        changeset.id, reviewer="qa_human", explicit=True, expected_baseline_hash=baseline
    )
    data, status = DeliveryCoordinator(store).start(
        {
            "project_id": "prj_demo",
            "approved_changeset_id": changeset.id,
            "expected_baseline_hash": baseline,
            "idempotency_key": "qa_idem_1",
        }
    )
    assert status == 202
    return store, data["job_id"], real_machine


def _request(tmp_path, job_id: str, **kwargs: Any) -> DeliveryChainRequest:
    return DeliveryChainRequest(
        project_id="prj_demo",
        job_id=job_id,
        project_name="Demo",
        workspace_dir=str(tmp_path / "ws"),
        cpu_type_identifier="6ES7511-1AK02-0AB0/V2.9",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# A. G1 · Patch 原子性 / base_revision 边界 / 并发交错
# --------------------------------------------------------------------------- #
class TestPatchAtomicityAndRevisionBoundaries:
    def test_two_conflicting_ops_roll_back_every_change(self) -> None:
        """两个互相冲突的 op（min 2000 后 max 1500）必须整体 422，且第一个 op 不留痕。"""
        ir = build_valid_demo_ir()
        before = ir.to_dict()
        original_hash = ir.ir_sha256

        patch = make_patch(
            ir.project_id,
            ir.revision,
            [
                {"op": "set_step_parameter", "step_id": "S2", "field": "min_duration_ms", "value": 2000},
                {"op": "set_step_parameter", "step_id": "S2", "field": "max_duration_ms", "value": 1500},
            ],
        )
        with pytest.raises(SemanticValidationError) as exc:
            apply_patch_atomic(ir, patch)

        assert exc.value.code == "SEMANTIC_VALIDATION_FAILED"
        assert exc.value.unchanged_ir_hash == original_hash
        assert ir.to_dict() == before
        assert ir.revision == 0
        assert ir.process.step_index()["S2"].min_duration_ms == 1000
        assert len(exc.value.issues) >= 1

    def test_valid_op_followed_by_unknown_op_rolls_back(self) -> None:
        ir = build_valid_demo_ir()
        before = ir.to_dict()
        patch = make_patch(
            ir.project_id,
            ir.revision,
            [
                {"op": "set_component_name", "component_id": "CM1", "name": "已改名"},
                {"op": "eval_free_scl"},
            ],
        )
        with pytest.raises(SemanticValidationError):
            apply_patch_atomic(ir, patch)
        assert ir.to_dict() == before
        assert ir.components[0].name != "已改名"

    def test_valid_ops_then_final_graph_validation_failure_rolls_back(self) -> None:
        """_apply_op 全部成功但终点静态校验失败时，也必须整体回滚。"""
        ir = build_valid_demo_ir()
        before = ir.to_dict()
        patch = make_patch(
            ir.project_id,
            ir.revision,
            [
                {"op": "set_view_layout", "layout": {"x": 42}},
                {
                    "op": "add_transition",
                    "id": "TR_QA_BAD",
                    "from_step": "S0",
                    "to_step": "S4",
                    "guard": {"node_type": "CONST", "value_type": "BOOL", "value": "not_a_bool"},
                },
            ],
        )
        with pytest.raises(SemanticValidationError) as exc:
            apply_patch_atomic(ir, patch)
        assert any("CONST BOOL" in issue["reason"] for issue in exc.value.issues)
        assert ir.to_dict() == before

    @pytest.mark.parametrize("stale", [1])
    def test_base_revision_boundaries_return_409_without_mutation(self, stale: Any) -> None:
        """合法但漂移的 revision 必须 409，且 IR 不变。

        P-10 裁定后，非法值（负数 / 超大整数 / bool / 浮点）不再走 409，
        而是由 make_patch 抛结构化 422；见下一个测试。
        """
        ir = build_valid_demo_ir()
        before = ir.to_dict()
        with pytest.raises(PatchConflictError) as exc:
            apply_patch_atomic(
                ir, make_patch(ir.project_id, stale, [{"op": "set_view_layout", "layout": {}}])
            )
        assert exc.value.current_revision == ir.revision
        assert exc.value.to_dict()["code"] == "BASE_REVISION_CONFLICT"
        assert ir.to_dict() == before

    @pytest.mark.parametrize("illegal", [-1, 2**63, 10**40, True, 1.5, "abc", None])
    def test_illegal_base_revision_returns_structured_422_without_mutation(self, illegal: Any) -> None:
        """P-10：type(x) is int and 0 <= x <= MAX；非法值统一结构化 422，IR 不变。"""
        ir = build_valid_demo_ir()
        before = ir.to_dict()
        with pytest.raises(SemanticValidationError) as exc:
            apply_patch_atomic(
                ir, make_patch(ir.project_id, illegal, [{"op": "set_view_layout", "layout": {}}])
            )
        assert exc.value.to_dict()["code"] == "SEMANTIC_VALIDATION_FAILED"
        assert exc.value.issues[0]["field"] == "base_revision"
        assert ir.to_dict() == before

    def test_base_revision_zero_is_valid_for_initial_revision(self) -> None:
        ir = build_valid_demo_ir()
        assert ir.revision == 0
        new_ir, result = apply_patch_atomic(
            ir, make_patch(ir.project_id, 0, [{"op": "set_view_layout", "layout": {}}])
        )
        assert result.revision == 1
        assert new_ir.ir_sha256 == new_ir.semantic_hash()

    def test_concurrent_interleaved_patches_have_exactly_one_winner(self, tmp_path) -> None:
        """6 个线程用同一 stale base_revision 并发提交：只能 1 成功，5 个 409，无丢失更新。"""
        store = build_store(tmp_path)

        def submit(index: int) -> tuple[str, Any]:
            try:
                result = store.commit_patch(
                    "prj_demo",
                    make_patch(
                        "prj_demo",
                        0,
                        [{"op": "set_view_layout", "layout": {"x": index}}],
                        request_id=f"qa_concurrent_{index}",
                    ),
                )
                return ("OK", result.revision)
            except Exception as exc:  # 记录具体异常类型，便于定位并发缺陷
                return (type(exc).__name__, str(exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(submit, range(6)))

        winners = [r for r in results if r[0] == "OK"]
        conflicts = [r for r in results if r[0] == "PatchConflictError"]
        assert len(winners) == 1, results
        assert len(conflicts) == 5, results
        assert store.get_project("prj_demo").current_revision == 1
        assert len(store.list_revisions("prj_demo")) == 2  # rev 0 + rev 1，无重复写入


# --------------------------------------------------------------------------- #
# B. G3 · GuardAST 注入 / fail-closed
# --------------------------------------------------------------------------- #
class TestGuardAstInjection:
    def test_free_text_key_nested_in_children_is_rejected(self) -> None:
        payload = {
            "node_type": "AND",
            "value_type": "BOOL",
            "children": [
                {"node_type": "SIGNAL", "value_type": "BOOL", "signal": "CmdStart"},
                {"node_type": "CONST", "value_type": "BOOL", "value": True, "expression": "1=1"},
            ],
        }
        with pytest.raises(GuardValidationError):
            GuardAST.from_dict(payload)

    @pytest.mark.parametrize("key", ["expression", "ExPrEsSiOn", "EVAL", "formula"])
    def test_free_text_keys_are_case_insensitively_rejected(self, key: str) -> None:
        with pytest.raises(GuardValidationError):
            GuardAST.from_dict({"node_type": "CONST", "value_type": "BOOL", "value": True, key: "x"})

    def test_guard_string_is_never_executed_as_code(self) -> None:
        """即使 signal 长得像 Python 代码，未知信号也必须 fail-closed 且不执行。"""
        guard = GuardAST.from_dict(
            {"node_type": "SIGNAL", "value_type": "BOOL", "signal": "__import__('os').system('calc')"}
        )
        result, issues = guard.evaluate_detailed({})
        assert result is False
        assert issues and "fail-closed" in issues[0]

    def test_unknown_signal_and_type_mismatch_are_fail_closed(self) -> None:
        guard = GuardAST.from_dict({"node_type": "SIGNAL", "value_type": "BOOL", "signal": "CmdStart"})
        assert guard.evaluate({"CmdStart": "true"}) is False  # 类型不匹配
        assert guard.evaluate({}) is False  # 未知信号
        assert guard.evaluate({"CmdStart": True}) is True


# --------------------------------------------------------------------------- #
# C. G2 / G4 · IO 未绑定 / 确定性 / 三方同步
# --------------------------------------------------------------------------- #
class TestIoBindingAndDeterminism:
    def test_unbound_io_generates_no_fictional_address_or_block_number(self) -> None:
        ir = build_valid_demo_ir()
        bundle = ir.derive_all()
        generated = "\n".join(bundle.scl_files.values()) + json.dumps(
            bundle.manifest.to_dict(include_content=True), ensure_ascii=False
        )
        assert not re.search(r"%[IQ]\d", generated)
        assert all(component.io_bindings is None for component in ir.components)
        assert all(item.block_number is None for item in bundle.manifest.files)
        assert not bundle.manifest.validate_import_order()

    def test_imported_address_stays_fail_closed_at_ir_validation(self) -> None:
        """一致性观察：patch.py:203 允许 source=imported 绑定 %Q，
        ValidationEngine:68 却无条件拒绝；至少最终 IR 校验保持 fail-closed。"""
        ir = build_valid_demo_ir()
        component = ir.components[0]
        component.source = FieldSource.IMPORTED
        component.io_bindings = {"CmdExtend": "%Q0.0"}
        report = ValidationEngine().validate(ir)
        assert not report.passed
        assert any("physical address" in issue["reason"] for issue in report.issues)

    def test_s2_1000_to_2000_syncs_ir_scl_trace_and_manifest(self) -> None:
        """US-3 定量验证：S2 活跃帧数、SCL 常量、manifest hash 三方同步变化。"""
        ir = build_valid_demo_ir()
        before = ir.derive_all()
        assert "T#1000ms" in before.scl_files["scl/FB_Sequence.scl"]
        s2_before = _s2_frame_count(before.trace)

        new_ir, result = apply_patch_atomic(
            ir,
            make_patch(
                ir.project_id,
                ir.revision,
                [{"op": "set_step_parameter", "step_id": "S2", "field": "min_duration_ms", "value": 2000}],
            ),
        )
        after = new_ir.derive_all()

        assert result.revision == 1
        assert "S2" in result.changed_ir_ids
        assert new_ir.process.step_index()["S2"].min_duration_ms == 2000
        assert "T#2000ms" in after.scl_files["scl/FB_Sequence.scl"]
        assert "T#1000ms" not in after.scl_files["scl/FB_Sequence.scl"]
        assert _s2_frame_count(after.trace) > s2_before
        assert after.manifest.sha256 != before.manifest.sha256
        assert new_ir.ir_sha256 != ir.ir_sha256
        assert assert_deterministic(new_ir)["deterministic"] is True

    def test_ui_layout_only_patch_does_not_regenerate_any_derived_artifact(self) -> None:
        ir = build_valid_demo_ir()
        before = ir.derive_all()
        new_ir, result = apply_patch_atomic(
            ir,
            make_patch(
                ir.project_id,
                ir.revision,
                [{"op": "set_view_layout", "layout": {"S2": {"x": 999, "y": -3}}}],
            ),
        )
        after = new_ir.derive_all()
        assert result.changed_ir_ids == []
        assert new_ir.semantic_hash() == ir.semantic_hash()
        assert after.manifest.sha256 == before.manifest.sha256
        assert after.scl_files == before.scl_files


# --------------------------------------------------------------------------- #
# D. G5/G7 · 归档绑定 / 状态机 / 证据等级
# --------------------------------------------------------------------------- #
class TestArtifactBindingAndStateMachine:
    def _registered_store(self, tmp_path, *, tamper: bool = False):
        real = tmp_path / "job_current.zap19"
        real.write_bytes(b"CURRENT JOB NATIVE ARCHIVE")
        (tmp_path / "job_old.zap19").write_bytes(b"OLD JOB ARCHIVE - MUST NOT BE SERVED")
        store = WorkspaceStore(db_path=str(tmp_path / "qa.db"), ir_store_dir=str(tmp_path / "qa_ir"))
        astore = ArtifactStore(store, root=tmp_path / "astore")
        artifact = NativeTiaArtifact(
            artifact_id="a_qa_1",
            job_id="job_1",
            project_id="prj_a",
            archive_path=str(real),
            archive_sha256=compute_file_sha256(real),
            size_bytes=real.stat().st_size,
            kind="zap19",
            reopen_ok=True,
        )
        stored = astore.store_file(real, kind="zap19")
        astore.register(artifact.to_dict(), stored=stored)
        if tamper:
            astore._resolve(str(stored["path"])).write_bytes(b"TAMPERED ARCHIVE")
        return astore, artifact

    def test_tampered_stored_file_rejected_with_and_without_sha256(self, tmp_path) -> None:
        astore, artifact = self._registered_store(tmp_path, tamper=True)
        for supplied in ("", artifact.archive_sha256):
            with pytest.raises(ArtifactJobMismatchError) as exc:
                astore.download("a_qa_1", project_id="prj_a", job_id="job_1", sha256=supplied)
            assert "SHA256_MISMATCH" in str(exc.value)

    def test_cross_job_cross_project_and_forged_sha_are_rejected(self, tmp_path) -> None:
        astore, artifact = self._registered_store(tmp_path)
        with pytest.raises(ArtifactJobMismatchError):
            astore.download("a_qa_1", project_id="prj_a", job_id="job_OTHER", sha256=artifact.archive_sha256)
        with pytest.raises(ArtifactJobMismatchError):
            astore.download("a_qa_1", project_id="prj_OTHER", job_id="job_1", sha256=artifact.archive_sha256)
        with pytest.raises(ArtifactJobMismatchError):
            astore.download("a_qa_1", project_id="prj_a", job_id="job_1", sha256="sha256:" + "f" * 64)
        data, meta = astore.download("a_qa_1", project_id="prj_a", job_id="job_1")
        assert data == b"CURRENT JOB NATIVE ARCHIVE"
        assert b"OLD JOB" not in data
        assert meta["job_id"] == "job_1"

    def test_compile_error_count_positive_forces_failed_state(self, tmp_path) -> None:
        """即使 adapter 自报 real_machine=True，编译 error_count>0 也必须回退 FAILED。"""
        store, job_id, _ = _prepared_job(tmp_path)
        worker, _ = make_fake_openness_worker(tmp_path, error_count=3, warning_count=7)
        result = DeliveryCoordinator(store).run_chain(
            job_id,
            adapter=TiaOpennessCliAdapter(worker=worker, real_machine=True),
            request=_request(tmp_path, job_id),
        )
        assert result["state"] == "FAILED"
        assert result["error_code"] == "COMPILE_FAILED"
        job = DeliveryCoordinator(store).get_job(job_id)
        assert job["state"] == "FAILED"
        assert job["native_artifact"] is None
        assert job["evidence_level"] != EvidenceLevel.V19_REAL.value
        assert not any(e["state"] == "NATIVE_ARCHIVED" for e in store.get_job_events(job_id))

    def test_missing_retrieve_receipt_never_publishes_native_archived(self, tmp_path) -> None:
        store, job_id, _ = _prepared_job(tmp_path)
        base, _ = make_fake_openness_worker(tmp_path)

        def no_retrieve(command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
            if command == "retrieve":
                return {"ok": False, "error": "retrieve_receipt_missing"}
            return base(command, *args, timeout_s=timeout_s)

        result = DeliveryCoordinator(store).run_chain(
            job_id,
            adapter=TiaOpennessCliAdapter(worker=no_retrieve, real_machine=True),
            request=_request(tmp_path, job_id),
        )
        assert result["state"] == "FAILED"
        assert result["error_code"] == "REOPEN_FAILED"
        assert store.get_job(job_id)["state"] == "FAILED"
        assert DeliveryCoordinator(store).get_job(job_id)["native_artifact"] is None

    def test_reopen_ok_missing_in_receipt_never_publishes_native_archived(self, tmp_path) -> None:
        store, job_id, _ = _prepared_job(tmp_path)
        base, _ = make_fake_openness_worker(tmp_path)

        def no_reopen_flag(command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
            receipt = base(command, *args, timeout_s=timeout_s)
            if command == "retrieve":
                receipt.pop("reopenOk", None)
                receipt["retrieve"].pop("reopenOk", None)
            return receipt

        result = DeliveryCoordinator(store).run_chain(
            job_id,
            adapter=TiaOpennessCliAdapter(worker=no_reopen_flag, real_machine=True),
            request=_request(tmp_path, job_id),
        )
        assert result["state"] == "FAILED"
        assert result["error_code"] == "REOPEN_FAILED"

    def test_pending_job_never_claims_delivery_complete(self, tmp_path) -> None:
        store = build_store(tmp_path)
        changeset = EngineeringServiceV2.freeze_changeset(store, "prj_demo", base_revision=0)
        baseline = store.get_project("prj_demo").baseline_hash
        ApprovalGate(store).approve(
            changeset.id, reviewer="qa_human", explicit=True, expected_baseline_hash=baseline
        )
        data, status = DeliveryCoordinator(store).start(
            {
                "project_id": "prj_demo",
                "approved_changeset_id": changeset.id,
                "expected_baseline_hash": baseline,
                "idempotency_key": "qa_pending_1",
            }
        )
        assert status == 202
        job = DeliveryCoordinator(store).get_job(data["job_id"])
        assert job["state"] == "QUEUED"
        assert job["evidence_level"] == EvidenceLevel.PENDING_REAL_MACHINE.value
        assert job["native_artifact"] is None
        assert "交付完成" not in json.dumps(job, ensure_ascii=False)
        assert "pending_real_machine" in job["notice"]


# --------------------------------------------------------------------------- #
# E. API 证据等级 / SOURCE_READY 语义
# --------------------------------------------------------------------------- #
class TestApiEvidenceLevel:
    def test_every_v2_json_endpoint_carries_evidence_level(self, tmp_path) -> None:
        store = build_store(tmp_path)
        app.dependency_overrides[get_store] = lambda: store
        try:
            with TestClient(app) as client:
                calls = [
                    ("post", "/api/v2/projects", {"project_id": "prj_qa_api"}),
                    ("get", "/api/v2/projects/prj_demo", None),
                    ("get", "/api/v2/projects/prj_demo/ir", None),
                    ("get", "/api/v2/projects/prj_demo/blocks", None),
                    ("post", "/api/v2/projects/prj_demo/intent", {"message": "一只双作用气缸"}),
                    ("post", "/api/v2/projects/prj_demo/validate", {}),
                    ("post", "/api/v2/projects/prj_demo/simulate", {"scenario": "normal_cycle"}),
                    ("post", "/api/v2/projects/prj_demo/preview", {"include_scl": True}),
                    ("post", "/api/v2/projects/prj_demo/changesets", {"base_revision": 0, "ops": []}),
                    ("post", "/api/v2/projects/prj_demo/patches",
                     {"base_revision": 0, "ops": [{"op": "set_view_layout", "layout": {}}]}),
                ]
                for method, path, payload in calls:
                    response = getattr(client, method)(path, json=payload) if payload is not None else client.get(path)
                    body = response.json()
                    assert "evidence_level" in body, f"{method} {path} -> {body}"
                    assert body["evidence_level"] in ("offline", "mocked", "V19_real", "pending_real_machine")
        finally:
            app.dependency_overrides.clear()

    def test_source_package_is_explicitly_not_a_native_project(self, tmp_path) -> None:
        store = build_store(tmp_path)
        app.dependency_overrides[get_store] = lambda: store
        try:
            with TestClient(app) as client:
                response = client.get("/api/v2/projects/prj_demo/source-package")
                assert response.status_code == 200
                assert response.headers["X-Artifact-Kind"] == "source_import_package_not_native"
                assert response.headers["X-Evidence-Level"] == "offline"
                assert "非原生工程" in response.content.decode("utf-8", errors="ignore") or \
                       "NOTICE.txt" in response.content.decode("latin-1", errors="ignore")
        finally:
            app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# F. 本次独立验收抓到的源码缺陷（严格按 PRD 期望断言；当前实现会 FAILED）
#    —— 路由：Engineer；QA 不修改源码。复现命令见报告。
# --------------------------------------------------------------------------- #
class TestSourceDefectsFoundByQA:
    def test_fake_worker_cannot_be_labelled_v19_real(self, tmp_path) -> None:
        """P-01（PRD 6.4 / 设计 9.3）：V19_real 只认真实 Siemens.Engineering.dll 回执。

        期望：注入纯 Python fake worker 时，即使调用方传 ``real_machine=True``，
        链也不得输出 ``V19_real`` / ``NATIVE_ARCHIVED``（缺少 receipt 级防伪）。
        实际：evidence/v2/qa/07_probe_observations.txt P1 → V19_real + NATIVE_ARCHIVED。
        工程师测试 tests/unit/test_retrieve_reopen_v2.py:90-95 亦以 fake worker
        断言 ``V19_real``，注释却写 "NOT a real TIA run"。
        """
        worker, _ = make_fake_openness_worker(tmp_path)
        adapter = TiaOpennessCliAdapter(worker=worker, real_machine=True)
        chain = execute_chain(adapter, _request(tmp_path, "job_qa_p01"))
        assert chain.evidence_level != EvidenceLevel.V19_REAL.value
        assert chain.state != "NATIVE_ARCHIVED"

    def test_compile_ok_requires_static_gate_passed(self) -> None:
        """P-02（PRD 6.4 强制规则 2）：compile_ok = error_count==0 ∧ static_gate_passed ∧ 真实回执。

        期望：staticGatePassed=false 时 compile_ok 必须为 False。
        实际：plc_engine/engineering_ir/models.py:747 漏掉 static_gate_passed → compile_ok=True。
        对照：gateway/app/services/plc/evidence_v2.py:111 的 compile_ok() 实现是正确的三条件。
        """
        receipt = CompileReceipt.from_worker(
            {"ok": True, "compile": {"state": "Success", "errorCount": 0,
                                     "warningCount": 0, "staticGatePassed": False}},
            raw='{"ok":true}',
            evidence=EvidenceLevel.V19_REAL,
        )
        assert receipt.static_gate_passed is False
        assert receipt.compile_ok is False

    def test_static_gate_failure_blocks_native_archived(self, tmp_path) -> None:
        """P-03（PRD 6.4 / 设计 4.4）：静态门禁失败不得进入 NATIVE_ARCHIVED。

        期望：manifest 依赖顺序违规（static_gate_passed=False）时应拒绝置位。
        实际：tia_delivery_v2.py:344 只写 flag、未重算 compile_ok，
        :425 仍按 adapter.real_machine 置 NATIVE_ARCHIVED（探测 P2）。
        """
        udt = ArtifactFile(path="scl/UDT_X.scl", sha256="sha256:aaa", role="UDT", content="x")
        ob = ArtifactFile(path="scl/OB_X.scl", sha256="sha256:bbb", role="OB", content="y")
        bad_manifest = ArtifactManifest(
            files=[udt, ob],
            import_order=["scl/OB_X.scl", "scl/UDT_X.scl"],
            dependencies={"scl/OB_X.scl": ["scl/UDT_X.scl"]},
        )
        assert bad_manifest.validate_import_order()
        worker, _ = make_fake_openness_worker(tmp_path)
        chain = execute_chain(
            TiaOpennessCliAdapter(worker=worker, real_machine=True),
            _request(tmp_path, "job_qa_p03", manifest=bad_manifest),
        )
        assert chain.artifact is not None
        assert chain.artifact.compile.static_gate_passed is False
        assert chain.state != "NATIVE_ARCHIVED"

    def test_malformed_guard_signal_is_rejected_by_static_validation(self) -> None:
        """P-04（PRD 7.6 fail-closed / T04 负例）：非法标识符必须被静态校验拒绝。

        期望：signal 含 ``; (* ... *)`` / 换行 / 引号时 ValidationEngine 不通过。
        实际：guard_ast.py:139-143 仅检查非空，validate() 返回 passed=True（探测 P4）。
        """
        ir = build_valid_demo_ir("prj_qa_p04")
        ir.process.transitions[0].guard_ast = GuardAST.from_dict(
            {"node_type": "SIGNAL", "value_type": "BOOL",
             "signal": "X : BOOL; (* QA_INJECTED *)"}
        )
        report = ValidationEngine().validate(ir)
        assert not report.passed

    def test_malformed_guard_signal_does_not_leak_into_generated_scl(self) -> None:
        """P-04b（PRD 7.9 / A6）：生成的 SCL 不得夹带注入文本。

        期望：非法 signal 名被转义/拒绝，SCL 内容不含 ``QA_INJECTED``。
        实际：scl_lowering.py:34 ``f"#{guard.signal}"`` 直接拼接（探测 P4）。
        """
        ir = build_valid_demo_ir("prj_qa_p04b")
        ir.process.transitions[0].guard_ast = GuardAST.from_dict(
            {"node_type": "SIGNAL", "value_type": "BOOL",
             "signal": "X : BOOL; (* QA_INJECTED *)"}
        )
        manifest, _ = CompilerService(ir.af_profile).lower(ir)
        generated = "\n".join(item.content for item in manifest.files)
        assert "QA_INJECTED" not in generated

    def test_guard_from_dict_rejects_unknown_fields_as_documented(self) -> None:
        """P-05（guard_ast.py:95 docstring "rejects ... unknown fields" / 设计 9.9）。

        期望：未知顶层键被拒绝（strict schema）。
        实际：只拒绝 6 个自由文本键，``arbitrary_unknown_key`` 被静默忽略（探测 P5）。
        """
        with pytest.raises(GuardValidationError):
            GuardAST.from_dict(
                {"node_type": "CONST", "value_type": "BOOL", "value": True,
                 "arbitrary_unknown_key": "junk"}
            )
