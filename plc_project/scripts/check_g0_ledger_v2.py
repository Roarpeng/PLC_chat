"""P-06 ledger consistency self-check (T09).

Run: uv run python scripts/check_g0_ledger_v2.py
Verifies the four G0 files agree on tiaRunning / processCount /
probe_receipt_id / g5_status, and that the misleading 'approved' wording is
fully removed from both evidence files and the generator.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T01 = ROOT / "evidence" / "v2" / "T01"
OLD_WORD = "static_approved_candidate_v19"

EXPECTED_ID = "g0_d32beeb9478950dd"
EXPECTED_AT = "2026-11-09T15:03:48.281136+00:00"


def load(name: str) -> dict:
    return json.loads((T01 / name).read_text(encoding="utf-8"))


def main() -> None:
    cap = load("capability_probe.json")
    g0 = load("g0_probe.json")
    batch = load("batch_receipt.json")
    cpu = load("cpu_selection.json")
    report = (ROOT / "docs" / "v2" / "baseline-report.md").read_text(encoding="utf-8")
    generator = (ROOT / "gateway" / "app" / "services" / "plc" / "capability_v2.py").read_text(encoding="utf-8")

    checks: dict[str, bool] = {}
    for name, payload in (("capability_probe.json", cap), ("g0_probe.json", g0)):
        checks[f"{name}:tiaRunning"] = payload.get("tiaRunning") is True
        checks[f"{name}:processCount"] = payload.get("processCount") == 1
        checks[f"{name}:probe_receipt_id"] = payload.get("probe_receipt_id") == EXPECTED_ID
        checks[f"{name}:probed_at"] = payload.get("probed_at") == EXPECTED_AT
        checks[f"{name}:g5_status"] = payload.get("g5_status") == "pending_real_machine"
        checks[f"{name}:evidence_scope"] = payload.get("evidence_scope") == "read_only_status_probe"
        checks[f"{name}:chain_tested_false"] = payload.get("real_tia_v19_chain_tested") is False
        checks[f"{name}:correction_note"] = "更正" in str(payload.get("correction_note", ""))

    checks["g0_probe:real_tia_v19_tested_kept"] = g0.get("real_tia_v19_tested") is True
    checks["g0_probe:selection_note_scoped"] = "AC-01" in str(g0.get("selection_note", ""))
    checks["batch_receipt:correction"] = batch.get("g0_receipt_correction", {}).get("tiaRunning") is True
    checks["batch_receipt:processCount"] = batch.get("g0_receipt_correction", {}).get("processCount") == 1
    checks["batch_receipt:probe_receipt_id"] = batch.get("g0_receipt_correction", {}).get("probe_receipt_id") == EXPECTED_ID
    checks["batch_receipt:g5_status"] = batch.get("g0_receipt_correction", {}).get("g5_status") == "pending_real_machine"
    checks["batch_receipt:no_false_transcription"] = all(
        "tiaRunning=false" not in str(item) and "processCount=0" not in str(item)
        for item in batch.get("pending_real_machine", [])
    )
    checks["batch_receipt:correction_note"] = "更正说明" in str(batch.get("correction_note", ""))
    checks["cpu_selection:not_approved"] = cpu.get("approved") is False and cpu.get("verification_required") is True
    checks["cpu_selection:selected_by_lead"] = cpu.get("selection_status") == "selected_by_lead"

    checks["baseline_report:true"] = '"tiaRunning": true' in report
    checks["baseline_report:count1"] = '"processCount": 1' in report
    checks["baseline_report:detected_message"] = "TIA Portal process detected." in report
    checks["baseline_report:no_false_transcription"] = "tiaRunning=false" not in report and "processCount=0" not in report
    checks["baseline_report:probe_receipt_id"] = EXPECTED_ID in report
    checks["baseline_report:g5_status"] = "g5_status=pending_real_machine" in report
    checks["baseline_report:correction_note"] = "更正说明（P-06" in report

    files = [T01 / name for name in ("capability_probe.json", "g0_probe.json", "cpu_selection.json", "batch_receipt.json")]
    checks["wording:evidence_files_clean"] = all(OLD_WORD not in f.read_text(encoding="utf-8") for f in files)
    checks["wording:generator_clean"] = OLD_WORD not in generator
    checks["wording:new_term_present"] = all(
        "static_candidate_v19_unverified" in (T01 / name).read_text(encoding="utf-8")
        for name in ("capability_probe.json", "g0_probe.json", "cpu_selection.json")
    )

    failed = [key for key, ok in checks.items() if not ok]
    result = {
        "checked": len(checks),
        "passed": len(checks) - len(failed),
        "failed": failed,
        "tiaRunning": True,
        "processCount": 1,
        "probe_receipt_id": EXPECTED_ID,
        "g5_status": "pending_real_machine",
        "IS_PASS": "YES" if not failed else "NO",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
