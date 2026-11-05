"""Greenfield 强类型 IR —— Phase 1 唯一权威规格（§3.1 / §3.2 / §3.6）。

设计：``扁平注册表 + 全局 ID 引用 + edges[] 边列表``。连线 = 对 ``edges[]``
的一次原子增删改，三视图只是 ``project_views(ir)`` 的确定性只读投影。
``AfProject`` 只在 ``to_af_project()`` 里**瞬时派生**（Phase 2 生成时现场构造），
不落盘、不被前端持有、不参与 spec_hash，从机制上杜绝平行状态源。

本模块只依赖 Python 标准库、``af_model`` / ``af_numbering``（既有只读资产）
与同通道的 ``greenfield_edges`` / ``greenfield_ports``；**零 import 存量重构链**。
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Iterable

from plc_engine.af.af_model import (
    AfCm,
    AfEm,
    AfJob,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)
from plc_engine.af.af_numbering import (
    get_em0_ob_numbers,
    get_em_ob_numbers,
    get_unit_ob_numbers,
)
from plc_engine.af.greenfield_edges import (
    BRANCH_TERMINAL_STATES,
    EdgeKind,
    MODE_IDS,
    NAMESPACE_RULES,
    NodeKind,
    PACKML_STATES,
    PACKML_TRANSITIONS,
    PLCOPEN_SIGNALS,
    VIRTUAL_NODE_IDS,
    edge_id,
    matches_namespace,
)
from plc_engine.af.greenfield_ports import GreenfieldStage

IR_VERSION = "gf-ir-1.0"
AF_PROFILE = "SIEMENS_AF_BASIC_FOLDER_V19"
PROJECTION_VERSION = "gf-view-1.0"
SPEC_HASH_DOMAIN = "GF-SPEC-v1"

#: §3.6.4「只在 IR、不上图」十项字段组标识（R3 / M3）。
IR_ONLY_FIELD_KEYS: tuple[str, ...] = (
    "frozen_contract",
    "namespace_af_profile",
    "plcopen_signals",
    "step_interlock_fields",
    "job_cm_parameters",
    "packml_matrix",
    "control_node_fields",
    "io_binding_map",
    "receipt_spec_meta",
    "view_layout",
)

#: 十项字段组的结构化目录（供右侧校验面板渲染表单）。
IR_ONLY_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "key": "frozen_contract",
        "label": "只读冻结契约",
        "panel": "只读冻结契约清单",
        "editable": False,
        "fields": ["io_entries[].logical_address", "db_structs[].members[].offset",
                   "db_structs[].members[].initial_value", "db_structs[].scl_body",
                   "symbols[].name", "ob_entries[].number", "ob_entries[].call_order",
                   "safety_entries[]"],
        "note": "六类物理不可变，灰锁只读（GF_CONTRACT_IMMUTABLE）",
    },
    {
        "key": "namespace_af_profile",
        "label": "命名空间与档位",
        "panel": "工程视角属性面板",
        "editable": False,
        "fields": ["project.namespace_prefix", "project.af_profile", "units[].ob_numbers",
                   "ems[].ob_numbers", "ems[].namespace_prefix"],
        "note": "由编号公式派生，只读",
    },
    {
        "key": "plcopen_signals",
        "label": "设备五信号",
        "panel": "设备属性表单",
        "editable": True,
        "fields": ["cms[].plcopen.enable", "cms[].plcopen.valid", "cms[].plcopen.busy",
                   "cms[].plcopen.error", "cms[].plcopen.status"],
        "note": "缺一不得建立控制节点边",
    },
    {
        "key": "step_interlock_fields",
        "label": "步序与联锁字段",
        "panel": "步序 / 联锁属性表单",
        "editable": True,
        "fields": ["steps[].actions", "steps[].transition_condition", "steps[].timeout_ms",
                   "steps[].error_step_id", "interlocks[].expression"],
        "note": "来源为 inferred 的联锁自动进入待确认问题",
    },
    {
        "key": "job_cm_parameters",
        "label": "作业与设备参数",
        "panel": "作业 / 设备属性表单",
        "editable": True,
        "fields": ["jobs[].start_condition", "jobs[].single_cycle_job",
                   "cms[].parameters.timeout_ms", "cms[].parameters.releaseWork",
                   "cms[].parameters.releaseHome"],
        "note": "业务参数可编辑并参与 spec_hash",
    },
    {
        "key": "packml_matrix",
        "label": "模式与迁移许可",
        "panel": "模式属性表单",
        "editable": True,
        "fields": ["modes[].enabled_states", "modes[].enabled_transitions",
                   "modes[].enable_hold", "modes[].enable_complete"],
        "note": "改动须同步触发迁移合法性校验",
    },
    {
        "key": "control_node_fields",
        "label": "控制节点字段路径",
        "panel": "控制节点属性表单",
        "editable": False,
        "fields": ["control_nodes[].commands", "control_nodes[].status",
                   "control_nodes[].sequence_ref"],
        "note": "结构约束，只读",
    },
    {
        "key": "io_binding_map",
        "label": "信号映射条目",
        "panel": "信号映射表单",
        "editable": True,
        "fields": ["io_bindings[].compat_ref_id", "io_bindings[].field_path",
                   "io_bindings[].channel"],
        "note": "direction 恒为 IO_READ，只读契约",
    },
    {
        "key": "receipt_spec_meta",
        "label": "回执与冻结元数据",
        "panel": "冻结 / 回执面板",
        "editable": False,
        "fields": ["compat_refs[].contract_sha", "spec_meta.receipt_id",
                   "spec_meta.spec_version", "spec_meta.spec_hash", "spec_meta.frozen_at"],
        "note": "只读留痕",
    },
    {
        "key": "view_layout",
        "label": "三视图布局坐标",
        "panel": "不展示",
        "editable": False,
        "fields": ["views.layout"],
        "note": "纯 UI 坐标，不进 spec_hash",
    },
)


def _to_plain(value: Any) -> Any:
    """递归把 dataclass / Enum / dict / list 转为纯 JSON 可序列化结构。"""
    if isinstance(value, _GFEntity):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_plain(v) for v in value]
    return value


def canonical_dumps(obj: Any) -> str:
    """全局 canonical JSON 口径（§3.5.2 / §8）。"""
    return json.dumps(_to_plain(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(payload: str | bytes) -> str:
    """返回裸 64 位小写 hex。"""
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(raw).hexdigest()


def sha256_prefixed(payload: str | bytes) -> str:
    """返回统一哈希格式 ``sha256:<64hex>``（小写）。"""
    return f"sha256:{sha256_hex(payload)}"


def _as_int(value: Any, default: int) -> int:
    """把 JSON 值还原为 int；``0`` 是合法值，不能被 ``or default`` 吞掉。"""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list_of(data: dict[str, Any], key: str, cls: type) -> list[Any]:
    """把 JSON 列表逐项还原为 dataclass（已是对象则原样保留）。"""
    result: list[Any] = []
    for item in data.get(key) or []:
        if isinstance(item, dict):
            result.append(cls.from_dict(item))
        else:
            result.append(item)
    return result


def _entity_of(data: dict[str, Any], key: str, cls: type, default: Any) -> Any:
    """把嵌套 JSON 对象还原为 dataclass；缺失时返回默认值。"""
    raw = data.get(key)
    if isinstance(raw, dict):
        return cls.from_dict(raw)
    if isinstance(raw, cls):
        return raw
    return default


@dataclass
class _GFEntity:
    """所有 IR 实体的公共序列化基类。"""

    def to_dict(self) -> dict[str, Any]:
        """输出纯 JSON 结构（字段声明顺序无关，哈希走 sort_keys）。"""
        return {f.name: _to_plain(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        """子类必须实现；基类不提供隐式实现。"""
        raise NotImplementedError(f"{cls.__name__}.from_dict 未实现")


@dataclass
class GFProject(_GFEntity):
    """顶层项目档位信息。"""

    name: str = "AssemblyCell"
    business_label: str = "装配工位"
    af_profile: str = AF_PROFILE
    namespace_prefix: str = "GF"
    tia_version: str = "V19"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFProject":
        return cls(
            name=str(data.get("name") or "AssemblyCell"),
            business_label=str(data.get("business_label") or "装配工位"),
            af_profile=str(data.get("af_profile") or AF_PROFILE),
            namespace_prefix=str(data.get("namespace_prefix") or "GF"),
            tia_version=str(data.get("tia_version") or "V19"),
        )


@dataclass
class GFUnit(_GFEntity):
    """ISA-88 层级根（唯一父为 null）。"""

    id: str = "U1"
    unit_idx: int = 1
    name: str = "AssemblyCell"
    business_label: str = "装配工位"
    namespace_prefix: str = "U1_"
    parent_id: str | None = None
    ob_numbers: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFUnit":
        return cls(
            id=str(data.get("id") or "U1"),
            unit_idx=_as_int(data.get("unit_idx"), 1),
            name=str(data.get("name") or "AssemblyCell"),
            business_label=str(data.get("business_label") or "装配工位"),
            namespace_prefix=str(data.get("namespace_prefix") or "U1_"),
            parent_id=data.get("parent_id"),
            ob_numbers=dict(data.get("ob_numbers") or {}),
        )


@dataclass
class GFEm(_GFEntity):
    """工序（Equipment Module）；``unit_id`` 强制唯一父。"""

    id: str = "U1EM1"
    em_idx: int = 1
    unit_id: str = "U1"
    name: str = "Feeding"
    business_label: str = "上料工序"
    namespace_prefix: str = "U1EM1_"
    control_node_id: str = "U1EM1_CN"
    job_ids: list[str] = field(default_factory=list)
    initial_step_id: int = 10
    ob_numbers: dict[str, int] = field(default_factory=dict)
    sc_policy: str = "SC_ON_COMPLETE"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFEm":
        return cls(
            id=str(data.get("id") or "U1EM1"),
            em_idx=_as_int(data.get("em_idx"), 1),
            unit_id=str(data.get("unit_id") or "U1"),
            name=str(data.get("name") or "Feeding"),
            business_label=str(data.get("business_label") or "上料工序"),
            namespace_prefix=str(data.get("namespace_prefix") or "U1EM1_"),
            control_node_id=str(data.get("control_node_id") or ""),
            job_ids=[str(x) for x in (data.get("job_ids") or [])],
            initial_step_id=_as_int(data.get("initial_step_id"), 10),
            ob_numbers=dict(data.get("ob_numbers") or {}),
            sc_policy=str(data.get("sc_policy") or "SC_ON_COMPLETE"),
        )


@dataclass
class GFCm(_GFEntity):
    """设备（Control Module）；五信号齐备才允许建控制节点边。"""

    id: str = "U1EM1_CM1"
    em_id: str = "U1EM1"
    cm_type: str = "LBC_MotorStarter"
    business_label: str = "上料输送带"
    plcopen: dict[str, bool] = field(default_factory=dict)
    io_binding_ids: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    def has_plcopen_five(self) -> bool:
        """PLCOpen 五信号是否全部显式置位（§3.7.4）。"""
        return all(self.plcopen.get(sig) is True for sig in PLCOPEN_SIGNALS)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFCm":
        return cls(
            id=str(data.get("id") or "U1EM1_CM1"),
            em_id=str(data.get("em_id") or "U1EM1"),
            cm_type=str(data.get("cm_type") or "LBC_MotorStarter"),
            business_label=str(data.get("business_label") or "上料输送带"),
            plcopen=dict(data.get("plcopen") or {}),
            io_binding_ids=[str(x) for x in (data.get("io_binding_ids") or [])],
            parameters=dict(data.get("parameters") or {}),
        )


@dataclass
class GFControlNode(_GFEntity):
    """序列↔设备唯一中枢（字段全部 ir_only）。"""

    id: str = "U1EM1_CN"
    em_id: str = "U1EM1"
    namespace_prefix: str = "U1EM1_"
    sequence_ref: str = "U1EM1_SEQ"
    commands: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFControlNode":
        return cls(
            id=str(data.get("id") or "U1EM1_CN"),
            em_id=str(data.get("em_id") or "U1EM1"),
            namespace_prefix=str(data.get("namespace_prefix") or "U1EM1_"),
            sequence_ref=str(data.get("sequence_ref") or ""),
            commands=[str(x) for x in (data.get("commands") or [])],
            status=[str(x) for x in (data.get("status") or [])],
        )


@dataclass
class GFJob(_GFEntity):
    """作业（LAF_SelectJob 语义）。"""

    id: str = "U1EM1_J1"
    em_id: str = "U1EM1"
    job_id: int = 1
    name: str = "AutoProduction"
    initial_step_id: int = 10
    start_condition: str = "TRUE"
    interlock_id: str | None = None
    single_cycle_job: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFJob":
        return cls(
            id=str(data.get("id") or "U1EM1_J1"),
            em_id=str(data.get("em_id") or "U1EM1"),
            job_id=_as_int(data.get("job_id"), 1),
            name=str(data.get("name") or "AutoProduction"),
            initial_step_id=_as_int(data.get("initial_step_id"), 10),
            start_condition=str(data.get("start_condition") or "TRUE"),
            interlock_id=data.get("interlock_id"),
            single_cycle_job=bool(data.get("single_cycle_job", True)),
        )


@dataclass
class GFStep(_GFEntity):
    """步序；与 ``AfSequenceStep`` 字段对齐，``to_af_project()`` 近零转换。"""

    id: str = "U1EM1_S10"
    em_id: str = "U1EM1"
    job_id: str = "U1EM1_J1"
    step_id: int = 10
    name: str = "STEP_10"
    actions: list[str] = field(default_factory=list)
    transition_condition: str = "TRUE"
    next_step_id: int = 20
    error_step_id: int = 999
    timeout_ms: int = 5000
    branch: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFStep":
        return cls(
            id=str(data.get("id") or "U1EM1_S10"),
            em_id=str(data.get("em_id") or "U1EM1"),
            job_id=str(data.get("job_id") or "U1EM1_J1"),
            step_id=_as_int(data.get("step_id"), 10),
            name=str(data.get("name") or "STEP_10"),
            actions=[str(x) for x in (data.get("actions") or [])],
            transition_condition=str(data.get("transition_condition") or "TRUE"),
            next_step_id=_as_int(data.get("next_step_id"), 0),
            error_step_id=_as_int(data.get("error_step_id"), 999),
            timeout_ms=_as_int(data.get("timeout_ms"), 5000),
            branch=dict(data.get("branch") or {}),
        )


@dataclass
class GFMode(_GFEntity):
    """PackML 模式与迁移许可位集（全部 ir_only）。"""

    id: str = "MODE_AUTO"
    name: str = "Auto"
    business_label: str = "自动模式"
    packml_mode: str = "Production"
    enabled_states: list[str] = field(default_factory=list)
    enabled_transitions: list[str] = field(default_factory=list)
    enable_hold: bool = True
    enable_complete: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFMode":
        return cls(
            id=str(data.get("id") or "MODE_AUTO"),
            name=str(data.get("name") or "Auto"),
            business_label=str(data.get("business_label") or "自动模式"),
            packml_mode=str(data.get("packml_mode") or "Production"),
            enabled_states=[str(x) for x in (data.get("enabled_states") or [])],
            enabled_transitions=[str(x) for x in (data.get("enabled_transitions") or [])],
            enable_hold=bool(data.get("enable_hold", True)),
            enable_complete=bool(data.get("enable_complete", True)),
        )


@dataclass
class GFInterlock(_GFEntity):
    """联锁 / 放行条件；``source == "inferred"`` 自动进「待确认问题」。"""

    id: str = "IL_1"
    target_id: str = ""
    expression: str = "TRUE"
    source: str = "user"
    applies_to: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFInterlock":
        return cls(
            id=str(data.get("id") or "IL_1"),
            target_id=str(data.get("target_id") or ""),
            expression=str(data.get("expression") or "TRUE"),
            source=str(data.get("source") or "user"),
            applies_to=[str(x) for x in (data.get("applies_to") or [])],
        )


@dataclass
class GFIoBinding(_GFEntity):
    """物理冻结铁律唯一通道：业务节点只经适配节点只读接触契约。"""

    id: str = "IOB_1"
    cm_id: str = ""
    direction: str = "IO_READ"
    channel: str = "IO-Mapping"
    compat_ref_id: str = ""
    field_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFIoBinding":
        return cls(
            id=str(data.get("id") or "IOB_1"),
            cm_id=str(data.get("cm_id") or ""),
            direction=str(data.get("direction") or "IO_READ"),
            channel=str(data.get("channel") or "IO-Mapping"),
            compat_ref_id=str(data.get("compat_ref_id") or ""),
            field_path=str(data.get("field_path") or ""),
        )


@dataclass
class GFCompatRef(_GFEntity):
    """指向冻结契约条目的只读引用；``immutable`` 为类级语义常量。"""

    id: str = "CR_IO_TAG_1"
    kind: str = "IO_TAG"
    contract_id: str = ""
    raw_ref: str = ""
    immutable: bool = True
    contract_sha: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFCompatRef":
        # 不可变标记不接受外部覆写（构造后仍为 True）。
        return cls(
            id=str(data.get("id") or "CR_IO_TAG_1"),
            kind=str(data.get("kind") or "IO_TAG"),
            contract_id=str(data.get("contract_id") or ""),
            raw_ref=str(data.get("raw_ref") or ""),
            immutable=True,
            contract_sha=str(data.get("contract_sha") or ""),
        )


@dataclass
class GFEdge(_GFEntity):
    """手动连线的**唯一编辑对象**；三视图共享同一 ``id``。"""

    id: str = "E_HIER_UNIT_EM_U1__U1EM1"
    kind: EdgeKind = EdgeKind.E_HIER_UNIT_EM
    src_id: str = "U1"
    dst_id: str = "U1EM1"
    view_mask: list[str] = field(default_factory=lambda: ["flow"])
    origin: str = "suggested"
    label: str = "层级"
    immutable: bool = False
    created_at: str = ""

    def kind_value(self) -> str:
        """返回边类型字符串（兼容非法外部输入）。"""
        return self.kind.value if isinstance(self.kind, EdgeKind) else str(self.kind)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFEdge":
        raw_kind = data.get("kind") or EdgeKind.E_HIER_UNIT_EM.value
        try:
            kind: Any = EdgeKind(raw_kind)
        except (ValueError, TypeError):
            kind = str(raw_kind)  # 保留原值，交由 validator 以 GF_EDGE_RULE_VIOLATION 拦截
        return cls(
            id=str(data.get("id") or ""),
            kind=kind,
            src_id=str(data.get("src_id") or ""),
            dst_id=str(data.get("dst_id") or ""),
            view_mask=[str(x) for x in (data.get("view_mask") or [])],
            origin=str(data.get("origin") or "suggested"),
            label=str(data.get("label") or ""),
            immutable=bool(data.get("immutable", False)),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass
class GFViewSnapshot(_GFEntity):
    """单个视图的确定性投影快照。"""

    mermaid: str = ""
    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFViewSnapshot":
        return cls(
            mermaid=str(data.get("mermaid") or ""),
            node_ids=[str(x) for x in (data.get("node_ids") or [])],
            edge_ids=[str(x) for x in (data.get("edge_ids") or [])],
        )


@dataclass
class GFViews(_GFEntity):
    """三视图快照；``layout`` 是纯 UI 坐标，明确不进 spec_hash。"""

    flow: GFViewSnapshot = field(default_factory=GFViewSnapshot)
    seq: GFViewSnapshot = field(default_factory=GFViewSnapshot)
    state: GFViewSnapshot = field(default_factory=GFViewSnapshot)
    shared_id_namespace: bool = True
    projection_version: str = PROJECTION_VERSION
    layout: dict[str, Any] = field(default_factory=dict)

    def snapshot(self, view: str) -> GFViewSnapshot:
        """按视图名取快照；未知视图返回空快照（不抛异常，便于前端容错）。"""
        return {"flow": self.flow, "seq": self.seq, "state": self.state}.get(
            view, GFViewSnapshot()
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFViews":
        return cls(
            flow=_entity_of(data, "flow", GFViewSnapshot, GFViewSnapshot()),
            seq=_entity_of(data, "seq", GFViewSnapshot, GFViewSnapshot()),
            state=_entity_of(data, "state", GFViewSnapshot, GFViewSnapshot()),
            shared_id_namespace=bool(data.get("shared_id_namespace", True)),
            projection_version=str(data.get("projection_version") or PROJECTION_VERSION),
            layout=dict(data.get("layout") or {}),
        )


@dataclass
class GFSpecMeta(_GFEntity):
    """冻结元数据（全部 ir_only）。"""

    spec_version: str = "v0"
    spec_hash: str = ""
    prev_spec_hash: str | None = None
    stage: GreenfieldStage = GreenfieldStage.DRAFT
    frozen_at: str | None = None
    frozen_by: str | None = None
    contract_hashes: list[str] = field(default_factory=list)
    receipt_id: str = ""
    open_questions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GFSpecMeta":
        raw_stage = data.get("stage") or GreenfieldStage.DRAFT.value
        try:
            stage: Any = GreenfieldStage(raw_stage)
        except (ValueError, TypeError):
            stage = GreenfieldStage.DRAFT
        return cls(
            spec_version=str(data.get("spec_version") or "v0"),
            spec_hash=str(data.get("spec_hash") or ""),
            prev_spec_hash=data.get("prev_spec_hash"),
            stage=stage,
            frozen_at=data.get("frozen_at"),
            frozen_by=data.get("frozen_by"),
            contract_hashes=[str(x) for x in (data.get("contract_hashes") or [])],
            receipt_id=str(data.get("receipt_id") or ""),
            open_questions=[str(x) for x in (data.get("open_questions") or [])],
        )


@dataclass
class IRPatch(_GFEntity):
    """四种结构化 IRPatch（§3.6.2 M2）：编辑的唯一入口。

    - ``add_edge``    : ``edge`` 必填，追加一条边
    - ``remove_edge`` : ``edge_id`` 必填，删除一条边（系统骨架不可删）
    - ``redirect_edge``: ``edge_id`` + ``src_id`` / ``dst_id``，改向并重建边 ID
    - ``set_ir_only_field``: ``field_path`` + ``value``，只改 ir_only 字段
    """

    op: str = "add_edge"
    edge: GFEdge | None = None
    edge_id: str | None = None
    src_id: str = ""
    dst_id: str = ""
    field_path: str = ""
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "edge": self.edge.to_dict() if self.edge is not None else None,
            "edge_id": self.edge_id,
            "src_id": self.src_id,
            "dst_id": self.dst_id,
            "field_path": self.field_path,
            "value": _to_plain(self.value),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IRPatch":
        raw_edge = data.get("edge")
        edge = GFEdge.from_dict(raw_edge) if isinstance(raw_edge, dict) else None
        return cls(
            op=str(data.get("op") or "add_edge"),
            edge=edge,
            edge_id=data.get("edge_id"),
            src_id=str(data.get("src_id") or ""),
            dst_id=str(data.get("dst_id") or ""),
            field_path=str(data.get("field_path") or ""),
            value=data.get("value"),
        )


#: 四种合法 patch 操作。
IR_PATCH_OPS: frozenset[str] = frozenset(
    {"add_edge", "remove_edge", "redirect_edge", "set_ir_only_field"}
)


@dataclass
class GreenfieldIR(_GFEntity):
    """Greenfield 唯一权威规格（§3.1.1）。

    ``project`` 放在首位，使 ``GreenfieldIR(GFProject(...))`` 与类图
    ``__init__(project: GFProject)`` 兼容。
    """

    project: GFProject = field(default_factory=GFProject)
    ir_version: str = IR_VERSION
    units: list[GFUnit] = field(default_factory=list)
    ems: list[GFEm] = field(default_factory=list)
    cms: list[GFCm] = field(default_factory=list)
    control_nodes: list[GFControlNode] = field(default_factory=list)
    jobs: list[GFJob] = field(default_factory=list)
    steps: list[GFStep] = field(default_factory=list)
    modes: list[GFMode] = field(default_factory=list)
    interlocks: list[GFInterlock] = field(default_factory=list)
    io_bindings: list[GFIoBinding] = field(default_factory=list)
    compat_refs: list[GFCompatRef] = field(default_factory=list)
    edges: list[GFEdge] = field(default_factory=list)
    views: GFViews = field(default_factory=GFViews)
    spec_meta: GFSpecMeta = field(default_factory=GFSpecMeta)

    # ---------- 序列化 ----------

    def to_dict(self) -> dict[str, Any]:
        """输出完整纯 JSON 结构（含 views / spec_meta / edges）。"""
        return {f.name: _to_plain(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GreenfieldIR":
        """从 ``to_dict()`` 结果无损还原（往返无损）。"""
        return cls(
            project=_entity_of(data, "project", GFProject, GFProject()),
            ir_version=str(data.get("ir_version") or IR_VERSION),
            units=_list_of(data, "units", GFUnit),
            ems=_list_of(data, "ems", GFEm),
            cms=_list_of(data, "cms", GFCm),
            control_nodes=_list_of(data, "control_nodes", GFControlNode),
            jobs=_list_of(data, "jobs", GFJob),
            steps=_list_of(data, "steps", GFStep),
            modes=_list_of(data, "modes", GFMode),
            interlocks=_list_of(data, "interlocks", GFInterlock),
            io_bindings=_list_of(data, "io_bindings", GFIoBinding),
            compat_refs=_list_of(data, "compat_refs", GFCompatRef),
            edges=_list_of(data, "edges", GFEdge),
            views=_entity_of(data, "views", GFViews, GFViews()),
            spec_meta=_entity_of(data, "spec_meta", GFSpecMeta, GFSpecMeta()),
        )

    def _canonical_payload(self) -> dict[str, Any]:
        """哈希用载荷：剔除易变字段（§3.5.2）。"""
        payload = copy.deepcopy(self.to_dict())
        payload.get("views", {}).pop("layout", None)
        meta = payload.get("spec_meta") or {}
        for key in ("spec_hash", "frozen_at", "frozen_by", "created_at"):
            meta.pop(key, None)
        for edge in payload.get("edges") or []:
            edge.pop("created_at", None)
        return payload

    def canonical_json(self) -> str:
        """确定性 canonical JSON：同内容必同串（sort_keys / 紧凑分隔）。"""
        return canonical_dumps(self._canonical_payload())

    def ir_sha256(self) -> str:
        """IR 内容哈希（``sha256:<64hex>``），排除布局与冻结元数据。"""
        return sha256_prefixed(self.canonical_json())

    def _replace_from(self, other: "GreenfieldIR") -> None:
        """用候选 IR 的字段整体替换自身（供 ``apply_patch`` 原子提交）。"""
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))

    # ---------- 派生与索引 ----------

    def node_index(self) -> dict[str, dict[str, Any]]:
        """全局 ID → 节点描述（含 kind / label / immutable / 领域字段）。

        虚拟节点（``DB_UNITS`` / ``IOMAP`` / ``OP`` / PackML 状态 / ``ST_*``）
        不在扁平注册表内，由本方法按常量确定性注册，保证三视图共享同一
        ID 命名空间且 ``validate_edge`` 可判定任意端点类型。
        """
        index: dict[str, dict[str, Any]] = {}
        for unit in self.units:
            index[unit.id] = {
                "kind": NodeKind.UNIT.value, "label": unit.business_label or unit.name,
                "immutable": False, "ref": unit, "unit_idx": unit.unit_idx,
                "namespace_prefix": unit.namespace_prefix,
            }
        for em in self.ems:
            index[em.id] = {
                "kind": NodeKind.EM.value, "label": em.business_label or em.name,
                "immutable": False, "ref": em, "unit_id": em.unit_id,
                "em_idx": em.em_idx, "namespace_prefix": em.namespace_prefix,
            }
        for cm in self.cms:
            index[cm.id] = {
                "kind": NodeKind.CM.value, "label": cm.business_label or cm.id,
                "immutable": False, "ref": cm, "em_id": cm.em_id,
                "plcopen": dict(cm.plcopen), "cm_type": cm.cm_type,
            }
        for cn in self.control_nodes:
            index[cn.id] = {
                "kind": NodeKind.CONTROL_NODE.value, "label": "控制节点",
                "immutable": False, "ref": cn, "em_id": cn.em_id,
            }
        for job in self.jobs:
            index[job.id] = {
                "kind": NodeKind.JOB.value, "label": job.name,
                "immutable": False, "ref": job, "em_id": job.em_id,
            }
        for step in self.steps:
            index[step.id] = {
                "kind": NodeKind.STEP.value, "label": step.name,
                "immutable": False, "ref": step, "em_id": step.em_id,
                "branch": dict(step.branch),
            }
        for mode in self.modes:
            index[mode.id] = {
                "kind": NodeKind.MODE.value, "label": mode.business_label,
                "immutable": False, "ref": mode,
            }
        for interlock in self.interlocks:
            index[interlock.id] = {
                "kind": NodeKind.INTERLOCK.value, "label": "联锁",
                "immutable": False, "ref": interlock, "source": interlock.source,
            }
        for binding in self.io_bindings:
            index[binding.id] = {
                "kind": NodeKind.IO_BINDING.value, "label": "信号映射",
                "immutable": False, "ref": binding, "direction": binding.direction,
            }
        for ref in self.compat_refs:
            index[ref.id] = {
                "kind": NodeKind.COMPAT_REF.value, "label": ref.raw_ref,
                "immutable": True, "ref": ref, "raw_ref": ref.raw_ref,
                "contract_id": ref.contract_id, "contract_sha": ref.contract_sha,
            }
        for node_id, kind in VIRTUAL_NODE_IDS.items():
            label = {"DB_UNITS": "接口数据区", "IOMAP": "信号适配层", "OP": "操作员"}[node_id]
            index[node_id] = {
                "kind": kind.value, "label": label,
                "immutable": node_id == "IOMAP", "ref": None,
            }
        for state in PACKML_STATES:
            index[state] = {
                "kind": NodeKind.PACKML_STATE.value, "label": state,
                "immutable": False, "ref": None,
            }
            index[f"ST_{state}"] = {
                "kind": NodeKind.PACKML_STATE.value, "label": state,
                "immutable": False, "ref": None,
            }
        for mode_id in MODE_IDS:
            if mode_id not in index:
                index[mode_id] = {
                    "kind": NodeKind.MODE.value, "label": mode_id,
                    "immutable": False, "ref": None,
                }
        return index

    def ir_only_fields(self) -> list[str]:
        """§3.6.4 十项「只在 IR、不上图」字段组标识。"""
        return list(IR_ONLY_FIELD_KEYS)

    def ir_only_catalog(self) -> list[dict[str, Any]]:
        """十项字段组的结构化目录（供右侧面板渲染表单）。"""
        return [dict(item) for item in IR_ONLY_CATALOG]

    def to_af_project(self) -> AfProject:
        """瞬时派生 ``AfProject``（S6：兼容而非复制，零新增 AF 领域模型）。

        产物只在 Phase 2 生成时现场构造，不落盘、不缓存为会话状态、
        不参与 spec_hash；``GFEdge.view_mask`` / ``GFStep.branch`` 等 IR-only
        信息不会丢失（仍留在 IR 中）。
        """
        units: list[AfUnit] = []
        for unit in self.units:
            af_ems: list[AfEm] = []
            for em in self.ems:
                if em.unit_id != unit.id:
                    continue
                af_jobs = [
                    AfJob(
                        job_id=job.job_id,
                        name=job.name,
                        description=job.start_condition,
                        initial_step=job.initial_step_id,
                    )
                    for job in self.jobs
                    if job.em_id == em.id
                ]
                af_steps = [
                    AfSequenceStep(
                        step_id=step.step_id,
                        name=step.name,
                        description=str(step.branch.get("condition") or ""),
                        actions=list(step.actions),
                        transition_condition=step.transition_condition,
                        next_step_id=step.next_step_id,
                        timeout_ms=step.timeout_ms,
                        error_step_id=step.error_step_id,
                    )
                    for step in self.steps
                    if step.em_id == em.id
                ]
                af_cms = [
                    AfCm(
                        name=cm.id,
                        cm_type=cm.cm_type,  # type: ignore[arg-type]  # Literal 运行期不校验
                        description=cm.business_label,
                        io_mapping={},
                        parameters=dict(cm.parameters),
                    )
                    for cm in self.cms
                    if cm.em_id == em.id
                ]
                first_step = min((s.step_id for s in af_steps), default=em.initial_step_id)
                af_ems.append(
                    AfEm(
                        em_idx=em.em_idx,
                        name=em.name,
                        description=em.business_label,
                        namespace=em.namespace_prefix,
                        jobs=af_jobs or [AfJob(job_id=1, name="AutoProduction", initial_step=first_step)],
                        sequence=AfSequence(
                            initial_step=em.initial_step_id,
                            ready_step=1,
                            steps=af_steps,
                        ),
                        control_modules=af_cms,
                    )
                )
            units.append(
                AfUnit(
                    unit_idx=unit.unit_idx,
                    name=unit.name,
                    description=unit.business_label,
                    namespace=unit.namespace_prefix,
                    equipment_modules=af_ems,
                )
            )
        return AfProject(
            name=self.project.name,
            description=self.project.business_label,
            units=units,
            global_constants={},
        )

    @classmethod
    def from_af_project(
        cls,
        project: AfProject,
        *,
        prompt: str = "",
        contract: Any | None = None,
    ) -> "GreenfieldIR":
        """把 ``planner.plan_af_project_from_spec()`` 的确定性输出提升为强类型 IR。

        纯确定性、零 LLM 依赖（Q2）。命名空间前缀与 OB 号按 ``af_numbering``
        公式派生（Q10）；若与冻结契约已占 OB 号段冲突，写入「待确认问题」。
        """
        ir = cls(project=GFProject(name=project.name, business_label=project.description or project.name))
        occupied_obs: set[int] = set()
        # CM 编号在整份 IR 内全局递增（U1EM1_CM1 / U1EM1_CM2 / U1EM2_CM3 …），
        # 与 docs/greenfield/03-first-mermaid.md 的首版节点 ID 对齐，避免跨工序引用悬空。
        cm_counter = 0
        if contract is not None:
            for entry in getattr(contract, "ob_entries", []) or []:
                number = getattr(entry, "number", None)
                if isinstance(number, int):
                    occupied_obs.add(number)

        for af_unit in project.units:
            uidx = af_unit.unit_idx
            unit_id = f"U{uidx}"
            unit_obs = get_unit_ob_numbers(uidx)
            ir.units.append(
                GFUnit(
                    id=unit_id,
                    unit_idx=uidx,
                    name=af_unit.name,
                    business_label=af_unit.description or af_unit.name,
                    namespace_prefix=f"U{uidx}_",
                    parent_id=None,
                    ob_numbers={
                        "startup": unit_obs.startup,
                        "main": unit_obs.main,
                        "prodiag": unit_obs.prodiag,
                    },
                )
            )
            for number in (unit_obs.startup, unit_obs.main, unit_obs.prodiag):
                if number in occupied_obs:
                    ir.spec_meta.open_questions.append(
                        f"派生 OB 号 {number} 与冻结契约已占号段冲突，请人工确认回避策略"
                    )

            for af_em in af_unit.equipment_modules:
                eidx = af_em.em_idx
                em_id = f"U{uidx}EM{eidx}"
                em_obs = get_em0_ob_numbers(uidx) if eidx == 0 else get_em_ob_numbers(uidx, eidx)
                cn_id = f"{em_id}_CN" if eidx > 0 else ""
                job_ids: list[str] = []
                for af_job in af_em.jobs or []:
                    job_id = f"{em_id}_J{af_job.job_id}"
                    job_ids.append(job_id)
                    ir.jobs.append(
                        GFJob(
                            id=job_id,
                            em_id=em_id,
                            job_id=af_job.job_id,
                            name=af_job.name,
                            initial_step_id=af_job.initial_step,
                            start_condition="TRUE",
                            interlock_id=None,
                            single_cycle_job=True,
                        )
                    )
                if not job_ids:
                    job_id = f"{em_id}_J1"
                    job_ids.append(job_id)
                    ir.jobs.append(
                        GFJob(
                            id=job_id, em_id=em_id, job_id=1, name="AutoProduction",
                            initial_step_id=10, start_condition="TRUE", single_cycle_job=True,
                        )
                    )
                initial_step = min(
                    (s.step_id for s in (af_em.sequence.steps or [])), default=10
                )
                ir.ems.append(
                    GFEm(
                        id=em_id,
                        em_idx=eidx,
                        unit_id=unit_id,
                        name=af_em.name,
                        business_label=af_em.description or af_em.name,
                        namespace_prefix=f"U{uidx}EM{eidx}_",
                        control_node_id=cn_id,
                        job_ids=job_ids,
                        initial_step_id=initial_step,
                        ob_numbers={
                            "startup": em_obs.startup,
                            "main": em_obs.main,
                            "prodiag": em_obs.prodiag,
                        },
                        sc_policy="SC_ON_COMPLETE",
                    )
                )
                for number in (em_obs.startup, em_obs.main, em_obs.prodiag):
                    if number in occupied_obs:
                        ir.spec_meta.open_questions.append(
                            f"派生 OB 号 {number} 与冻结契约已占号段冲突，请人工确认回避策略"
                        )
                if cn_id:
                    ir.control_nodes.append(
                        GFControlNode(
                            id=cn_id,
                            em_id=em_id,
                            namespace_prefix=f"U{uidx}EM{eidx}_",
                            sequence_ref=f"{em_id}_SEQ",
                            commands=["start", "stop", "reset"],
                            status=["stepCurrent", "busy", "error", "stateComplete"],
                        )
                    )
                for af_step in af_em.sequence.steps or []:
                    ir.steps.append(
                        GFStep(
                            id=f"{em_id}_S{af_step.step_id}",
                            em_id=em_id,
                            job_id=job_ids[0],
                            step_id=af_step.step_id,
                            name=af_step.name,
                            actions=list(af_step.actions or []),
                            transition_condition=af_step.transition_condition or "TRUE",
                            next_step_id=af_step.next_step_id,
                            error_step_id=af_step.error_step_id,
                            timeout_ms=af_step.timeout_ms,
                            branch={},
                        )
                    )
                for af_cm in af_em.control_modules or []:
                    cm_counter += 1
                    ir.cms.append(
                        GFCm(
                            id=f"{em_id}_CM{cm_counter}",
                            em_id=em_id,
                            cm_type=af_cm.cm_type if isinstance(af_cm.cm_type, str) else str(af_cm.cm_type),
                            business_label=af_cm.description or af_cm.name,
                            plcopen={sig: True for sig in PLCOPEN_SIGNALS},
                            io_binding_ids=[],
                            parameters=dict(af_cm.parameters or {}),
                        )
                    )

        ir.modes = [
            GFMode(
                id="MODE_AUTO", name="Auto", business_label="自动模式",
                packml_mode="Production", enabled_states=list(PACKML_STATES),
                enabled_transitions=["PACKML_TRANSITIONS"], enable_hold=True, enable_complete=True,
            ),
            GFMode(
                id="MODE_MANUAL", name="Manual", business_label="手动模式",
                packml_mode="Manual", enabled_states=["Stopped", "Idle", "Execute"],
                enabled_transitions=[], enable_hold=False, enable_complete=False,
            ),
        ]
        if contract is not None:
            ir.spec_meta.receipt_id = str(getattr(contract, "receipt_id", "") or "")
            ir.spec_meta.contract_hashes = [str(getattr(contract, "contract_sha", "") or "")]
            ir.compat_refs = _compat_refs_from_contract(contract)
            ir.io_bindings = _io_bindings_from_contract(ir, contract)
        ir.edges = _build_default_edges(ir)
        if prompt:
            ir.project.business_label = ir.project.business_label or prompt[:40]
        return ir

    def apply_patch(self, patch: IRPatch) -> Any:
        """委托给 ``greenfield_validator.apply_patch``（局部 import 避免循环）。

        返回 ``ValidationReport``；非法 patch 原子拒绝，本对象字节不变。
        """
        from plc_engine.af.greenfield_validator import apply_patch as _apply_patch

        return _apply_patch(self, patch)


# ---------------------------------------------------------------------------
# 契约引用注入与默认边集
# ---------------------------------------------------------------------------

def _compat_refs_from_contract(contract: Any) -> list[GFCompatRef]:
    """把冻结契约的 IO / 符号 / OB / 安全条目投影为只读引用（不写契约）。"""
    refs: list[GFCompatRef] = []
    contract_id = str(getattr(contract, "contract_id", "") or "")
    contract_sha = str(getattr(contract, "contract_sha", "") or "")
    for idx, entry in enumerate(getattr(contract, "io_entries", []) or [], start=1):
        refs.append(
            GFCompatRef(
                id=f"CR_IO_TAG_{idx}", kind="IO_TAG", contract_id=contract_id,
                raw_ref=str(getattr(entry, "logical_address", "") or ""),
                immutable=True, contract_sha=contract_sha,
            )
        )
    for idx, entry in enumerate(getattr(contract, "symbols", []) or [], start=1):
        refs.append(
            GFCompatRef(
                id=f"CR_SYMBOL_{idx}", kind="SYMBOL", contract_id=contract_id,
                raw_ref=str(getattr(entry, "raw", "") or ""),
                immutable=True, contract_sha=contract_sha,
            )
        )
    return refs


def _io_bindings_from_contract(ir: GreenfieldIR, contract: Any) -> list[GFIoBinding]:
    """为每个设备分配一条只读映射条目（方向恒 ``IO_READ``）。"""
    refs = ir.compat_refs
    bindings: list[GFIoBinding] = []
    for idx, cm in enumerate(ir.cms, start=1):
        ref = refs[(idx - 1) % len(refs)] if refs else None
        bindings.append(
            GFIoBinding(
                id=f"IOB_{idx}",
                cm_id=cm.id,
                direction="IO_READ",
                channel="IO-Mapping" if idx % 2 else "DB-Adapter",
                compat_ref_id=ref.id if ref is not None else "",
                field_path="status.value",
            )
        )
        if ref is not None:
            cm.io_binding_ids.append(ref.id)
    return bindings


def _make_edge(
    kind: EdgeKind,
    src: str,
    dst: str,
    views: list[str],
    label: str,
    *,
    immutable: bool = False,
    origin: str = "suggested",
) -> GFEdge:
    """构造一条符合 ``E_{KIND}_{src}__{dst}`` 命名规则的边。"""
    return GFEdge(
        id=edge_id(kind, src, dst),
        kind=kind,
        src_id=src,
        dst_id=dst,
        view_mask=list(views),
        origin=origin,
        label=label,
        immutable=immutable,
        created_at="",  # 明确不进哈希；无时间戳也可复现
    )


def _build_default_edges(ir: GreenfieldIR) -> list[GFEdge]:
    """确定性生成首版建议边 / 系统骨架边，覆盖 §4.1 的 12 类合法边。

    留白位 A/B/C（跨工序联锁 / 手动点动 / 工序交接）**故意不预置**（Q6），
    由用户在画布上手动连线；白名单内亦可自由新增其它边。
    """
    edges: list[GFEdge] = []
    for unit in ir.units:
        for em in ir.ems:
            if em.unit_id == unit.id:
                edges.append(
                    _make_edge(
                        EdgeKind.E_HIER_UNIT_EM, unit.id, em.id, ["flow"], "层级",
                        immutable=True, origin="system",
                    )
                )
    root_em = next((em for em in ir.ems if em.em_idx > 0), None)
    if root_em is not None and ir.units:
        edges.append(
            _make_edge(
                EdgeKind.E_MODE_STATE_DOWN, ir.units[0].id, "DB_UNITS", ["flow"], "命令下行"
            )
        )
    for em in ir.ems:
        if em.em_idx == 0 or not em.control_node_id:
            continue
        cn = em.control_node_id
        edges.append(
            _make_edge(EdgeKind.E_CMD_UNIT_EM, "DB_UNITS", em.id, ["flow", "seq"], "下发命令")
        )
        edges.append(
            _make_edge(EdgeKind.E_SC_UP, em.id, "DB_UNITS", ["flow", "seq"], "完成汇总上行")
        )
        edges.append(
            _make_edge(EdgeKind.E_SEQ_TO_CN, em.id, cn, ["flow", "seq"], "步序经控制节点")
        )
        for cm in ir.cms:
            if cm.em_id != em.id:
                continue
            edges.append(
                _make_edge(EdgeKind.E_CN_TO_CM, cn, cm.id, ["flow", "seq"], "命令下发")
            )
            edges.append(
                _make_edge(EdgeKind.E_CM_TO_CN, cm.id, cn, ["flow", "seq"], "状态回读")
            )
            edges.append(
                _make_edge(EdgeKind.E_IO_READ, cm.id, "IOMAP", ["flow"], "只读信号")
            )
    if ir.units:
        edges.append(_make_edge(EdgeKind.E_MSG_STEP, "OP", ir.units[0].id, ["seq"], "选择模式并启动"))
        for em in ir.ems:
            if em.em_idx == 0:
                continue
            edges.append(_make_edge(EdgeKind.E_MSG_STEP, ir.units[0].id, em.id, ["seq"], "作业启动"))
            if em.control_node_id:
                edges.append(
                    _make_edge(EdgeKind.E_MSG_STEP, em.id, em.control_node_id, ["seq"], "作业初始化")
                )
    # 异常分支（alt / else）与手动模式（opt）：结构上收敛到已定义异常态。
    if root_em is not None and root_em.control_node_id:
        edges.append(
            _make_edge(
                EdgeKind.E_BRANCH_ALT_OPT, root_em.control_node_id, "Aborting",
                ["seq"], "异常分支收敛到中止态",
            )
        )
        edges.append(
            _make_edge(
                EdgeKind.E_BRANCH_ALT_OPT, root_em.control_node_id, "Held",
                ["seq"], "手动模式可选段",
            )
        )
    for raw in sorted(PACKML_TRANSITIONS):
        if raw.startswith("[*]"):
            continue
        src, dst = raw.split("->", 1)
        edges.append(
            _make_edge(EdgeKind.E_PACKML_TRANSITION, src, dst, ["state"], "状态迁移")
        )
    edges.append(_make_edge(EdgeKind.E_MODE_SWITCH, "MODE_AUTO", "MODE_MANUAL", ["state"], "切换模式"))
    edges.append(_make_edge(EdgeKind.E_MODE_SWITCH, "MODE_MANUAL", "MODE_AUTO", ["state"], "切换模式"))
    return edges


def _sample_af_project() -> AfProject:
    """构造 ``03-first-mermaid.md`` 示例机型对应的 AfProject（确定性夹具）。"""
    return AfProject(
        name="AssemblyCell",
        description="装配工位",
        units=[
            AfUnit(
                unit_idx=1,
                name="AssemblyCell",
                description="装配工位",
                namespace="U1_",
                equipment_modules=[
                    AfEm(
                        em_idx=0, name="General", description="公共联锁", namespace="U1EM0_",
                        jobs=[], sequence=AfSequence(initial_step=0, ready_step=1, steps=[]),
                        control_modules=[],
                    ),
                    AfEm(
                        em_idx=1, name="Feeding", description="上料工序", namespace="U1EM1_",
                        jobs=[AfJob(job_id=1, name="AutoProduction", initial_step=10)],
                        sequence=AfSequence(
                            initial_step=10, ready_step=1,
                            steps=[
                                AfSequenceStep(
                                    step_id=10, name="WAIT_PART",
                                    actions=["// 等待工件到位"],
                                    transition_condition="#controlNodes.sensorPartPresent.status.signal",
                                    next_step_id=20, timeout_ms=5000, error_step_id=999,
                                ),
                                AfSequenceStep(
                                    step_id=20, name="FEED_FORWARD",
                                    actions=["#controlNodes.motorFeeder.commands.forward := TRUE;"],
                                    transition_condition="#controlNodes.motorFeeder.status.running",
                                    next_step_id=1, timeout_ms=5000, error_step_id=999,
                                ),
                            ],
                        ),
                        control_modules=[
                            AfCm(name="motorFeeder", cm_type="LBC_MotorStarter", description="上料输送带"),
                            AfCm(name="sensorPartPresent", cm_type="LBC_DigitalSignal", description="到位传感器"),
                        ],
                    ),
                    AfEm(
                        em_idx=2, name="Pressing", description="压装工序", namespace="U1EM2_",
                        jobs=[AfJob(job_id=1, name="AutoProduction", initial_step=10)],
                        sequence=AfSequence(
                            initial_step=10, ready_step=1,
                            steps=[
                                AfSequenceStep(
                                    step_id=10, name="CYL_EXTEND",
                                    actions=["#controlNodes.cylPress.commands.workPosition := TRUE;"],
                                    transition_condition="#controlNodes.cylPress.status.inWorkPosition",
                                    next_step_id=20, timeout_ms=3000, error_step_id=999,
                                ),
                                AfSequenceStep(
                                    step_id=20, name="CYL_RETRACT",
                                    actions=["#controlNodes.cylPress.commands.homePosition := TRUE;"],
                                    transition_condition="#controlNodes.cylPress.status.inHomePosition",
                                    next_step_id=1, timeout_ms=3000, error_step_id=999,
                                ),
                                AfSequenceStep(
                                    step_id=900, name="PRESS_TIMEOUT",
                                    actions=["// 异常上报，进入中止"],
                                    transition_condition="TRUE",
                                    next_step_id=999, timeout_ms=3000, error_step_id=999,
                                ),
                            ],
                        ),
                        control_modules=[
                            AfCm(name="cylPress", cm_type="LBC_TwoWayActuator", description="压装气缸"),
                        ],
                    ),
                ],
            )
        ],
    )


def build_sample_ir() -> GreenfieldIR:
    """构造与 ``03-first-mermaid.md`` 示例机型一致的基准 IR（投影夹具 / 首版导出）。

    纯确定性；不含 ``inferred`` 来源的联锁，因而可直接通过校验并冻结。
    """
    ir = GreenfieldIR.from_af_project(_sample_af_project(), prompt="装配工位：上料与压装")
    ir.compat_refs = [
        GFCompatRef(
            id="CR_IO_TAG_1", kind="IO_TAG", contract_id="CC_SAMPLE",
            raw_ref="%I0.0", immutable=True, contract_sha="sha256:sample_contract_sha_placeholder",
        ),
        GFCompatRef(
            id="CR_IO_TAG_2", kind="IO_TAG", contract_id="CC_SAMPLE",
            raw_ref="%Q0.1", immutable=True, contract_sha="sha256:sample_contract_sha_placeholder",
        ),
    ]
    ir.io_bindings = [
        GFIoBinding(
            id="IOB_1", cm_id="U1EM1_CM1", direction="IO_READ", channel="IO-Mapping",
            compat_ref_id="CR_IO_TAG_2", field_path="status.running",
        ),
        GFIoBinding(
            id="IOB_2", cm_id="U1EM1_CM2", direction="IO_READ", channel="IO-Mapping",
            compat_ref_id="CR_IO_TAG_1", field_path="status.signal",
        ),
        GFIoBinding(
            id="IOB_3", cm_id="U1EM2_CM3", direction="IO_READ", channel="DB-Adapter",
            compat_ref_id="CR_IO_TAG_2", field_path="commands.workPosition",
        ),
    ]
    for cm in ir.cms:
        cm.io_binding_ids = [b.id for b in ir.io_bindings if b.cm_id == cm.id]
    ir.interlocks = [
        GFInterlock(
            id="IL_1", target_id="U1EM2_CM3", expression="releaseWork AND releaseHome",
            source="user", applies_to=["U1EM2_S10"],
        )
    ]
    for step in ir.steps:
        if step.step_id == 900:
            step.branch = {"kind": "else", "condition": "压装超时或急停"}
        elif step.step_id == 20 and step.em_id == "U1EM2":
            step.branch = {"kind": "alt", "condition": "气缸在 3000ms 内到达工作位"}
    return ir
