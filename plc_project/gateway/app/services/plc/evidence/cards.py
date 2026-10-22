"""Evidence-gated PLC block cards for chat."""

from __future__ import annotations

from typing import Any

from .blocks import (
    _block_assoc_lines,
    _block_io_lists,
    _block_network_titles,
    _call_relation_names,
)
from .nested import _format_nested_fb_line, _format_typed_as_nest_lines
from .optimize import _block_risk_notes
from .scl import (
    _folded_logic_lines,
    _format_block_scl_markdown,
    _format_scl_logic_block,
    _purpose_from_fold,
)
from .shared import _join_capped

__all__ = [
    "_describe_block_function",
    "_explain_block_understanding",
    "_focused_optimize_advice",
    "_format_block_runtime_explain",
]


def _explain_block_understanding(
    job: dict[str, Any],
    block_name: str,
    block: dict[str, Any],
    *,
    folded: list[str],
    reads: list[str],
    writes: list[str],
) -> str:
    """Narrative「理解」line — role in project, not a SCL dump."""
    comment = str(block.get("comment") or "").strip()
    titles = _block_network_titles(job, block_name)
    callers, callees = _call_relation_names(job, block_name)
    btype = str(block.get("type") or "块")
    bits: list[str] = [f"`{block_name}` 是工程中的 {btype}"]
    if comment:
        bits.append(f"注释为「{comment}」")
    if callers:
        bits.append("由 " + "、".join(f"`{c}`" for c in callers[:6]) + " 调用")
    if callees:
        bits.append("向下调用 " + "、".join(f"`{c}`" for c in callees[:8]))
    if titles:
        bits.append("主要网络/步序：" + " → ".join(titles[:10]))
    else:
        fold_purpose = _purpose_from_fold(folded, reads, writes)
        if fold_purpose and "无足够" not in fold_purpose:
            bits.append(fold_purpose.rstrip("。"))
    if reads or writes:
        io_bits = []
        if reads:
            io_bits.append("读 " + "、".join(reads[:6]))
        if writes:
            io_bits.append("写 " + "、".join(writes[:6]))
        bits.append("；".join(io_bits))
    return "；".join(bits) + "。"


def _describe_block_function(
    job: dict[str, Any],
    block_name: str,
    block: dict[str, Any],
    *,
    include_full_scl: bool = False,
) -> list[str]:
    """Concise card: role / IO / calls / ≤5 steps. Full SCL only on demand.

    Target: ≤12 lines so canvas click answers stay scannable.
    """
    comment = str(block.get("comment") or "").strip()
    instance_of = str(block.get("instance_of") or "").strip()
    interface_only = bool(block.get("interface_only"))
    protected = bool(block.get("protected"))
    body_available = block.get("body_available")
    if body_available is None:
        body_available = not interface_only and not (
            protected and int(block.get("networks") or 0) == 0
        )
    reads, writes, iface_inout = _block_io_lists(job, block_name, block)
    folded = _folded_logic_lines(job, block_name)
    if not folded:
        scl = (job.get("scl_sources") or {}).get(block_name) or ""
        folded = [
            ln.strip().rstrip(";")
            for ln in scl.splitlines()
            if (":=" in ln or "=>" in ln or "(" in ln)
            and not ln.strip().startswith("//")
            and not ln.strip().startswith("(*")
            and not ln.strip().upper().startswith("NETWORK")
            and "VAR" not in ln.upper().split()[:1]
        ][:8]

    titles = _block_network_titles(job, block_name)
    callers, callees = _call_relation_names(job, block_name)
    lines: list[str] = []

    if interface_only or (protected and not body_available):
        lines.append("状态：接口开放 · 程序体不可用（不臆测内部逻辑）")
        purpose = comment or "封装功能块；结合接口与上下游调用理解角色。"
        lines.append(f"理解：{purpose}")
        lines.append(f"作用：{purpose}")
    else:
        understanding = _explain_block_understanding(
            job, block_name, block, folded=folded, reads=reads, writes=writes
        )
        # Keep「理解」to one short clause when possible
        if len(understanding) > 160:
            understanding = understanding[:157].rstrip("；。,，") + "…"
        lines.append(f"理解：{understanding}")
        lines.append(f"作用：{_purpose_from_fold(folded, reads, writes)}")

    lines.append(f"输入：{_join_capped(reads) if reads else '（无已验证读取）'}")
    lines.append(f"输出：{_join_capped(writes) if writes else '（无已验证写入）'}")
    if iface_inout and not (set(iface_inout) <= set(reads) & set(writes)):
        lines.append(f"InOut：{_join_capped(iface_inout, limit=4)}")

    call_bits: list[str] = []
    if callers:
        call_bits.append("被调用：" + _join_capped(callers, limit=4))
    if callees:
        call_bits.append("调用：" + _join_capped(callees, limit=4))
    if call_bits:
        lines.append("；".join(call_bits))
    elif instance_of:
        lines.append(f"实例类型：`{instance_of}`")

    assoc = _block_assoc_lines(job, block_name)
    for line in assoc:
        if line.startswith("使用") or line.startswith("被使用"):
            lines.append(line)

    nest_line = None if include_full_scl else _format_nested_fb_line(job, block_name)
    if nest_line:
        lines.append(nest_line)

    step_titles = titles[:5]
    if step_titles:
        lines.append("逻辑：" + " → ".join(step_titles))
    elif folded:
        # One-line logic peek (no code fence)
        peek = folded[0]
        if len(peek) > 72:
            peek = peek[:69] + "…"
        lines.append(f"逻辑：`{peek}`" + (f" 等{len(folded)}条" if len(folded) > 1 else ""))

    for note in _block_risk_notes(job, block_name)[:1]:
        lines.append(f"注意：{note}")

    if interface_only or (protected and not body_available):
        lines.append("程序体：未导出/未索引（未解密 / 无程序体）— 不做 SCL 展开，不编造内部逻辑")
        if include_full_scl:
            lines.extend(_format_block_scl_markdown(job, block_name))
            lines.extend(
                _format_typed_as_nest_lines(job, block_name, compact=False, always=False)
            )
    elif include_full_scl:
        lines.extend(_format_block_scl_markdown(job, block_name))
        lines.extend(
            _format_typed_as_nest_lines(job, block_name, compact=False, always=False)
        )
    elif (job.get("scl_sources") or {}).get(block_name):
        lines.append("_下一步：说「展开 SCL」看完整源码；或问「谁读写这些信号」/「优化建议」。_")
    else:
        lines.append("_下一步：可选中画布查看信号子图；或问「优化建议」。_")
    return lines


