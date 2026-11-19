"""Pydantic v2 schemas for AF-Studio v5 Spatio-Temporal Orthogonal HyperGraph API."""
from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PortSpecIn(BaseModel):
    """Port socket descriptor on a spatial instance or station boundary card."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    label: str = ""
    type: str = "SEQ"  # 'SEQ' | 'GUARD'
    isFaultLeaf: bool = Field(
        default=False,
        validation_alias=AliasChoices("isFaultLeaf", "is_fault_leaf"),
    )


class PositionIn(BaseModel):
    """2D canvas position of a spatial node."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    x: float = 0.0
    y: float = 0.0


class SpatialInstanceNodeIn(BaseModel):
    """Unique physical spatial instance node V_spatial (never duplicated across cycles)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    role: str = "ACTUATOR"  # 'BOUNDARY_IN' | 'BOUNDARY_OUT' | 'ACTUATOR'
    title: str = ""
    driverClass: str = Field(
        default="FB_AF_Actuator2Pos",
        validation_alias=AliasChoices("driverClass", "driver_class"),
    )
    instanceDb: str = Field(
        default="",
        validation_alias=AliasChoices("instanceDb", "instance_db"),
    )
    position: PositionIn | None = None
    x: float | None = None
    y: float | None = None
    isPinned: bool = Field(
        default=True,
        validation_alias=AliasChoices("isPinned", "is_pinned"),
    )
    hasPartPresentSensor: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "hasPartPresentSensor",
            "hasPartSensor",
            "has_part_present_sensor",
            "has_part_sensor",
        ),
    )
    discreteStates: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("discreteStates", "discrete_states"),
    )
    initialHomeState: str = Field(
        default="AtHome",
        validation_alias=AliasChoices("initialHomeState", "initial_home_state"),
    )
    cohesiveIoMap: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("cohesiveIoMap", "cohesive_io_map"),
    )
    ioText: str = Field(
        default="",
        validation_alias=AliasChoices("ioText", "io_text"),
    )
    theme: str = ""
    isPhysicalRootCause: bool = Field(
        default=False,
        validation_alias=AliasChoices("isPhysicalRootCause", "is_physical_root_cause"),
    )
    inPorts: list[PortSpecIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("inPorts", "in_ports"),
    )
    outPorts: list[PortSpecIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("outPorts", "out_ports"),
    )


class CrossStationRefIn(BaseModel):
    """Upstream physical terminal reference for cross-station safety guardrails."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    upstreamStationId: str = Field(
        default="",
        validation_alias=AliasChoices("upstreamStationId", "upstream_station_id"),
    )
    upstreamInstanceId: str = Field(
        default="",
        validation_alias=AliasChoices("upstreamInstanceId", "upstream_instance_id"),
    )
    physicalTerminal: str = Field(
        default="",
        validation_alias=AliasChoices("physicalTerminal", "physical_terminal"),
    )
    cabinetWireTag: str = Field(
        default="",
        validation_alias=AliasChoices("cabinetWireTag", "cabinet_wire_tag"),
    )


class SafetyGuardEdgeIn(BaseModel):
    """Permanent spatial safety guardrail edge E_guard."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    fromNode: str = Field(validation_alias=AliasChoices("fromNode", "from_node"))
    fromPort: str = Field(default="", validation_alias=AliasChoices("fromPort", "from_port"))
    toNode: str = Field(validation_alias=AliasChoices("toNode", "to_node"))
    toPort: str = Field(default="", validation_alias=AliasChoices("toPort", "to_port"))
    requiredSourceState: str = Field(
        default="AtHome",
        validation_alias=AliasChoices("requiredSourceState", "required_source_state"),
    )
    diagCodeHex: str = Field(
        default="",
        validation_alias=AliasChoices("diagCodeHex", "diagCode", "diag_code_hex", "diag_code"),
    )
    humanDescription: str = Field(
        default="",
        validation_alias=AliasChoices(
            "humanDescription",
            "humanRule",
            "human_description",
            "human_rule",
        ),
    )
    isHealthy: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("isHealthy", "is_healthy"),
    )
    isCrossStation: bool = Field(
        default=False,
        validation_alias=AliasChoices("isCrossStation", "is_cross_station"),
    )
    crossStationRef: CrossStationRefIn | None = Field(
        default=None,
        validation_alias=AliasChoices("crossStationRef", "cross_station_ref"),
    )


class StepInvocationIn(BaseModel):
    """Single target-instance method invocation inside a temporal step hyperedge."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    targetNodeId: str = Field(
        default="",
        validation_alias=AliasChoices("targetNodeId", "target_node_id"),
    )
    methodId: str = Field(
        default="",
        validation_alias=AliasChoices("methodId", "method_id"),
    )
    actionLabel: str = Field(
        default="",
        validation_alias=AliasChoices("actionLabel", "action_label"),
    )
    targetDiscreteState: str = Field(
        default="",
        validation_alias=AliasChoices("targetDiscreteState", "target_discrete_state"),
    )
    sclStatement: str = Field(
        default="",
        validation_alias=AliasChoices("sclStatement", "scl_statement", "sclCall"),
    )
    waitPredicateScl: str = Field(
        default="TRUE",
        validation_alias=AliasChoices("waitPredicateScl", "wait_predicate_scl", "waitDesc"),
    )


