"""Graph, type and resource validation for SequenceIR (blueprint A3/A4, G3).

All rules are deterministic pure functions. The single-writer arbitration
helper is shared verbatim by the scan simulator and SCL lowering so the compiled
SCL and the offline Trace can never disagree about output semantics.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from plc_engine.engineering_ir.models import EngineeringIRV2
from plc_engine.process.guard_ast import GuardAST, GuardNodeType
from plc_engine.process.sequence_ir import Action, EdgeType, SequenceIR

#: Command-name pairs that must never be asserted simultaneously.
REVERSE_COMMAND_PAIRS: tuple[tuple[str, str], ...] = (
    ("extend", "retract"),
    ("forward", "reverse"),
    ("up", "down"),
    ("open", "close"),
    ("start", "stop"),
    ("on", "off"),
)


def _issue(source_id: str, reason: str, field_name: str = "") -> dict[str, Any]:
    return {"source_id": source_id, "node_id": source_id, "field": field_name, "reason": reason}


# --------------------------------------------------------------------------- #
# Graph algorithms
# --------------------------------------------------------------------------- #


def reachable_steps(sequence: SequenceIR) -> set[str]:
    """BFS reachability from ``initial_step`` over all transitions."""
    adjacency: dict[str, list[str]] = {}
    for tr in sequence.transitions:
        adjacency.setdefault(tr.from_step, []).append(tr.to_step)
    # Exception/timeout paths are legitimate reachability edges (FAULT steps
    # are reached through exceptions, not through normal transitions).
    for exc in sequence.exceptions:
        if exc.from_step and exc.to_step:
            adjacency.setdefault(exc.from_step, []).append(exc.to_step)
    if not sequence.initial_step:
        return set()
    seen: set[str] = {sequence.initial_step}
    queue: deque[str] = deque([sequence.initial_step])
    while queue:
        current = queue.popleft()
        for nxt in sorted(adjacency.get(current, [])):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def tarjan_sccs(sequence: SequenceIR) -> list[list[str]]:
    """Tarjan strongly connected components over the transition graph."""
    index_counter = [0]
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []

    adjacency: dict[str, list[str]] = {step_id: [] for step_id in sequence.step_ids()}
    for tr in sequence.transitions:
        if tr.from_step in adjacency:
            adjacency[tr.from_step].append(tr.to_step)

    def strongconnect(node: str) -> None:
        # Iterative Tarjan to avoid recursion limits on large graphs.
        work: list[tuple[str, int]] = [(node, 0)]
        while work:
            current, child_index = work[-1]
            if child_index == 0:
                indices[current] = index_counter[0]
                lowlink[current] = index_counter[0]
                index_counter[0] += 1
                stack.append(current)
                on_stack.add(current)
            neighbors = adjacency.get(current, [])
            if child_index < len(neighbors):
                work[-1] = (current, child_index + 1)
                nxt = neighbors[child_index]
                if nxt not in indices:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    lowlink[current] = min(lowlink[current], indices[nxt])
                continue
            if lowlink[current] == indices[current]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == current:
                        break
                result.append(sorted(component))
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[current])

    for step_id in sequence.step_ids():
        if step_id not in indices:
            strongconnect(step_id)
    return result


def sccs_without_exit(sequence: SequenceIR) -> list[list[str]]:
    """Return SCCs that form a non-terminating cycle (no outgoing edge)."""
    blocked: list[list[str]] = []
    for component in tarjan_sccs(sequence):
        members = set(component)
        is_cycle = len(component) > 1 or any(
            tr.from_step == component[0] and tr.to_step == component[0]
            for tr in sequence.transitions
        )
        if not is_cycle:
            continue
        has_exit = any(
            tr.from_step in members and tr.to_step not in members
            for tr in sequence.transitions
        )
        has_exception_exit = any(
            exc.from_step in members and exc.to_step not in members
            for exc in sequence.exceptions
        )
        if not has_exit and not has_exception_exit:
            blocked.append(component)
    return blocked


# --------------------------------------------------------------------------- #
# Guard / branch rules
# --------------------------------------------------------------------------- #


def _positive_signals(guard: GuardAST) -> set[str]:
    found: set[str] = set()
    if guard.node_type is GuardNodeType.SIGNAL:
        found.add(guard.signal)
    for child in guard.children:
        found.update(_positive_signals(child))
    return found


def _negative_signals(guard: GuardAST) -> set[str]:
    found: set[str] = set()
    if guard.node_type is GuardNodeType.NOT:
        for child in guard.children:
            found.update(_positive_signals(child))
    for child in guard.children:
        found.update(_negative_signals(child))
    return found


def guards_are_provably_exclusive(left: GuardAST, right: GuardAST) -> bool:
    """Prove mutual exclusion via an explicit signal / NOT-signal pair.

    No constraint solver and no input-order heuristics: exclusivity must be
    written into the structured Guard AST itself (blueprint A4).
    """
    for signal in _positive_signals(left):
        if signal in _negative_signals(right):
            return True
    for signal in _positive_signals(right):
        if signal in _negative_signals(left):
            return True
    return False


# --------------------------------------------------------------------------- #
# Single writer arbitration (shared by simulator and SCL lowering)
# --------------------------------------------------------------------------- #


def reverse_command_pairs(command_names: Iterable[str]) -> list[tuple[str, str]]:
    """Detect reverse-output pairs among a driver's command port names."""
    names = sorted({str(name) for name in command_names})
    pairs: list[tuple[str, str]] = []
    for left in names:
        low_left = left.lower()
        for right in names:
            if left >= right:
                continue
            low_right = right.lower()
            for a, b in REVERSE_COMMAND_PAIRS:
                if (a in low_left and b in low_right) or (b in low_left and a in low_right):
                    pairs.append((left, right))
                    break
    return pairs