def _format_block_runtime_explain(
    job: dict[str, Any],
    block_name: str,
    block: dict[str, Any],
    *,
    through_member: str | None = None,
    nest_block: str | None = None,
) -> list[str]:
    """分析 / 这个块干什么 / 运行逻辑：role, IO, CALLS, 网络步序, folded SCL, 全链."""
    comment = str(block.get("comment") or "").strip()
    interface_only = bool(block.get("interface_only"))
    protected = bool(block.get("protected"))
    body_available = block.get("body_available")
    if body_available is None:
        body_available = not interface_only and not (
            protected and int(block.get("networks") or 0) == 0
        )
    reads, writes, iface_inout = _block_io_lists(job, block_name, block)
    folded = _folded_logic_lines(job, block_name)
    if not folded:
        scl = (job.get("scl_sources") or {}).get(block_name) or ""
        folded = [
            ln.strip().rstrip(";")
            for ln in str(scl).splitlines()
            if (":=" in ln or "=>" in ln or "(" in ln)
            and not ln.strip().startswith("//")
            and not ln.strip().startswith("(*")
            and not ln.strip().upper().startswith("NETWORK")
            and "VAR" not in ln.upper().split()[:1]
        ][:16]
    titles = _block_network_titles(job, block_name)
    callers, callees = _call_relation_names(job, block_name)
    lines: list[str] = []

    if interface_only or (protected and not body_available):
        lines.append("状态：接口开放 · 程序体不可用（不臆测内部逻辑）")
        purpose = comment or "封装功能块；结合接口与上下游调用理解角色。"
        lines.append(f"理解：{purpose}")
        lines.append(f"作用：{purpose}")
    else:
        understanding = _explain_block_understanding(
            job, block_name, block, folded=folded, reads=reads, writes=writes
        )
        lines.append(f"理解：{understanding}")
        lines.append(f"作用：{_purpose_from_fold(folded, reads, writes)}")

    lines.append(f"输入：{_join_capped(reads) if reads else '（无已验证读取）'}")
    lines.append(f"输出：{_join_capped(writes) if writes else '（无已验证写入）'}")
    if iface_inout and not (set(iface_inout) <= set(reads) & set(writes)):
        lines.append(f"InOut：{_join_capped(iface_inout, limit=4)}")

    call_bits: list[str] = []
    if callers:
        call_bits.append("被调用：" + _join_capped(callers, limit=8))
    if callees:
        call_bits.append("调用：" + _join_capped(callees, limit=8))
    if call_bits:
        lines.append("；".join(call_bits))
    for line in _block_assoc_lines(job, block_name):
        if line.startswith("使用") or line.startswith("被使用"):
            if line not in lines:
                lines.append(line)

    if titles:
        lines.append("逻辑：" + " → ".join(titles[:16]))
        lines.append("运行步骤：" + " → ".join(titles[:16]))
    if not (interface_only or (protected and not body_available)):
        lines.extend(_format_scl_logic_block(folded))
    else:
        lines.append("程序体：未导出/未索引（未解密 / 无程序体）")

    lines.extend(
        _format_typed_as_nest_lines(
            job,
            nest_block or block_name,
            through_member=through_member,
            compact=False,
            always=True,
        )
    )
    lines.extend(_engineering_network_explain(job, block_name))
    return lines


