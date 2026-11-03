"""回写链路编排层。

把三个独立能力串成一条 fail-closed 的流水线：

    mark_interface_change  →  dependents_closure  →  lint  →  filter_dirty  →  bundle

设计原则来自 docs/plc_chat_v3_0.html 的两条硬约束：

1. **fail-closed**：静态门禁出现 error 就不允许产出文件，绝不允许"带病回写"。
   回写是破坏性操作，宁可整批拒绝，也不能把半个批次写进博途。
2. **接口变更必须连带下游**：改了 UDT 字段，所有直接或间接依赖它的块
   （含背景 DB、调用链上的 OB）都要一起进批次，否则博途会报接口时间戳不一致。

本模块只做编排，不做任何解析或代码生成；所有能力来自：
    plc_engine.writeback_contract  共享 DTO
    plc_engine.dependency_closure  反向闭包与接口传播
    plc_engine.writeback_linter    五条静态门禁
    plc_engine.mega_source         拓扑排序 / 脏块过滤 / 单文件打包
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from plc_engine.dependency_closure import (
    ClosureResult,
    dependents_closure,
    mark_interface_change,
)
from plc_engine.mega_source import BundleResult, bundle, filter_dirty
from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_linter import Finding, lint_bundle


@dataclass
class WritebackPlan:
    """一次回写的完整决策结果，可直接序列化给前端做审阅。"""

    # 闭包选中的块名（含种子），已按 type_order + 名称排序
    selected: list[str]
    # 块名 -> 入选原因（seed / depends-on:X / interface-propagation:X / external:X）
    reasons: dict[str, str]
    # 依赖闭包的最大实际深度
    max_depth: int
    # 因 sha256 命中缓存而未写入的块
    skipped_unchanged: list[str] = field(default_factory=list)
    # 依赖了但本次批次未提供的块（通常是博世 LAF 标准库）
    external_dependencies: list[str] = field(default_factory=list)
    # 门禁结果；存在 severity == "error" 时 planned_text 为空
    findings: list[Finding] = field(default_factory=list)
    # 最终要写盘的 SCL 文本（未通过门禁时为 None）
    planned_text: str | None = None
    # 打包后的实际写出顺序
    block_names: list[str] = field(default_factory=list)
    # 供下一轮复用的 hash 缓存（全量，不是只含脏块）
    cache: dict[str, str] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    @property
    def writable(self) -> bool:
        return self.planned_text is not None and not self.has_errors


class WritebackBlocked(RuntimeError):
    """门禁未通过，拒绝生成回写文件。"""

    def __init__(self, findings: Sequence[Finding]) -> None:
        errors = [f for f in findings if f.severity == "error"]
        lines = [f"[{f.rule}] {f.block}:{f.line or '-'} {f.message}" for f in errors]
        super().__init__(
            f"静态门禁拦截 {len(errors)} 条 error，已拒绝回写：\n" + "\n".join(lines)
        )
        self.findings = list(findings)
        self.errors = errors


def _index(blocks: Sequence[BlockArtifact]) -> dict[str, BlockArtifact]:
    return {b.name.lower(): b for b in blocks}


def build_plan(
    blocks: Sequence[BlockArtifact],
    *,
    seeds: Iterable[str] | None = None,
    cache: Mapping[str, str] | None = None,
    bom_enabled: bool = True,
    propagate_interface: bool = True,
) -> WritebackPlan:
    """计算一次回写计划，但不写盘。

    seeds 为 None 时视为全量重建（所有块都进批次）。
    显式给 seeds 时只回写这些块及其全部下游。
    """
    if not blocks:
        return WritebackPlan(selected=[], reasons={}, max_depth=0, cache=dict(cache or {}))

    # 1. 接口变更沿正向依赖向下游传播，并把结果作为新列表
    prepared = list(mark_interface_change(blocks)) if propagate_interface else list(blocks)

    # 2. 反向依赖闭包
    if seeds is None:
        closure = ClosureResult(
            selected=[b.name for b in prepared],
            reasons={b.name: "seed" for b in prepared},
            max_depth=0,
        )
    else:
        closure = dependents_closure(prepared, seeds)

    by_name = _index(prepared)
    selected_blocks = [by_name[n.lower()] for n in closure.selected if n.lower() in by_name]

    # 3. 静态门禁（fail-closed）
    findings = lint_bundle(selected_blocks, bom_enabled=bom_enabled)
    plan = WritebackPlan(
        selected=list(closure.selected),
        reasons=dict(closure.reasons),
        max_depth=closure.max_depth,
        findings=findings,
    )
    if plan.has_errors:
        return plan

    # 4. 脏块过滤
    if cache is None:
        dirty, new_cache = selected_blocks, {b.name: b.sha256() for b in selected_blocks}
        skipped: list[str] = []
    else:
        dirty, new_cache = filter_dirty(selected_blocks, cache)
        dirty_names = {b.name.lower() for b in dirty}
        skipped = [b.name for b in selected_blocks if b.name.lower() not in dirty_names]

    # 5. 单文件打包。全部命中缓存时 bundle 会产出空文本，属正常情形。
    result: BundleResult = bundle(dirty, keep_unchanged=True)
    plan.skipped_unchanged = skipped
    plan.external_dependencies = list(result.external_dependencies)
    plan.block_names = list(result.block_names)
    plan.planned_text = result.text
    plan.cache = new_cache
    return plan


def materialize(plan: WritebackPlan, out_path: str | Path) -> Path:
    """把计划写成带 BOM 的 .scl。门禁未通过或无可写内容时拒绝。"""
    if plan.has_errors:
        raise WritebackBlocked(plan.findings)
    if not plan.planned_text:
        raise ValueError("计划中没有可写内容（可能全部命中脏块缓存）")

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.planned_text, encoding="utf-8-sig", newline="\n")
    return path


def plan_for_block_names(
    blocks: Sequence[BlockArtifact],
    names: Iterable[str],
    **kwargs: object,
) -> WritebackPlan:
    """便捷入口：按块名发起增量回写。"""
    return build_plan(blocks, seeds=names, **kwargs)  # type: ignore[arg-type]
