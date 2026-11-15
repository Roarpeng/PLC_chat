"""SQLite persistence for the traceability stack (PLAN §7 handover guarantee).

``attach_persistence`` archives a TraceabilityService's current state into the
shared ``records`` store and swaps its sub-services to write-through SQLite, so
a process restart restores objects, relationships, SourceMap entries, alarms,
events, incidents and project id maps exactly as archived — stable object IDs,
review records and incident access survive engineer handover. ULIDs are
restored from the archive, never regenerated. Attaching is idempotent: the same
state upserts without duplicates or errors.

Namespaces (one generic ``records`` table, no SQL text ever assembled):
``registry_objects`` / ``registry_relations`` / ``sourcemap`` / ``incidents`` /
``alarms`` / ``alarm_events`` / ``project_ids``.
"""
from __future__ import annotations

import os

from processos.incident import IncidentService
from processos.registry import ObjectRegistry
from processos.registry.objects import new_object_id, relationship_payload
from processos.sourcemap import SourceMapRegistry
from processos.store import JsonDao, open_db
from processos.traceability import TraceabilityService

NS_OBJECTS = "registry_objects"
NS_RELATIONS = "registry_relations"
NS_SOURCEMAP = "sourcemap"
NS_INCIDENTS = "incidents"
NS_ALARMS = "alarms"
NS_ALARM_EVENTS = "alarm_events"
NS_PROJECT_IDS = "project_ids"


def attach_persistence(trace: TraceabilityService,
                       db_path: str | os.PathLike[str]) -> TraceabilityService:
    """Archive ``trace``'s state, then swap its sub-services to SQLite write-through.

    Existing in-memory state is upserted first, so one call both persists a
    running service and restores a fresh one from disk. Sub-services are
    REPLACED (hold the facade, not its children); object ids are restored as
    archived. Idempotent for identical state. Close the store with
    :func:`close_persistence` (required before temp-dir cleanup on Windows).
    """
    conn = open_db(db_path)
    obj_dao = JsonDao(conn, NS_OBJECTS)
    rel_dao = JsonDao(conn, NS_RELATIONS)
    sm_dao = JsonDao(conn, NS_SOURCEMAP)
    inc_dao = JsonDao(conn, NS_INCIDENTS)
    alarm_dao = JsonDao(conn, NS_ALARMS)
    evt_dao = JsonDao(conn, NS_ALARM_EVENTS)
    proj_dao = JsonDao(conn, NS_PROJECT_IDS)

    _archive_registry(trace, obj_dao, rel_dao)
    _archive_sourcemap(trace, sm_dao)
    _archive_incidents(trace, inc_dao, alarm_dao, evt_dao)
    for project_id, ids in trace._ids.items():
        proj_dao.put(project_id, "project_ids", {"ids": ids})

    trace.registry = ObjectRegistry(dao=obj_dao)
    trace.sourcemap = SourceMapRegistry(dao=sm_dao)
    trace.incidents = IncidentService(dao=inc_dao)
    for row in proj_dao.list_by_kind("project_ids"):
        trace._ids[row["id"]] = dict(row.get("ids") or {})
    trace._ids_dao = proj_dao
    trace._store_conn = conn
    return trace


def close_persistence(trace: TraceabilityService) -> None:
    """Close the store connection attached to ``trace``; in-memory state stays readable.

    Call before removing the database directory (Windows holds open files).
    Mutations after close raise; re-attach to continue with write-through.
    """
    conn = trace._store_conn
    if conn is not None:
        conn.close()
        trace._store_conn = None
        trace._ids_dao = None


def _archive_registry(trace: TraceabilityService, obj_dao: JsonDao, rel_dao: JsonDao) -> None:
    for obj in trace.registry.all_objects():
        obj_dao.put(obj.object_id, "object", obj.to_dict())
    for seq, rel in enumerate(trace.registry.relationships()):
        rid = rel.record_id or new_object_id("rel")
        rel_dao.put(rid, "relationship", relationship_payload(seq, rel, rid))


def _archive_sourcemap(trace: TraceabilityService, sm_dao: JsonDao) -> None:
    for entry in trace.sourcemap.all_entries():
        sm_dao.put(entry.source_map_id, "sourcemap", entry.to_dict())


def _archive_incidents(trace: TraceabilityService, inc_dao: JsonDao,
                       alarm_dao: JsonDao, evt_dao: JsonDao) -> None:
    for d in trace.incidents.all_alarm_definitions():
        alarm_dao.put(d.definition_id, "alarm_def", d.to_dict())
    for e in trace.incidents.all_alarm_events():
        evt_dao.put(e.event_id, "alarm_event", e.to_dict())
    for inc in trace.incidents.all_incidents():
        inc_dao.put(inc.incident_id, "incident", inc.to_dict())