def arbitrate_single_writer(
    actions: list[Action],
    safety_permit: bool,
    *,
    reverse_pairs: list[tuple[str, str]] | None = None,
) -> tuple[dict[tuple[str, str], bool], list[str]]:
    """Deterministic single-writer / reverse-interlock / SafetyPermit arbitration.

    Returns ``({(component_id, command): bool}, alarms)``. SafetyPermit is a
    **software interlock only** (PRD 7.3): when false, all commands are forced
    off. Reverse outputs asserted together are both forced off with an alarm.
    """
    alarms: list[str] = []
    commands: dict[tuple[str, str], bool] = {}
    ordered = sorted(actions, key=lambda a: (a.target_component_id, a.command, a.source_id or a.id))
    for action in ordered:
        key = (action.target_component_id, action.command)
        value = bool(action.value)
        if not safety_permit and value:
            commands[key] = False
            continue
        if key in commands and commands[key] != value:
            alarms.append(f"single_writer_conflict:{key[0]}.{key[1]}")
            commands[key] = False
            continue
        commands[key] = commands.get(key, False) or value

    for left, right in reverse_pairs or []:
        for component_id in {a.target_component_id for a in ordered}:
            left_key = (component_id, left)
            right_key = (component_id, right)
            if commands.get(left_key) and commands.get(right_key):
                alarms.append(f"reverse_outputs_interlocked:{component_id}:{left}|{right}")
                commands[left_key] = False
                commands[right_key] = False
    if not safety_permit:
        alarms.append("safety_permit_lost:all_commands_inhibited_software_interlock_only")
    return commands, sorted(set(alarms))


# --------------------------------------------------------------------------- #
# Top-level validation
# --------------------------------------------------------------------------- #


