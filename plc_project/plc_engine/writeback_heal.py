"""编译错误自愈闭环编排层（docs/plc_chat_v3_0.html Tab5 第二节）。

职责边界 —— 本模块**只编排**：

* 不调 LLM：LLM 以可注入的 ``repair_fn`` 形式进入，测试可在零网络下跑完整闭环；
* 不写盘：``materialize`` 由调用方在拿到干净计划后自行执行；
* 不碰 Openness：编译报错由调用方以 ``list[CompileErrorItem]`` 喂进来。

闭环形态::

    compile errors ──> SelfHealRequest ──> repair_fn ──> 补丁落到 BlockArtifact.source
          ▲                                                        │
          └────────── build_plan 门禁 → lint error 转 CompileErrorItem ◄──┘

每轮结束后**必须重跑门禁**：补丁可能修掉老错也可能引入新错，
``build_plan`` 的 lint error 会被翻译成 ``CompileErrorItem`` 计入下一轮，
绝不允许"带病回写"（与 writeback_pipeline 的 fail-closed 同源）。

五道退出闸（stop_reason）：

* ``clean``            错误清零，成功返回
* ``no_progress``      本轮错误集合与上一轮逐字相同（补丁没起任何作用）
* ``circuit_breaker``  同一块的同类错误连续出现 ``CIRCUIT_THRESHOLD`` 次
* ``max_retries``      达到重试上限
* ``repair_rejected``  repair_fn 放弃（返回 None）或补丁键在源码里定位不到
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from plc_engine.contracts import (
    AvailableStructDefinition,
    CompileErrorItem,
    PatchedSlotDelta,
    SelfHealRequest,
)
from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_linter import Finding
from plc_engine.writeback_pipeline import WritebackBlocked, build_plan

# 连续出现几次同类错误就熔断。2 次即可判定"LLM 在这个错上打转"，再多就是烧 token。
CIRCUIT_THRESHOLD = 2
DEFAULT_MAX_RETRIES = 3

STOP_CLEAN = "clean"
STOP_MAX_RETRIES = "max_retries"
STOP_CIRCUIT_BREAKER = "circuit_breaker"
STOP_REPAIR_REJECTED = "repair_rejected"
STOP_NO_PROGRESS = "no_progress"

__all__ = [
    "CIRCUIT_THRESHOLD",
    "DEFAULT_MAX_RETRIES",
    "STOP_CIRCUIT_BREAKER",
    "STOP_CLEAN",
    "STOP_MAX_RETRIES",
    "STOP_NO_PROGRESS",
    "STOP_REPAIR_REJECTED",
    "CircuitBreaker",
    "HealCircuitOpen",
    "HealOutcome",
    "SlotPatchRejected",
    "apply_slot_patch",
    "build_self_heal_request",
    "findings_to_errors",
    "heal_loop",
    "normalize_error_text",
]


class HealCircuitOpen(RuntimeError):
    """同一块的同类错误连续出现达到阈值，熔断器跳闸。

    由 ``CircuitBreaker.update()`` 抛出；``heal_loop`` 把它翻译成
    ``stop_reason="circuit_breaker"`` 的结果对象。调用方若想 fail-fast，
    可直接用 ``CircuitBreaker`` 而不吞这个异常。
    """


class SlotPatchRejected(RuntimeError):
    """补丁无法落到 SCL 源码上（键为空 / 键在所有块里都找不到）。"""


@dataclass
class HealOutcome:
    """一次自愈闭环的完整审计结果，可直接 ``to_dict`` 给前端。"""

    success: bool
    attempts: int
    final_errors: list[CompileErrorItem] = field(default_factory=list)
    # 每一轮实际发出的结构化载荷，便于事后追责"LLM 当时看到了什么"
    requests: list[SelfHealRequest] = field(default_factory=list)
    stop_reason: str = STOP_CLEAN
    repaired_blocks: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# 错误归一化与熔断
# --------------------------------------------------------------------------


def normalize_error_text(text: str) -> str:
    """同类错误的归一化键：忽略大小写与空白差异。

    刻意**不抹掉数字**：``Q_Valve_R1`` 与 ``Q_Valve_R2`` 是两条不同的错，
    而 ``Line 6`` 这类行号本来就不进这个键（行号只在 no_progress 指纹里）。
    """
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _error_key(item: CompileErrorItem) -> tuple[str, str]:
    return (item.block_name.strip().casefold(), normalize_error_text(item.tia_description))


def _signature(errors: Sequence[CompileErrorItem]) -> frozenset[tuple[str, str, str]]:
    """错误集合指纹，用于 no_progress 判定。"""
    return frozenset(
        (
            e.block_name.strip().casefold(),
            (e.network_or_line or "").strip(),
            normalize_error_text(e.tia_description),
        )
        for e in errors
    )


class CircuitBreaker:
    """按 (块名, 归一化报错) 统计连续出现次数。"""

    def __init__(self, threshold: int = CIRCUIT_THRESHOLD) -> None:
        self.threshold = threshold
        self._streak: dict[tuple[str, str], int] = {}

    def update(self, errors: Sequence[CompileErrorItem]) -> None:
        keys = {_error_key(e) for e in errors}
        # 本轮没再出现的键清零 —— 只认"连续"，中断一次就重新计数
        self._streak = {k: self._streak.get(k, 0) + 1 for k in keys}
        blown = [(k, n) for k, n in self._streak.items() if n >= self.threshold]
        if blown:
            (block, desc), hits = blown[0]
            raise HealCircuitOpen(
                f"块 {block!r} 的同类错误连续出现 {hits} 次，已熔断（阈值 {self.threshold}）：{desc}"
            )

    @property
    def streaks(self) -> dict[tuple[str, str], int]:
        return dict(self._streak)


# --------------------------------------------------------------------------
# 自愈请求载荷
# --------------------------------------------------------------------------


def _build_instruction(
    errors: Sequence[CompileErrorItem],
    struct: AvailableStructDefinition,
    station_id: str,
    attempt: int,
    max_retries: int,
) -> str:
    lines = [
        (
            f"第 {attempt}/{max_retries} 次编译自愈。以下是 TIA 编译器对"
            f"「{station_id or '未指定工站'}」返回的真实报错，请逐条定位到出错的槽位表达式："
        )
    ]
    for item in errors:
        lines.append(
            f"  · {item.block_name}:{item.network_or_line or '-'} — {item.tia_description}"
        )
    if struct.fields:
        lines.append(
            f"结构体 {struct.type_name or '(未命名)'} 的合法字段白名单："
            f"{'、'.join(struct.fields)}。"
            f"只能使用白名单内的字段名，禁止编造或臆测成员名。"
        )
    else:
        lines.append(
            "本次未提供结构体定义：禁止引入任何新的成员名，只能复用报错行中已经出现的符号。"
        )
    lines.append(
        "硬性约束：仅输出修正后的 JSON 槽位（键为出错的槽位/表达式原文，值为修正后的 SCL 片段）；"
        "禁止触碰底层状态机外壳与物理 Q 映射（CASE 骨架、步序转换、Slot 1/2/6 外壳，"
        "以及 %Q 直写一概不动）；不要输出解释性文字，也不要改写未报错的槽位。"
    )
    return "\n".join(lines)


def build_self_heal_request(
    errors: Sequence[CompileErrorItem],
    *,
    attempt: int,
    max_retries: int,
    struct_definition: AvailableStructDefinition | None = None,
    station_id: str = "",
) -> SelfHealRequest:
    """把编译器报错组装成给 LLM 的结构化修复请求。

    ``instruction`` 里强制列出 ``available_struct_definition.fields``，
    是为了堵死"LLM 编造字段名"这条最常见的自愈死循环路径。
    """
    struct = struct_definition or AvailableStructDefinition()
    return SelfHealRequest(
        task="SELF_HEAL_COMPILE_ERROR",
        retry_attempt=attempt,
        max_retries=max_retries,
        compiler_errors=list(errors),
        available_struct_definition=struct,
        instruction=_build_instruction(errors, struct, station_id, attempt, max_retries),
    )


# --------------------------------------------------------------------------
# 补丁落盘（落到内存里的 BlockArtifact.source）
# --------------------------------------------------------------------------


def _ordered_targets(
    blocks: Sequence[BlockArtifact], station_id: str
) -> list[BlockArtifact]:
    """station_id 命中的块优先，其余块兜底。"""
    if not station_id:
        return list(blocks)
    needle = station_id.strip().casefold()
    preferred = [b for b in blocks if needle in b.name.casefold()]
    if not preferred:
        return list(blocks)
    preferred_ids = {id(b) for b in preferred}
    return preferred + [b for b in blocks if id(b) not in preferred_ids]


def apply_slot_patch(
    blocks: Sequence[BlockArtifact], delta: PatchedSlotDelta
) -> list[str]:
    """把 ``PatchedSlotDelta.patch`` 应用到 ``BlockArtifact.source``，返回改动的块名。

    语义：patch 的键是**出错的槽位/表达式原文**（那一小段 SCL），值是修正后的 SCL 片段。
    定位顺序：``delta.station_id`` 命中的块优先，其次在全部块里找第一个含该键的块。
    任一键定位不到就整批拒绝（``SlotPatchRejected``），绝不半改半留 ——
    半个补丁比不打补丁危险得多。
    """
    if not delta.patch:
        raise SlotPatchRejected("补丁为空，没有任何槽位可应用")

    targets = _ordered_targets(blocks, delta.station_id)
    pending: dict[str, list[tuple[str, str]]] = {}
    for key, value in delta.patch.items():
        if not key.strip():
            raise SlotPatchRejected("补丁键为空，无法定位槽位表达式")
        hit = next((b for b in targets if key in b.source), None)
        if hit is None:
            raise SlotPatchRejected(f"补丁键在源码中找不到：{key!r}")
        pending.setdefault(hit.name, []).append((key, value))

    by_name = {b.name: b for b in blocks}
    changed: list[str] = []
    for name, replacements in pending.items():
        block = by_name[name]
        source = block.source
        for key, value in replacements:
            source = source.replace(key, value)
        if source != block.source:
            block.source = source
            changed.append(name)
    return changed


# --------------------------------------------------------------------------
# 门禁
# --------------------------------------------------------------------------


def findings_to_errors(findings: Sequence[Finding]) -> list[CompileErrorItem]:
    """静态门禁 error → 编译错误条目（warning 不阻断，不计入）。"""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    return [
        CompileErrorItem(
            block_name=f.block,
            network_or_line=f"L{f.line}" if f.line else "",
            tia_description=f"[{f.rule}] {f.message}",
            block_path="",
            timestamp=stamp,
        )
        for f in findings
        if f.severity == "error"
    ]


def _run_gate(
    blocks: Sequence[BlockArtifact],
    seeds: Iterable[str] | None,
    cache: Mapping[str, str] | None,
) -> tuple[list[CompileErrorItem], Mapping[str, str] | None]:
    """重跑一次 build_plan 门禁，把 error 翻成 CompileErrorItem。

    契约允许门禁失败有两种形态：返回 ``has_errors`` 的计划，或直接抛
    ``WritebackBlocked``；两种都收敛成同一批 CompileErrorItem。
    """
    try:
        plan = build_plan(blocks, seeds=seeds, cache=cache)
    except WritebackBlocked as exc:
        return findings_to_errors(exc.findings), cache
    if plan.has_errors:
        return findings_to_errors(plan.findings), cache
    return [], plan.cache


def _valid_seeds(
    blocks: Sequence[BlockArtifact], seeds: Iterable[str] | None
) -> list[str] | None:
    """只保留真实存在的块名；全被过滤掉时退化为全量（None）。

    dependents_closure 对不存在的种子会抛 KeyError，回写批次宁可放大也不能崩。
    """
    if seeds is None:
        return None
    known = {b.name.casefold(): b.name for b in blocks}
    picked = [known[s.casefold()] for s in seeds if s.casefold() in known]
    return picked or None


# --------------------------------------------------------------------------
# 主闭环
# --------------------------------------------------------------------------


def heal_loop(
    blocks: Sequence[BlockArtifact],
    initial_errors: Sequence[CompileErrorItem],
    repair_fn: Callable[[SelfHealRequest], PatchedSlotDelta | None],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    seeds: Iterable[str] | None = None,
    cache: Mapping[str, str] | None = None,
    struct_definition: AvailableStructDefinition | None = None,
) -> HealOutcome:
    """编译错误自愈主循环。

    ``repair_fn`` 接收本轮的 :class:`SelfHealRequest`，返回
    :class:`PatchedSlotDelta`（放弃修复则返回 ``None``）。它是唯一的 LLM 入口，
    因此整个闭环可以在没有模型的情况下被完整测试。
    """
    errors = list(initial_errors)
    requests: list[SelfHealRequest] = []
    repaired: list[str] = []
    breaker = CircuitBreaker()
    cache_state: Mapping[str, str] | None = dict(cache) if cache is not None else None
    active_seeds = _valid_seeds(blocks, seeds)
    attempts = 0
    prev_signature: frozenset[tuple[str, str, str]] | None = None

    # 没有编译报错不代表一定干净：先跑一次门禁确认（补丁之外的块也可能带病）。
    if not errors:
        errors, cache_state = _run_gate(blocks, active_seeds, cache_state)
        if not errors:
            return HealOutcome(
                success=True,
                attempts=0,
                final_errors=[],
                requests=requests,
                stop_reason=STOP_CLEAN,
                repaired_blocks=repaired,
            )

    def stop(reason: str) -> HealOutcome:
        return HealOutcome(
            success=False,
            attempts=attempts,
            final_errors=list(errors),
            requests=list(requests),
            stop_reason=reason,
            repaired_blocks=list(repaired),
        )

    while errors:
        signature = _signature(errors)

        # 1. 无进展：本轮错误集合与上一轮逐字相同，再问一次 LLM 也是浪费
        if prev_signature is not None and signature == prev_signature:
            return stop(STOP_NO_PROGRESS)

        # 2. 熔断：同一块的同类错误连续出现，先于 max_retries 生效
        try:
            breaker.update(errors)
        except HealCircuitOpen:
            return stop(STOP_CIRCUIT_BREAKER)

        # 3. 重试上限
        if attempts >= max_retries:
            return stop(STOP_MAX_RETRIES)

        attempts += 1
        request = build_self_heal_request(
            errors,
            attempt=attempts,
            max_retries=max_retries,
            struct_definition=struct_definition,
            station_id=errors[0].block_name,
        )
        requests.append(request)

        delta = repair_fn(request)
        if delta is None:
            return stop(STOP_REPAIR_REJECTED)
        try:
            changed = apply_slot_patch(blocks, delta)
        except SlotPatchRejected:
            return stop(STOP_REPAIR_REJECTED)
        if not changed:
            # 补丁键找得到但替换后源码一字未变，等价于"什么都没修"
            return stop(STOP_REPAIR_REJECTED)

        for name in changed:
            if name not in repaired:
                repaired.append(name)
        # 被改过的块全部进批次（连同它们的下游），下一轮门禁在这批块上重跑
        active_seeds = _valid_seeds(blocks, repaired)

        prev_signature = signature
        errors, cache_state = _run_gate(blocks, active_seeds, cache_state)

    return HealOutcome(
        success=True,
        attempts=attempts,
        final_errors=[],
        requests=list(requests),
        stop_reason=STOP_CLEAN,
        repaired_blocks=list(repaired),
    )
