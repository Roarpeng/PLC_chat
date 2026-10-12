"""Publish PLC-IR knowledge graph into the ResearchOS graph store (Neo4j or memory)."""

from __future__ import annotations

from typing import Any

from agents.plc.tia.kg import PlcKnowledgeGraph
from knowledge.models import Entity, Relation
from knowledge.retrieval.graph import create_knowledge_graph, neo4j_safe_properties


def plc_kg_to_entities_relations(
    kg: PlcKnowledgeGraph,
    *,
    project_key: str,
) -> tuple[list[Entity], list[Relation]]:
    """Map PlcKnowledgeGraph → knowledge Entity/Relation (PLC* types).

    Nested maps (e.g. CALLS ``call_params`` ``{name, data_type, section}``) are
    JSON-stringified so Neo4j ``SET n += $props`` stays within primitive types.
    In-memory ``PlcKnowledgeGraph`` is left unchanged.
    """
    entities: list[Entity] = []
    for node in kg.nodes.values():
        etype = {
            "Project": "PLCProject",
            "Block": "PLCBlock",
            "Tag": "PLCTag",
            "TagTable": "PLCTagTable",
            "Network": "PLCNetwork",
            "Variable": "PLCVariable",
            "Part": "PLCPart",
        }.get(node.type, f"PLC{node.type}")
        name = str(node.props.get("name") or node.id)
        props = neo4j_safe_properties(dict(node.props))
        props["plc_node_type"] = node.type
        props["project_key"] = project_key
        entities.append(
            Entity(
                type=etype,
                canonical_key=f"plc:{project_key}:{node.id}",
                name=name,
                properties=props,
            )
        )

    relations: list[Relation] = []
    for edge in kg.edges:
        relations.append(
            Relation(
                type=edge.type,
                from_key=f"plc:{project_key}:{edge.source}",
                to_key=f"plc:{project_key}:{edge.target}",
                from_type="PLC",
                to_type="PLC",
                properties=neo4j_safe_properties(
                    {**dict(edge.props), "chunk_id": f"plc:{project_key}"}
                ),
            )
        )
    return entities, relations


def publish_plc_knowledge_graph(
    kg: PlcKnowledgeGraph,
    *,
    project_name: str = "",
) -> dict[str, Any]:
    """Upsert PLC graph into configured KnowledgeGraph backend.

    Uses Neo4j when NEO4J_URI+password are set; otherwise in-memory registry.
    Bypasses research-domain MCP whitelist (called from PLC tools directly).
    """
    project_key = (project_name or "plc_project").strip() or "plc_project"
    entities, relations = plc_kg_to_entities_relations(kg, project_key=project_key)
    graph = create_knowledge_graph()
    backend = type(graph).__name__
    if hasattr(graph, "upsert"):
        counts = graph.upsert(entities, relations)  # type: ignore[attr-defined]
    else:
        counts = {
            "entities": graph.upsert_entities(entities),
            "relations": graph.upsert_relations(relations),
        }
    return {
        "ok": True,
        "backend": backend,
        "project_key": project_key,
        "entities": counts.get("entities", len(entities)),
        "relations": counts.get("relations", len(relations)),
    }
