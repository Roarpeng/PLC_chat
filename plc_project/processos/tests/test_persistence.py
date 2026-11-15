"""PLAN §7 persistence tests: traceability state survives process restart.

Stable object IDs, review records and incident access must be recoverable from
the SQLite archive after a restart — engineer handover cannot depend on one
person's live process. ULIDs are restored from the archive, never regenerated.
All tests pass explicit ``tmp_path`` db files; connections are closed before
teardown so Windows can release them.
"""
from __future__ import annotations

import pytest

from processos.contract import clamp_contract
from processos.store import open_db
from processos.store.persistence import NS_ALARMS, NS_ALARM_EVENTS, NS_INCIDENTS, NS_OBJECTS, \
    NS_PROJECT_IDS, NS_RELATIONS, NS_SOURCEMAP, attach_persistence, close_persistence
from processos.traceability import TraceabilityService


@pytest.fixture()
def db_file(tmp_path):
    return tmp_path / "trace.sqlite3"


@pytest.fixture()
def attach():
    """attach_persistence that closes every store connection on teardown."""
    attached: list[TraceabilityService] = []

    def _attach(trace: TraceabilityService, db) -> TraceabilityService:
        attach_persistence(trace, db)
        attached.append(trace)
        return trace

    yield _attach
    for trace in attached:
        close_persistence(trace)


def _build_trace() -> tuple[TraceabilityService, object, dict[str, str]]:
    t = TraceabilityService()
    c = clamp_contract()
    t.register_project(c.id, c, physical_station="电池更换站")
    t.record_build(c.id, "build_219", c, tia_project_id="TIA_PRJ_001", tia_plc_id="PLC_1")
    ids = t.ids_for(c.id)
    cm = ids["CM_CLAMP_CYL"]
    t.incidents.define_alarm("alarm_clamp_timeout", "CM_MOTION_TIMEOUT", cm, "伸出到位信号未在规定时间内出现")
    t.incidents.raise_alarm("evt_876", "alarm_clamp_timeout", "2026-11-15T09:17:08+08:00",
                            "build_219", 876, "OBSERVED")
    t.incidents.create_incident(
        "INC-2026-0042", cm,
        software={"deployed_build_id": "build_219"},
        behavior={"step_id": ids["S_EXTEND"], "expected": "extended within 3000ms",
                  "observed": "extended=false at 3000ms"},
        triage={"fact": "伸出反馈未按时出现", "hypotheses": ["气压不足", "线圈未动作"], "root_cause": None},
    )
    t.incidents.update_triage("INC-2026-0042", root_cause="传感器故障", root_cause_verified=True)
    t.incidents.set_handover("INC-2026-0042", "engineer_on_duty", "INVESTIGATING",
                             "检查线圈输出及现场传感器")
    t.registry.rename(cm, "夹紧气缸（改名）")
    return t, c, ids


def _rel_keys(trace):
    return sorted((r.from_id, r.relation, r.to_id, r.version) for r in trace.registry.relationships())


# ---------- restart survival ----------

def test_restart_restores_full_state(attach, db_file):
    t1, c, ids = _build_trace()
    ctx_before = t1.object_context(ids["CM_CLAMP_CYL"], "build_219")
    ho_before = t1.handover("INC-2026-0042")
    objs_before = {o.object_id: o.to_dict() for o in t1.registry.all_objects()}

    attach(t1, db_file)  # first boot: archive + switch to write-through
    t2 = attach(TraceabilityService(), db_file)  # process restart: restore from archive

    # objects restored with the SAME object ids — ULIDs never regenerated
    objs_after = {o.object_id: o.to_dict() for o in t2.registry.all_objects()}
    assert objs_after == objs_before
    assert _rel_keys(t2) == _rel_keys(t1)
    assert t2.ids_for(c.id) == ids
    # SourceMap entries, all fields
    assert [e.to_dict() for e in t2.sourcemap.all_entries()] == [e.to_dict() for e in t1.sourcemap.all_entries()]
    assert t2.sourcemap.resolve(ids["CM_CLAMP_CYL"], "build_219")[0].block_kind == "FB"
    assert t2.sourcemap.resolve(ids["S_EXTEND"], "build_219")[0].scl_line_range is not None
    # alarm definitions, events, incident incl. triage/handover
    assert t2.incidents.alarm_def("alarm_clamp_timeout").to_dict() \
        == t1.incidents.alarm_def("alarm_clamp_timeout").to_dict()
    assert [e.to_dict() for e in t2.incidents.events_for_build("build_219")] \
        == [e.to_dict() for e in t1.incidents.events_for_build("build_219")]
    assert t2.incidents.get("INC-2026-0042").to_dict() == t1.incidents.get("INC-2026-0042").to_dict()
    assert t2.incidents.get("INC-2026-0042").triage["root_cause"] == "传感器故障"
    # rename alias survives: old name still resolves to the same object id
    assert t2.registry.find_by_name("夹紧气缸（双作用）").object_id == ids["CM_CLAMP_CYL"]
    # aggregated context and handover package identical across restart
    assert t2.object_context(ids["CM_CLAMP_CYL"], "build_219") == ctx_before
    assert t2.handover("INC-2026-0042") == ho_before


