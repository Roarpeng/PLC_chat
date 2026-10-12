"""Shared knowledge-layer pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


SectionType = Literal[
    "title",
    "specification",
    "parameter",
    "table",
    "faq",
    "review",
    "news",
    "narrative",
    "fallback_window",
]

BlockType = Literal[
    "heading",
    "paragraph",
    "list",
    "table",
    "code",
    "figure_caption",
    "footer",
    "header",
    "slide_title",
    "slide_body",
    "faq_q",
    "faq_a",
    "review_body",
    "unknown",
]


class Locator(BaseModel):
    """Provenance locator: page/paragraph/offset/url extras."""

    page: int | None = None
    paragraph: int | None = None
    offset_start: int | None = None
    offset_end: int | None = None
    url: str | None = None
    slide: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def as_string(self) -> str:
        parts: list[str] = []
        if self.page is not None:
            parts.append(f"page={self.page}")
        if self.slide is not None:
            parts.append(f"slide={self.slide}")
        if self.paragraph is not None:
            parts.append(f"paragraph={self.paragraph}")
        if self.offset_start is not None and self.offset_end is not None:
            parts.append(f"offset={self.offset_start}-{self.offset_end}")
        if self.url:
            parts.append(f"url={self.url}")
        return ";".join(parts) if parts else "locator=unknown"


class Citation(BaseModel):
    citation_id: str = Field(default_factory=lambda: new_id("cite"))
    chunk_id: str
    source_id: str
    source: str
    locator: Locator = Field(default_factory=Locator)
    time: datetime | None = None
    score: float = 0.0
    section_type: str | None = None
    object_key: str | None = None
    quote: str | None = None


class ParseBlock(BaseModel):
    id: str
    type: BlockType = "paragraph"
    level: int | None = None
    text: str
    paragraph: int | None = None
    bbox: list[float] | None = None
    table: dict[str, Any] | None = None


class ParsePage(BaseModel):
    page: int
    blocks: list[ParseBlock] = Field(default_factory=list)


class ParseIR(BaseModel):
    doc_id: str
    parser: dict[str, str] = Field(default_factory=dict)
    language: str | None = None
    pages: list[ParsePage] = Field(default_factory=list)
    markdown: str = ""
    warnings: list[str] = Field(default_factory=list)
    source_file: str | None = None
    object_key: str | None = None
    url: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class Chunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: new_id("chk"))
    doc_id: str
    workspace_id: str = "default"
    source_id: str
    section_type: SectionType = "narrative"
    section_path: list[str] = Field(default_factory=list)
    text: str
    locator: Locator = Field(default_factory=Locator)
    source_file: str | None = None
    object_key: str | None = None
    url: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    language: str | None = None
    parser: str | None = None
    parent_chunk_id: str | None = None
    parent_section_id: str | None = None
    content_hash: str | None = None
    model: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "workspace_id": self.workspace_id,
            "source_id": self.source_id,
            "section_type": self.section_type,
            "section_path": self.section_path,
            "text": self.text,
            "locator": self.locator.model_dump(),
            "source_file": self.source_file,
            "object_key": self.object_key,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "language": self.language,
            "parser": self.parser,
            "parent_chunk_id": self.parent_chunk_id,
            "parent_section_id": self.parent_section_id,
            "content_hash": self.content_hash,
            "model": self.model,
            "tags": self.tags,
            "metadata": self.metadata,
        }


class Entity(BaseModel):
    type: str
    canonical_key: str
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class Relation(BaseModel):
    type: str
    from_key: str
    to_key: str
    from_type: str | None = None
    to_type: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class Passage(BaseModel):
    chunk_id: str
    text: str
    section_type: str | None = None
    score: float
    channels: list[str] = Field(default_factory=list)
    citation: Citation
    source_id: str
    locator: Locator


class ContextPack(BaseModel):
    query: str
    passages: list[Passage] = Field(default_factory=list)
    subgraph: dict[str, Any] = Field(default_factory=lambda: {"nodes": [], "edges": []})
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class DocumentMeta(BaseModel):
    doc_id: str = Field(default_factory=lambda: new_id("doc"))
    workspace_id: str = "default"
    title: str | None = None
    mime_type: str | None = None
    extension: str | None = None
    source_file: str | None = None
    object_key: str | None = None
    content_hash: str | None = None
    status: str = "registered"
    parser_name: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResult(BaseModel):
    doc_id: str
    status: str
    chunk_count: int = 0
    entity_count: int = 0
    relation_count: int = 0
    object_key: str | None = None
    parser: str | None = None
    warnings: list[str] = Field(default_factory=list)
    channels: dict[str, bool] = Field(default_factory=dict)
