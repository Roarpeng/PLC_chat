"""LLM settings schemas — up to 3 slots per kind (chat / embed / rerank)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SlotKind = Literal["chat", "embed", "rerank"]


class LlmModelInfo(BaseModel):
    id: str
    label: str
    provider: str = "slot"
    kind: str = "chat"
    requires_key: str | None = None


class LlmSlotStatus(BaseModel):
    id: str
    label: str
    kind: SlotKind
    configured: bool
    hint: str | None = None
    model: str = ""
    base_url: str = ""
    default_model: str = ""
    default_base_url: str = ""
    primary: bool = False
    removable: bool = False


class LlmSlotUpdate(BaseModel):
    api_key: str | None = Field(
        default=None,
        description="Omit to keep; empty string clears",
    )
    model: str | None = None
    base_url: str | None = None


class LlmAgentBinding(BaseModel):
    """Agent roles bind to chat slots (or embed / rerank)."""

    research: str = "chat_a"
    planner: str = "chat_a"
    researcher: str = "chat_a"
    writer: str = "chat_a"
    plc: str = "chat_a"
    embed: str = "embed"
    rerank: str = "rerank"


class LlmSettingsResponse(BaseModel):
    catalog: list[LlmModelInfo]
    agents: LlmAgentBinding
    slots: list[LlmSlotStatus]
    # backward-compatible alias used by older UI
    providers: list[LlmSlotStatus] = Field(default_factory=list)
    litellm_base_url: str | None = None
    default_model: str = "chat_a"
    notes: list[str] = Field(default_factory=list)


class LlmSettingsUpdate(BaseModel):
    agents: LlmAgentBinding | None = None
    slots: dict[str, LlmSlotUpdate] | None = Field(
        default=None,
        description="Map of slot id → {api_key?, model?, base_url?}",
    )
    add_slot: SlotKind | None = Field(
        default=None,
        description="Enable the next spare slot of this kind (chat/embed/rerank)",
    )
    remove_slot: str | None = Field(
        default=None,
        description="Disable a non-primary slot",
    )
    # legacy aliases
    providers: dict[str, LlmSlotUpdate] | None = None
    provider_keys: dict[str, str] | None = None


class LlmSlotTestRequest(BaseModel):
    slot_id: str = Field(..., description="chat_a|chat_b|chat_c|embed|embed_b|embed_c|rerank|rerank_b|rerank_c")
    api_key: str | None = Field(default=None, description="Optional draft key (else saved/env)")
    model: str | None = None
    base_url: str | None = None


class LlmSlotTestResult(BaseModel):
    ok: bool
    slot_id: str
    kind: str
    model: str = ""
    base_url: str = ""
    latency_ms: int = 0
    message: str = ""
    detail: str | None = None
