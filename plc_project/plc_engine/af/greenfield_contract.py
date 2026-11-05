"""Greenfield 只读冻结契约（§3.4）+ fail-closed 解析回执（§3.4.3）。

契约一经用户确认回执即冻结（Q3）：``CompatContract`` 构造后**任何字段赋值**
抛 ``ContractViolationError(GF_CONTRACT_IMMUTABLE)``；六类物理不可变内容
（DB 布局/偏移/初值、``%I/%Q`` 绝对地址、符号名、OB 编号与调用顺序、
F/安全块、``S7_Optimized_Access``）另有 ``assert_immutable()`` 显式拦截入口。

本模块只依赖标准库与同通道 ``greenfield_ir`` / ``greenfield_ports``，
**不 import 底层 ``io_import`` / ``db_import``**（严格化在 wrapper 层完成）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from plc_engine.af.greenfield_ir import (
    GFCompatRef,
    _as_int,
    canonical_dumps,
    sha256_hex,
    sha256_prefixed,
)
from plc_engine.af.greenfield_ports import ContractViolationError, GateLockedError

#: 六类物理不可变（P0-4 / BR-2）。
IMMUTABLE_CATEGORIES: tuple[str, ...] = (
    "db_layout",          # 布局 / 偏移 / 初值 / data_type / scl_body
    "io_absolute_address",  # %I / %Q 绝对地址
    "symbol_name",        # 符号名
    "ob_number_order",    # OB 编号与调用顺序
    "safety_block",       # F / 安全块
    "optimized_access",   # S7_Optimized_Access 属性
)

#: 六类对应的契约字段路径（用于拦截定位与留痕明细）。
IMMUTABLE_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "db_layout": (
        "db_structs[].members[].offset", "db_structs[].members[].initial_value",
        "db_structs[].members[].data_type", "db_structs[].scl_body",
        "db_structs[].initial_assignments",
    ),
    "io_absolute_address": ("io_entries[].logical_address",),
    "symbol_name": ("io_entries[].name", "symbols[].name", "db_structs[].name"),
    "ob_number_order": ("ob_entries[].number", "ob_entries[].call_order"),
    "safety_block": ("safety_entries[]",),
    "optimized_access": ("db_structs[].optimized_access",),
}


@dataclass
class ContractMutation:
    """一次「写入契约」的尝试描述（供 ``assert_immutable`` 拦截并留痕）。"""

    category: str
    field: str
    value: Any = None


@dataclass(frozen=True)
class IoEntry:
    """IO 表条目（物理地址与符号名只读）。"""

    name: str = ""
    path: str = ""
    data_type: str = ""
    logical_address: str = ""
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IoEntry":
        return cls(
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            data_type=str(data.get("data_type") or ""),
            logical_address=str(data.get("logical_address") or ""),
            comment=str(data.get("comment") or ""),
        )


@dataclass(frozen=True)
class DbMember:
    """DB 成员（点路径名 / 类型 / 初值 / 注释 / 偏移，全部只读）。"""

    name: str = ""
    data_type: str = ""
    initial_value: str = ""
    comment: str = ""
    offset: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DbMember":
        return cls(
            name=str(data.get("name") or ""),
            data_type=str(data.get("data_type") or ""),
            initial_value=str(data.get("initial_value") or ""),
            comment=str(data.get("comment") or ""),
            offset=_as_int(data.get("offset"), 0),
        )


@dataclass(frozen=True)
class DbStruct:
    """一个 ``DATA_BLOCK`` 的完整只读快照（``scl_body`` 逐字保留）。"""

    name: str = ""
    optimized_access: str = "FALSE"
    members: tuple[DbMember, ...] = ()
    initial_assignments: dict[str, str] = field(default_factory=dict)
    scl_body: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "optimized_access": self.optimized_access,
            "members": [m.to_dict() for m in self.members],
            "initial_assignments": dict(self.initial_assignments),
            "scl_body": self.scl_body,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DbStruct":
        return cls(
            name=str(data.get("name") or ""),
            optimized_access=str(data.get("optimized_access") or "FALSE"),
            members=tuple(
                DbMember.from_dict(m) if isinstance(m, dict) else m
                for m in (data.get("members") or [])
            ),
            initial_assignments={str(k): str(v) for k, v in (data.get("initial_assignments") or {}).items()},
            scl_body=str(data.get("scl_body") or ""),
        )


@dataclass(frozen=True)
class ObEntry:
    """OB 编号与调用顺序（只读）。"""

    number: int = 0
    ob_type: str = ""
    call_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObEntry":
        return cls(
            number=_as_int(data.get("number"), 0),
            ob_type=str(data.get("ob_type") or ""),
            call_order=_as_int(data.get("call_order"), 0),
        )


@dataclass(frozen=True)
class SafetyEntry:
    """F / 安全块（只读）。"""

    name: str = ""
    reason: str = "F/安全块物理不可变"

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyEntry":
        return cls(
            name=str(data.get("name") or ""),
            reason=str(data.get("reason") or "F/安全块物理不可变"),
        )


@dataclass(frozen=True)
class SymbolEntry:
    """符号名与原始地址（只读）。"""

    name: str = ""
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SymbolEntry":
        return cls(name=str(data.get("name") or ""), raw=str(data.get("raw") or ""))


@dataclass(frozen=True)
class ReceiptError:
    """一条失败明细：``{file, row, column, code, message}``。"""

    file: str = ""
    row: int = 0
    column: str = ""
    code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReceiptError":
        return cls(
            file=str(data.get("file") or ""),
            row=_as_int(data.get("row"), 0),
            column=str(data.get("column") or ""),
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
        )


@dataclass
class ParseReceipt:
    """fail-closed 解析回执（整批原子拒绝）。

    ``status == "rejected"`` 时 ``items_accepted`` 恒为 0 且不生成契约；
    ``user_confirmed`` 是冻结契约的**前置**（Q3），默认 False。
    ``draft`` 只在内存保存解析草案，不落盘、不计入副作用计数。
    """

    receipt_id: str = ""
    status: str = "parsed"
    items_total: int = 0
    items_accepted: int = 0
    errors: list[ReceiptError] = field(default_factory=list)
    contract_draft_hash: str = ""
    user_confirmed: bool = False
    files: list[str] = field(default_factory=list)
    draft: dict[str, Any] = field(default_factory=dict)
    confirmed_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "status": self.status,
            "items_total": self.items_total,
            "items_accepted": self.items_accepted,
            "errors": [e.to_dict() for e in self.errors],
            "contract_draft_hash": self.contract_draft_hash,
            "user_confirmed": self.user_confirmed,
            "files": list(self.files),
            "draft": self.draft,
            "confirmed_by": self.confirmed_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParseReceipt":
        return cls(
            receipt_id=str(data.get("receipt_id") or ""),
            status=str(data.get("status") or "parsed"),
            items_total=_as_int(data.get("items_total"), 0),
            items_accepted=_as_int(data.get("items_accepted"), 0),
            errors=[
                ReceiptError.from_dict(e) if isinstance(e, dict) else e
                for e in (data.get("errors") or [])
            ],
            contract_draft_hash=str(data.get("contract_draft_hash") or ""),
            user_confirmed=bool(data.get("user_confirmed", False)),
            files=[str(x) for x in (data.get("files") or [])],
            draft=dict(data.get("draft") or {}),
            confirmed_by=str(data.get("confirmed_by") or ""),
        )


class CompatContract:
    """只读冻结契约：构造后不可写，六类物理不可变内容零改动。"""

    def __init__(
        self,
        *,
        receipt_id: str = "",
        frozen_at: str = "",
        io_entries: list[IoEntry] | None = None,
        db_structs: list[DbStruct] | None = None,
        ob_entries: list[ObEntry] | None = None,
        safety_entries: list[SafetyEntry] | None = None,
        symbols: list[SymbolEntry] | None = None,
        compat_notes: list[str] | None = None,
    ) -> None:
        # 构造期统一用 object.__setattr__ 绕过写入拦截；构造完成后密封。
        object.__setattr__(self, "immutable", True)
        object.__setattr__(self, "contract_id", "")
        object.__setattr__(self, "contract_sha", "")
        object.__setattr__(self, "receipt_id", receipt_id)
        object.__setattr__(self, "frozen_at", frozen_at)
        object.__setattr__(self, "io_entries", tuple(io_entries or []))
        object.__setattr__(self, "db_structs", tuple(db_structs or []))
        object.__setattr__(self, "ob_entries", tuple(ob_entries or []))
        object.__setattr__(self, "safety_entries", tuple(safety_entries or []))
        object.__setattr__(self, "symbols", tuple(symbols or []))
        object.__setattr__(self, "compat_notes", tuple(compat_notes or []))
        digest = contract_sha256(self)
        object.__setattr__(self, "contract_sha", digest)
        object.__setattr__(self, "contract_id", f"CC_{digest[-12:]}")

    def __setattr__(self, name: str, value: Any) -> None:
        raise ContractViolationError(
            f"只读冻结契约不可修改（字段 {name}）：六类物理不可变内容零改动",
            details={"field": name, "contract_id": self.contract_id},
        )

    def to_dict(self) -> dict[str, Any]:
        """输出完整只读快照（含 contract_sha，可被 ``from_dict`` 复现）。"""
        return {
            "contract_id": self.contract_id,
            "contract_sha": self.contract_sha,
            "receipt_id": self.receipt_id,
            "frozen_at": self.frozen_at,
            "immutable": self.immutable,
            "io_entries": [e.to_dict() for e in self.io_entries],
            "db_structs": [d.to_dict() for d in self.db_structs],
            "ob_entries": [o.to_dict() for o in self.ob_entries],
            "safety_entries": [s.to_dict() for s in self.safety_entries],
            "symbols": [s.to_dict() for s in self.symbols],
            "compat_notes": list(self.compat_notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompatContract":
        """从只读快照还原；哈希不一致说明内容被篡改，直接拒绝。"""
        contract = cls(
            receipt_id=str(data.get("receipt_id") or ""),
            frozen_at=str(data.get("frozen_at") or ""),
            io_entries=[IoEntry.from_dict(x) for x in (data.get("io_entries") or [])],
            db_structs=[DbStruct.from_dict(x) for x in (data.get("db_structs") or [])],
            ob_entries=[ObEntry.from_dict(x) for x in (data.get("ob_entries") or [])],
            safety_entries=[SafetyEntry.from_dict(x) for x in (data.get("safety_entries") or [])],
            symbols=[SymbolEntry.from_dict(x) for x in (data.get("symbols") or [])],
            compat_notes=[str(x) for x in (data.get("compat_notes") or [])],
        )
        expected = str(data.get("contract_sha") or "")
        if expected and expected != contract.contract_sha:
            raise ContractViolationError(
                "冻结契约内容哈希不一致，可能被篡改，拒绝装载",
                details={"expected": expected, "actual": contract.contract_sha},
            )
        return contract

    def ref(self, kind: str, raw: str) -> GFCompatRef:
        """投影一个只读契约引用（IR 侧 ``GFCompatRef``，``immutable=True``）。"""
        suffix = int(sha256_hex(f"{kind}|{raw}")[:8], 16)
        return GFCompatRef(
            id=f"CR_{kind.upper()}_{suffix}",
            kind=kind.upper(),
            contract_id=self.contract_id,
            raw_ref=raw,
            immutable=True,
            contract_sha=self.contract_sha,
        )

    def assert_immutable(self, mutation: ContractMutation | None = None) -> None:
        """六类物理不可变写入拦截 + 内容完整性校验（G5）。

        Args:
            mutation: 一次写入尝试；非空时必然抛 ``ContractViolationError``。

        Raises:
            ContractViolationError: 契约未冻结、存在写入尝试、或内容被篡改。
        """
        if not self.immutable:
            raise ContractViolationError("契约尚未冻结，不能作为只读边界")
        if mutation is not None:
            category = mutation.category
            reason = (
                "物理冻结铁律：六类内容不可变"
                if category in IMMUTABLE_CATEGORIES
                else "只读冻结契约不接受任何写入"
            )
            raise ContractViolationError(
                f"{reason}（{mutation.field}）",
                details={
                    "category": category,
                    "field": mutation.field,
                    "contract_id": self.contract_id,
                    "value": mutation.value,
                },
            )
        if contract_sha256(self) != self.contract_sha:
            raise ContractViolationError(
                "冻结契约内容已被改动，哈希不复现",
                details={"contract_id": self.contract_id},
            )

    def summary(self) -> dict[str, Any]:
        """面板灰锁清单摘要（A7 ``contract_summary``）。"""
        return {
            "contract_id": self.contract_id,
            "contract_sha": self.contract_sha,
            "receipt_id": self.receipt_id,
            "frozen_at": self.frozen_at,
            "immutable": True,
            "counts": {
                "io_entries": len(self.io_entries),
                "db_structs": len(self.db_structs),
                "db_members": sum(len(d.members) for d in self.db_structs),
                "ob_entries": len(self.ob_entries),
                "safety_entries": len(self.safety_entries),
                "symbols": len(self.symbols),
            },
            "immutable_categories": list(IMMUTABLE_CATEGORIES),
            "compat_notes": list(self.compat_notes),
        }


def _contract_payload(contract: CompatContract) -> dict[str, Any]:
    """哈希载荷：只覆盖条目内容，排除自引用 / 时间戳 / 只读标记。"""
    payload = contract.to_dict()
    for key in ("contract_id", "contract_sha", "frozen_at", "immutable"):
        payload.pop(key, None)
    return payload


def contract_sha256(contract: CompatContract) -> str:
    """契约内容哈希（``sha256:<64hex>``，同内容同值）。"""
    return sha256_prefixed(canonical_dumps(_contract_payload(contract)))


def assert_immutable(
    contract: CompatContract, mutation: ContractMutation | None = None
) -> None:
    """模块级拦截入口；等价于 ``contract.assert_immutable(mutation)``。"""
    contract.assert_immutable(mutation)


def confirm_receipt(receipt: ParseReceipt, by: str = "user") -> ParseReceipt:
    """用户显式确认解析回执（Q3 前置）；不改变内容，只置确认标记。"""
    if receipt.status != "parsed":
        raise GateLockedError(
            "解析回执整批拒绝，不能确认冻结",
            code="GF_UPLOAD_RECEIPT_REJECTED",
            details={"receipt_id": receipt.receipt_id, "errors": [e.to_dict() for e in receipt.errors]},
        )
    receipt.user_confirmed = True
    receipt.confirmed_by = by
    return receipt


def freeze_contract(receipt: ParseReceipt, frozen_at: str = "") -> CompatContract:
    """由**已确认**回执生成只读冻结契约；未确认直接拒绝（Q3 / G5）。"""
    if receipt.status != "parsed":
        raise GateLockedError(
            "解析回执未通过（整批拒绝），禁止冻结契约",
            code="GF_UPLOAD_RECEIPT_REJECTED",
        )
    if not receipt.user_confirmed:
        raise GateLockedError(
            "解析回执尚未由用户确认，禁止冻结契约",
            code="GF_GATE_NOT_CONFIRMED",
            details={"receipt_id": receipt.receipt_id},
        )
    draft = receipt.draft or {}
    contract = CompatContract(
        receipt_id=receipt.receipt_id,
        frozen_at=frozen_at,
        io_entries=[IoEntry.from_dict(x) for x in (draft.get("io_entries") or [])],
        db_structs=[DbStruct.from_dict(x) for x in (draft.get("db_structs") or [])],
        ob_entries=[ObEntry.from_dict(x) for x in (draft.get("ob_entries") or [])],
        safety_entries=[SafetyEntry.from_dict(x) for x in (draft.get("safety_entries") or [])],
        symbols=[SymbolEntry.from_dict(x) for x in (draft.get("symbols") or [])],
        compat_notes=[str(x) for x in (draft.get("compat_notes") or [])],
    )
    return contract
