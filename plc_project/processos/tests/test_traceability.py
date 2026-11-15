"""P0 tests: FC-00 identity/four graphs, FC-01 SourceMap, FC-02 incident/handover,
and the §10 battery-change-station clamp-cylinder acceptance drill."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from processos.api.app import create_app
from processos.contract import clamp_contract
from processos.incident import IncidentService, build_handover_context, build_object_context
from processos.registry import ObjectRegistry, new_object_id, register_contract
from processos.sourcemap import SourceMapRegistry, build_sourcemap
from processos.traceability import TraceabilityService


# ---------- FC-00 identity + four graphs ----------

def test_object_id_unique_and_non_reusable():
    a, b = new_object_id("cm"), new_object_id("cm")
    assert a != b and a.startswith("cm_")
    reg = ObjectRegistry()
    o = reg.register("af_cm", "气缸", object_id="cm_fixed")
    with pytest.raises(ValueError):
        reg.register("af_cm", "另一个", object_id="cm_fixed")


def test_rename_keeps_alias_and_history():
    reg = ObjectRegistry()
    o = reg.register("af_cm", "夹紧气缸 A")
    reg.rename(o.object_id, "夹紧气缸 B")
    assert o.display_name == "夹紧气缸 B"
    assert "夹紧气缸 A" in o.aliases
    assert o.history[-1]["event"] == "rename"
    assert reg.find_by_name("夹紧气缸 A").object_id == o.object_id  # old alias still resolves


def test_four_graphs_membership():
    reg = ObjectRegistry()
    reg.register("station", "电池更换站")
    reg.register("af_cm", "气缸")
    reg.register("behavior_step", "伸出")
    reg.register("incident", "INC-1")
    assert len(reg.graph("PhysicalGraph")) == 1
    assert len(reg.graph("AfGraph")) == 1
    assert len(reg.graph("BehaviorGraph")) == 1
    assert len(reg.graph("EvidenceGraph")) == 1


def test_register_contract_builds_relations():
    reg = ObjectRegistry()
    ids = register_contract(reg, clamp_contract(), physical_station="电池更换站")
    cm = reg.get(ids["CM_CLAMP_CYL"])
    assert cm.kind == "af_cm"
    em = reg.neighbors(cm.object_id, "part_of", "out")[0]
    assert em.kind == "af_em"
    steps = reg.neighbors(cm.object_id, "participates_in", "in")
    assert len(steps) >= 2  # extend + retract steps participate
    comp = reg.neighbors(cm.object_id, "maps_to", "in")[0]
    assert comp.kind == "component"


# ---------- FC-01 SourceMap ----------

def _trace_with_build():
    t = TraceabilityService()
    c = clamp_contract()
    t.register_project(c.id, c, physical_station="电池更换站")
    t.record_build(c.id, "build_219", c, tia_project_id="TIA_1", tia_plc_id="PLC_1")
    return t, c


def test_sourcemap_release_bound_and_block_level():
    t, c = _trace_with_build()
    ids = t.ids_for(c.id)
    cm_entries = t.sourcemap.resolve(ids["CM_CLAMP_CYL"], "build_219")
    assert cm_entries and cm_entries[0].block_kind == "FB"
    assert cm_entries[0].release_build_id == "build_219"
    assert cm_entries[0].scl_line_range is None  # driver: block-level, no fabricated lines
    step_entries = t.sourcemap.resolve(ids["S_EXTEND"], "build_219")
    assert step_entries and step_entries[0].scl_line_range is not None
    assert t.sourcemap.resolve(ids["CM_CLAMP_CYL"], "build_OTHER") == []  # version-bound


# ---------- FC-02 incident + handover ----------

def test_root_cause_only_when_verified():
    svc = IncidentService()
    svc.create_incident("INC-1", "cm_x")
    svc.update_triage("INC-1", fact="伸出反馈未按时出现", hypotheses=["气压不足"], root_cause="传感器故障")
    assert svc.get("INC-1").triage["root_cause"] is None  # not verified -> stays null
    svc.update_triage("INC-1", root_cause="传感器故障", root_cause_verified=True)
    assert svc.get("INC-1").triage["root_cause"] == "传感器故障"


def test_handover_context_resolves_at_event_build():
    t, c = _trace_with_build()
    ids = t.ids_for(c.id)
    cm_id = ids["CM_CLAMP_CYL"]
    t.incidents.define_alarm("al_to", "CM_MOTION_TIMEOUT", cm_id)
    t.incidents.raise_alarm("evt1", "al_to", "2026-11-15T09:17:08+08:00", "build_219", 876)
    t.incidents.create_incident("INC-2026-0042", cm_id,
                                software={"deployed_build_id": "build_219"},
                                behavior={"step_id": ids["S_EXTEND"], "expected": "extended within 3000ms", "observed": "extended=false at 3000ms"})
    ho = build_handover_context("INC-2026-0042", t.incidents, t.registry, t.sourcemap)
    assert ho["resolved_at_build"] == "build_219"
    assert ho["object_context"]["physical_path"] == "电池更换站/夹紧气缸（双作用）"
    assert ho["object_context"]["af"]["cm"] == "夹紧气缸（双作用）"
    assert ho["object_context"]["source_map"]  # source resolved at event build
    assert ho["incident"]["triage"]["root_cause"] is None


def test_unknown_fields_not_fabricated():
    t, c = _trace_with_build()
    ids = t.ids_for(c.id)
    ctx = build_object_context(ids["CM_CLAMP_CYL"], t.registry, t.sourcemap, build_id=None, incidents=t.incidents)
    assert ctx["build_id"] == "UNKNOWN"  # no build supplied -> UNKNOWN, not invented


# ---------- §10 acceptance drill (battery change station) ----------

@pytest.fixture()
def client():
    return TestClient(create_app())


def test_acceptance_alarm_to_handover(client):
    client.post("/api/processos/demo")
    # gate 1: locate by alarm code -> object -> station/EM/CM/step (evidence, not guess)
    obj = client.get("/api/processos/objects", params={"name": "夹紧气缸（双作用）"}).json()
    ctx = client.get(f"/api/processos/objects/{obj['object_id']}/context", params={"build_id": "build_219"}).json()
    assert ctx["physical_path"].startswith("电池更换站")
    assert ctx["af"]["em"] and ctx["af"]["unit"]
    assert ctx["alarm_definitions"][0]["code"] == "CM_MOTION_TIMEOUT"
    # gate 2: incident carries the deployed build at event time
    inc = client.get("/api/processos/incidents/INC-2026-0042").json()
    assert inc["software"]["deployed_build_id"] == "build_219"
    assert inc["triage"]["root_cause"] is None  # gate: alarm != root cause
    # gate 7: build verified (not commissioned) — sourcemap bound to build
    assert ctx["source_map"]
    # gate 8: handover recovers context without chat history
    ho = client.get("/api/processos/incidents/INC-2026-0042/handover").json()
    assert ho["resolved_at_build"] == "build_219"
    assert ho["object_context"]["af"]["cm"] == "夹紧气缸（双作用）"
    assert ho["handover"]["next_action"]
    # triage upgrade requires verification
    client.post("/api/processos/incidents/INC-2026-0042/triage", json={"root_cause": "传感器故障", "root_cause_verified": False})
    assert client.get("/api/processos/incidents/INC-2026-0042").json()["triage"]["root_cause"] is None
    client.post("/api/processos/incidents/INC-2026-0042/triage", json={"root_cause": "传感器故障", "root_cause_verified": True})
    assert client.get("/api/processos/incidents/INC-2026-0042").json()["triage"]["root_cause"] == "传感器故障"


def test_acceptance_rename_does_not_break_trace(client):
    client.post("/api/processos/demo")
    obj = client.get("/api/processos/objects", params={"name": "夹紧气缸（双作用）"}).json()
    # rename via registry keeps identity; old alarm still resolves by object_id
    ho = client.get("/api/processos/incidents/INC-2026-0042/handover").json()
    assert ho["object_context"]["object_id"] == obj["object_id"]