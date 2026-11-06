"""Greenfield 差异计算与 F6 派生层共享纯函数（WP-04 / F17 / F6 / 契约 §2.3）。

本模块是 B（校验器与派生层）所有权范围内的**零依赖基础模块**：

- 不 import A / C 正在并行修改的任何模块的具体类；规格输入一律用
  ``typing.Protocol`` / ``Mapping`` 解耦，避免并行期签名漂移。
- 仅做纯计算：不写盘、不调 LLM、不碰 Openness、不侵入生成链。

对外提供两类能力：

1. ``spec vN -> vN+1`` 差异计算：``compute_spec_diff`` / ``diff_source_blocks``
   / ``extract_source_blocks``；
2. F6 派生层共享纯函数（供 ``greenfield_delivery.py`` 与 ``fidelity.py`` 复用）：
   ``sha256_prefixed`` / ``canonical_json`` / ``canonical_hash`` /
   ``stable_source_id`` / ``partition_for_block`` / ``build_baseline_manifest`` /
   ``spec_version_of``。

所有哈希均为确定性规范化结果，同输入恒等，支撑 UC-14 可复现。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol


# ---------------------------------------------------------------------------
# 通用哈希工具（确定性、规范化）
# ---------------------------------------------------------------------------

def sha256_prefixed(payload: str | bytes) -> str:
    """返回统一格式 ``sha256:<64hex>``（小写）。"""
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical_json(payload: Any) -> str:
    """把任意可 JSON 化对象规范化为稳定字符串（键排序、ASCII 直引号、无多余空白）。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def canonical_hash(payload: Any) -> str:
    """对 dict / list / 标量做规范化 sha256；相同语义输入恒得相同哈希。"""
    return sha256_prefixed(canonical_json(payload))


# ---------------------------------------------------------------------------
# 契约 §2.3 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceBlock:
    source_id: str
    kind: str
    payload: dict


@dataclass(frozen=True)
class SpecDiff:
    base_spec_version: int
    target_spec_version: int
    changed: tuple[SourceBlock, ...]
    added: tuple[SourceBlock, ...]
    removed: tuple[SourceBlock, ...]
    changed_source_ids: tuple[str, ...]


