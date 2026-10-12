"""Unit tests — KB-first PLC docs connector (KnowledgeBackedPlcDocsConnector)."""

from __future__ import annotations

from typing import Any

from industrial.connectors.plc_docs import (
    FakePlcDocsConnector,
    KnowledgeBackedPlcDocsConnector,
)
from tools.plc import server as plc_server


class FakePipeline:
    """Injectable stand-in for knowledge.pipeline.KnowledgePipeline."""

    def __init__(self, pack: dict[str, Any] | None = None, error: Exception | None = None):
        self.pack = pack if pack is not None else {"query": "", "passages": []}
        self.error = error

    def search(self, query: str, *, top_k: int = 8) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.pack


def _passage(
    text: str = "PROFINET commissioning overview for the S7-1500 family.",
    *,
    source_id: str = "doc_s7",
    source: str | None = "SIMATIC S7-1500 System Manual",
    url: str | None = "https://kb.example/s7-1500",
) -> dict[str, Any]:
    return {
        "chunk_id": "chk_s7_1",
        "text": text,
        "score": 0.91,
        "source_id": source_id,
        "citation": {
            "source_id": source_id,
            "source": source,
            "locator": {"url": url},
        },
    }


def _pack(passages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"query": "q", "passages": passages}


def test_kb_search_maps_passages_to_entries():
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(pack=_pack([_passage()]))
    )
    hits = connector.search("S7 PROFINET", limit=10)
    assert len(hits) == 1
    entry = hits[0]
    assert entry.id == "doc_s7"
    assert entry.title == "SIMATIC S7-1500 System Manual"
    assert entry.url == "https://kb.example/s7-1500"
    assert entry.summary.startswith("PROFINET commissioning overview")
    assert entry.source == "knowledge"
    assert entry.vendor == "knowledge"


def test_kb_search_truncates_snippet_and_falls_back_to_source_id_title():
    long_text = "x" * 500
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(pack=_pack([_passage(long_text, source=None, url=None)]))
    )
    entry = connector.search("x", limit=10)[0]
    assert len(entry.summary) == 240
    assert entry.title == "doc_s7"
    assert entry.url == ""  # url=None mapped to empty string


def test_kb_exception_falls_back_to_fake_catalog():
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(error=RuntimeError("kb down"))
    )
    hits = connector.search("siemens", limit=10)
    assert hits, "expected degraded fallback to FAKE_CATALOG"
    assert all(e.source == "fallback_catalog" for e in hits)
    assert any(e.vendor == "Siemens" for e in hits)


def test_kb_zero_hits_falls_back_to_fake_catalog():
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(pack=_pack([]))
    )
    hits = connector.search("compactlogix", limit=10)
    assert hits
    assert all(e.source == "fallback_catalog" for e in hits)
    assert any(e.vendor == "Rockwell" for e in hits)


def test_get_returns_cached_search_result_and_fallback_entry():
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(pack=_pack([_passage()]))
    )
    connector.search("S7", limit=10)
    cached = connector.get("doc_s7")
    assert cached is not None and cached.source == "knowledge"

    fallback = connector.get("plc_siemens_s7")
    assert fallback is not None and fallback.source == "fallback_catalog"
    assert connector.get("nope") is None


def test_alarm_explain_attaches_kb_passages(monkeypatch):
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(pack=_pack([_passage()]))
    )
    monkeypatch.setattr(plc_server, "_connector", connector)
    res = plc_server.plc_alarm_explain("E2304")
    assert res["ok"] is True
    assert res.get("kb_passages"), "expected kb_passages on KB hit"
    assert res["kb_passages"][0]["source_id"] == "doc_s7"
    assert res["citation"]["id"] == "plc_siemens_s7"


def test_alarm_explain_falls_back_to_static_catalog_when_kb_empty(monkeypatch):
    connector = KnowledgeBackedPlcDocsConnector(
        pipeline=FakePipeline(pack=_pack([]))
    )
    monkeypatch.setattr(plc_server, "_connector", connector)
    res = plc_server.plc_alarm_explain("E2304")
    assert res["ok"] is True
    assert "kb_passages" not in res
    assert res["citation"]["id"] == "plc_siemens_s7"


def test_connector_selection_env_switch(monkeypatch):
    monkeypatch.setenv("PLC_DOCS_CONNECTOR", "fake")
    assert isinstance(plc_server._make_connector(), FakePlcDocsConnector)

    monkeypatch.setenv("PLC_DOCS_CONNECTOR", "knowledge")
    assert isinstance(plc_server._make_connector(), KnowledgeBackedPlcDocsConnector)

    monkeypatch.delenv("PLC_DOCS_CONNECTOR", raising=False)
    assert isinstance(plc_server._make_connector(), KnowledgeBackedPlcDocsConnector)
