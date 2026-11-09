"""G5 / AC-01: strict native delivery chain (offline orchestration + negatives).

All runs here are MOCKED orchestration unless explicitly flagged as a
real_machine adapter; no test claims a V19 real full-chain receipt.
"""
from __future__ import annotations

from pathlib import Path

from gateway.app.services.plc.tia_delivery_v2 import (
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    execute_chain,
)
from plc_engine.engineering_ir.evidence import EvidenceLevel
from tests.v2_fixtures import make_fake_openness_worker as make_worker


def request_for(tmp_path: Path) -> DeliveryChainRequest:
    return DeliveryChainRequest(
        project_id="prj_chain", job_id="job_chain_1", project_name="Demo",
        workspace_dir=str(tmp_path / "ws"), cpu_type_identifier="6ES7511-1AK02-0AB0/V2.9",
        archive_name="Demo.zap19",
    )


def test_mocked_full_chain_never_claims_native_archived(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    adapter = TiaOpennessCliAdapter(worker=worker)  # real_machine=False by default
    result = execute_chain(adapter, request_for(tmp_path))
    assert result.ok is True
    assert result.state == "MOCKED_CHAIN_OK"
    assert result.evidence_level == EvidenceLevel.MOCKED.value
    assert result.artifact is not None
    assert result.artifact.is_native_archived() is False
    assert [r.stage for r in result.stage_receipts][-1] == "RETRIEVE_REOPEN"
    assert "retrieve" in adapter.calls[-1]["command"]


def test_real_machine_receipt_is_required_for_native_archived(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    adapter = TiaOpennessCliAdapter(worker=worker, real_machine=True,
                                    evidence_level=EvidenceLevel.V19_REAL)
    result = execute_chain(adapter, request_for(tmp_path))
    assert result.state == "NATIVE_ARCHIVED"
    assert result.evidence_level == EvidenceLevel.V19_REAL.value
    assert result.artifact is not None and result.artifact.is_native_archived() is True
    assert result.artifact.compile.error_count == 0
    assert result.artifact.compile.warning_count == 2  # warnings listed separately
    assert result.artifact.reopen_ok is True
    assert result.artifact.archive_sha256.startswith("sha256:")


def test_compile_failure_never_publishes_artifact(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, error_count=3)
    result = execute_chain(TiaOpennessCliAdapter(worker=worker, real_machine=True),
                           request_for(tmp_path))
    assert result.state == "FAILED"
    assert result.error_code == "COMPILE_FAILED"
    assert result.artifact is None
    assert result.stage_receipts[-1].stage == "COMPILE"


def test_archive_missing_never_publishes_artifact(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, archive_ok=False)
    result = execute_chain(TiaOpennessCliAdapter(worker=worker, real_machine=True),
                           request_for(tmp_path))
    assert result.state == "FAILED"
    assert result.error_code == "ARCHIVE_MISSING"
    assert result.artifact is None


def test_missing_create_project_path_is_explicit_failure(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, create_path_ok=False)
    result = execute_chain(TiaOpennessCliAdapter(worker=worker), request_for(tmp_path))
    assert result.state == "FAILED"
    assert "create.projectPath" in result.error_message
    assert result.artifact is None


def test_cpu_not_selected_is_explicit_failure(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    request = request_for(tmp_path)
    request.cpu_type_identifier = ""
    result = execute_chain(TiaOpennessCliAdapter(worker=worker), request)
    assert result.state == "FAILED"
    assert result.error_code == "CPU_TEMPLATE_NOT_SELECTED"
    assert result.artifact is None
    assert result.stage_receipts[0].stage == "CREATE"
    assert result.stage_receipts[0].ok is False


def test_reopen_failure_is_rejected_before_native_archived(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, reopen_ok=False)
    result = execute_chain(TiaOpennessCliAdapter(worker=worker, real_machine=True),
                           request_for(tmp_path))
    assert result.state == "FAILED"
    assert result.error_code == "REOPEN_FAILED"
    assert result.artifact is None
    assert result.stage_receipts[-1].stage == "RETRIEVE_REOPEN"


def test_save_failure_is_explicit_and_keeps_evidence(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, save_ok=False)
    result = execute_chain(TiaOpennessCliAdapter(worker=worker), request_for(tmp_path))
    assert result.state == "FAILED"
    assert result.stage_receipts[-1].stage == "SAVE"
    assert result.to_dict()["stage_receipts"]


def test_sha256_mismatch_is_rejected(tmp_path, monkeypatch) -> None:
    worker, _ = make_worker(tmp_path)
    original = worker

    def tampered(command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
        receipt = original(command, *args, timeout_s=timeout_s)
        if command == "archive-project":
            receipt["archive"]["archiveSha256"] = "sha256:" + "0" * 64
        return receipt

    result = execute_chain(TiaOpennessCliAdapter(worker=tampered, real_machine=True),
                           request_for(tmp_path))
    assert result.state == "FAILED"
    assert result.error_code == "ARCHIVE_MISSING"
    assert "sha256 mismatch" in result.error_message