def _focused_optimize_advice(
    job: dict[str, Any],
    block_name: str,
    block: dict[str, Any],
) -> str:
    """Node-scoped optimization consultation; no whole-project interview dump."""
    focus = str(block_name or "").strip()
    lines = [f"**优化逻辑（`{focus}`）**"]
    lines.append("这是控制逻辑计划，不是 SCL 文件；改写前必须由工程师确认边界。")

    from agents.plc.tia.understanding import (
        _format_confirmed_facts,
        confirmed_nested,
        confirmed_role,
    )

    role = confirmed_role(job, focus)
    nest = confirmed_nested(job, focus)
    facts = _format_confirmed_facts(job, focus=focus)
    if facts:
        lines.extend(["", "**已确认（工程师为准）**：", *facts])

    callers, callees = _call_relation_names(job, focus)
    if callers or callees:
        chain_bits = []
        if callers:
            chain_bits.append("调用方：" + "、".join(f"`{x}`" for x in callers[:4]))
        if callees:
            chain_bits.append("调用目标：" + "、".join(f"`{x}`" for x in callees[:4]))
        lines.append("位置：" + "；".join(chain_bits) + "。")

    engineering = _engineering_network_explain(job, focus)
    if len(engineering) > 1:
        lines.extend(engineering)
    else:
        lines.append("_该块没有可折叠程序体；只能基于接口、调用关系和注释给出审查方向。_")

    if nest:
        kind = str(nest.get("kind") or "")
        label = str(nest.get("label") or kind)
        chain_lines = _format_typed_as_nest_lines(
            job,
            focus,
            compact=False,
            always=True,
        )
        principle = (
            "保留西门子多实例嵌套，不建议拍平、不发明 I/O、不臆造 CALLS。"
            if kind == "required_multi_instance"
            else "确认为意外耦合后，仅可在既有 I/O 范围内评估提取 helper；仍需 HITL。"
        )
        lines.extend(
            [
                "",
                f"嵌套判定：`{focus}` 为 **{label}**。",
                *chain_lines[:4],
                f"处理原则：{principle}",
            ]
        )
    elif role:
        lines.append(f"角色判定：`{focus}` 为 **{role.get('label')}**。")

    lines.extend(["", "**优化提示（待你确认，不是结论）**"])
    if not (role or nest):
        lines.append("- 确认还不够，先不要编造改写；请先给这个块一个明确角色。")
    risks = _block_risk_notes(job, focus)
    finding_lines: list[str] = []
    try:
        from agents.plc.tia.analyst import analyze_block

        findings = analyze_block(job, focus).get("findings") or []
        for finding in findings:
            severity = str(finding.get("severity") or "")
            message = str(finding.get("message") or "").strip()
            if severity in {"warn", "risk"} and message:
                finding_lines.append(f"- [{severity}] {message}")
    except Exception:  # noqa: BLE001
        pass
    for note in risks[:3]:
        item = f"- [review] {note}"
        if item not in finding_lines:
            finding_lines.append(item)

    if finding_lines:
        lines.extend(["", "**优化前必须确认**：", *finding_lines[:6]])
    else:
        lines.append("- 当前图谱没有发现 warn/risk 级问题；先审查状态步和复位路径。")

    lines.extend(
        [
            "",
            "**建议的工程师决策**：",
            "- 先确认状态步/互锁条件是否完整，再考虑改写；不要只看单个赋值。",
            "- 若存在多写入点，先确认每个模式的复位路径和优先级。",
            "- 定时器重点核对超时值、掉电恢复和卡死保护。",
            "- 跨系统 SWAP/字节序转换先保留边界测试，不建议静默简化。",
            "- 角色未确认前不改写；请选择：工艺主控 / 设备驱动 / 厂商库 / 可拆辅助 / 不要动。",
            "",
            "_确认边界后可点「优化SCL」生成该块 HITL diff；不会自动反写。_",
        ]
    )
    return "\n".join(lines)

def _clean_network_title(title: object) -> str:
    value = " ".join(str(title or "").split())
    return value.strip("*-=_ ")


def _refs_in_expr(value: Any, *, limit: int = 3) -> list[str]:
    refs: list[str] = []

    def walk(item: Any) -> None:
        if len(refs) >= limit:
            return
        if isinstance(item, dict):
            access = str(item.get("access") or "").strip()
            if access and access not in {"TRUE", "FALSE"} and access not in refs:
                refs.append(access.strip('"'))
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return refs


