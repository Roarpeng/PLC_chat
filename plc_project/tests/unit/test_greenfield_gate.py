"""T05 / AC-4 / AC-5：确认硬门禁、零副作用、冻结 spec 可复现与旧版不可变。"""
from __future__ import annotations

from pathlib import Path

import pytest

from gateway.app.services.plc import greenfield_service as svc
from gateway.app.services.plc.greenfield_session import GreenfieldSession
from plc_engine.af.greenfield_ports import (
    GateLockedError,
    GreenfieldStage,
    SpecImmutableError,
)
from plc_engine.af.greenfield_spec import FrozenSpec, write_spec


def _ready(session_id: str) -> GreenfieldSession:
    session = GreenfieldSession(session_id=session_id)
    svc.draft_from_prompt(session, "")
    svc.revalidate(session)
    return session


def test_no_side_effects_before_confirm(tmp_path: Path) -> None:
    session = _ready("gate-zero")
    assert all(value == 0 for value in session.counters.values())
    session.assert_no_side_effects()
    for action in ("generate", "writeback", "confirm-writeback", "compile-jobs", "disk_write"):
        with pytest.raises(GateLockedError):
            session.assert_gate(action)


def test_confirm_requires_explicit_user_action(tmp_path: Path) -> None:
    session = _ready("gate-explicit")
    with pytest.raises(GateLockedError) as exc:
        svc.confirm_and_freeze(session, explicit=False, base_dir=tmp_path)
    assert exc.value.code == "GF_GATE_NOT_CONFIRMED"
    assert not session.specs
    assert all(value == 0 for value in session.counters.values())


def test_confirm_requires_engineering_summary(tmp_path: Path) -> None:
    session = _ready("gate-summary")
    with pytest.raises(GateLockedError):
        svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path)
    svc.engineering_summary(session)
    assert session.engineering_summary_shown is True


def test_frozen_spec_is_reproducible_and_immutable(tmp_path: Path) -> None:
    session = _ready("gate-freeze")
    svc.engineering_summary(session)
    result = svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path)
    payload = result["spec"]
    spec = FrozenSpec.from_dict(payload)
    assert spec.spec_hash == payload["spec_hash"]
    assert spec.recompute_hash() == payload["spec_hash"]
    assert session.stage is GreenfieldStage.FROZEN
    assert session.counters["disk_writes"] == 1
    assert session.counters["ops"] == 0
    assert session.counters["writebacks"] == 0
    assert session.counters["generations"] == 0

    path = Path(result["path"])
    before = path.read_bytes()
    with pytest.raises(SpecImmutableError):
        write_spec(spec, tmp_path, session.session_id)
    assert path.read_bytes() == before, "旧版 spec 字节不得改写"


def test_edit_after_freeze_creates_new_version(tmp_path: Path) -> None:
    session = _ready("gate-version")
    svc.engineering_summary(session)
    first = svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path)["spec"]
    svc.begin_edit(session)
    assert session.stage is GreenfieldStage.LINKABLE
    assert not session.engineering_summary_shown
    svc.revalidate(session)
    svc.engineering_summary(session)
    second = svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path)["spec"]
    assert second["spec_version"] == first["spec_version"] + 1
    assert second["prev_spec_hash"] == first["spec_hash"]
    assert len(session.specs) == 2


def test_draft_export_import_is_side_effect_free() -> None:
    session = _ready("gate-draft")
    payload = session.export_draft()
    assert payload["format"] == "greenfield-draft-v1"
    assert payload["ir"] is not None
    assert all(value == 0 for value in session.counters.values())
    restored = GreenfieldSession(session_id="gate-restored")
    restored.import_draft(payload)
    assert restored.ir is not None
    assert restored.ir.ir_sha256() == session.ir.ir_sha256()
    assert all(value == 0 for value in restored.counters.values())


