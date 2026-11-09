"""V2 IR / editing request schemas (design 5.1 endpoints 1, 5-11)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from gateway.app.schemas.v2_common import V2RequestEnvelope


class CreateProjectIn(BaseModel):
    """POST /api/v2/projects."""

    project_id: str = ""
    origin: str = "greenfield"
    request_id: str = ""
    legacy_ir: dict[str, Any] | None = None
    v1_fixture: dict[str, Any] | None = None


class PatchIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/patches — atomic semantic patch."""

    ops: list[dict[str, Any]] = Field(default_factory=list)


class IntentIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/intent — NL to CandidatePatch only."""

    message: str = ""
    context_slice: dict[str, Any] = Field(default_factory=dict)


class ValidateIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/validate."""

    full: bool = True


class SimulateIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/simulate."""

    scenario: str = "normal_cycle"


class PreviewIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/preview."""

    include_scl: bool = True


class ChangesetIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/changesets."""

    ops: list[dict[str, Any]] = Field(default_factory=list)


class ApproveIn(V2RequestEnvelope):
    """POST /api/v2/changesets/{id}/approve — explicit human sign-off."""

    reviewer_id: str = ""
    explicit: bool = False
    expected_baseline_hash: str = ""


class BrownfieldDiffPlanIn(V2RequestEnvelope):
    """A-3 placeholder: interface + schema only (Q-04, no real TIA write)."""

    ops: list[dict[str, Any]] = Field(default_factory=list)
    source_bindings: list[dict[str, Any]] = Field(default_factory=list)