def test_write_through_after_restart_survives_next_restart(attach, db_file):
    t1, _, ids = _build_trace()
    attach(t1, db_file)
    t2 = attach(TraceabilityService(), db_file)
    # new work on the restored service must itself be durable
    t2.incidents.define_alarm("al_stall", "CM_STALL", ids["CM_CLAMP_CYL"])
    t2.incidents.raise_alarm("evt_900", "al_stall", "2026-11-15T10:00:00+08:00", "build_219")
    t2.incidents.create_incident("INC-2026-0043", ids["CM_CLAMP_CYL"])
    chg = t2.registry.register("changeset", "chg_019", {"title": "超时 3000→5000"})
    t2.registry.relate(chg.object_id, "modifies", ids["CM_CLAMP_CYL"])

    t3 = attach(TraceabilityService(), db_file)
    assert t3.incidents.alarm_def("al_stall") is not None
    assert [e.event_id for e in t3.incidents.events_for_build("build_219")] == ["evt_876", "evt_900"]
    assert t3.incidents.get("INC-2026-0043") is not None
    assert t3.registry.get(chg.object_id) is not None
    assert ids["CM_CLAMP_CYL"] in [o.object_id for o in t3.registry.neighbors(chg.object_id, "modifies", "out")]
    assert t3.ids_for("PRJ_CLAMP") == ids


# ---------- idempotency ----------

def test_attach_same_state_twice_no_duplicates(attach, db_file):
    t1, _, _ = _build_trace()
    attach(t1, db_file)
    n_objects = len(t1.registry.all_objects())
    n_rels = len(t1.registry.relationships())
    n_entries = len(t1.sourcemap.all_entries())

    attach(t1, db_file)  # same state attached again: upsert, no error
    t2 = attach(TraceabilityService(), db_file)
    assert len(t2.registry.all_objects()) == n_objects
    assert len(t2.registry.relationships()) == n_rels
    assert len(t2.sourcemap.all_entries()) == n_entries
    assert len(t2.incidents.all_incidents()) == 1
    assert len(t2.incidents.all_alarm_definitions()) == 1
    assert len(t2.incidents.all_alarm_events()) == 1


# ---------- default stays pure memory ----------

def test_default_without_persistence_is_pure_memory(tmp_path):
    t, c, ids = _build_trace()
    ctx = t.object_context(ids["CM_CLAMP_CYL"], "build_219")
    assert ctx["found"] and ctx["af"]["cm"]
    assert t.incidents.alarm_def("alarm_clamp_timeout").code == "CM_MOTION_TIMEOUT"
    assert t.registry.find_by_name("夹紧气缸（双作用）") is not None
    # no store attached: nothing is written anywhere, services stay isolated
    assert t._store_conn is None and t._ids_dao is None
    assert list(tmp_path.iterdir()) == []
    fresh = TraceabilityService()
    assert fresh.ids_for(c.id) == {}  # no global/hidden state leaked between services


# ---------- storage layout ----------

def test_records_share_one_table_with_expected_namespaces(attach, db_file):
    t1, _, _ = _build_trace()
    attach(t1, db_file)
    conn = open_db(db_file)
    try:
        namespaces = {row[0] for row in conn.execute("SELECT DISTINCT namespace FROM records")}
    finally:
        conn.close()
    assert {NS_OBJECTS, NS_RELATIONS, NS_SOURCEMAP, NS_INCIDENTS,
            NS_ALARMS, NS_ALARM_EVENTS, NS_PROJECT_IDS} <= namespaces
