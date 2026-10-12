"""PLC documentation connector — read-only stub with fake catalog."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol


@dataclass(frozen=True)
class PlcDocEntry:
    id: str
    title: str
    vendor: str
    family: str
    url: str
    summary: str
    tags: tuple[str, ...] = ()
    #: Provenance of this entry: "" (legacy), "knowledge", or "fallback_catalog".
    source: str = ""


class PlcDocsConnector(Protocol):
    def list_vendors(self) -> list[str]: ...

    def search(self, query: str, *, limit: int = 10) -> list[PlcDocEntry]: ...

    def get(self, doc_id: str) -> PlcDocEntry | None: ...


FAKE_CATALOG: list[PlcDocEntry] = [
    PlcDocEntry(
        id="plc_siemens_s7",
        title="SIMATIC S7-1500 System Manual",
        vendor="Siemens",
        family="S7-1500",
        url="https://example.com/plc/siemens-s7-1500",
        summary="CPU, I/O, and PROFINET commissioning overview for S7-1500.",
        tags=("plc", "profinet", "siemens"),
    ),
    PlcDocEntry(
        id="plc_beck_compactlogix",
        title="CompactLogix Controllers User Manual",
        vendor="Rockwell",
        family="CompactLogix",
        url="https://example.com/plc/compactlogix",
        summary="Controller architecture, EtherNet/IP, and ladder/ST guidance.",
        tags=("plc", "ethernet-ip", "rockwell"),
    ),
    PlcDocEntry(
        id="plc_beck_safety",
        title="Safety PLC Design Notes (stub)",
        vendor="Generic",
        family="Safety",
        url="https://example.com/plc/safety-notes",
        summary="Read-only safety design checklist; no download/write to field devices.",
        tags=("safety", "checklist"),
    ),
]


class FakePlcDocsConnector:
    def list_vendors(self) -> list[str]:
        return sorted({e.vendor for e in FAKE_CATALOG})

    def search(self, query: str, *, limit: int = 10) -> list[PlcDocEntry]:
        q = (query or "").strip().lower()
        if not q:
            return []

        def _haystack(e: PlcDocEntry) -> str:
            return " ".join(
                [e.title, e.summary, e.vendor, e.family, *e.tags]
            ).lower()

        # Exact phrase match first, then token-level scoring for compound queries.
        phrase_hits = [e for e in FAKE_CATALOG if q in _haystack(e)]
        if phrase_hits:
            return phrase_hits[:limit]

        tokens = [t for t in q.replace("-", " ").split() if len(t) >= 3]
        scored: list[tuple[int, int, PlcDocEntry]] = []
        for order, e in enumerate(FAKE_CATALOG):
            hay = _haystack(e)
            score = sum(1 for t in tokens if t in hay)
            if score:
                scored.append((score, order, e))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [e for _, _, e in scored[:limit]]

    def get(self, doc_id: str) -> PlcDocEntry | None:
        for e in FAKE_CATALOG:
            if e.id == doc_id:
                return e
        return None

    def as_dict(self, entry: PlcDocEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "title": entry.title,
            "vendor": entry.vendor,
            "family": entry.family,
            "url": entry.url,
            "summary": entry.summary,
            "tags": list(entry.tags),
            "readonly": True,
        }


_KB_SNIPPET_CHARS = 240


class KnowledgeBackedPlcDocsConnector:
    """KB-first manual connector; ``FAKE_CATALOG`` is a degraded fallback only.

    ``search`` queries the knowledge layer (``KnowledgePipeline.search``) and maps
    its passages onto :class:`PlcDocEntry`. A knowledge-layer failure or a zero-hit
    result degrades to a filtered ``FAKE_CATALOG`` search. Network/store exceptions
    are swallowed and treated as empty hits, so callers never see a raised error.
    """

    def __init__(self, *, top_k: int = 8, pipeline: Any | None = None) -> None:
        self._top_k = top_k
        #: Optional injected object exposing ``.search(query, top_k=...)`` (tests).
        self._pipeline = pipeline
        self._cache: dict[str, PlcDocEntry] = {}

    def _kb(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        from knowledge.pipeline import KnowledgePipeline

        return KnowledgePipeline()

    def _kb_passages(self, query: str) -> list[dict[str, Any]]:
        try:
            pack = self._kb().search(query, top_k=self._top_k)
        except Exception:
            return []
        if not isinstance(pack, dict):
            return []
        return list(pack.get("passages") or [])

    def _passage_to_entry(self, passage: dict[str, Any]) -> PlcDocEntry:
        citation = passage.get("citation") or {}
        locator = citation.get("locator") or {}
        source_id = str(
            passage.get("source_id")
            or citation.get("source_id")
            or passage.get("chunk_id")
            or ""
        )
        title = str(
            citation.get("title") or citation.get("source") or source_id or "knowledge"
        )
        url = str(citation.get("url") or locator.get("url") or "")
        snippet = str(passage.get("text") or "")[:_KB_SNIPPET_CHARS]
        return PlcDocEntry(
            id=source_id,
            title=title,
            vendor="knowledge",
            family="",
            url=url,
            summary=snippet,
            tags=(),
            source="knowledge",
        )

    def kb_passages(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Raw knowledge-layer passages (for ``plc.alarm.explain`` augmentation)."""
        return self._kb_passages(query)[:limit]

    def search(self, query: str, *, limit: int = 10) -> list[PlcDocEntry]:
        q = (query or "").strip()
        if not q:
            return []
        hits = [self._passage_to_entry(p) for p in self._kb_passages(q)]
        if hits:
            self._cache = {e.id: e for e in hits}
            return hits[:limit]
        fallback = [
            replace(e, source="fallback_catalog")
            for e in FakePlcDocsConnector().search(q, limit=limit)
        ]
        self._cache = {e.id: e for e in fallback}
        return fallback

    def get(self, doc_id: str) -> PlcDocEntry | None:
        if doc_id in self._cache:
            return self._cache[doc_id]
        entry = FakePlcDocsConnector().get(doc_id)
        if entry is None:
            return None
        return replace(entry, source="fallback_catalog")

    def list_vendors(self) -> list[str]:
        return sorted(
            {e.vendor for e in FAKE_CATALOG} | {e.vendor for e in self._cache.values()}
        )

    def as_dict(self, entry: PlcDocEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "title": entry.title,
            "vendor": entry.vendor,
            "family": entry.family,
            "url": entry.url,
            "summary": entry.summary,
            "tags": list(entry.tags),
            "source": entry.source,
            "readonly": True,
        }
