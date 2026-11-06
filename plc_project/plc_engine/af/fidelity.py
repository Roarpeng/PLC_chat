"""Greenfield 1:1 等价性校验器（WP-05 / F7 / F19 / D1 / 契约 §2.5）。

只读、纯函数实现：不写盘、不调 LLM、不碰 Openness、不侵入生成链（契约 §2.5 / §0.8）。

- ``fidelity_ok`` 与 ``compile_ok`` 是两个独立层，禁止互相替代（N9）；本模块
  **不产出任何编译结论**，涉真机项一律标 ``pending_real_machine``，禁止宣称
  L2 / L4 通过或「编译零错误」。
- 输入解耦：规格用 :class:`FrozenSpecLike` Protocol，产物用 ``Mapping[str, bytes|str]``；
  产物内容按约定可携带 JSON 块描述符（见 :func:`_parse_artifact_value`），
  从而无需 import A 的 ``GreenfieldIR`` / ``FrozenSpec`` 具体类。
- 依赖仅限 B 自有的零依赖模块 ``spec_diff`` / ``reverse_guard``。

产物描述符约定（``artifacts`` 的 value 可为 JSON 对象）：

===============  ==========================================================
字段             含义
===============  ==========================================================
source_id        该产物回溯到的 spec 对象 id（必含，框架基线块亦建议携带）
source_kind      对象类别（可选）
framework_baseline  是否为框架基线白名单块（命中基线不计 orphan）
content          实际块内容（SCL 文本等）
content_hash     声明的内容哈希；与 content 重算值不符即「映射字段被改写」
expected_hash    基线 / 映射期望哈希；与内容不符即「基线哈希不匹配」
spec_hash        生成时冻结的 spec_hash；与当前 spec 不符即漂移
ob_number        OB 编号偏差留痕（属不纳入 1:1 的域，禁止静默）
===============  ==========================================================

无法解析为带 ``source_id`` 描述符、且未命中 ``framework_baseline/`` 或非逻辑
资源前缀的产物，一律判为「无来源逻辑块」（orphan）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol

from plc_engine.af.reverse_guard import check_reverse_guard
from plc_engine.af.spec_diff import (
    DEFAULT_FRAMEWORK_BASELINE_VERSION,
    FRAMEWORK_BASELINE_PARTITION,
    SpecDiff,
    canonical_hash,
    extract_source_blocks,
    sha256_prefixed,
    spec_version_of,
)


class FrozenSpecLike(Protocol):
    """校验所需的最小规格协议（解耦 A 的 ``FrozenSpec`` 具体类，契约 §2.5）。"""

    @property
    def project_id(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def ir_snapshot(self) -> Mapping[str, Any]: ...

    @property
    def spec_hash(self) -> str: ...


@dataclass(frozen=True)
class FidelityReport:
    """1:1 等价性报告（契约 §2.5 全字段 + 只读留痕字段）。

    判定公式：``fidelity_ok = coverage==1.0 and orphan==0 and drift==0 and tia_side_drift==0``。
    ``ob_number_deviations`` 属不纳入 1:1 的域，必须留痕但**不参与**判定。
    """

    fidelity_ok: bool
    coverage: float
    orphan: int
    drift: int
    tia_side_drift: int
    mode: str
    base_spec_version: int | None
    changed_source_ids: tuple[str, ...]
    reverse_protection: dict[str, Any]
    coverage_matrix: dict[str, str]
    orphan_blocks: tuple[str, ...]
    drift_items: tuple[dict[str, Any], ...]
    unmapped_spec_objects: tuple[str, ...]
    ob_number_deviations: tuple[dict[str, Any], ...]
    # 以下为附加留痕字段，均不参与 fidelity_ok 判定
    spec_hash: str = ""
    spec_version: int = 0
    framework_baseline_version: str = ""
    product_hash: str = ""
    sampled_source_ids: tuple[str, ...] = ()
    pending_real_machine: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化 dict，便于产出 ``fidelity_report.json``。"""
        return asdict(self)


_NON_LOGIC_PREFIXES = ("framework_baseline/", "plc_tags/", "audit/", "docs/")
_NON_LOGIC_NAMES = frozenset(
    {
        "manifest.json",
        "baseline_manifest.json",
        "fidelity_report.json",
        "fidelity_context.json",
        "af_verification_report.json",
    }
)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_expected_source_ids(spec: Any) -> list[str]:
    """取期望 spec 对象集合：显式 id 列表优先，否则回退到宽松 IR 提取。"""
    snap = _attr(spec, "ir_snapshot", None)
    if isinstance(snap, Mapping):
        for key in ("expected_source_ids", "source_ids", "spec_object_ids"):
            val = snap.get(key)
            if isinstance(val, (list, tuple)) and val:
                return [str(x) for x in val]
    return list(extract_source_blocks(spec).keys())


