"""V2 Brownfield interface-only request/response schemas (WP-05 / Q-04)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from gateway.app.schemas.v2_common import V2RequestEnvelope


class BrownfieldBindingIn(BaseModel):
    source_id: str = ""
    source_block_id: str = ""
    tia_path: str = ""
    block_type: str = ""
    original_hash: str = ""
    original_xml_sha256: str = ""
    source_span: dict[str, Any] = Field(default_factory=dict)
    ir_ids: list[str] = Field(default_factory=list)
    ir_entities: list[str] = Field(default_factory=list)
    referenced_by: list[str] = Field(default_factory=list)
    writable: str = "requires_review"
    fidelity: str = "unknown"
    block_number: int | None = None


class BrownfieldDiffPlanIn(V2RequestEnvelope):
    ops: list[dict[str, Any]] = Field(default_factory=list)
    source_bindings: list[BrownfieldBindingIn] = Field(default_factory=list)
    expected_baseline_hash: str = ""
    mocked_orchestration: bool = False


class BrownfieldPlanOut(BaseModel):
    plan_id: str = ""
    executable: bool = False
    evidence_level: str = "mocked"
    issues: list[dict[str, str]] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    mocked_orchestration: dict[str, Any] | None = None
    notice: str = "interface + schema only; no real TIA ADD/MODIFY/DELETE"
