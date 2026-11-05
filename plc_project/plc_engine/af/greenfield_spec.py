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
        )
        if compute_spec_hash(spec) != spec.spec_hash:
            raise GreenfieldError(
                "冻结 spec 哈希复现失败，内容可能被改写",
                code="GF_SPEC_HASH_MISMATCH",
            )
        return spec

    def recompute_hash(self) -> str:
        return compute_spec_hash(self)


def compute_spec_hash(spec: "FrozenSpec | dict[str, Any]") -> str:
    """§3.5.2 分层口径：版本 + IR + 三视图各自 sha + 契约 + IR 版本 + AF 档位。

    ``frozen_at`` / ``frozen_by`` / ``layout`` / ``created_at`` 一律不进哈希。
    """
    d = spec.to_dict() if isinstance(spec, FrozenSpec) else dict(spec)
    parts = [
        SPEC_HASH_PREFIX,
        str(d.get("spec_version") or 1),
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
) -> FrozenSpec:
    """构造不可变冻结 spec；**不落盘**（落盘由 ``write_spec`` 显式执行）。"""
    view_texts = {
        "flow": views.flow.mermaid,
        "seq": views.seq.mermaid,
        "state": views.state.mermaid,
    }
    spec = FrozenSpec(
        spec_version=spec_version,
        prev_spec_hash=prev_spec_hash,
        ir_sha256=ir.ir_sha256(),
        view_hashes={k: sha256_hex(v) for k, v in view_texts.items()},
        contract_sha=(contract.contract_sha if contract is not None else ""),
        ir_version=ir.ir_version,
        af_profile=ir.project.af_profile,
        frozen_at=frozen_at or _now_iso(),
        frozen_by=frozen_by,
        session_id=session_id,
        ir_snapshot=ir.to_dict(),
        views_snapshot=view_texts,
        contract_refs=(contract.to_dict() if contract is not None else {}),
        open_questions=list(ir.spec_meta.open_questions or []),
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


def load_spec(path: Path) -> FrozenSpec:
    with Path(path).open("r", encoding="utf-8") as handle:
        return FrozenSpec.from_dict(json.load(handle))


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