class TemporalStepHyperEdgeIn(BaseModel):
    """Temporal step hyperedge T_seq mounting craft actions onto spatial instances."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    stepNo: int = Field(validation_alias=AliasChoices("stepNo", "step_no"))
    title: str = ""
    fromNode: str = Field(default="", validation_alias=AliasChoices("fromNode", "from_node"))
    fromPort: str = Field(default="", validation_alias=AliasChoices("fromPort", "from_port"))
    invocations: list[StepInvocationIn] = Field(default_factory=list)
    branchPredicate: str = Field(
        default="ALWAYS",
        validation_alias=AliasChoices("branchPredicate", "branch_predicate"),
    )
    # Flat fields compatible with prototype af_studio_v5.html
    toNode: str = Field(default="", validation_alias=AliasChoices("toNode", "to_node"))
    toPort: str = Field(default="", validation_alias=AliasChoices("toPort", "to_port"))
    actionLabel: str = Field(default="", validation_alias=AliasChoices("actionLabel", "action_label"))
    sclCall: str = Field(default="", validation_alias=AliasChoices("sclCall", "scl_call"))
    waitDesc: str = Field(default="", validation_alias=AliasChoices("waitDesc", "wait_desc"))
    parallelNode: str = Field(default="", validation_alias=AliasChoices("parallelNode", "parallel_node"))
    parallelActionLabel: str = Field(
        default="",
        validation_alias=AliasChoices("parallelActionLabel", "parallel_action_label"),
    )
    requiresZHomeGuard: bool = Field(
        default=False,
        validation_alias=AliasChoices("requiresZHomeGuard", "requires_z_home_guard"),
    )


class StationHyperGraphIn(BaseModel):
    """L2 station orthogonal hypergraph G_AF = <V_spatial, E_guard, T_seq>."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    stationId: str = Field(default="ST20", validation_alias=AliasChoices("stationId", "station_id"))
    stationName: str = Field(default="", validation_alias=AliasChoices("stationName", "station_name"))
    spatialNodes: list[SpatialInstanceNodeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("spatialNodes", "spatial_nodes"),
    )
    guardEdges: list[SafetyGuardEdgeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("guardEdges", "guard_edges"),
    )
    temporalSteps: list[TemporalStepHyperEdgeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("temporalSteps", "temporal_steps"),
    )
    ghostEdges: list[TemporalStepHyperEdgeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("ghostEdges", "ghost_edges"),
    )


class ProjectStationNodeIn(BaseModel):
    """L1 compound station node on the production line graph."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    stationId: str = Field(default="", validation_alias=AliasChoices("stationId", "station_id"))
    title: str = ""
    x: float = 0.0
    y: float = 0.0
    isPinned: bool = Field(default=True, validation_alias=AliasChoices("isPinned", "is_pinned"))
    instances: list[str] = Field(default_factory=list)
    inPorts: list[PortSpecIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("inPorts", "in_ports"),
    )
    outPorts: list[PortSpecIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("outPorts", "out_ports"),
    )


class ProjectEdgeIn(BaseModel):
    """L1 inter-station handshake or cross-station safety guardrail edge."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    fromNode: str = Field(validation_alias=AliasChoices("fromNode", "from_node"))
    fromPort: str = Field(default="", validation_alias=AliasChoices("fromPort", "from_port"))
    toNode: str = Field(validation_alias=AliasChoices("toNode", "to_node"))
    toPort: str = Field(default="", validation_alias=AliasChoices("toPort", "to_port"))
    kind: str = "SEQ"
    label: str = ""
    isFaultCutSet: bool = Field(
        default=False,
        validation_alias=AliasChoices("isFaultCutSet", "is_fault_cut_set"),
    )


