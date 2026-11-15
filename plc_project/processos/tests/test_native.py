"""WS6 native delivery integration tests (offline orchestration, MOCKED).

These prove the ProcessOS->Openness wiring, manifest import order and OB_Main
inclusion WITHOUT a real TIA. A mocked chain is labelled ``mocked`` and never
NATIVE_ARCHIVED. The real V19 compile is exercised separately (scripts/E2E).
"""
from __future__ import annotations

from pathlib import Path

from processos.backends import lower
from processos.codegen import generate
from processos.contract import clamp_contract
from processos.frameworks import register_hr001_af_v19
from processos.native import build_manifest, run_native_delivery


def _fake_worker(command, *args, timeout_s=300):
    if command == "create-project":
        return {"ok": True, "create": {"projectPath": "C:/mock/proj.ap19"}}
    if command == "create-device":
        return {"ok": True}
    if command == "generate-from-source":
        return {"ok": True}
    if command == "compile-plc":
        return {"ok": True, "compile": {"ok": True, "state": "Success", "errorCount": 0,
                "warningCount": 0, "apiAvailable": True, "message": "Compile State=Success errors=0 warnings=0",
                "inconsistentBlocks": ["Compiling finished (errors: 0; warnings: 0)"]}}
    if command == "save-project":
        return {"ok": True}
    if command == "archive-project":
        return {"ok": True, "archive": {"ok": True, "archivePath": "C:/mock/proj.zap19",
                "archiveSha256": "sha256:" + "ab" * 32, "sizeBytes": 1024, "projectPath": "C:/mock/proj.ap19"}}
    if command == "retrieve":
        return {"ok": True, "retrieve": {"ok": True, "reopenOk": True, "projectPath": "C:/mock/reopen.ap19"}}
    return {"ok": False, "error": f"unexpected command {command}"}


def test_manifest_import_order_fb_db_ob(tmp_path):
    profile = register_hr001_af_v19()
    contract = clamp_contract()
    project = lower(contract, profile)
    gen = generate(project, profile)
    manifest = build_manifest(gen, project, profile, tmp_path)
    roles = [f.role for f in manifest.files]
    assert roles == sorted(roles, key=lambda r: {"FB": 0, "FC": 1, "DB": 2, "OB": 3}[r])
    assert "OB" in roles
    assert all(f.path.endswith(".scl") for f in manifest.files)
    assert all(Path(f.path).exists() for f in manifest.files)
    assert manifest.sha256.startswith("sha256:")


def test_mocked_chain_completes_but_not_native(tmp_path):
    profile = register_hr001_af_v19()
    job = run_native_delivery(clamp_contract(), profile, real=False, worker=_fake_worker)
    assert job["status"] == "SUCCEEDED"
    assert job["evidence_level"] == "mocked"
    assert job["ob_main_included"] is True
    states = [e["state"] for e in job["events"]]
    assert "NATIVE_ARCHIVED" not in states
    assert job["chain_state"] == "MOCKED_CHAIN_OK"
    assert job["events"][-1]["stage"] == "RETRIEVE_REOPEN"


def test_mocked_chain_failure_is_fail_closed(tmp_path):
    def failing_worker(command, *args, timeout_s=300):
        if command == "compile-plc":
            return {"ok": True, "compile": {"ok": False, "state": "Error", "errorCount": 3,
                    "warningCount": 0, "apiAvailable": True, "message": "3 errors"}}
        return _fake_worker(command, *args, timeout_s=timeout_s)

    profile = register_hr001_af_v19()
    job = run_native_delivery(clamp_contract(), profile, real=False, worker=failing_worker)
    assert job["status"] == "FAILED"
    assert job["artifact"] is None
    assert any(d["stage"] == "COMPILE" for d in job["diagnostics"])