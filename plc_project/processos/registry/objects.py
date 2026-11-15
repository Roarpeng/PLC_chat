"""FC-00 · Object Registry + four graphs + stable, non-reusable object_id.

Identity is a permanent object_id, never a path string. Display names, station
order, canvas coordinates and TIA block names may change; renames keep alias
history. Four graphs (Physical / Af / Behavior / Evidence) are separate models
unified by reference. Historical alarms resolve against the deployed version at
event time, not the current version.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from processos.store import JsonDao

# Crockford base32 ULID: 48-bit time + 80-bit randomness, time-ordered, unique.
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid() -> str:
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rnd = int.from_bytes(os.urandom(10), "big")
    val = (ts << 80) | rnd
    chars = []
    for _ in range(26):
        chars.append(_B32[val & 31])
        val >>= 5
    return "".join(reversed(chars))


def new_object_id(prefix: str) -> str:
    return f"{prefix}_{_ulid()}"


#: Graph membership by object kind.
GRAPH_KINDS: dict[str, set[str]] = {
    "PhysicalGraph": {"site", "machine", "station", "cabinet", "assembly", "component"},
    "AfGraph": {"af_unit", "af_em", "af_cm", "af_job", "af_controlnodes", "af_sequence", "library_ref"},
    "BehaviorGraph": {"behavior_step", "transition", "guard", "action", "interlock", "timeout", "recovery"},
    "EvidenceGraph": {"incident", "alarm_def", "alarm_event", "changeset", "test", "build", "deployment", "sourcemap"},
}

RELATIONS = ("maps_to", "participates_in", "compiles_to", "originates_from", "raised_at", "modifies", "part_of")


def graph_of(kind: str) -> str:
    for g, kinds in GRAPH_KINDS.items():
        if kind in kinds:
            return g
    return "EvidenceGraph"


@dataclass
class Object:
    object_id: str
    kind: str
    display_name: str = ""
    aliases: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "DESIGNED"
    created_at: float = field(default_factory=time.time)
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def graph(self) -> str:
        return graph_of(self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id, "kind": self.kind, "graph": self.graph,
            "display_name": self.display_name, "aliases": list(self.aliases),
            "attributes": dict(self.attributes), "status": self.status,
            "created_at": self.created_at, "history": list(self.history),
        }


@dataclass
class Relationship:
    from_id: str
    relation: str
    to_id: str
    version: int = 1
    valid_from: float = field(default_factory=time.time)
    record_id: str = ""  # persistence key; empty for ad-hoc, unpersisted edges

    def to_dict(self) -> dict[str, Any]:
        return {"from_id": self.from_id, "relation": self.relation, "to_id": self.to_id,
                "version": self.version, "valid_from": self.valid_from}


def object_from_dict(data: dict[str, Any]) -> Object:
    """Rebuild an Object from its persisted dict; object_id is restored, never reminted."""
    return Object(
        object_id=data["object_id"], kind=data["kind"],
        display_name=data.get("display_name", ""),
        aliases=list(data.get("aliases") or []),
        attributes=dict(data.get("attributes") or {}),
        status=data.get("status", "DESIGNED"),
        created_at=data.get("created_at", time.time()),
        history=list(data.get("history") or []),
    )


def relationship_from_dict(data: dict[str, Any]) -> Relationship:
    """Rebuild a Relationship from its persisted dict (record_id included)."""
    return Relationship(
        from_id=data["from_id"], relation=data["relation"], to_id=data["to_id"],
        version=data.get("version", 1), valid_from=data.get("valid_from", time.time()),
        record_id=data.get("record_id", ""),
    )


def relationship_payload(seq: int, rel: Relationship, record_id: str) -> dict[str, Any]:
    """Persist payload for an edge; ``seq`` preserves insertion order across restarts."""
    return {"seq": seq, **rel.to_dict(), "record_id": record_id}


class ObjectRegistry:
    """In-memory object store + relationship index with optional write-through SQLite.

    Default (no ``dao``) stays pure memory. With a ``dao``, the constructor
    restores prior state from the archive and every mutation writes through;
    restored objects keep their original object_id (ULIDs are never regenerated).
    """

    def __init__(self, dao: JsonDao | None = None) -> None:
        self._objects: dict[str, Object] = {}
        self._rels: list[Relationship] = []
        self._dao = dao
        self._rel_dao = JsonDao(dao.conn, "registry_relations") if dao is not None else None
        if dao is not None:
            for row in dao.list_by_kind("object"):
                obj = object_from_dict(row)
                self._objects[obj.object_id] = obj
        if self._rel_dao is not None:
            for row in sorted(self._rel_dao.list_by_kind("relationship"),
                              key=lambda r: r.get("seq", 0)):
                self._rels.append(relationship_from_dict(row))

    def register(self, kind: str, display_name: str = "", attributes: dict[str, Any] | None = None,
                 object_id: str | None = None, status: str = "DESIGNED") -> Object:
        prefix = kind.split("_")[0]
        oid = object_id or new_object_id(prefix)
        if oid in self._objects:
            raise ValueError(f"object_id reuse forbidden: {oid}")
        obj = Object(object_id=oid, kind=kind, display_name=display_name,
                     attributes=attributes or {}, status=status)
        self._objects[oid] = obj
        self._put_object(obj)
        return obj

    def get(self, object_id: str) -> Object | None:
        return self._objects.get(object_id)

    def rename(self, object_id: str, new_name: str) -> Object:
        obj = self._objects[object_id]
        if obj.display_name and obj.display_name != new_name:
            obj.aliases.append(obj.display_name)
            obj.history.append({"event": "rename", "from": obj.display_name, "to": new_name, "at": time.time()})
        obj.display_name = new_name
        self._put_object(obj)
        return obj

    def set_status(self, object_id: str, status: str) -> Object:
        obj = self._objects[object_id]
        obj.history.append({"event": "status", "from": obj.status, "to": status, "at": time.time()})
        obj.status = status
        self._put_object(obj)
        return obj

    def relate(self, from_id: str, relation: str, to_id: str, version: int = 1) -> Relationship:
        if relation not in RELATIONS:
            raise ValueError(f"unknown relation {relation!r}")
        if from_id not in self._objects or to_id not in self._objects:
            raise ValueError("relationship endpoints must be registered objects")
        rel = Relationship(from_id=from_id, relation=relation, to_id=to_id, version=version,
                           record_id=new_object_id("rel"))
        self._rels.append(rel)
        if self._rel_dao is not None:
            self._rel_dao.put(rel.record_id, "relationship",
                              relationship_payload(len(self._rels) - 1, rel, rel.record_id))
        return rel

    def _put_object(self, obj: Object) -> None:
        if self._dao is not None:
            self._dao.put(obj.object_id, "object", obj.to_dict())

    def neighbors(self, object_id: str, relation: str | None = None, direction: str = "out") -> list[Object]:
        out = []
        for r in self._rels:
            if relation and r.relation != relation:
                continue
            if direction == "out" and r.from_id == object_id:
                out.append(self._objects[r.to_id])
            elif direction == "in" and r.to_id == object_id:
                out.append(self._objects[r.from_id])
            elif direction == "both" and object_id in (r.from_id, r.to_id):
                other = r.to_id if r.from_id == object_id else r.from_id
                out.append(self._objects[other])
        return out

    def relationships(self, object_id: str | None = None) -> list[Relationship]:
        if object_id is None:
            return list(self._rels)
        return [r for r in self._rels if object_id in (r.from_id, r.to_id)]

    def by_kind(self, kind: str) -> list[Object]:
        return [o for o in self._objects.values() if o.kind == kind]

    def graph(self, name: str) -> list[Object]:
        kinds = GRAPH_KINDS.get(name, set())
        return [o for o in self._objects.values() if o.kind in kinds]

    def find_by_name(self, name: str) -> Object | None:
        for o in self._objects.values():
            if o.display_name == name or name in o.aliases:
                return o
        return None

    def all_objects(self) -> list[Object]:
        return list(self._objects.values())


def register_contract(registry: ObjectRegistry, contract: Any, physical_station: str | None = None) -> dict[str, str]:
    """Bridge a ProcessContract into the registry: Unit/EM/CM/Step + relations.

    Returns a map of contract-local id -> stable object_id. A physical station,
    if given, is registered and mapped to its CMs (PhysicalGraph maps_to AfGraph).
    """
    ids: dict[str, str] = {}
    unit = registry.register("af_unit", contract.unit, {"name": contract.unit})
    ids[contract.unit] = unit.object_id
    station_obj = None
    if physical_station:
        station_obj = registry.register("station", physical_station, {"name": physical_station})
        ids["station:" + physical_station] = station_obj.object_id

    for op in contract.operations:
        em = registry.register("af_em", op.name or op.em, {"em": op.em, "unit": contract.unit})
        ids[op.em] = em.object_id
        registry.relate(em.object_id, "part_of", unit.object_id)
        for rid in op.resource_ids:
            res = contract.resource(rid)
            if res is None:
                continue
            cm = registry.register("af_cm", res.name or res.id,
                                   {"cm": res.id, "kind": res.kind, "commands": res.commands,
                                    "feedback": res.feedback, "driver_contract": res.kind})
            ids[rid] = cm.object_id
            registry.relate(cm.object_id, "part_of", em.object_id)
            if station_obj is not None:
                comp = registry.register("component", res.name or res.id, {"cm": res.id})
                ids["component:" + rid] = comp.object_id
                registry.relate(comp.object_id, "part_of", station_obj.object_id)
                registry.relate(comp.object_id, "maps_to", cm.object_id)
        for st in op.steps:
            step = registry.register("behavior_step", st.name or st.id,
                                     {"step": st.id, "guard": st.guard, "em": op.em,
                                      "timeout_ms": st.timeout_ms, "is_fault": st.is_fault})
            ids[st.id] = step.object_id
            registry.relate(step.object_id, "part_of", em.object_id)
            for a in st.entry + st.exit:
                if a.target in ids:
                    registry.relate(step.object_id, "participates_in", ids[a.target])
    return ids