def validate_process(ir: EngineeringIRV2) -> list[dict[str, Any]]:
    """Run all graph/type/resource checks; return sorted node-level issues."""
    issues: list[dict[str, Any]] = []
    sequence = ir.process

    if not sequence.steps:
        issues.append(_issue(sequence.id, "sequence has no steps", "steps"))
        return issues
    if not sequence.initial_step:
        issues.append(_issue(sequence.id, "sequence initial_step is not set", "initial_step"))
        return issues

    # 1. Guard AST static typing + no free text.
    for tr in sequence.transitions:
        if tr.guard_ast is None:
            issues.append(_issue(tr.id, "transition requires a structured GuardAST (free text forbidden)", "guard_ast"))
            continue
        for problem in tr.guard_ast.validate_types():
            issues.append(_issue(tr.id, f"guard: {problem}", "guard_ast"))
    for exc in sequence.exceptions:
        if exc.guard_ast is not None:
            for problem in exc.guard_ast.validate_types():
                issues.append(_issue(exc.id, f"exception guard: {problem}", "guard_ast"))

    # 2. BFS reachability.
    reached = reachable_steps(sequence)
    for step in sequence.steps:
        if step.id not in reached:
            issues.append(_issue(step.id, "step is unreachable from initial_step", "reachability"))

    # 3. Tarjan SCC without exit.
    for component in sccs_without_exit(sequence):
        issues.append(
            _issue(component[0], f"non-terminating cycle without exit: {','.join(component)}", "cycle")
        )

    # 4. Branch priority or proven mutual exclusion.
    by_from: dict[str, list[Any]] = {}
    for tr in sequence.transitions:
        if (tr.edge_type.value if hasattr(tr.edge_type, "value") else str(tr.edge_type)) == EdgeType.NORMAL.value:
            by_from.setdefault(tr.from_step, []).append(tr)
    for from_step, edges in sorted(by_from.items()):
        if len(edges) < 2:
            continue
        priorities = [int(tr.priority) for tr in edges]
        if len(set(priorities)) != len(priorities):
            all_exclusive = True
            for i, left in enumerate(edges):
                for right in edges[i + 1:]:
                    if left.guard_ast is None or right.guard_ast is None or not guards_are_provably_exclusive(left.guard_ast, right.guard_ast):
                        all_exclusive = False
            if not all_exclusive:
                issues.append(
                    _issue(from_step, "branch guards share a priority without an exclusivity proof", "priority")
                )

    # 5. Timeout / FAULT paths.
    has_fault_path = bool(sequence.exceptions) or any(
        (tr.edge_type.value if hasattr(tr.edge_type, "value") else str(tr.edge_type)) in
        (EdgeType.EXCEPTION.value, EdgeType.TIMEOUT.value)
        for tr in sequence.transitions
    )
    motion_steps = [step for step in sequence.steps if step.all_actions()]
    for step in sequence.steps:
        if step.max_duration_ms > 0 and not step.failure_target:
            has_local_exception = any(exc.from_step == step.id for exc in sequence.exceptions)
            if not has_local_exception:
                issues.append(_issue(step.id, "step declares max_duration_ms but has no timeout/failure target", "timeout"))
    if motion_steps and not has_fault_path:
        issues.append(_issue(sequence.id, "motion steps require at least one FAULT / exception path", "exceptions"))

    # 6. Command resource conflicts (single writer, reverse outputs).
    catalogue_pairs: dict[str, list[tuple[str, str]]] = {}
    for component in ir.components:
        spec = ir.driver_specs.get(component.driver_spec_id)
        if spec is None:
            continue
        catalogue_pairs[component.id] = reverse_command_pairs(
            [port.name for port in spec.command_ports]
        )
    for step in sequence.steps:
        pairs = catalogue_pairs.get(
            next((a.target_component_id for a in step.all_actions()), ""), []
        )
        entry_actions = step.entry_actions + step.cyclic_actions
        _, alarms = arbitrate_single_writer(entry_actions, True, reverse_pairs=pairs)
        for alarm in alarms:
            if alarm.startswith("reverse_outputs_interlocked") or alarm.startswith("single_writer_conflict"):
                issues.append(_issue(step.id, f"command resource conflict: {alarm}", "actions"))
    for component_id, pairs in sorted(catalogue_pairs.items()):
        spec_component = next((c for c in ir.components if c.id == component_id), None)
        spec = ir.driver_specs.get(spec_component.driver_spec_id) if spec_component else None
        if spec is None:
            continue
        for left, right in pairs:
            left_port = spec.typed_ports.get(left)
            right_port = spec.typed_ports.get(right)
            if left_port and right_port and left_port.writer != right_port.writer:
                issues.append(
                    _issue(component_id, f"reverse outputs {left}/{right} have different single writers", "writer")
                )

    # 7. Unsupported parallel run semantics (display only, fail-closed).
    if sequence.parallel_groups:
        node_ids = sorted({str(group.get("id") or "") for group in sequence.parallel_groups})
        issues.append(
            _issue(
                sequence.id,
                "UNSUPPORTED_PARALLEL_SEMANTICS: Fork/Join run semantics are not implemented; delivery blocked",
                "parallel_groups",
            )
        )
        issues[-1]["node_ids"] = node_ids

    # 8. Protected source bindings (interface-only in this batch).
    for binding in ir.source_bindings:
        if binding.is_protected() and binding.writable != "requires_review":
            issues.append(_issue(binding.source_id, "protected source binding must not be writable", "writable"))

    return sorted(issues, key=lambda i: (str(i.get("source_id") or ""), str(i.get("reason") or "")))


def shortest_counterexample(ir: EngineeringIRV2) -> list[str]:
    """Return the shortest step path from the initial step to a fault target.

    Used by the Trace view to show a concrete counterexample instead of a bare
    "simulation failed" message.
    """
    sequence = ir.process
    fault_targets: set[str] = {exc.to_step for exc in sequence.exceptions}
    fault_targets.update(
        tr.to_step for tr in sequence.transitions
        if (tr.edge_type.value if hasattr(tr.edge_type, "value") else str(tr.edge_type))
        in (EdgeType.EXCEPTION.value, EdgeType.TIMEOUT.value)
    )
    fault_targets.discard("")
    if not fault_targets or not sequence.initial_step:
        return []
    adjacency: dict[str, list[str]] = {}
    for tr in sequence.transitions:
        adjacency.setdefault(tr.from_step, []).append(tr.to_step)
    for exc in sequence.exceptions:
        if exc.from_step and exc.to_step:
            adjacency.setdefault(exc.from_step, []).append(exc.to_step)
    queue: deque[list[str]] = deque([[sequence.initial_step]])
    seen: set[str] = {sequence.initial_step}
    while queue:
        path = queue.popleft()
        current = path[-1]
        if current in fault_targets:
            return path
        for nxt in sorted(adjacency.get(current, [])):
            if nxt not in seen:
                seen.add(nxt)
                queue.append([*path, nxt])
    return []
