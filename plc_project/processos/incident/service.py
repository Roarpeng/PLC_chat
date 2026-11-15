"""FC-02 · Incident / AlarmMap + cross-engineer handover context.

An alarm locates an object; it does not prove a root cause. Triage keeps
observed fact, candidate hypotheses and a root_cause that stays null until
human/instrument verification. Unknown fields are UNKNOWN, never fabricated.
Historical alarms resolve against the deployed build at event time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from processos.registry import ObjectRegistry
from processos.sourcemap import SourceMapRegistry
from processos.store import JsonDao

UNKNOWN = "UNKNOWN"


@dataclass
class AlarmDefinition:
    definition_id: str
    code: str
    originates_from: str  # object_id (CM/EM)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"definition_id": self.definition_id, "code": self.code,
                "originates_from": self.originates_from, "description": self.description}


@dataclass
class AlarmEvent:
    event_id: str
    definition_id: str
    event_time: str
    deployed_build_id: str
    sequence: int = 0
    quality: str = "OBSERVED"  # OBSERVED | REPORTED | INFERRED

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "definition_id": self.definition_id,
                "event_time": self.event_time, "deployed_build_id": self.deployed_build_id,
                "sequence": self.sequence, "quality": self.quality}


@dataclass
class Incident:
    incident_id: str
    object_id: str
    asset_id: str = UNKNOWN
    physical_path_at_event: str = UNKNOWN
    af_refs: dict[str, str] = field(default_factory=dict)
    alarm: dict[str, Any] = field(default_factory=dict)
    behavior: dict[str, Any] = field(default_factory=dict)
    software: dict[str, Any] = field(default_factory=dict)
    references: dict[str, Any] = field(default_factory=dict)
    triage: dict[str, Any] = field(default_factory=lambda: {"fact": "", "hypotheses": [], "root_cause": None})
    handover: dict[str, Any] = field(default_factory=lambda: {"owner": UNKNOWN, "status": "OPEN", "next_action": ""})
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id, "object_id": self.object_id, "asset_id": self.asset_id,
            "physical_path_at_event": self.physical_path_at_event, "af_refs": dict(self.af_refs),
            "alarm": dict(self.alarm), "behavior": dict(self.behavior), "software": dict(self.software),
            "references": dict(self.references), "triage": dict(self.triage),
            "handover": dict(self.handover), "created_at": self.created_at,
        }


def alarm_definition_from_dict(data: dict[str, Any]) -> AlarmDefinition:
    return AlarmDefinition(
        definition_id=data["definition_id"], code=data["code"],
        originates_from=data["originates_from"], description=data.get("description", ""),
    )


def alarm_event_from_dict(data: dict[str, Any]) -> AlarmEvent:
    return AlarmEvent(
        event_id=data["event_id"], definition_id=data["definition_id"],
        event_time=data["event_time"], deployed_build_id=data["deployed_build_id"],
        sequence=data.get("sequence", 0), quality=data.get("quality", "OBSERVED"),
    )


def incident_from_dict(data: dict[str, Any]) -> Incident:
    return Incident(
        incident_id=data["incident_id"], object_id=data["object_id"],
        asset_id=data.get("asset_id", UNKNOWN),
        physical_path_at_event=data.get("physical_path_at_event", UNKNOWN),
        af_refs=dict(data.get("af_refs") or {}),
        alarm=dict(data.get("alarm") or {}),
        behavior=dict(data.get("behavior") or {}),
        software=dict(data.get("software") or {}),
        references=dict(data.get("references") or {}),
        triage=dict(data.get("triage") or {}),
        handover=dict(data.get("handover") or {}),
        created_at=data.get("created_at", time.time()),
    )


class IncidentService:
    """Alarm definitions/events + incidents; optional write-through SQLite.

    Default (no ``dao``) stays pure memory. With a ``dao`` (incidents namespace),
    the constructor restores prior state and every mutation writes through.
    """

    def __init__(self, dao: JsonDao | None = None) -> None:
        self._defs: dict[str, AlarmDefinition] = {}
        self._events: dict[str, AlarmEvent] = {}
        self._incidents: dict[str, Incident] = {}
        self._dao = dao  # incidents namespace
        self._alarm_dao = JsonDao(dao.conn, "alarms") if dao is not None else None
        self._event_dao = JsonDao(dao.conn, "alarm_events") if dao is not None else None
        if self._alarm_dao is not None:
            for row in self._alarm_dao.list_by_kind("alarm_def"):
                d = alarm_definition_from_dict(row)
                self._defs[d.definition_id] = d
            for row in self._event_dao.list_by_kind("alarm_event"):
                e = alarm_event_from_dict(row)
                self._events[e.event_id] = e
        if dao is not None:
            for row in dao.list_by_kind("incident"):
                inc = incident_from_dict(row)
                self._incidents[inc.incident_id] = inc

    def define_alarm(self, definition_id: str, code: str, originates_from: str, description: str = "") -> AlarmDefinition:
        d = AlarmDefinition(definition_id, code, originates_from, description)
        self._defs[definition_id] = d
        if self._alarm_dao is not None:
            self._alarm_dao.put(definition_id, "alarm_def", d.to_dict())
        return d

    def raise_alarm(self, event_id: str, definition_id: str, event_time: str, deployed_build_id: str,
                    sequence: int = 0, quality: str = "OBSERVED") -> AlarmEvent:
        if definition_id not in self._defs:
            raise ValueError(f"unknown alarm definition {definition_id}")
        e = AlarmEvent(event_id, definition_id, event_time, deployed_build_id, sequence, quality)
        self._events[event_id] = e
        if self._event_dao is not None:
            self._event_dao.put(event_id, "alarm_event", e.to_dict())
        return e

    def create_incident(self, incident_id: str, object_id: str, **kw: Any) -> Incident:
        inc = Incident(incident_id=incident_id, object_id=object_id, **kw)
        self._incidents[incident_id] = inc
        if self._dao is not None:
            self._dao.put(incident_id, "incident", inc.to_dict())
        return inc

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def all_incidents(self) -> list[Incident]:
        return list(self._incidents.values())

    def update_triage(self, incident_id: str, fact: str | None = None,
                      hypotheses: list[str] | None = None, root_cause: str | None = None,
                      root_cause_verified: bool = False) -> Incident:
        inc = self._incidents[incident_id]
        if fact is not None:
            inc.triage["fact"] = fact
        if hypotheses is not None:
            inc.triage["hypotheses"] = hypotheses
        if root_cause is not None:
            # root cause only upgrades from null when explicitly verified
            inc.triage["root_cause"] = root_cause if root_cause_verified else None
            inc.triage["root_cause_verified"] = root_cause_verified
        if self._dao is not None:
            self._dao.put(incident_id, "incident", inc.to_dict())
        return inc

    def set_handover(self, incident_id: str, owner: str, status: str, next_action: str) -> Incident:
        inc = self._incidents[incident_id]
        inc.handover = {"owner": owner, "status": status, "next_action": next_action}
        if self._dao is not None:
            self._dao.put(incident_id, "incident", inc.to_dict())
        return inc

    def alarm_def(self, definition_id: str) -> AlarmDefinition | None:
        return self._defs.get(definition_id)

    def events_for_build(self, build_id: str) -> list[AlarmEvent]:
        return [e for e in self._events.values() if e.deployed_build_id == build_id]

    def all_alarm_definitions(self) -> list[AlarmDefinition]:
        return list(self._defs.values())

    def all_alarm_events(self) -> list[AlarmEvent]:
        return list(self._events.values())


def _physical_path(obj_id: str, registry: ObjectRegistry) -> str:
    parts: list[str] = []
    cur = registry.get(obj_id)
    seen = set()
    while cur is not None and cur.object_id not in seen:
        seen.add(cur.object_id)
        if cur.kind in ("component", "assembly", "station", "machine", "site", "cabinet"):
            parts.append(cur.display_name or cur.object_id)
        parents = registry.neighbors(cur.object_id, "part_of", "out")
        cur = parents[0] if parents else None
    return "/".join(reversed(parts)) if parts else UNKNOWN


def build_object_context(object_id: str, registry: ObjectRegistry, sourcemap: SourceMapRegistry,
                         build_id: str | None = None, incidents: IncidentService | None = None) -> dict[str, Any]:
    """Aggregate physical / AF / behavior / source / alarm context for an object."""
    obj = registry.get(object_id)
    if obj is None:
        return {"object_id": object_id, "found": False}

    af: dict[str, Any] = {}
    if obj.kind == "af_cm":
        ems = registry.neighbors(object_id, "part_of", "out")
        if ems:
            af["em"] = ems[0].display_name
            units = registry.neighbors(ems[0].object_id, "part_of", "out")
            if units:
                af["unit"] = units[0].display_name
        af["cm"] = obj.display_name
    elif obj.kind == "behavior_step":
        ems = registry.neighbors(object_id, "part_of", "out")
        if ems:
            af["em"] = ems[0].display_name
        af["step"] = obj.display_name
    elif obj.kind == "component":
        cms = registry.neighbors(object_id, "maps_to", "out")
        if cms:
            af["cm"] = cms[0].display_name

    behavior = [s.to_dict() for s in registry.neighbors(object_id, "participates_in", "in")]
    source = [e.to_dict() for e in sourcemap.resolve(object_id, build_id)]
    alarms = []
    if incidents is not None:
        alarms = [d.to_dict() for d in incidents._defs.values() if d.originates_from == object_id]

    # AF objects resolve physical location via the component that maps_to them.
    phys_id = object_id
    if obj.graph == "AfGraph":
        comps = registry.neighbors(object_id, "maps_to", "in")
        if comps:
            phys_id = comps[0].object_id
    physical_path = _physical_path(phys_id, registry)

    return {
        "object_id": object_id, "found": True, "kind": obj.kind, "graph": obj.graph,
        "display_name": obj.display_name, "aliases": obj.aliases, "status": obj.status,
        "physical_path": physical_path,
        "af": af, "behavior": behavior, "source_map": source, "alarm_definitions": alarms,
        "history": obj.history, "build_id": build_id or UNKNOWN,
    }


def build_handover_context(incident_id: str, incidents: IncidentService, registry: ObjectRegistry,
                           sourcemap: SourceMapRegistry) -> dict[str, Any]:
    """The transferable package: a new engineer recovers context without chat history."""
    inc = incidents.get(incident_id)
    if inc is None:
        return {"incident_id": incident_id, "found": False}
    build_id = inc.software.get("deployed_build_id") or None
    context = build_object_context(inc.object_id, registry, sourcemap, build_id, incidents)
    recent_changes = [o.to_dict() for o in registry.graph("EvidenceGraph") if o.kind == "changeset"][-3:]
    return {
        "incident": inc.to_dict(),
        "resolved_at_build": build_id or UNKNOWN,
        "object_context": context,
        "recent_changes": recent_changes,
        "triage_note": "观测事实与候选原因不等于已验证根因；root_cause 仅在人工/仪器确认后升级。",
        "handover": inc.handover,
    }