class SpecLike(Protocol):
    """差异 / 校验所需的最小规格协议（解耦 A 的 ``FrozenSpec`` 具体类）。"""

    @property
    def project_id(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def ir_snapshot(self) -> Mapping[str, Any]: ...

    @property
    def spec_hash(self) -> str: ...


# ---------------------------------------------------------------------------
# 规格版本读取（容错：兼容契约 §2.1 的 version 与现状 spec_version）
# ---------------------------------------------------------------------------

def spec_version_of(spec: Any) -> int:
    """容错读取规格版本号，不依赖具体类。取不到时返回 0。"""
    for attr in ("version", "spec_version"):
        val = spec.get(attr) if isinstance(spec, Mapping) else getattr(spec, attr, None)
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.lstrip("vV").isdigit():
            return int(val.lstrip("vV"))
    return 0


# ---------------------------------------------------------------------------
# 从规格快照宽松提取 source blocks
# ---------------------------------------------------------------------------

_SNAPSHOT_COLLECTION_KEYS = (
    "source_objects", "spec_objects", "objects", "nodes",
    "units", "ems", "cms", "edges", "hw_nodes", "hw_links",
    "var_bindings", "cm_mounts",
)
_EXPLICIT_ID_KEYS = ("expected_source_ids", "source_ids", "spec_object_ids")
_ITEM_ID_KEYS = ("source_id", "id", "name", "node_id")
_ITEM_KIND_KEYS = ("kind", "source_kind", "type", "node_kind", "block_type")


def _first(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def extract_source_blocks(spec: Any) -> dict[str, SourceBlock]:
    """从规格快照宽松提取 ``source_id -> SourceBlock``。

    兼容并行期 A 的 IR 结构漂移：优先读显式 id 列表，其次遍历常见对象集合；
    每个对象优先用自带 ``source_id``，缺失时按 ``<集合键>#<序号>`` 生成稳定 id。
    """
    snap = spec.get("ir_snapshot") if isinstance(spec, Mapping) else getattr(spec, "ir_snapshot", None)
    if not isinstance(snap, Mapping):
        snap = {}
    result: dict[str, SourceBlock] = {}

    explicit = _first(snap, _EXPLICIT_ID_KEYS)
    if isinstance(explicit, (list, tuple)):
        for raw_id in explicit:
            sid = str(raw_id)
            result[sid] = SourceBlock(source_id=sid, kind="spec_object", payload={"source_id": sid})
        return result

    for coll_key in _SNAPSHOT_COLLECTION_KEYS:
        seq = snap.get(coll_key)
        if not isinstance(seq, (list, tuple)):
            continue
        for idx, item in enumerate(seq):
            obj = item if isinstance(item, Mapping) else {"value": item}
            raw_id = _first(obj, _ITEM_ID_KEYS)
            sid = str(raw_id) if raw_id is not None else f"{coll_key}#{idx}"
            raw_kind = _first(obj, _ITEM_KIND_KEYS)
            kind = str(raw_kind) if raw_kind is not None else coll_key
            payload = dict(obj)
            payload.setdefault("source_id", sid)
            result[sid] = SourceBlock(source_id=sid, kind=kind, payload=payload)
    return result


# ---------------------------------------------------------------------------
# 差异计算核心
# ---------------------------------------------------------------------------

def diff_source_blocks(
    base: Mapping[str, SourceBlock],
    target: Mapping[str, SourceBlock],
    base_spec_version: int,
    target_spec_version: int,
) -> SpecDiff:
    """按 ``source_id`` 计算两个块集合的差异（契约 §2.3）。

    ``changed``：两版共有但 ``payload`` 规范化哈希不同的块；
    ``added`` / ``removed``：仅在 target / base 中出现的块；
    ``changed_source_ids``：所有发生变动的 source_id（changed + added + removed），
    供增量 fidelity 对变更块做 100% 校验。
    """
    base_ids = set(base)
    target_ids = set(target)

    added_ids = sorted(target_ids - base_ids)
    removed_ids = sorted(base_ids - target_ids)
    common_ids = sorted(base_ids & target_ids)

    added = tuple(target[sid] for sid in added_ids)
    removed = tuple(base[sid] for sid in removed_ids)
    changed = tuple(
        target[sid]
        for sid in common_ids
        if canonical_hash(base[sid].payload) != canonical_hash(target[sid].payload)
    )
    changed_source_ids = tuple(
        sorted(set(added_ids) | set(removed_ids) | {blk.source_id for blk in changed})
    )

    return SpecDiff(
        base_spec_version=base_spec_version,
        target_spec_version=target_spec_version,
        changed=changed,
        added=added,
        removed=removed,
        changed_source_ids=changed_source_ids,
    )


def compute_spec_diff(
    base_spec: Any,
    target_spec: Any,
    *,
    base_blocks: Mapping[str, SourceBlock] | None = None,
    target_blocks: Mapping[str, SourceBlock] | None = None,
) -> SpecDiff:
    """计算 ``spec vN -> vN+1`` 差异（契约 §2.3 / F17）。

    ``base_spec`` / ``target_spec`` 只需满足 :class:`SpecLike` 协议；版本用
    :func:`spec_version_of` 容错读取。调用方可显式传入 ``base_blocks`` /
    ``target_blocks``，完全绕过 A 的 IR 结构（并行期零耦合）。
    """
    base = base_blocks if base_blocks is not None else extract_source_blocks(base_spec)
    target = target_blocks if target_blocks is not None else extract_source_blocks(target_spec)
    return diff_source_blocks(
        base,
        target,
        spec_version_of(base_spec),
        spec_version_of(target_spec),
    )


# ---------------------------------------------------------------------------
# F6 派生层共享纯函数（greenfield_delivery.py 与 fidelity.py 复用）
# ---------------------------------------------------------------------------

FRAMEWORK_BASELINE_PARTITION = "framework_baseline"
DERIVED_PARTITION = "derived"
DEFAULT_FRAMEWORK_BASELINE_VERSION = "af-basic-folder-1.0"
_FRAMEWORK_BASELINE_FOLDERS = {"01_AF_Standard_Library", "90_Compat_Frozen_Boundary"}


def stable_source_id(
    name: str,
    block_type: str = "",
    af_role: str = "",
    number: Any = None,
) -> str:
    """为派生产物生成**唯一且可复现**的 ``source_id``（F6 / UC-14）。

    仅由块自身稳定属性派生，不依赖会话内存态、时间戳或随机数；
    同名块在同一工程内唯一，故结果稳定且唯一。
    """
    parts = (
        str(block_type or "").upper(),
        str(name or ""),
        str(af_role or ""),
        str(number) if number is not None else "",
    )
    return "::".join(parts)


def partition_for_block(
    folder: str = "",
    name: str = "",
    af_role: str = "",
    block_type: str = "",
) -> str:
    """判定产物分栏：``derived`` 或 ``framework_baseline``（F6 / 契约 §2.6）。

    框架基线白名单：AF 标准库（LAF_ / LBC_）、LegacyCompat 冻结边界、UDT 类型库。
    """
    role = (af_role or "").lower()
    btype = (block_type or "").upper()
    lname = name or ""
    if folder in _FRAMEWORK_BASELINE_FOLDERS:
        return FRAMEWORK_BASELINE_PARTITION
    if lname.startswith(("LAF_", "LBC_")) or btype == "UDT" or role == "legacy_superseded":
        return FRAMEWORK_BASELINE_PARTITION
    return DERIVED_PARTITION


def build_baseline_manifest(
    entries: Iterable[Mapping[str, Any]],
    framework_baseline_version: str = DEFAULT_FRAMEWORK_BASELINE_VERSION,
) -> dict[str, Any]:
    """构建 ``baseline_manifest.json``（契约 §2.6）：基线条目 + 版本 + 内容 sha256。

    确定性：条目按 ``source_id`` 排序、只保留哈希不保留大文本、整体清单计算
    ``manifest_sha256``；同输入两次调用结果恒等（UC-14 可复现）。纯函数，不写盘。
    """
    normalized: list[dict[str, Any]] = []
    for raw in entries:
        item = dict(raw)
        sid = str(item.get("source_id") or item.get("name") or "")
        item["source_id"] = sid
        provided = item.get("content_sha256") or item.get("sha256")
        if provided:
            item["content_sha256"] = str(provided)
        else:
            content = item.get("content", "")
            raw_bytes = content if isinstance(content, (str, bytes)) else canonical_json(content)
            item["content_sha256"] = sha256_prefixed(raw_bytes)
        item.pop("content", None)
        normalized.append(item)
    normalized.sort(key=lambda x: x["source_id"])

    body: dict[str, Any] = {
        "framework_baseline_version": str(framework_baseline_version),
        "entry_count": len(normalized),
        "entries": normalized,
    }
    body["manifest_sha256"] = canonical_hash(body)
    return body
