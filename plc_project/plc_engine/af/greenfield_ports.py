"""Greenfield 通道：阶段枚举、门禁异常与 Phase 2 交付接口位。

本模块是 ``greenfield_*`` 领域层的公共基础，只依赖 Python 标准库。

**Phase 2 边界（Q7 / R1 裁定）**：``DeliveryPort`` 只作为接口位（Protocol）
存在，本轮**零实现体、零 import 回写链、零并线**。任何生成 / 回写 / 打包
动作都不在 Phase 1 范围内；真机 TIA Portal V19 编译零错误是 Phase 2 出口。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover —— 仅类型检查期引用，运行期零 import
    from plc_engine.af.greenfield_spec import FrozenSpec

#: Phase 2 交付结果 DTO（本轮不构造、不消费）。
DeliveryResult = dict[str, Any]


class GreenfieldStage(str, Enum):
    """阶段状态机（§4.2）。字符串枚举便于 JSON 序列化与前端比较。"""

    DRAFT = "DRAFT"
    LINKABLE = "LINKABLE"
    VALIDATING = "VALIDATING"
    FROZEN = "FROZEN"
    LOCKED = "LOCKED"


PHASE2_PIPELINE_DOC = """见 docs/greenfield/02-architecture.md §9：
P2-1 装载复现 → P2-2 IR 瞬时派生 AfProject → P2-3 生成标准工程 →
P2-4 SCL 源包 + SimaticML XML 补充包 + 标签表 → P2-5 四层静态门禁 →
P2-6 PCEC 账本（事务 / 基线 / V0-V3，基线变化 fail-closed）→
P2-7 并线交付 + 回写 → P2-8 TIA V19 编译零错误（唯一验收口径）→ P2-9 HMI（不在范围）。
本轮（Phase 1）不实现、不并线、不触碰 writeback_pipeline / pcec /
compile_jobs / refactor_pipeline / C# 回写栈，仅保留 DeliveryPort 接口位。"""

#: R7 业务化徽章文案（默认可见，零 AF / 架构 / 软件单元 / Unit / EM / CM 术语）。
STAGE_BADGES: dict[GreenfieldStage, str] = {
    GreenfieldStage.DRAFT: "草稿",
    GreenfieldStage.LINKABLE: "可连线",
    GreenfieldStage.VALIDATING: "校验中",
    GreenfieldStage.FROZEN: "已冻结",
    GreenfieldStage.LOCKED: "已锁定",
}

#: 阶段 → 允许的动作集合。``assert_gate`` 的唯一裁定表（§4.3 G1）。
STAGE_ALLOWED_ACTIONS: dict[GreenfieldStage, frozenset[str]] = {
    GreenfieldStage.DRAFT: frozenset(
        {"read", "upload", "receipt_confirm", "draft", "validate", "views", "export", "stage", "spec"}
    ),
    GreenfieldStage.LINKABLE: frozenset(
        {"read", "upload", "receipt_confirm", "link", "validate", "views", "export", "stage", "spec"}
    ),
    GreenfieldStage.VALIDATING: frozenset(
        {"read", "link", "validate", "confirm", "views", "export", "stage", "spec"}
    ),
    GreenfieldStage.FROZEN: frozenset(
        {"read", "views", "export", "stage", "spec", "begin_edit"}
    ),
    GreenfieldStage.LOCKED: frozenset({"read"}),
}

#: 越阶段操作的解释性提示，禁止静默失败（P0-11 / AC-4）。
LOCKED_HINT = "规格尚未确认，确认前禁止任何生成或写回"

#: 确认前一律禁止的写类动作（含预览式生成），后端二次拦截用。
FORBIDDEN_PREGATE_ACTIONS: frozenset[str] = frozenset(
    {
        "generate",
        "generate_project",
        "writeback",
        "confirm-writeback",
        "compile-jobs",
        "generate-from-requirement",
        "generate-from-mermaid",
        "refactor",
        "chat-ops",
        "disk_write",
    }
)


@runtime_checkable
class DeliveryPort(Protocol):
    """Phase 2 交付通道接口位。

    本轮**无任何实现体**；方法体是 Protocol 的标准签名占位，不表示可调用。
    实现方（Phase 2 的 ``greenfield_delivery.py``）必须先并线对话主链并挂
    PCEC 账本，基线变化 fail-closed；本文件不 import 任何回写链模块。
    """

    def deliver(self, spec: "FrozenSpec") -> DeliveryResult:
        """把已冻结 spec 交付为工程并回写编译（Phase 2，本轮不实现）。"""
        ...

    def assert_pcec_gate(self, spec: "FrozenSpec") -> None:
        """PCEC 事务 / 基线 / V0-V3 门禁（Phase 2，本轮不实现）。"""
        ...


class GreenfieldError(Exception):
    """Greenfield 领域异常基类，统一携带 ``GF_`` 前缀错误码。"""

    default_code: str = "GF_ERROR"

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code: str = code or self.default_code
        self.message: str = message or self.code
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """序列化为网关错误体 ``{code, message, details}``。"""
        return {"code": self.code, "message": self.message, "details": self.details or None}


class GateLockedError(GreenfieldError):
    """越阶段 / 确认门禁未满足（HTTP 409）。"""

    default_code = "GF_GATE_LOCKED"


class ContractViolationError(GreenfieldError):
    """对只读冻结契约六类物理不可变内容的写入尝试（HTTP 400）。"""

    default_code = "GF_CONTRACT_IMMUTABLE"


class EdgeRejectedError(GreenfieldError):
    """连线白名单拒绝（HTTP 422，附带 view / node_id 定位）。"""

    default_code = "GF_EDGE_REJECTED"


class ViewProjectionError(GreenfieldError):
    """三视图结构层 roundtrip 不一致（HTTP 422）。"""

    default_code = "GF_VIEW_PROJECTION"


class SpecImmutableError(GreenfieldError):
    """试图覆写已冻结的旧版 spec（HTTP 409）。"""

    default_code = "GF_SPEC_IMMUTABLE"
