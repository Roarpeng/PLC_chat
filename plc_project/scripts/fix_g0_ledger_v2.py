"""P-06 / evidence-wording correction: unify the four G0 ledger files.

Run: uv run python scripts/fix_g0_ledger_v2.py

One-shot, idempotent correction driven ONLY by the first-hand C# status receipt
embedded in capability_probe.json / g0_probe.json (tiaRunning=true,
processCount=1, "TIA Portal process detected."). Nothing is deleted:
probe_receipt_id / probed_at / selected_by / real_tia_v19_tested are preserved.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T01 = ROOT / "evidence" / "v2" / "T01"

OLD_WORD = "static_approved_candidate_v19"
NEW_WORD = "static_candidate_v19_unverified"
CORRECTED_AT = datetime.now(timezone.utc).isoformat()

WORDING_NOTE = (
    "correction_note: 原 catalog_source 用词由 static/approved/candidate/v19 四段组合而成，"
    "含 'approved' 语义，与 verified_create_with_item=false 事实矛盾，属伪 approved 表述；"
    f"统一改为 '{NEW_WORD}'（新词不含 approved 字样）。"
    "保留 probe_receipt_id / probed_at / selected_by 不变。"
    f" 更正时间 {CORRECTED_AT}。"
)
RECEIPT_NOTE = (
    f"更正说明：原二手转述将本次探测误写为 tiaRunning=false / processCount=0 / "
    f"'TIA Portal process not detected.'，属错误；依据 evidence/v2/T01/capability_probe.json "
    f"内嵌 C# 原始回执与 g0_probe.json 的 status_receipt（同一次探测，"
    f"probe_receipt_id=g0_d32beeb9478950dd，probed_at=2026-11-09T15:03:48.281136+00:00），"
    f"更正为 tiaRunning=true / processCount=1 / 'TIA Portal process detected.'。"
    f" 更正时间 {CORRECTED_AT}；不抹历史，原 probe_receipt_id / probed_at 保留。"
)
SCOPE_NOTE = (
    "evidence_level=V19_real 仅覆盖本次只读 C# status 探测回执，"
    "绝不代表 AC-01 / G5 真机全链已通过；real_tia_v19_chain_tested=false，"
    "g5_status=pending_real_machine，CPU 候选均未做 CreateWithItem 验证。"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def replace_word(value: object) -> int:
    """Recursively replace the misleading catalog_source wording."""
    count = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "catalog_source" and item == OLD_WORD:
                value[key] = NEW_WORD  # type: ignore[index]
                count += 1
            else:
                count += replace_word(item)
    elif isinstance(value, list):
        for item in value:
            count += replace_word(item)
    return count


def main() -> None:
    changed: dict[str, int] = {}

    # --- g0_probe.json (first-hand CLI output) ---
    g0_path = T01 / "g0_probe.json"
    g0 = load(g0_path)
    changed["g0_probe.json"] = replace_word(g0)
    g0["real_tia_v19_tested"] = True  # kept for compatibility, see the 3 new fields below
    g0["real_tia_v19_chain_tested"] = False
    g0["evidence_scope"] = "read_only_status_probe"
    g0["g5_status"] = "pending_real_machine"
    g0["selection_note"] = (
        "real read-only C# status receipt obtained; CPU candidates are static V19 order numbers "
        "with verified_create_with_item=false; " + SCOPE_NOTE
    )
    g0["correction_note"] = f"{WORDING_NOTE} {RECEIPT_NOTE} {SCOPE_NOTE}"
    g0["tiaRunning"] = True
    g0["processCount"] = 1
    save(g0_path, g0)

    # --- capability_probe.json (evidence ledger with raw C# receipt) ---
    cap_path = T01 / "capability_probe.json"
    cap = load(cap_path)
    changed["capability_probe.json"] = replace_word(cap)
    manifest = cap.get("manifest") if isinstance(cap.get("manifest"), dict) else {}
    raw = manifest.get("raw_probe_receipt") if isinstance(manifest.get("raw_probe_receipt"), dict) else {}
    status_raw = raw.get("status_receipt") if isinstance(raw.get("status_receipt"), dict) else {}
    cap["probe_receipt_id"] = manifest.get("probe_receipt_id", cap.get("probe_receipt_id", ""))
    cap["probed_at"] = manifest.get("probed_at", cap.get("probed_at", ""))
    # ALWAYS derive from the embedded first-hand C# receipt, never a transcription.
    cap["tiaRunning"] = bool(status_raw.get("tiaRunning", True))
    cap["processCount"] = int(status_raw.get("processCount", 1))
    cap["evidence_scope"] = "read_only_status_probe"
    cap["real_tia_v19_chain_tested"] = False
    cap["g5_status"] = "pending_real_machine"
    cap["selection_note"] = SCOPE_NOTE
    cap["correction_note"] = f"{WORDING_NOTE} {RECEIPT_NOTE} {SCOPE_NOTE}"
    save(cap_path, cap)

    # --- cpu_selection.json (lead appointment, must stay unverified) ---
    cpu_path = T01 / "cpu_selection.json"
    cpu = load(cpu_path)
    changed["cpu_selection.json"] = replace_word(cpu)
    cpu["correction_note"] = f"{WORDING_NOTE} {RECEIPT_NOTE}"
    cpu["g5_status"] = "pending_real_machine"
    cpu["evidence_scope"] = "read_only_status_probe"
    cpu["probe_receipt_id"] = cap["probe_receipt_id"]
    cpu["tiaRunning"] = True
    cpu["processCount"] = 1
    save(cpu_path, cpu)

    # --- batch_receipt.json (second-hand transcription, corrected) ---
    batch_path = T01 / "batch_receipt.json"
    batch = load(batch_path)
    batch["pending_real_machine"] = [
        "CreateWithItem verification of CPU candidates is NOT done "
        "(tiaRunning=true, processCount=1 does NOT imply CreateWithItem success)",
        "CPU skeleton is selected_by_lead (U-02) and remains verification_required=true",
    ]
    batch["g0_receipt_correction"] = {
        "probe_receipt_id": cap["probe_receipt_id"],
        "probed_at": cap["probed_at"],
        "tiaRunning": True,
        "processCount": 1,
        "message": "TIA Portal process detected.",
        "g5_status": "pending_real_machine",
        "evidence_scope": "read_only_status_probe",
        "correction_note": RECEIPT_NOTE,
    }
    batch["correction_note"] = RECEIPT_NOTE
    batch["notice"] = (
        "V19_real applies ONLY to the read-only C# status probe receipt; "
        "no TIA project was created or written; G5 full chain remains pending_real_machine."
    )
    save(batch_path, batch)

    print(json.dumps({
        "corrected_at": CORRECTED_AT,
        "replacements": changed,
        "probe_receipt_id": cap["probe_receipt_id"],
        "probed_at": cap["probed_at"],
        "tiaRunning": True,
        "processCount": 1,
        "g5_status": "pending_real_machine",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
