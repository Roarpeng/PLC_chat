"""Optional MOCKED DiffPlan orchestration demo (explicitly labelled).

It NEVER calls any real Openness write API and NEVER emits V19_real evidence.
The response always carries `evidence_level=mocked` and `applied=false`.
"""
from __future__ import annotations

from typing import Any

from plc_engine.changeplan.diff_plan import DiffPlan
from plc_engine.changeplan.impact_closure import reverse_reference_closure
from plc_engine.changeplan.source_binding import SourceBinding


def mocked_orchestrate(
    plan: DiffPlan,
    bindings: list[SourceBinding],
) -> dict[str, Any]:
    """Return a purely declarative mocked orchestration receipt."""
    targets = [op.source_id or op.target for op in plan.ops if op.op in ("MODIFY", "DELETE")]
    closure = reverse_reference_closure(bindings, targets)
    return {
        "plan_id": plan.plan_id,
        "executable": False,
        "applied": False,
        "evidence_level": "mocked",
        "real_tia_v19_tested": False,
        "impact_closure": closure,
        "declaration_only": True,
        "notice": (
            "mocked orchestration demo only: no TIA ADD/MODIFY/DELETE, "
            "no original project modification, no V19 real evidence. "
            "AC-02 real-machine acceptance is out of scope this batch."
        ),
    }
