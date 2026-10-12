"""Knowledge graph adapter — in-memory default, optional Neo4j."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from knowledge.models import Entity, Relation
from knowledge.retrieval.filters import payload_matches_filters
from knowledge.settings import KnowledgeSettings, get_settings

logger = logging.getLogger("researchos.knowledge.graph")

_NEO4J_PRIMITIVES = (str, int, float, bool)

# Typed node labels / relationship types (docs/knowledge/04-entity-and-schema.md).
_ENTITY_TYPES = {
    "Product",
    "Feature",
    "Specification",
    "PainPoint",
    "Review",
    "News",
    "Company",
    "Patent",
    "Document",
    "Chunk",
    "Standard",
    "Version",
}

_RELATION_TYPES = {
    "HAS_FEATURE",
    "COMPARES",
    "REFERENCES",
    "UPDATED_BY",
    "PRODUCED_BY",
}


def _safe_label(entity_type: str | None, key: str = "") -> str:
    """Resolve a typed node label from an entity type or canonical_key prefix.

    Falls back to the generic ``Entity`` label when the type is unknown, so
    non-whitelisted callers keep working (back-compat).
    """
    if entity_type and entity_type in _ENTITY_TYPES:
        return entity_type
    prefix = key.split(":", 1)[0] if ":" in key else ""
    for known in _ENTITY_TYPES:
        if known.lower() == prefix.lower():
            return known
    return "Entity"


def _safe_rel_type(rel_type: str | None) -> str:
    if rel_type and rel_type in _RELATION_TYPES:
        return rel_type
    return "RELATED"


def _node_merge_clause(var: str, key: str, entity_type: str | None) -> str:
    """Build a MERGE clause for a node (typed label, chunk-aware key)."""
    label = _safe_label(entity_type, key)
    if label == "Chunk":
        return f"MERGE ({var}:Chunk {{chunk_id: $p_{var}}})"
    return f"MERGE ({var}:{label} {{canonical_key: $p_{var}}})"


def neo4j_safe_properties(props: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce property maps to Neo4j-legal values (primitives or arrays thereof).

    Nested dicts / lists-of-dicts become JSON strings. ``None`` is omitted.
    """
    if not props:
        return {}
    out: dict[str, Any] = {}
    for key, value in props.items():
        if value is None:
            continue
        out[str(key)] = _neo4j_safe_value(value)
    return out


def _neo4j_safe_value(value: Any) -> Any:
    if isinstance(value, _NEO4J_PRIMITIVES):
        return value
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, default=str)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
        if not items:
            return []
        if all(isinstance(x, _NEO4J_PRIMITIVES) for x in items) and _neo4j_homogeneous(items):
            return items
        return json.dumps(items, ensure_ascii=False, default=str)
    return json.dumps(value, ensure_ascii=False, default=str)


def _neo4j_homogeneous(items: list[Any]) -> bool:
    kinds = {type(x) for x in items}
    return len(kinds) == 1 or kinds <= {int, float}


@dataclass
class GraphHit:
    chunk_id: str
    score: float
    paths: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


class KnowledgeGraph(Protocol):
    def upsert_entities(self, entities: list[Entity]) -> int: ...

    def upsert_relations(self, relations: list[Relation]) -> int: ...

    def query(
        self,
        query: str,
        *,
        template: str | None = None,
        params: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]: ...

    def search_chunks(self, query: str, top_k: int = 10) -> list[GraphHit]: ...


