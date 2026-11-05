"""Greenfield 连线白名单：边类型、节点类型、规则常量与非法边目录。

权威规格见 ``docs/greenfield/02-architecture.md §3.7 / §8``。本模块是**纯常量 +
纯函数**，不 import 任何存量重构 / 回写链模块，也不依赖 ``greenfield_ir``，
以避免循环导入。

口径说明（§3.7.1）：架构表按 **12 行 / 12 类规则**组织（L1–L12），其中 L12
含两种具体 ``EdgeKind``（``E_PACKML_TRANSITION`` / ``E_MODE_SWITCH``），L1–L11
各一种，另 L2 的层级骨架边 ``E_HIER_EM_CM`` 亦为合法具体类型。因此
``EdgeKind`` 共 13 个具体值，归入 12 个规则组（``LEGAL_EDGE_GROUPS``）。
**规则集合是代码常量，不可配置；仅拦截文案可配置（P2-4）。**
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class EdgeKind(str, Enum):
    """12 类合法边规则对应的 13 个具体边类型（§3.7.1）。"""

    E_HIER_UNIT_EM = "E_HIER_UNIT_EM"
    E_HIER_EM_CM = "E_HIER_EM_CM"
    E_MODE_STATE_DOWN = "E_MODE_STATE_DOWN"
    E_CMD_UNIT_EM = "E_CMD_UNIT_EM"
    E_SC_UP = "E_SC_UP"
    E_SEQ_TO_CN = "E_SEQ_TO_CN"
    E_CN_TO_CM = "E_CN_TO_CM"
    E_CM_TO_CN = "E_CM_TO_CN"
    E_IO_READ = "E_IO_READ"
    E_MSG_STEP = "E_MSG_STEP"
    E_BRANCH_ALT_OPT = "E_BRANCH_ALT_OPT"
    E_PACKML_TRANSITION = "E_PACKML_TRANSITION"
    E_MODE_SWITCH = "E_MODE_SWITCH"


class NodeKind(str, Enum):
    """IR 节点分类；虚拟节点（接口数据区 / 适配层 / 操作员）也在其中。"""

    UNIT = "UNIT"
    EM = "EM"
    CM = "CM"
    CONTROL_NODE = "CONTROL_NODE"
    INTERFACE_DB = "INTERFACE_DB"
    IO_MAPPING = "IO_MAPPING"
    COMPAT_REF = "COMPAT_REF"
    MODE = "MODE"
    PACKML_STATE = "PACKML_STATE"
    OPERATOR = "OPERATOR"
    JOB = "JOB"
    STEP = "STEP"
    INTERLOCK = "INTERLOCK"
    IO_BINDING = "IO_BINDING"
    UNKNOWN = "UNKNOWN"


#: 视图标识（与 ``GFEdge.view_mask`` 一致）。
VIEW_FLOW = "flow"
VIEW_SEQ = "seq"
VIEW_STATE = "state"
ALL_VIEWS: tuple[str, str, str] = (VIEW_FLOW, VIEW_SEQ, VIEW_STATE)


@dataclass(frozen=True)
class EdgeRule:
    """一条合法边规则：允许的端点类型、投影视图、附加约束。"""

    src_kinds: frozenset[NodeKind]
    dst_kinds: frozenset[NodeKind]
    views: tuple[str, ...]
    immutable: bool = False
    requires: tuple[str, ...] = ()
    note: str = ""


def _kinds(*names: str) -> frozenset[NodeKind]:
    """把 NodeKind 名（字符串）转成 frozen set，避免大量重复字面量。"""
    return frozenset(NodeKind(name) for name in names)


#: 12 行规则 → 具体 kind 分组（``LEGAL_EDGE_GROUPS`` 长度恒为 12）。
LEGAL_EDGE_GROUPS: dict[str, tuple[EdgeKind, ...]] = {
    "L1": (EdgeKind.E_HIER_UNIT_EM,),
    "L2": (EdgeKind.E_HIER_EM_CM,),
    "L3": (EdgeKind.E_MODE_STATE_DOWN,),
    "L4": (EdgeKind.E_CMD_UNIT_EM,),
    "L5": (EdgeKind.E_SC_UP,),
    "L6": (EdgeKind.E_SEQ_TO_CN,),
    "L7": (EdgeKind.E_CN_TO_CM,),
    "L8": (EdgeKind.E_CM_TO_CN,),
    "L9": (EdgeKind.E_IO_READ,),
    "L10": (EdgeKind.E_MSG_STEP,),
    "L11": (EdgeKind.E_BRANCH_ALT_OPT,),
    "L12": (EdgeKind.E_PACKML_TRANSITION, EdgeKind.E_MODE_SWITCH),
}

#: §4.1 建议边清单的 12 类（不含 L2 系统骨架 EM→CM）；供「12 类合法边全放行」回归。
PRIMARY_LEGAL_EDGE_KINDS: tuple[EdgeKind, ...] = (
    EdgeKind.E_HIER_UNIT_EM,
    EdgeKind.E_MODE_STATE_DOWN,
    EdgeKind.E_CMD_UNIT_EM,
    EdgeKind.E_SC_UP,
    EdgeKind.E_SEQ_TO_CN,
    EdgeKind.E_CN_TO_CM,
    EdgeKind.E_CM_TO_CN,
    EdgeKind.E_IO_READ,
    EdgeKind.E_MSG_STEP,
    EdgeKind.E_BRANCH_ALT_OPT,
    EdgeKind.E_PACKML_TRANSITION,
    EdgeKind.E_MODE_SWITCH,
)

#: 白名单矩阵：kind.value → EdgeRule。校验器以 ``ALLOWED_EDGES`` 为唯一裁定。
ALLOWED_EDGES: dict[str, EdgeRule] = {
    EdgeKind.E_HIER_UNIT_EM.value: EdgeRule(
        src_kinds=_kinds("UNIT"),
        dst_kinds=_kinds("EM"),
        views=(VIEW_FLOW,),
        immutable=True,
        requires=("unique_parent",),
        note="层级唯一父：dst.unit_id == src.id；系统骨架不可删除",
    ),
    EdgeKind.E_HIER_EM_CM.value: EdgeRule(
        src_kinds=_kinds("EM"),
        dst_kinds=_kinds("CM"),
        views=(VIEW_FLOW,),
        immutable=True,
        requires=("unique_parent",),
        note="层级唯一父：dst.em_id == src.id；系统骨架不可删除",
    ),
    EdgeKind.E_MODE_STATE_DOWN.value: EdgeRule(
        src_kinds=_kinds("UNIT"),
        dst_kinds=_kinds("INTERFACE_DB"),
        views=(VIEW_FLOW, VIEW_STATE),
        requires=("via_interface_db",),
        note="命令下行只经接口数据区",
    ),
    EdgeKind.E_CMD_UNIT_EM.value: EdgeRule(
        src_kinds=_kinds("INTERFACE_DB"),
        dst_kinds=_kinds("EM"),
        views=(VIEW_FLOW, VIEW_SEQ),
        requires=("dataflow_down",),
        note="数据流单向：Unit → EM，禁止直连设备",
    ),
    EdgeKind.E_SC_UP.value: EdgeRule(
        src_kinds=_kinds("EM"),
        dst_kinds=_kinds("INTERFACE_DB"),
        views=(VIEW_FLOW, VIEW_SEQ),
        requires=("dataflow_up",),
        note="仅完成汇总上行（EM → 接口数据区），方向恒单向",
    ),
    EdgeKind.E_SEQ_TO_CN.value: EdgeRule(
        src_kinds=_kinds("EM"),
        dst_kinds=_kinds("CONTROL_NODE"),
        views=(VIEW_FLOW, VIEW_SEQ),
        requires=("via_control_node",),
        note="序列↔设备只经控制节点",
    ),
    EdgeKind.E_CN_TO_CM.value: EdgeRule(
        src_kinds=_kinds("CONTROL_NODE"),
        dst_kinds=_kinds("CM"),
        views=(VIEW_FLOW, VIEW_SEQ),
        requires=("plcopen_out",),
        note="出向必须携带 enable，设备五信号齐备",
    ),
    EdgeKind.E_CM_TO_CN.value: EdgeRule(
        src_kinds=_kinds("CM"),
        dst_kinds=_kinds("CONTROL_NODE"),
        views=(VIEW_FLOW, VIEW_SEQ),
        requires=("plcopen_in",),
        note="入向必须携带 valid/busy/error/status，设备五信号齐备",
    ),
    EdgeKind.E_IO_READ.value: EdgeRule(
        src_kinds=_kinds("CM"),
        dst_kinds=_kinds("IO_MAPPING"),
        views=(VIEW_FLOW,),
        requires=("io_read_only",),
        note="只读；必须经 IO-Mapping / DB-Adapter 适配节点，方向恒只读；"
             "直接连契约条目由 GF_EDGE_CONTRACT_BYPASS 拦截",
    ),
    EdgeKind.E_MSG_STEP.value: EdgeRule(
        src_kinds=_kinds("OPERATOR", "UNIT", "EM", "CONTROL_NODE", "CM", "INTERFACE_DB"),
        dst_kinds=_kinds("OPERATOR", "UNIT", "EM", "CONTROL_NODE", "CM", "INTERFACE_DB"),
        views=(VIEW_SEQ,),
        requires=(),
        note="步序消息：参与方须在白名单内",
    ),
    EdgeKind.E_BRANCH_ALT_OPT.value: EdgeRule(
        src_kinds=_kinds("STEP", "EM", "CONTROL_NODE"),
        dst_kinds=_kinds("STEP", "PACKML_STATE", "EM"),
        views=(VIEW_SEQ, VIEW_STATE),
        requires=("branch_balanced",),
        note="alt/opt 首臂进主链，else 臂收敛到 Aborting/Aborted 或 Holding/Held",
    ),
    EdgeKind.E_PACKML_TRANSITION.value: EdgeRule(
        src_kinds=_kinds("PACKML_STATE"),
        dst_kinds=_kinds("PACKML_STATE"),
        views=(VIEW_STATE,),
        requires=("packml_table",),
        note="迁移必须落在 PACKML_TRANSITIONS 许可表",
    ),
    EdgeKind.E_MODE_SWITCH.value: EdgeRule(
        src_kinds=_kinds("MODE"),
        dst_kinds=_kinds("MODE"),
        views=(VIEW_STATE,),
        requires=("mode_switch_only",),
        note="仅自动模式 ↔ 手动模式互切，不得连到状态节点",
    ),
}


@dataclass(frozen=True)
class IllegalEdgeRule:
    """一条非法边目录项：错误码 + 拦截理由 + 定位视图。"""

    code: str
    reason: str
    view: str
    description: str


#: 10 类非法边（I1–I10）→ 错误码 / 理由。100% 拦截，错误码不可配置。
ILLEGAL_EDGE_CATALOG: dict[str, IllegalEdgeRule] = {
    "I1": IllegalEdgeRule(
        "GF_EDGE_CROSS_LAYER_CM",
        "违反层级唯一父（工位→工序→设备），必须经工序",
        VIEW_FLOW,
        "工位直连设备",
    ),
    "I2": IllegalEdgeRule(
        "GF_EDGE_CM_DIRECT",
        "数据流必须经控制节点 / 接口数据区，禁止设备间直连",
        VIEW_FLOW,
        "设备 → 设备（同/跨工序）直连",
    ),
    "I3": IllegalEdgeRule(
        "GF_EDGE_CROSS_EM",
        "跨工序交换只经接口数据区，禁止工序间直连",
        VIEW_FLOW,
        "工序 → 工序直连",
    ),
    "I4": IllegalEdgeRule(
        "GF_EDGE_BYPASS_CN",
        "序列只与控制节点交互，禁止直连设备引脚",
        VIEW_FLOW,
        "工序（序列）→ 设备 绕过控制节点",
    ),
    "I5": IllegalEdgeRule(
        "GF_EDGE_CONTRACT_WRITE",
        "物理冻结六类不可变；只读契约不允许写入边",
        VIEW_FLOW,
        "任意节点 → 只读契约条目的写向边",
    ),
    "I6": IllegalEdgeRule(
        "GF_EDGE_CONTRACT_BYPASS",
        "新逻辑只经适配节点访问；工序/工位只见接口数据区",
        VIEW_FLOW,
        "绕过 IO-Mapping / DB-Adapter 直接连契约条目",
    ),
    "I7": IllegalEdgeRule(
        "GF_EDGE_PACKML_ILLEGAL",
        "不在许可表；动作态/等待态迁移规则",
        VIEW_STATE,
        "非法状态迁移（如 Execute → Idle 直跳）",
    ),
    "I8": IllegalEdgeRule(
        "GF_EDGE_PLCOPEN_MISSING",
        "设备必须 enable/valid/busy/error/status 五信号齐备",
        VIEW_FLOW,
        "控制节点 ↔ 设备边但五信号不齐",
    ),
    "I9": IllegalEdgeRule(
        "GF_EDGE_NAMESPACE_INVALID",
        "命名空间前缀规则；防与冻结契约符号重名",
        VIEW_FLOW,
        "节点 ID 缺前缀或与冻结契约符号名冲突",
    ),
    "I10": IllegalEdgeRule(
        "GF_EDGE_BRANCH_UNBALANCED",
        "异常分支必须收敛到中止/保持态，且 Mermaid 结构合法",
        VIEW_SEQ,
        "else 异常臂未落到已定义异常态 / alt 与 end 不配对",
    ),
}

#: 全部 ``GF_EDGE_*`` 拦截码（含校验器附加的通用规则码）。
EDGE_ERROR_CODES: frozenset[str] = frozenset(
    {rule.code for rule in ILLEGAL_EDGE_CATALOG.values()}
    | {"GF_EDGE_RULE_VIOLATION", "GF_EDGE_IMMUTABLE", "GF_EDGE_UNKNOWN_NODE", "GF_EDGE_VIEW_MASK"}
)


#: PackML 17 态（§8）。
PACKML_STATES: tuple[str, ...] = (
    "Clearing",
    "Stopped",
    "Resetting",
    "Idle",
    "Starting",
    "Execute",
    "Stopping",
    "Holding",
    "Held",
    "Unholding",
    "Suspending",
    "Suspended",
    "Unsuspending",
    "Completing",
    "Completed",
    "Aborting",
    "Aborted",
)

#: 命令集合（§8）。
PACKML_COMMANDS: tuple[str, ...] = (
    "Start", "Stop", "Reset", "Clear", "Hold",
    "Suspend", "Abort", "Unhold", "Unsuspend", "Complete",
)


def _transition(*pairs: tuple[str, str]) -> frozenset[str]:
    """把 (src, dst) 元组规范化为 ``src->dst`` 许可集合。"""
    return frozenset(f"{a}->{b}" for a, b in pairs)


#: 合法迁移许可表（§3.7.3，17 态；``[*]`` 为起始伪态）。
PACKML_TRANSITIONS: frozenset[str] = _transition(
    ("[*]", "Stopped"),
    ("Stopped", "Resetting"),
    ("Completed", "Resetting"),
    ("Resetting", "Idle"),
    ("Idle", "Starting"),
    ("Starting", "Execute"),
    ("Execute", "Completing"),
    ("Completing", "Completed"),
    ("Execute", "Holding"),
    ("Holding", "Held"),
    ("Held", "Unholding"),
    ("Unholding", "Execute"),
    ("Execute", "Suspending"),
    ("Suspending", "Suspended"),
    ("Suspended", "Unsuspending"),
    ("Unsuspending", "Execute"),
    ("Execute", "Stopping"),
    ("Stopping", "Stopped"),
    ("Execute", "Aborting"),
    ("Completing", "Aborting"),
    ("Aborting", "Aborted"),
    ("Aborted", "Clearing"),
    ("Clearing", "Stopped"),
)

#: 异常分支必须收敛到的态（I10 裁定）。
BRANCH_TERMINAL_STATES: frozenset[str] = frozenset(
    {"Aborting", "Aborted", "Holding", "Held"}
)

#: PLCOpen 五信号（§3.7.4）。
PLCOPEN_SIGNALS: tuple[str, ...] = ("enable", "valid", "busy", "error", "status")
PLCOPEN_OUT_SIGNALS: tuple[str, ...] = ("enable",)
PLCOPEN_IN_SIGNALS: tuple[str, ...] = ("valid", "busy", "error", "status")

#: 模式节点 ID 白名单。
MODE_IDS: frozenset[str] = frozenset({"MODE_AUTO", "MODE_MANUAL", "MODE_MAINTENANCE"})
MODE_SWITCH_PAIRS: frozenset[str] = frozenset({"MODE_AUTO->MODE_MANUAL", "MODE_MANUAL->MODE_AUTO"})

#: 虚拟节点 ID → NodeKind（IR 中不落实体，由 ``node_index()`` 确定性注册）。
VIRTUAL_NODE_IDS: dict[str, NodeKind] = {
    "DB_UNITS": NodeKind.INTERFACE_DB,
    "IOMAP": NodeKind.IO_MAPPING,
    "OP": NodeKind.OPERATOR,
}

#: 命名空间规则（§3.7.4 / §8）。key 为实体类别，value 为锚定正则。
NAMESPACE_RULES: dict[str, str] = {
    "unit_id": r"^U[1-9]$",
    "em_id": r"^U[1-9]EM(?:0|[1-9][0-9]?)$",
    "cm_id": r"^U[1-9]EM(?:0|[1-9][0-9]?)_?CM[1-9][0-9]*$",
    "control_node_id": r"^U[1-9]EM(?:0|[1-9][0-9]?)_?CN$",
    "step_id": r"^U[1-9]EM(?:0|[1-9][0-9]?)_?S[0-9]+$",
    "job_id": r"^U[1-9]EM(?:0|[1-9][0-9]?)_?J[0-9]+$",
    "mode_id": r"^MODE_(?:AUTO|MANUAL|MAINTENANCE)$",
    "packml_state_id": r"^ST_[A-Za-z]+$",
    "compat_ref_id": r"^CR_[A-Z_]+_[0-9]+$",
    "io_binding_id": r"^IOB_[0-9]+$",
    "interlock_id": r"^IL_[0-9]+$",
    "edge_id": r"^E_[A-Z_]+_[A-Za-z0-9_]+__[A-Za-z0-9_]+$",
    "unit_prefix": r"^U[1-9]_$",
    "em_prefix": r"^U[1-9]EM(?:0|[1-9][0-9]?)_$",
    "scl_identifier": r"^[A-Za-z_][A-Za-z0-9_]*$",
}

_COMPILED_NAMESPACE_RULES: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern) for key, pattern in NAMESPACE_RULES.items()
}


def matches_namespace(category: str, value: str) -> bool:
    """判断 ``value`` 是否符合某类命名空间规则；未知类别返回 False。"""
    pattern = _COMPILED_NAMESPACE_RULES.get(category)
    if pattern is None:
        return False
    return pattern.match(value) is not None


def edge_id(kind: EdgeKind | str, src_id: str, dst_id: str) -> str:
    """构造全局唯一边 ID：``E_{KIND}_{src}__{dst}``（§8）。"""
    kind_value = kind.value if isinstance(kind, EdgeKind) else str(kind)
    return f"{kind_value}_{src_id}__{dst_id}"


def is_packml_transition(src: str, dst: str) -> bool:
    """查询迁移是否在 ``PACKML_TRANSITIONS`` 许可表内。"""
    return f"{src}->{dst}" in PACKML_TRANSITIONS


def is_legal_edge_kind(kind: EdgeKind | str) -> bool:
    """查询边类型是否在白名单内。"""
    kind_value = kind.value if isinstance(kind, EdgeKind) else str(kind)
    return kind_value in ALLOWED_EDGES


def illegal_codes() -> list[str]:
    """返回 10 类非法边的错误码（I1–I10 顺序），供测试与前端白名单展示。"""
    return [ILLEGAL_EDGE_CATALOG[key].code for key in sorted(ILLEGAL_EDGE_CATALOG)]


def rule_for(kind: EdgeKind | str) -> EdgeRule | None:
    """按边类型取规则；不在白名单返回 None。"""
    kind_value = kind.value if isinstance(kind, EdgeKind) else str(kind)
    return ALLOWED_EDGES.get(kind_value)


def as_dict() -> dict[str, Any]:
    """导出常量表摘要（供 API A7 的白名单面板使用，纯数据、不可变语义）。"""
    return {
        "edge_kinds": [k.value for k in EdgeKind],
        "legal_edge_groups": {g: [k.value for k in ks] for g, ks in LEGAL_EDGE_GROUPS.items()},
        "node_kinds": [k.value for k in NodeKind],
        "illegal_catalog": {
            key: {
                "code": rule.code,
                "reason": rule.reason,
                "view": rule.view,
                "description": rule.description,
            }
            for key, rule in ILLEGAL_EDGE_CATALOG.items()
        },
        "packml_states": list(PACKML_STATES),
        "packml_transitions": sorted(PACKML_TRANSITIONS),
        "plcopen_signals": list(PLCOPEN_SIGNALS),
        "mode_ids": sorted(MODE_IDS),
        "namespace_rules": dict(NAMESPACE_RULES),
    }
