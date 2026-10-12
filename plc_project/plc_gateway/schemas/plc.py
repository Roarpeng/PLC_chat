"""PLC Intelligence job schemas — ResearchOS industrial feature (not the whole product)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlcJobCreatePath(BaseModel):
    """Create a PLC ingest job from a server-visible path."""

    source_type: Literal["path"] = "path"
    path: str = Field(..., description="Absolute path under PLC_PATH_ALLOWLIST roots")
    project_name: str = ""
    publish_graph: bool = True
    plc_name: str = ""
    tia_version: str = ""


class PlcChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    block_name: str | None = Field(
        default=None,
        description="Optional PLC block focus (OB/FB/FC/DB name)",
    )


class PlcGraphQueryRequest(BaseModel):
    op: str
    block_name: str | None = None
    tag: str | None = None
    target_block: str | None = None
    roots: list[str] | None = None


class PlcGraphQueryResponse(BaseModel):
    op: str
    result: Any
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class PlcChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    block_name: str | None = None
    created_at: datetime | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)


class PlcProjectBrief(BaseModel):
    """Layered handover Brief — readable before full SCL translate."""

    job_id: str | None = None
    project_name: str = ""
    phase: str = "queued"
    brief_ready: bool = False
    purpose: str = ""
    main_ob: str | None = None
    main_entry: str | None = None
    block_counts_by_status: dict[str, int] = Field(default_factory=dict)
    top_level_calls: list[dict[str, Any]] = Field(default_factory=list)
    device_sensor_summary: dict[str, Any] = Field(default_factory=dict)
    run_logic_entry: str = ""
    export_gaps: list[dict[str, Any]] = Field(default_factory=list)
    block_stubs: list[dict[str, Any]] = Field(default_factory=list)
    engineer_prompts: list[dict[str, str]] = Field(default_factory=list)
    timing: dict[str, Any] = Field(default_factory=dict)


class PlcAnalyzeRequest(BaseModel):
    """Optional block focus for deterministic KG/folded-logic analysis."""

    block_name: str | None = Field(
        default=None,
        description="Optional PLC block focus (OB/FB/FC/DB name)",
    )


class PlcLogicNode(BaseModel):
    id: str
    label: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)


class PlcLogicEdge(BaseModel):
    source: str
    target: str
    type: str


class PlcJobSummary(BaseModel):
    id: str
    status: str
    source_type: str
    source_path: str | None = None
    project_path: str | None = None
    project_name: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    export_ready: bool = False
    coverage: dict[str, Any] | None = Field(
        default=None,
        description="Language/Part/TODO histogram; also on GET job detail",
    )
    brief_ready: bool = False
    ingest_phase: str | None = None


class PlcJobDetail(PlcJobSummary):
    extraction_notes: list[str] = Field(default_factory=list)
    progress: list[dict[str, Any]] = Field(default_factory=list)
    openness_export_dir: str | None = None
    logic_graph: dict[str, Any] = Field(default_factory=dict)
    knowledge_graph: dict[str, Any] = Field(default_factory=dict)
    folded_logic: dict[str, Any] = Field(default_factory=dict)
    scl_sources: dict[str, str] = Field(default_factory=dict)
    report: str = ""
    graph_publish: dict[str, Any] | None = None
    chat: list[PlcChatTurn] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    changeset: dict[str, Any] | None = None
    writeback: dict[str, Any] | None = None
    optimize_plan: str = ""
    scl_files: dict[str, str] = Field(default_factory=dict)
    scl_diffs: list[dict[str, Any]] = Field(default_factory=list)
    scl_skipped: list[dict[str, Any]] = Field(default_factory=list)
    source_xmls: list[str] = Field(default_factory=list)
    timings: dict[str, int] = Field(
        default_factory=dict,
        description="Ingest stage wall-clock timings in milliseconds",
    )
    coverage: dict[str, Any] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(
        default_factory=dict,
        description="Trusted structure inventory: units + layers + counts",
    )
    hardware: list[dict[str, Any]] = Field(default_factory=list)
    body_pull_queue: list[dict[str, Any]] = Field(default_factory=list)
    block_stubs: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic review-rule findings (double write, set/reset, orphans)",
    )
    dossiers: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-block evidence packs: identity, calls, IO, coverage, preset Q&A",
    )


class PlcProposeChangeRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    block_name: str | None = None


class PlcOptimizeRequest(BaseModel):
    """Evidence-gated optimization proposal (dead + decouple + SCL rewrite)."""

    block_name: str | None = Field(
        default=None,
        description="Optional focus block; project-wide dead-block scan always runs",
    )
    message: str = Field(
        default="优化工程逻辑并准备反写",
        max_length=4000,
    )


class PlcStructureRetryRequest(BaseModel):
    """Re-run Openness/structure export for failed or pending units."""

    names: list[str] = Field(
        default_factory=list,
        description="Optional unit names to emphasize; empty retries the full inventory",
    )


class DeviceCardAnnotationRequest(BaseModel):
    """Engineer note that overrides cited tag/HMI comments on a Q1 card."""

    text: str = Field(..., min_length=1, max_length=2000)
    author: str = Field(default="", max_length=120)


class DeviceCardCitation(BaseModel):
    kind: str
    locator: str = ""
    quote: str = ""


class DeviceCardUsage(BaseModel):
    block: str
    access: str
    network_id: str = ""
    network_title: str = ""
    part: str = ""


class DeviceCardHmiText(BaseModel):
    device: str = ""
    screen: str = ""
    text: str = ""


class DeviceSensorCard(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="researchos.device_sensor_card.v1", alias="schema")
    id: str
    kind: str
    symbol_name: str
    address: str = ""
    comment: str = ""
    io_type: str = "UNKNOWN"
    data_type: str = ""
    tag_table: str = ""
    meaning_status: str
    meaning_text: str = ""
    meaning_source: str = "none"
    hmi_texts: list[DeviceCardHmiText] = Field(default_factory=list)
    used_by: list[DeviceCardUsage] = Field(default_factory=list)
    hardware: dict[str, Any] | None = None
    annotation: dict[str, Any] | None = None
    citations: list[DeviceCardCitation] = Field(default_factory=list)


class DeviceCardListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="researchos.device_sensor_card.v1", alias="schema")
    job_id: str | None = None
    project_name: str = ""
    counts: dict[str, Any] = Field(default_factory=dict)
    cards: list[DeviceSensorCard] = Field(default_factory=list)


class ProjectBriefResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="researchos.project_brief.v1", alias="schema")
    job_id: str | None = None
    project_name: str = ""
    status: str = ""
    sections: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    card_count: int = 0


class PlcWritebackRequest(BaseModel):
    """HITL confirm: apply KG changes and optionally import XML/SCL into .apxx."""

    project_path: str | None = Field(
        default=None,
        description="Target .ap19/.apxx; defaults to job.project_path from ingest",
    )
    plc_name: str = ""
    accept_changeset: bool = True
    execute_openness_import: bool = True
    archive_zap: bool = Field(
        default=True,
        description="After successful Openness import+save, Archive compressed .zap*",
    )
    xml_paths: list[str] = Field(
        default_factory=list,
        description="Optional XML files to stage; defaults to job source XML",
    )
    block_name: str | None = Field(
        default=None,
        description=(
            "Optional node-scoped confirm: apply only this block and helper FCs "
            "created for it. Empty = whole-project changeset."
        ),
    )