def _engineering_network_explain(job: dict[str, Any], block_name: str) -> list[str]:
    """Senior-engineer view: control phases, actions, conditions and risks."""
    folded = job.get("folded_logic")
    networks = folded.get(block_name) if isinstance(folded, dict) else None
    if not isinstance(networks, list):
        return []

    phases: list[dict[str, Any]] = []
    write_targets: dict[str, int] = {}
    unconditional_writes = 0
    timer_calls = 0
    swap_moves = 0

    for network in networks:
        if not isinstance(network, dict):
            continue
        statements = [item for item in (network.get("statements") or []) if isinstance(item, dict)]
        if not statements:
            continue
        title = _clean_network_title(network.get("title"))
        actions: list[str] = []
        conditions: list[str] = []
        seen_actions: set[str] = set()

        def add_action(text: str) -> None:
            if text not in seen_actions:
                actions.append(text)
                seen_actions.add(text)

        for stmt in statements:
            kind = str(stmt.get("kind") or "")
            target = str(stmt.get("target") or "").strip()
            value = stmt.get("value")
            enable = stmt.get("enable")
            enable_refs = _refs_in_expr(enable, limit=2)
            if enable is None or enable_refs in ([], ["TRUE"]):
                if kind in {"coil", "move", "set", "reset"}:
                    unconditional_writes += 1

            normalized_target = target.split(" := ", 1)[0].strip()
            if normalized_target:
                key = normalized_target.strip('"').removeprefix("#")
                root = key.split(".", 1)[0]
                write_targets[root] = write_targets.get(root, 0) + 1

            if kind == "call":
                call_name = normalized_target.removeprefix("#").split("(", 1)[0]
                if "TON(" in target or ".TON" in target:
                    timer_calls += 1
                    add_action("启动/驱动定时器判断")
                else:
                    add_action(f"调用 `{call_name}`")
            elif kind == "move":
                destination = normalized_target.strip('"').removeprefix("#")
                if str((value or {}).get("name", "")).upper() == "SWAP":
                    swap_moves += 1
                    add_action(f"交换/转换并写入 `{destination}`")
                else:
                    add_action(f"写入 `{destination}`")
            elif kind == "set":
                add_action(f"置位 `{normalized_target.strip(chr(34)).removeprefix('#')}`")
            elif kind == "reset":
                add_action(f"复位 `{normalized_target.strip(chr(34)).removeprefix('#')}`")
            elif kind == "neg_coil":
                add_action(f"取反驱动 `{normalized_target.strip(chr(34)).removeprefix('#')}`")
            elif kind == "coil":
                add_action(f"驱动 `{normalized_target.strip(chr(34)).removeprefix('#')}`")

            conditions.extend(x for x in enable_refs if x != "TRUE" and x not in conditions)

        if title or actions:
            phases.append(
                {
                    "title": title or "未命名网络",
                    "actions": actions[:4],
                    "conditions": conditions[:4],
                    "statement_count": len(statements),
                }
            )

    lines = ["### 工程逻辑解读（按网络）"]
    if not phases:
        lines.append("_该块的导出体中没有可折叠成 SCL 的网络。_")
        return lines

    meaningful = [item for item in phases if item["title"] and item["actions"]]
    shown = (meaningful or phases)[:6]
    for index, phase in enumerate(shown, start=1):
        bits = [f"{index}. **{phase['title']}**"]
        if phase["actions"]:
            bits.append("动作：" + "；".join(phase["actions"]))
        if phase["conditions"]:
            bits.append("条件：" + "、".join(f"`{x}`" for x in phase["conditions"]))
        bits.append(f"约 {phase['statement_count']} 条语句")
        lines.append("  \n".join(bits))

    risks: list[str] = []
    hot_writes = sorted(write_targets.items(), key=lambda item: (-item[1], item[0]))[:3]
    if hot_writes:
        risks.append("高频影响对象：" + "、".join(f"`{name}`×{count}" for name, count in hot_writes))
    if unconditional_writes:
        risks.append(f"{unconditional_writes} 个写入缺少可见使能条件，需确认是否由前序 RLO 保证")
    if timer_calls:
        risks.append(f"{timer_calls} 处定时器调用，重点检查超时值、复位路径和卡死保护")
    if swap_moves:
        risks.append(f"{swap_moves} 处 SWAP/字节序转换，跨通信接口时需确认端序约定")
    unresolved = sum(len(net.get("unresolved_parts") or []) for net in networks if isinstance(net, dict))
    if unresolved:
        risks.append(f"{unresolved} 个指令未能折叠为 SCL，需要保留原始 LAD 证据")
    if risks:
        lines.append("**工程师检查点**：" + "；".join(risks) + "。")
    lines.append("_继续问：这个网络为什么会动作？谁复位它？或说「展开这一步」。_")
    return lines
