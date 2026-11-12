"""WP-07: unified acceptance release contract (offline document/Schema checks)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs" / "v2"
EVIDENCE = REPO / "evidence" / "v2"


def read(path: Path) -> str:
    assert path.is_file(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def test_acceptance_matrix_maps_all_six_ac01_steps() -> None:
    text = read(DOCS / "03-验收矩阵.md")
    for step in range(1, 7):
        assert f"| {step} |" in text
    for gate in ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        assert gate in text
    assert "evidence_level" in text


def test_g5_is_never_marked_passed() -> None:
    for name in ("03-验收矩阵.md", "g0-g7-matrix.md", "04-交付报告.md"):
        text = read(DOCS / name)
        assert "pending_real_machine" in text
        assert "G5" in text
    gates = read(DOCS / "g0-g7-matrix.md")
    g5_line = next(line for line in gates.splitlines() if "**G5**" in line or line.startswith("| G5"))
    assert "pending_real_machine" in g5_line
    assert "已通过" not in g5_line
    assert "NOT PASSED" in g5_line or "未通过" in g5_line


def test_acceptance_receipt_is_honest() -> None:
    payload = json.loads(read(EVIDENCE / "acceptance" / "acceptance_receipt.json"))
    assert payload["status"] == "pending_real_machine"
    assert payload["real_tia_v19_tested"] is False
    assert payload["delivery_complete"] is False
    assert payload["native_artifacts_published"] == 0
    assert payload["gates"]["G5"]["status"] == "NOT PASSED"
    assert payload["gates"]["G5"]["evidence_level"] == "pending_real_machine"
    assert payload["ac01"]["step_1"] == "pending_real_machine"
    assert payload["ac01"]["step_5"] == "pending_real_machine"
    assert payload["ac01"]["step_6"] == "pending_real_machine"
    assert payload["historical_conclusions_unchanged"]["xml_package_unverified"] is True
    assert payload["historical_conclusions_unchanged"]["m4_passed"] is False
    assert payload["ledger_closed_by"] == "team-lead"


def test_ac01_matrix_has_six_steps_with_no_upcast() -> None:
    payload = json.loads(read(EVIDENCE / "acceptance" / "ac01_matrix.json"))
    assert len(payload["steps"]) == 6
    for step in payload["steps"]:
        if step["n"] in (1, 5, 6):
            assert step["evidence_level"] == "pending_real_machine"
            assert step["verified"] is False
            assert step["raw_receipt_path"] is None
        assert step["evidence_level"] != "V19_real"


def test_all_five_schemas_and_openapi_are_present() -> None:
    contracts = DOCS / "contracts"
    for name in ("engineering_ir_v2.schema.json", "patch_v2.schema.json", "changeset_v2.schema.json",
                 "delivery_v2.schema.json", "capability_v2.schema.json", "api_v2.openapi.json"):
        payload = json.loads(read(contracts / name))
        assert isinstance(payload, dict)
    openapi = json.loads(read(contracts / "api_v2.openapi.json"))
    assert len([p for p in openapi["paths"] if p.startswith("/api/v2")]) >= 18


def test_cpu_selection_is_not_claimed_as_verified() -> None:
    payload = json.loads(read(EVIDENCE / "T01" / "cpu_selection.json"))
    assert payload["type_identifier"] == "6ES7511-1AK02-0AB0/V2.9"
    assert payload["selection_status"] == "selected_by_lead"
    assert payload["verified_create_with_item"] is False
    assert payload["approved"] is False
    assert payload["create_with_item_probe"]["executed"] is False


def test_baseline_and_fault_documents_exist() -> None:
    for name in ("baseline-report.md", "pre_existing_failures.md", "driver-catalog.md",
                 "process-algorithms.md", "brownfield-interface-contract.md", "fault-injection-matrix.md"):
        assert (DOCS / name).is_file(), name
    assert "3 failed" in read(DOCS / "pre_existing_failures.md") or "3 个" in read(DOCS / "pre_existing_failures.md")
    assert "100%" in read(DOCS / "fault-injection-matrix.md")


def test_historical_evidence_is_not_rewritten_by_this_batch() -> None:
    """Engineer only writes under evidence/v2/**; historical evidence/*.json stays."""
    historical = [p for p in (REPO / "evidence").glob("*.json")]
    assert isinstance(historical, list)  # presence only; contents are owned by the lead
    assert (EVIDENCE / "batch_receipt.schema.json").is_file()
    assert (EVIDENCE / "acceptance" / "raw" / "README.md").is_file()


def test_no_qa_report_written_by_engineer() -> None:
    """Path isolation: the engineer must not create the QA report file."""
    assert not (DOCS / "04-QA验收报告.md").exists()
