"""S7-GRAPH → executable CASE state-machine SCL (rule-based rebuild).

The IR already carries GraphStep/GraphTransition evidence (``simaticml._ingest_graph``).
This module rebuilds a scan-cycle state machine instead of the advisory
comment sequence:

    IF #GraphStep = 0 THEN
        #GraphStep := 1;  // init → <first step>
    END_IF;
    CASE #GraphStep OF
        1:  // <StepName> — <comment>
            // 动作: <action tokens>
            IF (<transition condition>) THEN
                #GraphStep := 2;  // → <target step>
            END_IF;
    END_CASE;

Semantics policy (HITL review + Openness compile gate still apply):

- transition conditions are emitted verbatim — SimaticML GRAPH conditions are
  SCL-compatible tokens; empty conditions and transitions whose endpoints do
  not resolve to a parsed step become ``(* TODO[graph_*] *)`` comments;
- interlock / supervision are emitted as comments only — this module refuses
  to invent their runtime semantics;
- one Int state variable per GRAPH network (``GraphStep``, ``GraphStep2``, …);
  ``scl.translate_block_to_scl`` injects it into the STATIC section for FB/FC.
"""

from __future__ import annotations

from agents.plc.tia.ir import GraphStep, Network


def has_graph_sequence(network: Network) -> bool:
    """True when the network carries parsed S7-GRAPH steps or transitions."""
    return bool(getattr(network, "graph_steps", None)) or bool(
        getattr(network, "graph_transitions", None)
    )


def graph_state_var_name(index: int) -> str:
    """Deterministic state-variable name for the Nth GRAPH network (1-based)."""
    return "GraphStep" if index <= 1 else f"GraphStep{index}"


def _step_numbers(steps: list[GraphStep]) -> dict[str, int]:
    """Map step name → CASE branch number (XML Number when present, else order)."""
    mapping: dict[str, int] = {}
    for order, step in enumerate(steps, start=1):
        number = step.number if step.number and step.number > 0 else order
        mapping.setdefault(step.name, number)
    return mapping


def graph_network_to_scl(network: Network, state_var: str) -> list[str] | None:
    """Rebuild one GRAPH network as an executable CASE state machine.

    Returns body lines with 4-space base indent (matching the SCL network
    emission style), or ``None`` when no step parsed (caller falls back to the
    advisory comment sequence).
    """
    steps = list(getattr(network, "graph_steps", None) or [])
    if not steps:
        return None
    transitions = list(getattr(network, "graph_transitions", None) or [])
    numbers = _step_numbers(steps)
    ref = state_var

    lines: list[str] = []
    lines.append("    // GRAPH 步序 → CASE 状态机（规则重建；转换条件需人工复核）")
    lines.append("    // 步号映射: " + ", ".join(f"{num}={name}" for name, num in sorted(numbers.items(), key=lambda kv: kv[1])))
    first_number = numbers.get(steps[0].name, 1)
    lines.append(f"    IF #{ref} = 0 THEN")
    lines.append(f"        #{ref} := {first_number};  // init → {steps[0].name}")
    lines.append("    END_IF;")
    lines.append(f"    CASE #{ref} OF")

    unresolved: list[str] = []
    for step in steps:
        branch = numbers.get(step.name, 1)
        head = f"        {branch}:  // {step.name}"
        if step.comment:
            head += f" — {step.comment}"
        lines.append(head)
        for action in step.actions:
            lines.append(f"            // 动作: {action}")
        if step.interlock:
            lines.append(f"            // Interlock: {step.interlock}")
        if step.supervision:
            lines.append(f"            // Supervision: {step.supervision}")
        step_transitions = [t for t in transitions if t.source_step == step.name]
        if not step_transitions:
            # terminal step is legitimate (no exit transition parsed); not a TODO
            lines.append("            // 终止步：未解析到出边转换")
        for transition in step_transitions:
            condition = (transition.condition or "").strip()
            target_number = numbers.get(transition.target_step)
            if not condition:
                unresolved.append(f"transition {transition.name}: empty condition")
                lines.append(
                    f"            (* TODO[graph_condition]: {transition.name} "
                    f"{step.name} -> {transition.target_step} 条件为空 *)"
                )
                continue
            if target_number is None:
                unresolved.append(f"transition {transition.name}: unknown target {transition.target_step}")
                lines.append(
                    f"            (* TODO[graph_target]: {transition.name} 目标步 "
                    f"{transition.target_step or '(空)'} 不在已解析步序中 *)"
                )
                continue
            lines.append(f"            IF ({condition}) THEN")
            lines.append(f"                #{ref} := {target_number};  // → {transition.target_step}")
            if transition.comment:
                lines.append(f"                // {transition.comment}")
            lines.append("            END_IF;")
        lines.append("            ;")

    lines.append("        ELSE")
    lines.append("            // 无效步号保持不变（不应出现；防御分支，非未翻译项）")
    lines.append("            ;")
    lines.append("    END_CASE;")
    return lines


def graph_unresolved_count(network: Network) -> int:
    """How many transitions will surface as TODO (coverage accounting)."""
    steps = list(getattr(network, "graph_steps", None) or [])
    transitions = list(getattr(network, "graph_transitions", None) or [])
    if not steps:
        return len(transitions)
    numbers = _step_numbers(steps)
    count = 0
    for transition in transitions:
        if not (transition.condition or "").strip() or transition.source_step not in numbers or numbers.get(transition.target_step) is None:
            count += 1
    return count
