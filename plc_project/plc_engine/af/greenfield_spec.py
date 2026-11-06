"""Greenfield 冻结 spec：版本号 + 内容哈希 + 三视图快照（T05 / §3.5）。

**门禁语义**：确认动作是 Phase 1 唯一合法副作用。冻结前的 IR / 视图 / 契约
全部驻留内存；``freeze()`` 只构造不可变对象，``write_spec()`` 才落盘，
且只增不改（temp + rename）。哈希排除 frozen_at / frozen_by / layout /
created_at，保证同一份规格可复现。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plc_engine.af.greenfield_contract import CompatContract
from plc_engine.af.greenfield_ir import (
    GFViews,
    GreenfieldIR,
    canonical_dumps,
    sha256_hex,
    sha256_prefixed,
)
from plc_engine.af.greenfield_ports import GreenfieldError, SpecImmutableError

SPEC_HASH_PREFIX = "GF-SPEC-v1"
SPEC_FILE_PREFIX = "v"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FrozenSpec:
    """已冻结规格快照；构造后视为不可变，旧版字节不得改写。"""

    spec_version: int = 1
    spec_hash: str = ""
    prev_spec_hash: str = ""
    ir_sha256: str = ""
    view_hashes: dict[str, str] = field(default_factory=dict)
    contract_sha: str = ""
    ir_version: str = ""
    af_profile: str = ""
    frozen_at: str = ""
    frozen_by: str = ""
    session_id: str = ""
    ir_snapshot: dict[str, Any] = field(default_factory=dict)
    views_snapshot: dict[str, str] = field(default_factory=dict)
    contract_refs: dict[str, Any] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    # ---------- WP-03 / §2.1 追加 ----------
    #: 项目一等公民标识（会话 / 拓扑 / 资料 / 规格 / 产物绑定）。
    project_id: str = ""
    #: 框架基线版本（确认硬门禁前置「基线版本锁定」）。
    framework_baseline_version: str = ""
    #: 快照创建时间（与 frozen_at 同源，不进哈希）。
    created_at: str = ""

    @property
    def version_label(self) -> str:
        return f"{SPEC_FILE_PREFIX}{self.spec_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "spec_hash": self.spec_hash,
            "prev_spec_hash": self.prev_spec_hash,
            "ir_sha256": self.ir_sha256,
            "view_hashes": dict(self.view_hashes),
            "contract_sha": self.contract_sha,
            "ir_version": self.ir_version,
            "af_profile": self.af_profile,
            "frozen_at": self.frozen_at,
            "frozen_by": self.frozen_by,
            "session_id": self.session_id,
            "ir_snapshot": self.ir_snapshot,
            "views_snapshot": dict(self.views_snapshot),
            "contract_refs": self.contract_refs,
            "open_questions": list(self.open_questions),
            "project_id": self.project_id,
            "framework_baseline_version": self.framework_baseline_version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FrozenSpec":
        spec = cls(
            spec_version=int(data.get("spec_version") or 1),
            spec_hash=str(data.get("spec_hash") or ""),
            prev_spec_hash=str(data.get("prev_spec_hash") or ""),
            ir_sha256=str(data.get("ir_sha256") or ""),
            view_hashes=dict(data.get("view_hashes") or {}),
            contract_sha=str(data.get("contract_sha") or ""),
            ir_version=str(data.get("ir_version") or ""),
            af_profile=str(data.get("af_profile") or ""),
            frozen_at=str(data.get("frozen_at") or ""),
            frozen_by=str(data.get("frozen_by") or ""),
            session_id=str(data.get("session_id") or ""),
            ir_snapshot=dict(data.get("ir_snapshot") or {}),
            views_snapshot=dict(data.get("views_snapshot") or {}),
            contract_refs=dict(data.get("contract_refs") or {}),
            open_questions=list(data.get("open_questions") or []),
            project_id=str(data.get("project_id") or ""),
            framework_baseline_version=str(data.get("framework_baseline_version") or ""),
            created_at=str(data.get("created_at") or ""),
        )
        if compute_spec_hash(spec) != spec.spec_hash:
            raise GreenfieldError(
                "冻结 spec 哈希复现失败，内容可能被改写",
                code="GF_SPEC_HASH_MISMATCH",
            )
        return spec

    def recompute_hash(self) -> str:
        return compute_spec_hash(self)

    def rebuild_ir(self) -> GreenfieldIR:
        """仅凭本快照完整重建画布 IR（含逻辑拓扑），不依赖会话内存态（§2.1）。"""
        return GreenfieldIR.from_dict(self.ir_snapshot)

    def rebuild_views(self):
        """由重建的 IR 确定性重投影四视图；验证快照自洽。"""
        from plc_engine.af.greenfield_views import project_views

        return project_views(self.rebuild_ir())


def compute_spec_hash(spec: "FrozenSpec | dict[str, Any]") -> str:
    """§3.5.2 / WP-03 全域口径。

    ``ir_sha256`` 由 ``GreenfieldIR.canonical_json()`` 派生，已覆盖 **拓扑
    (hw_nodes/hw_links/cm_mounts/var_bindings) + 节点 + 边 + 步序 + 资料 +
    project_id + 基线版本** 全域；再叠加版本 / 三视图各自 sha / 契约 / IR 版本 /
    AF 档位 / 项目标识 / 框架基线版本。``frozen_at`` / ``frozen_by`` / ``layout`` /
    ``created_at`` 一律不进哈希，保证同一画布状态两次 ``freeze()`` 哈希一致。
    """
    d = spec.to_dict() if isinstance(spec, FrozenSpec) else dict(spec)
    parts = [
        SPEC_HASH_PREFIX,
        str(d.get("spec_version") or 1),
        str(d.get("project_id") or ""),
        str(d.get("framework_baseline_version") or ""),
        str(d.get("ir_sha256") or ""),
        *[str((d.get("view_hashes") or {}).get(k) or "") for k in ("flow", "seq", "state")],
        str(d.get("contract_sha") or ""),
        str(d.get("ir_version") or ""),
        str(d.get("af_profile") or ""),
    ]
    return sha256_prefixed("|".join(parts))


def freeze(
    ir: GreenfieldIR,
    views: GFViews,
    contract: CompatContract | None,
    *,
    session_id: str = "",
    spec_version: int = 1,
    prev_spec_hash: str = "",
    frozen_by: str = "user",
    frozen_at: str = "",
    project_id: str = "",
    framework_baseline_version: str = "",
) -> FrozenSpec:
    """构造不可变冻结 spec；**不落盘**（落盘由 ``write_spec`` 显式执行）。

    ``ir_snapshot = ir.to_dict()`` 完整含逻辑拓扑（hw_nodes/hw_links/cm_mounts/
    var_bindings），因此 ``specs/vN.json`` 可独立重建画布，不依赖会话内存态。
    快照即确认按钮展示的那一份（§2.1）。
    """
    view_texts = {
        "flow": views.flow.mermaid,
        "seq": views.seq.mermaid,
        "state": views.state.mermaid,
    }
    timestamp = frozen_at or _now_iso()
    spec = FrozenSpec(
        spec_version=spec_version,
        prev_spec_hash=prev_spec_hash,
        ir_sha256=ir.ir_sha256(),
        view_hashes={k: sha256_hex(v) for k, v in view_texts.items()},
        contract_sha=(contract.contract_sha if contract is not None else ""),
        ir_version=ir.ir_version,
        af_profile=ir.project.af_profile,
        frozen_at=timestamp,
        frozen_by=frozen_by,
        session_id=session_id,
        ir_snapshot=ir.to_dict(),
        views_snapshot=view_texts,
        contract_refs=(contract.to_dict() if contract is not None else {}),
        open_questions=list(ir.spec_meta.open_questions or []),
        project_id=project_id or str(getattr(ir, "project_id", "") or ""),
        framework_baseline_version=(
            framework_baseline_version or str(getattr(ir, "baseline_version", "") or "")
        ),
        created_at=timestamp,
    )
    spec.spec_hash = compute_spec_hash(spec)
    return spec


def next_version(specs: list[FrozenSpec]) -> tuple[int, str]:
    """冻结后再次编辑 → 生成 vN+1 草稿，旧版哈希作为 prev。"""
    if not specs:
        return 1, ""
    latest = max(specs, key=lambda s: s.spec_version)
    return latest.spec_version + 1, latest.spec_hash


def spec_path(base_dir: Path, session_id: str, spec: FrozenSpec) -> Path:
    return Path(base_dir) / "greenfield" / session_id / "specs" / f"{spec.version_label}.json"


def write_spec(spec: FrozenSpec, base_dir: Path, session_id: str = "") -> Path:
    """确认后的唯一合法副作用：只增不改，temp + rename 原子写入。

    已存在同名文件时抛 ``SpecImmutableError``，绝不覆写旧版。
    """
    target = spec_path(base_dir, session_id or spec.session_id, spec)
    if target.exists():
        raise SpecImmutableError(
            f"规格 {spec.version_label} 已冻结，不可覆写；请生成新版本",
            details={"path": str(target), "spec_version": spec.spec_version},
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def load_spec(path: Path, project_id: str = "") -> FrozenSpec:
    """从 ``specs/vN.json`` 装载 FrozenSpec（§2.1 / §8）。

    支持传入 ``project_id`` 校验规格归属；规格未绑定项目时保持向后兼容。
    返回值可经 ``rebuild_ir()`` / ``rebuild_views()`` 仅凭该文件完整重建画布。
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    spec = FrozenSpec.from_dict(payload)
    if project_id and spec.project_id and spec.project_id != project_id:
        raise GreenfieldError(
            f"规格 {spec.version_label} 绑定项目 {spec.project_id}，与查询项目 {project_id} 不一致",
            code="GF_SPEC_PROJECT_MISMATCH",
        )
    return spec