def _parse_artifact_value(raw: bytes | str) -> dict[str, Any] | None:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _is_non_logic_resource(key: str) -> bool:
    return key in _NON_LOGIC_NAMES or key.startswith(_NON_LOGIC_PREFIXES)


def _actual_content_hash(data: Mapping[str, Any], raw: bytes | str) -> str:
    content = data.get("content")
    if content is not None:
        if isinstance(content, (bytes, str)):
            return sha256_prefixed(content)
        return canonical_hash(content)
    declared = data.get("content_hash") or data.get("sha256")
    if declared:
        return str(declared)
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return sha256_prefixed(text)


def _detect_drift(
    key: str,
    sid: str,
    data: Mapping[str, Any],
    actual: str,
    spec_hash: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    declared_spec = data.get("spec_hash")
    if declared_spec and spec_hash and str(declared_spec) != spec_hash:
        items.append(
            {"target": key, "source_id": sid, "type": "spec_hash_mismatch",
             "expected": spec_hash, "actual": str(declared_spec)}
        )
    declared_content = data.get("content_hash") or data.get("sha256")
    if data.get("content") is not None and declared_content and str(declared_content) != actual:
        items.append(
            {"target": key, "source_id": sid, "type": "declared_content_hash_tampered",
             "expected": str(declared_content), "actual": actual}
        )
    expected = data.get("expected_hash") or data.get("baseline_hash")
    if expected and str(expected) != actual:
        items.append(
            {"target": key, "source_id": sid, "type": "baseline_or_mapping_hash_mismatch",
             "expected": str(expected), "actual": actual}
        )
    return items


class FidelityChecker:
    """1:1 等价性只读校验器（契约 §2.5 / F7 / F19）。

    ``check`` 严格保持契约签名；四指标 ``coverage`` / ``orphan`` / ``drift`` /
    ``tia_side_drift`` 均为纯计算，不改变任何入参、不写盘、不调用生成链。
    """

    def check(
        self,
        spec: "FrozenSpecLike",
        artifacts: Mapping[str, bytes | str],
        *,
        mode: str = "full",
        base_spec_version: int | None = None,
        diff: "SpecDiff | None" = None,
        tia_side_snapshot: Mapping[str, str] | None = None,
    ) -> "FidelityReport":
        if mode not in ("full", "incremental"):
            raise ValueError("mode 必须是 'full' 或 'incremental'")

        spec_hash = str(_attr(spec, "spec_hash", "") or "")
        spec_version = spec_version_of(spec)
        framework_baseline_version = str(
            _attr(spec, "framework_baseline_version", None)
            or _attr(spec, "baseline_version", None)
            or DEFAULT_FRAMEWORK_BASELINE_VERSION
        )
        notes: list[str] = []

        # --- 1) 解析产物，建立映射 / 基线命中 / 孤儿 / 漂移 / OB 留痕 ---
        mapped: dict[str, str] = {}
        content_hash_by_sid: dict[str, str] = {}
        baseline_hits: list[str] = []
        orphan_blocks: list[str] = []
        drift_items: list[dict[str, Any]] = []
        ob_deviations: list[dict[str, Any]] = []

        for key in sorted(artifacts.keys()):
            raw = artifacts[key]
            data = _parse_artifact_value(raw)
            is_baseline_key = key.startswith(FRAMEWORK_BASELINE_PARTITION + "/")

            if key == "baseline_manifest.json" and isinstance(data, Mapping):
                mv = data.get("framework_baseline_version")
                if mv:
                    framework_baseline_version = str(mv)

            if isinstance(data, Mapping) and (data.get("source_id") or data.get("framework_baseline")):
                sid = str(data.get("source_id") or "")
                is_baseline = bool(data.get("framework_baseline")) or is_baseline_key
                actual = _actual_content_hash(data, raw)
                drift_items.extend(_detect_drift(key, sid, data, actual, spec_hash))

                ob = data.get("ob_number") or data.get("ob_number_deviation")
                if isinstance(ob, Mapping):
                    rec: dict[str, Any] = {"source_id": sid or key, "target": key}
                    rec.update({str(k): v for k, v in ob.items()})
                    ob_deviations.append(rec)

                if is_baseline:
                    baseline_hits.append(key)
                    if sid:
                        content_hash_by_sid.setdefault(sid, actual)
                elif sid:
                    mapped.setdefault(sid, key)
                    content_hash_by_sid.setdefault(sid, actual)
            else:
                if is_baseline_key or _is_non_logic_resource(key):
                    baseline_hits.append(key)
                else:
                    orphan_blocks.append(key)

        # --- 2) 期望 spec 对象集合（外部权威，coverage / unmapped 基准）---
        expected_set = set(_extract_expected_source_ids(spec))
        if not expected_set:
            expected_set = set(mapped)
            notes.append("规格未声明期望对象集合,退化为产物自描述口径(coverage 基准=产物声明的 source_id)")

        for sid, tgt in mapped.items():
            if sid not in expected_set:
                orphan_blocks.append(tgt)
                notes.append(f"产物 {tgt} 声明的 source_id={sid} 不在 spec 期望集合中(疑似臆造)")

        # --- 3) coverage / coverage_matrix / unmapped ---
        drifted_targets = {str(d.get("target")) for d in drift_items}
        clean_mapped = {sid: tgt for sid, tgt in mapped.items() if tgt not in drifted_targets}
        mapped_ok = set(clean_mapped) & expected_set
        coverage = len(mapped_ok) / len(expected_set) if expected_set else 1.0
        unmapped = tuple(sorted(expected_set - mapped_ok))
        coverage_matrix = {sid: clean_mapped[sid] for sid in sorted(clean_mapped) if sid in expected_set}

        orphan = len(set(orphan_blocks))
        drift = len(drift_items)

        # --- 4) tia_side_drift + reverse_protection（D10 联动，fail-closed）---
        if tia_side_snapshot is None:
            tia_side_drift = 0
            pending = True
            reverse_protection: dict[str, Any] = {
                "status": "pending_real_machine",
                "allowed": None,
                "drift_count": 0,
                "tia_side_drift": 0,
                "blocked_source_ids": [],
                "reason": "未提供 TIA 侧块快照,本批次为离线校验;涉真机结论标 pending_real_machine,禁止宣称 L2/L4 通过或编译零错误(N9)",
            }
            notes.append("离线校验:未提供 tia_side_snapshot,tia_side_drift 记 0 并标 pending_real_machine,禁止据此宣称真机通过")
        else:
            pending = False
            verdict = check_reverse_guard(content_hash_by_sid, tia_side_snapshot)
            tia_side_drift = verdict.tia_side_drift
            reverse_protection = {
                "status": "evaluated",
                "allowed": verdict.allowed,
                "drift_count": verdict.drift_count,
                "tia_side_drift": verdict.tia_side_drift,
                "blocked_source_ids": list(verdict.blocked_source_ids),
                "reason": verdict.reason,
            }
            if not verdict.allowed:
                notes.append("反向保护触发(fail-closed):TIA 侧漂移,Action C 必须在覆盖前被阻止(D10)")

        # --- 5) 增量字段（mode / base_spec_version / changed_source_ids）---
        if diff is not None:
            changed_ids = tuple(diff.changed_source_ids)
            if base_spec_version is None:
                base_spec_version = diff.base_spec_version
        else:
            changed_ids = ()
            if mode == "incremental":
                notes.append("增量模式未提供 diff,changed_source_ids 为空;建议由 /diff 产物注入")

        sampled: tuple[str, ...] = ()
        if mode == "incremental":
            required_changed = [sid for sid in changed_ids if sid in expected_set]
            missing_changed = [sid for sid in required_changed if sid not in coverage_matrix]
            if missing_changed:
                notes.append("增量模式:变更块 100% 校验未通过,以下变更块未通过 coverage -> " + ", ".join(missing_changed))
            else:
                notes.append("增量模式:变更块 100% 校验通过")
            sampled = tuple(sorted(set(coverage_matrix) - set(changed_ids)))
            notes.append("增量模式:非变更块纳入全量抽检(本实现按全量四指标复核,安全侧更严)")
            if tia_side_drift > 0:
                notes.append("增量模式:tia_side_drift>0,Action C 在步骤 3 即被阻止(§13.5 / §13.6)")

        # --- 6) ob_number_deviations 禁止静默 ---
        if ob_deviations:
            notes.append(
                f"ob_number_deviations 共 {len(ob_deviations)} 条:属不纳入 1:1 的域,"
                "已留痕(禁止静默),不影响 fidelity_ok"
            )
        else:
            notes.append("ob_number_deviations 为空(仍显式留痕,不静默)")

        # --- 7) fidelity_ok（N9：与 compile_ok 独立，此处不产出任何编译结论）---
        fidelity_ok = (
            coverage == 1.0
            and orphan == 0
            and drift == 0
            and tia_side_drift == 0
        )

        product_hash = canonical_hash(
            {
                k: (v.decode("utf-8") if isinstance(v, bytes) else str(v))
                for k, v in sorted(artifacts.items())
            }
        )

        return FidelityReport(
            fidelity_ok=fidelity_ok,
            coverage=coverage,
            orphan=orphan,
            drift=drift,
            tia_side_drift=tia_side_drift,
            mode=mode,
            base_spec_version=base_spec_version,
            changed_source_ids=changed_ids,
            reverse_protection=reverse_protection,
            coverage_matrix=coverage_matrix,
            orphan_blocks=tuple(sorted(set(orphan_blocks))),
            drift_items=tuple(drift_items),
            unmapped_spec_objects=unmapped,
            ob_number_deviations=tuple(ob_deviations),
            spec_hash=spec_hash,
            spec_version=spec_version,
            framework_baseline_version=framework_baseline_version,
            product_hash=product_hash,
            sampled_source_ids=sampled,
            pending_real_machine=pending,
            notes=tuple(notes),
        )
