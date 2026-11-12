"""Record the U-02 lead-appointed CPU skeleton (NO verification claim).

Run: uv run python scripts/apply_cpu_selection_v2.py

Writes ONLY evidence/v2/T01/cpu_selection.json. Historical evidence/*.json is
never touched. The selection is `selected_by_lead`, NOT approved/verified:
a real CreateWithItem probe (cpu_verification_v2) is still required.
"""
from __future__ import annotations

import json
from pathlib import Path

from gateway.app.services.plc.capability_v2 import apply_lead_cpu_selection, probe_capability
from gateway.app.services.plc.cpu_verification_v2 import LEAD_SELECTED_CPU
from gateway.app.services.plc.workspace_v2 import utc_now

OUTPUT = Path(__file__).resolve().parents[1] / "evidence" / "v2" / "T01" / "cpu_selection.json"
REASON = (
    "主理人齐活林 2026-11-09 裁定（U-02）：指定 S7-1500 CPU 1511-1 PN 为本期目标 CPU skeleton。"
    "4 个候选均为静态 V19 订货号、历史文档无可确认的已验证记录，故不得标为 approved/verified。"
)


def main() -> None:
    manifest = probe_capability(store=None, write_evidence=False)
    selected = apply_lead_cpu_selection(
        manifest,
        LEAD_SELECTED_CPU,
        selected_by="齐活林 (team-lead)",
        reason=REASON,
    )
    payload = {
        "task_id": "T05 / U-02 CPU 选型落地",
        "selected_by": "齐活林 (team-lead)",
        "selected_at": utc_now(),
        "type_identifier": LEAD_SELECTED_CPU,
        "cpu_template": "S7-1500 / CPU 1511-1 PN",
        "reason": REASON,
        "selection_status": "selected_by_lead",
        "verification_required": True,
        "verified_create_with_item": False,
        "approved": False,
        "notice": (
            "绝不冒充 approved/verified；--real 交付链必须先执行 CreateWithItem 验证（临时副本），"
            "验证通过才升级 approved 并允许继续；失败或 TIA 不可用一律 fail-closed，"
            "输出 CPU_TEMPLATE_NOT_SELECTED 或 pending_real_machine，绝不自动改用其它型号、绝不猜测。"
        ),
        "candidate_cpu_templates": selected.cpu_templates,
        "capability_manifest": selected.to_dict(),
        "create_with_item_probe": {
            "executed": False,
            "evidence_level": "pending_real_machine",
            "raw_evidence_path": "evidence/v2/T02/cpu_create_with_item_probe.json",
        },
        "real_tia_v19_tested": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "selected": LEAD_SELECTED_CPU,
        "status": payload["selection_status"],
        "verification_required": True,
        "verified_create_with_item": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