def export_md(spec: FrozenSpec) -> str:
    """冻结留痕导出（AC-7），供用户连线确认后归档。"""
    lines = [
        f"# 已确认规格 {spec.version_label}",
        "",
        f"- spec_hash: `{spec.spec_hash}`",
        f"- ir_sha256: `{spec.ir_sha256}`",
        f"- contract_sha: `{spec.contract_sha or '（未上传兼容契约）'}`",
        f"- prev_spec_hash: `{spec.prev_spec_hash or '（首版）'}`",
        f"- frozen_at: {spec.frozen_at} · frozen_by: {spec.frozen_by}",
        f"- af_profile: {spec.af_profile} · ir_version: {spec.ir_version}",
        f"- project_id: {spec.project_id or '（未绑定）'}",
        f"- framework_baseline_version: {spec.framework_baseline_version or '（未锁定）'}",
        "",
        "> 本文件是 Phase 1 出口留痕；**确认后生成标准工程与 TIA V19 回写零错误属 Phase 2，本轮未执行**。",
        "",
    ]
    for key, title in (("flow", "层级与数据流"), ("seq", "步序与异常"), ("state", "模式与状态")):
        lines += [f"## 视图 · {title}", "", "```mermaid", spec.views_snapshot.get(key, ""), "```", ""]
    if spec.open_questions:
        lines += ["## 待确认问题", "", *[f"- {q}" for q in spec.open_questions], ""]
    if spec.contract_refs:
        lines += [
            "## 只读兼容契约",
            "",
            "```json",
            canonical_dumps(spec.contract_refs),
            "```",
            "",
        ]
    return "\n".join(lines)
