"""FC-00 · Object identity, four graphs and relationship index."""
from __future__ import annotations

from .objects import (
    GRAPH_KINDS,
    RELATIONS,
    Object,
    ObjectRegistry,
    Relationship,
    graph_of,
    new_object_id,
    register_contract,
)

__all__ = ["Object", "ObjectRegistry", "Relationship", "GRAPH_KINDS", "RELATIONS",
           "graph_of", "new_object_id", "register_contract"]