"""V2 native delivery request/response schemas (design 5.1 endpoints 12-15)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from gateway.app.schemas.v2_common import V2RequestEnvelope


class DeliveryIn(V2RequestEnvelope):
    """POST /api/v2/projects/{id}/deliveries."""

    approved_changeset_id: str = ""
    expected_baseline_hash: str = ""
    idempotency_key: str = ""
    artifact_type: Literal["native_tia_archive", "source_package"] = "native_tia_archive"
    tia_version: Literal["V19"] = "V19"


class JobOut(BaseModel):
    """GET /api/v2/delivery-jobs/{id}."""

    job_id: str = ""
    state: str = "QUEUED"
    compile: dict | None = None
    native_artifact: dict | None = None
    evidence_id: str = ""
    evidence_level: str = "pending_real_machine"
    stage_cursor: str | None = None
    notice: str = ""


class ArtifactOut(BaseModel):
    """Exact 4-tuple bound artifact descriptor."""

    artifact_id: str = ""
    job_id: str = ""
    project_id: str = ""
    kind: str = "zap19"
    sha256: str = ""
    size_bytes: int = 0
    evidence_level: str = "pending_real_machine"
    reopen_ok: bool = False


class SourcePackageOut(BaseModel):
    """A-2: explicitly NOT a native TIA project."""

    kind: str = "source_import_package"
    native_tia_project: bool = False
    files: list[str] = Field(default_factory=list)
    notice: str = "源码包就绪（非原生工程）; SOURCE_READY != NATIVE_ARCHIVED"
    evidence_level: str = "offline"


class DeliveryChainProbeIn(BaseModel):
    """Optional real-machine chain probe request (serial QA schedule only)."""

    project_id: str = ""
    approved_changeset_id: str = ""
    expected_baseline_hash: str = ""
    idempotency_key: str = ""
    workspace_dir: str = ""
    cpu_type_identifier: str = ""