def test_views_and_export_available_before_confirm(tmp_path: Path) -> None:
    session = _ready("gate-export")
    views = svc.get_views(session)
    assert views["flow"].startswith("flowchart TB")
    assert views["seq"].startswith("sequenceDiagram")
    assert views["state"].startswith("stateDiagram-v2")
    md = svc.export_first_mermaid(session)
    assert "flowchart" in md and "确认前禁止" in md
    assert all(value == 0 for value in session.counters.values())


# ---------------------------------------------------------------------------
# WP-03 / §3：确认硬门禁具体原因 + 差异清单未确认零副作用
# ---------------------------------------------------------------------------

def test_confirm_prerequisites_return_specific_reasons(tmp_path: Path) -> None:
    """前置任一未满足返回具体原因（非笼统报错），并阻止确认，零副作用。"""
    session = _ready("gate-prereq")
    good = svc.check_confirm_prerequisites(session)
    assert good["ok"] is True, good["reasons"]
    assert good["checks"]["baseline_locked"] is True
    assert good["checks"]["open_questions_cleared"] is True

    session.topology_finalized = False
    bad = svc.check_confirm_prerequisites(session)
    assert bad["ok"] is False
    assert bad["checks"]["topology_finalized"] is False
    assert any("拓扑" in r for r in bad["reasons"]), bad["reasons"]
    with pytest.raises(GateLockedError) as exc:
        svc.confirm_and_freeze(session, explicit=True, base_dir=tmp_path)
    assert "拓扑" in str(exc.value)  # 具体原因透传
    assert not session.specs
    assert all(v == 0 for v in session.counters.values())


def test_confirm_diff_unconfirmed_keeps_zero_side_effects() -> None:
    """④ /confirm-diff 在 confirmed != true 时零副作用计数器恒 0。"""
    session = _ready("gate-diff")
    result = svc.confirm_diff_action(session, {"diff_id": "D1", "confirmed": False})
    assert result["confirmed"] is False
    assert result["zero_side_effects"] is True
    assert result["side_effect_counters"] == {
        "ops": 0, "disk_writes": 0, "writebacks": 0, "generations": 0
    }
    assert session.diff_confirmed is False
    assert all(v == 0 for v in session.counters.values())
    # 显式确认本身也不产生任何副作用计数
    ok = svc.confirm_diff_action(session, {"diff_id": "D1", "confirmed": True})
    assert ok["write_allowed"] is True
    assert all(v == 0 for v in session.counters.values())


def test_new_endpoints_produce_zero_side_effects_before_confirm() -> None:
    """④ HTTP 层：/patch /diff /confirm-diff 未确认时 counters 恒 0、阶段非 FROZEN。"""
    from fastapi.testclient import TestClient

    from gateway.app.main import app
    from gateway.app.services.plc.greenfield_session import registry

    registry.reset()
    client = TestClient(app)
    prefix = "/api/v1/plc/canvas/greenfield"
    sid = client.get(f"{prefix}/state?project_id=PRJ_Z").json()["data"]["session_id"]
    assert client.post(f"{prefix}/draft", json={"session_id": sid, "prompt": ""}).status_code == 200
    r_patch = client.post(
        f"{prefix}/patch",
        json={"session_id": sid, "project_id": "PRJ_Z",
              "ops": [{"op": "add_unit", "node": {"name": "S2"}}]},
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["data"]["ok"] is True
    assert client.post(
        f"{prefix}/diff", json={"session_id": sid, "from_version": 1, "to_version": 2}
    ).status_code == 200
    r_cd = client.post(
        f"{prefix}/confirm-diff",
        json={"session_id": sid, "diff_id": "D1", "confirmed": False},
    )
    assert r_cd.status_code == 200
    assert r_cd.json()["data"]["zero_side_effects"] is True
    state = client.get(f"{prefix}/state?session_id={sid}").json()["data"]
    assert state["stage"] != "FROZEN"
    assert all(v == 0 for v in state["counters"].values())
    assert not state["specs"]