class ProjectHyperGraphIn(BaseModel):
    """L1 production-line compound station graph."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    projectId: str = Field(
        default="AssyLine_01",
        validation_alias=AliasChoices("projectId", "project_id"),
    )
    projectName: str = Field(
        default="AssyLine_01",
        validation_alias=AliasChoices("projectName", "project_name"),
    )
    stations: list[ProjectStationNodeIn] = Field(default_factory=list)
    edges: list[ProjectEdgeIn] = Field(default_factory=list)


class GhostGraphTransactionIn(BaseModel):
    """Neuro-symbolic AI Ghost Diff Patch transaction."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    txId: str = Field(default="", validation_alias=AliasChoices("txId", "tx_id"))
    summary: str = ""
    addedNodes: list[SpatialInstanceNodeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("addedNodes", "added_nodes"),
    )
    addedGuardEdges: list[SafetyGuardEdgeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("addedGuardEdges", "added_guard_edges"),
    )
    addedTemporalSteps: list[TemporalStepHyperEdgeIn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("addedTemporalSteps", "added_temporal_steps"),
    )
    verificationPassed: bool = Field(
        default=True,
        validation_alias=AliasChoices("verificationPassed", "verification_passed"),
    )
    verifierWarnings: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("verifierWarnings", "verifier_warnings"),
    )


class HyperGraphVerifyIn(BaseModel):
    """POST /api/v2/af-studio/verify request."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    station: StationHyperGraphIn
    ghost_tx: GhostGraphTransactionIn | None = Field(
        default=None,
        validation_alias=AliasChoices("ghost_tx", "ghostTx"),
    )
    request_id: str = ""


class HyperGraphCompileIn(BaseModel):
    """POST /api/v2/af-studio/compile request."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    station: StationHyperGraphIn
    request_id: str = ""


class MerkleSyncIn(BaseModel):
    """POST /api/v2/af-studio/merkle-sync request."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    project_id: str = Field(
        default="AssyLine_01",
        validation_alias=AliasChoices("project_id", "projectId"),
    )
    station: StationHyperGraphIn
    previous_hashes: dict[str, str] | None = Field(
        default=None,
        validation_alias=AliasChoices("previous_hashes", "previousHashes"),
    )
    project_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("project_path", "projectPath"),
    )
    plc_name: str = Field(
        default="",
        validation_alias=AliasChoices("plc_name", "plcName"),
    )
    software_unit: str = Field(
        default="",
        validation_alias=AliasChoices("software_unit", "softwareUnit"),
    )
    request_id: str = ""


class CopilotGhostPatchIn(BaseModel):
    """POST /api/v2/af-studio/copilot/ghost-patch request."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    station: StationHyperGraphIn
    prompt: str | None = None
    timing_table_rows: list[dict[str, Any]] | None = Field(
        default=None,
        validation_alias=AliasChoices("timing_table_rows", "timingTableRows"),
    )
    io_table_rows: list[dict[str, Any]] | None = Field(
        default=None,
        validation_alias=AliasChoices("io_table_rows", "ioTableRows"),
    )
    request_id: str = ""


class CutSetSnapshotIn(BaseModel):
    """POST /api/v2/af-studio/diagnostics/cutset-snapshot request."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    project_graph: ProjectHyperGraphIn | None = Field(
        default=None,
        validation_alias=AliasChoices("project_graph", "projectGraph"),
    )
    station_graphs: dict[str, StationHyperGraphIn] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("station_graphs", "stationGraphs"),
    )
    fault_station_id: str = Field(
        default="ST20",
        validation_alias=AliasChoices("fault_station_id", "faultStationId"),
    )
    fault_step_no: int = Field(
        default=30,
        validation_alias=AliasChoices("fault_step_no", "faultStepNo"),
    )
    live_signals: dict[str, bool] | None = Field(
        default=None,
        validation_alias=AliasChoices("live_signals", "liveSignals"),
    )
    request_id: str = ""