class InMemoryKnowledgeGraph:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.relations: list[Relation] = []
        self.chunks: dict[str, dict[str, Any]] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self._chunk_links: dict[str, set[str]] = {}

    def clear(self) -> None:
        self.entities.clear()
        self.relations.clear()
        self.chunks.clear()
        self.payloads.clear()
        self._chunk_links.clear()

    def register_payloads(self, payloads: dict[str, dict[str, Any]]) -> None:
        for cid, p in payloads.items():
            self.payloads[str(cid)] = p

    def _materialize_node(self, key: str, node_type: str | None) -> None:
        """Ensure a referenced non-Chunk node exists (Neo4j MERGE parity)."""
        if node_type == "Chunk":
            self.chunks.setdefault(str(key), {"chunk_id": str(key), "type": "Chunk"})
            return
        if str(key) in self.entities:
            return
        label = _safe_label(node_type, str(key))
        if label == "Entity":
            return
        self.entities[str(key)] = Entity(
            type=label,
            canonical_key=str(key),
            name=str(key),
            properties={},
        )

    def upsert_entities(self, entities: list[Entity]) -> int:
        for e in entities:
            existing = self.entities.get(e.canonical_key)
            if existing:
                # Merge on (type, name) — canonical_key already encodes both.
                existing.properties.update(e.properties)
                existing.name = e.name or existing.name
                if e.type:
                    existing.type = e.type
            else:
                self.entities[e.canonical_key] = e
        return len(entities)

    def upsert_relations(self, relations: list[Relation]) -> int:
        n = 0
        for r in relations:
            self.relations.append(r)
            self._materialize_node(r.from_key, r.from_type)
            self._materialize_node(r.to_key, r.to_type)
            chunk_id = (r.properties or {}).get("chunk_id")
            if chunk_id:
                self._chunk_links.setdefault(str(chunk_id), set()).add(r.from_key)
                self._chunk_links.setdefault(str(chunk_id), set()).add(r.to_key)
            n += 1
        return n

    def upsert(self, entities: list[Entity], relations: list[Relation]) -> dict[str, int]:
        return {
            "entities": self.upsert_entities(entities),
            "relations": self.upsert_relations(relations),
        }

    def query(
        self,
        query: str,
        *,
        template: str | None = None,
        params: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        params = params or {}
        nodes = list(self.entities.values())
        edges = list(self.relations)
        if template == "product_specs":
            product_key = params.get("product_key")
            edges = [
                r
                for r in edges
                if r.type == "HAS_FEATURE" and (not product_key or r.from_key == product_key)
            ]
            keys = {r.from_key for r in edges} | {r.to_key for r in edges}
            nodes = [e for e in nodes if e.canonical_key in keys]
        elif template == "product_compare":
            edges = [r for r in edges if r.type == "COMPARES"]
            keys = {r.from_key for r in edges} | {r.to_key for r in edges}
            nodes = [e for e in nodes if e.canonical_key in keys]
        elif query:
            q = query.lower()
            nodes = [
                e
                for e in nodes
                if q in e.name.lower() or q in e.canonical_key.lower()
            ][:top_k]
            keys = {e.canonical_key for e in nodes}
            edges = [r for r in edges if r.from_key in keys or r.to_key in keys]
        evidence = sorted(
            {
                str(r.properties.get("chunk_id"))
                for r in edges
                if r.properties.get("chunk_id")
            }
        )
        return {
            "nodes": [e.model_dump() for e in nodes[:top_k]],
            "edges": [r.model_dump() for r in edges[: top_k * 2]],
            "evidence_chunk_ids": evidence[:top_k],
            "chunks": [dict(c) for c in list(self.chunks.values())[:top_k]],
        }

    def search_chunks(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        payloads: dict[str, dict[str, Any]] | None = None,
    ) -> list[GraphHit]:
        pld = dict(self.payloads)
        if payloads:
            pld.update(payloads)
        q = query.lower()
        tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", q))
        scored: dict[str, float] = {}
        paths: dict[str, list[dict[str, Any]]] = {}
        for key, ent in self.entities.items():
            blob = f"{ent.name} {ent.canonical_key}".lower()
            overlap = sum(1 for t in tokens if t and t in blob)
            if overlap == 0 and q not in blob:
                continue
            score = float(overlap) + (1.0 if q in blob else 0.0)
            for chunk_id, linked in self._chunk_links.items():
                if key in linked:
                    scored[chunk_id] = scored.get(chunk_id, 0.0) + score
                    paths.setdefault(chunk_id, []).append(
                        {"entity": key, "type": ent.type, "name": ent.name}
                    )
        # Also rank by relation mentions of product tokens in query
        for rel in self.relations:
            chunk_id = rel.properties.get("chunk_id")
            if not chunk_id:
                continue
            if any(
                t and (t in rel.from_key.lower() or t in rel.to_key.lower()) for t in tokens
            ):
                scored[str(chunk_id)] = scored.get(str(chunk_id), 0.0) + 0.5
                paths.setdefault(str(chunk_id), []).append(
                    {"relation": rel.type, "from": rel.from_key, "to": rel.to_key}
                )
        ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        hits: list[GraphHit] = []
        for cid, score in ranked:
            payload = pld.get(cid, {})
            if filters and not payload_matches_filters(payload, filters):
                continue
            hits.append(
                GraphHit(
                    chunk_id=cid,
                    score=score,
                    paths=paths.get(cid, []),
                    payload=payload,
                )
            )
            if len(hits) >= top_k:
                break
        return hits


class Neo4jKnowledgeGraph:
    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._driver.verify_connectivity()

    def close(self) -> None:
        self._driver.close()

    @staticmethod
    def _batched(rows: list[Any], size: int = 500):
        for start in range(0, len(rows), size):
            yield rows[start : start + size]

    def upsert_entities(self, entities: list[Entity]) -> int:
        with self._driver.session() as session:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for entity in entities:
                label = _safe_label(entity.type, entity.canonical_key)
                grouped.setdefault(label, []).append(
                    {
                        "key": entity.canonical_key,
                        "type": "Chunk" if label == "Chunk" else entity.type,
                        "name": entity.name,
                        "props": neo4j_safe_properties(entity.properties),
                    }
                )
            for label, rows in grouped.items():
                if label == "Chunk":
                    cypher = """
                    UNWIND $rows AS row
                    MERGE (n:Chunk {chunk_id: row.key})
                    SET n.type = row.type, n.name = row.name, n += row.props
                    """
                else:
                    cypher = f"""
                    UNWIND $rows AS row
                    MERGE (n:{label} {{canonical_key: row.key}})
                    SET n.type = row.type, n.name = row.name, n += row.props
                    """
                for batch in self._batched(rows):
                    session.run(cypher, rows=batch)
        return len(entities)

    def upsert_relations(self, relations: list[Relation]) -> int:
        with self._driver.session() as session:
            grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            for relation in relations:
                rtype = _safe_rel_type(relation.type)
                from_label = _safe_label(relation.from_type, relation.from_key)
                to_label = _safe_label(relation.to_type, relation.to_key)
                grouped.setdefault((from_label, to_label, rtype), []).append(
                    {
                        "from": relation.from_key,
                        "to": relation.to_key,
                        "props": neo4j_safe_properties(relation.properties),
                    }
                )
            for (from_label, to_label, rtype), rows in grouped.items():
                cypher = f"""
                UNWIND $rows AS row
                MERGE (a:{from_label} {{canonical_key: row.from}})
                MERGE (b:{to_label} {{canonical_key: row.to}})
                MERGE (a)-[rel:{rtype}]->(b)
                SET rel += row.props
                """
                for batch in self._batched(rows):
                    session.run(cypher, rows=batch)
        return len(relations)

    def query(
        self,
        query: str,
        *,
        template: str | None = None,
        params: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        params = params or {}
        cypher = """
        MATCH (n)
        WHERE (exists(n.type) OR exists(n.chunk_id))
          AND (
            toLower(coalesce(n.name, '')) CONTAINS toLower($q)
            OR toLower(coalesce(n.canonical_key, '')) CONTAINS toLower($q)
            OR toLower(coalesce(n.chunk_id, '')) CONTAINS toLower($q)
          )
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN n, collect(r) as rels, collect(m) as ms
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(cypher, q=query or params.get("product_key", ""), limit=top_k)
            nodes = []
            edges = []
            evidence: list[str] = []
            for record in result:
                n = record["n"]
                n_type = n.get("type") or (list(n.labels)[0] if n.labels else None)
                n_key = n.get("canonical_key") or n.get("chunk_id")
                nodes.append(
                    {
                        "type": n_type,
                        "canonical_key": n_key,
                        "name": n.get("name") or n_key,
                        "properties": dict(n),
                    }
                )
                for r, m in zip(record["rels"], record["ms"]):
                    if r is None or m is None:
                        continue
                    m_type = m.get("type") or (list(m.labels)[0] if m.labels else None)
                    edges.append(
                        {
                            "type": r.type if hasattr(r, "type") else r.get("type"),
                            "from_key": n.get("canonical_key") or n.get("chunk_id"),
                            "to_key": m.get("canonical_key") or m.get("chunk_id"),
                            "from_type": n_type,
                            "to_type": m_type,
                            "properties": dict(r),
                        }
                    )
                    if r.get("chunk_id"):
                        evidence.append(str(r.get("chunk_id")))
        return {
            "nodes": nodes,
            "edges": edges,
            "evidence_chunk_ids": sorted(set(evidence))[:top_k],
            "chunks": [],
        }

    def search_chunks(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        payloads: dict[str, dict[str, Any]] | None = None,
    ) -> list[GraphHit]:
        data = self.query(query, top_k=top_k)
        pld = payloads or {}
        hits = []
        for i, cid in enumerate(data.get("evidence_chunk_ids") or []):
            payload = pld.get(cid, {})
            if filters and not payload_matches_filters(payload, filters):
                continue
            hits.append(
                GraphHit(chunk_id=cid, score=1.0 / (i + 1), paths=[], payload=payload)
            )
            if len(hits) >= top_k:
                break
        return hits


def create_knowledge_graph(settings: KnowledgeSettings | None = None) -> KnowledgeGraph:
    cfg = settings or get_settings()
    if cfg.neo4j_uri and cfg.neo4j_password:
        try:
            kg = Neo4jKnowledgeGraph(cfg.neo4j_uri, cfg.neo4j_user, cfg.neo4j_password)
            logger.info("Using Neo4j at %s", cfg.neo4j_uri)
            return kg
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j unavailable (%s); using in-memory graph", exc)
    return InMemoryKnowledgeGraph()
