"""Bit-Chain Sequencer Miner for Legacy PLC Projects (Tab 3 Step 2 Pattern B).

Identifies Boolean flag sequencer chains (M-bits, DB flags) following the classic
industrial pattern:
    Step[n] := (Step[n-1] AND TransCondition) OR (Step[n] AND NOT Step[n+1]);
or compact Set/Reset chain transitions.

Linear-time, statement-sliced deterministic parsing without catastrophic regex backtracking.
Normalizes extracted bit flags into standardized Bosch AF integer steps:
    10, 20, 30, ...
with clean transition conditions and automatic step loop wiring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from plc_engine.af.af_mapper import ExtractedStep


@dataclass
class BitChainTransition:
    prev_step_var: str
    target_step_var: str
    next_step_var: str
    transition_condition: str
    source_line: str = ""


@dataclass
class MinedBitChain:
    step_variables: list[str]
    transitions: list[BitChainTransition]
    is_circular: bool = True
    normalized_steps: list[ExtractedStep] = field(default_factory=list)


class BitChainMiner:
    """Mines Boolean sequencer chains safely with O(N) linear statement scanning."""

    # Single-statement latch regex (safe, non-backtracking on single line/statement)
    _STMT_LATCH_RE = re.compile(
        r"""^\s*([#\w".]+)\s*:=\s*\(\s*([#\w".]+)\s+AND\s+([^()]+?)\s*\)\s*OR\s*\(\s*\1\s+AND\s+NOT\s+([#\w".]+)\s*\)\s*$""",
        re.IGNORECASE,
    )

    _STMT_LATCH_NO_PAREN_RE = re.compile(
        r"""^\s*([#\w".]+)\s*:=\s*([#\w".]+)\s+AND\s+([^;]+?)\s+OR\s+\1\s+AND\s+NOT\s+([#\w".]+)\s*$""",
        re.IGNORECASE,
    )

    def mine_chains(self, scl_code: str) -> list[MinedBitChain]:
        """Scan SCL code statements safely and detect all bit-chain sequencers."""
        if not scl_code or not scl_code.strip():
            return []

        # Strip comments safely before statement slicing
        clean_code = re.sub(r"//[^\r\n]*", "", scl_code)
        clean_code = re.sub(r"\(\*[\s\S]*?\*\)", "", clean_code)

        transitions: list[BitChainTransition] = []

        # 1. Statement-level parsing for self-holding latch pattern
        # Split by ';' to ensure O(N) evaluation and zero multi-line catastrophic backtracking
        statements = clean_code.split(";")
        for raw_stmt in statements:
            stmt = " ".join(raw_stmt.split()).strip()
            if not stmt or ":=" not in stmt or "OR" not in stmt:
                continue

            # Check parentheses form
            m = self._STMT_LATCH_RE.match(stmt)
            if m:
                target = m.group(1).strip()
                prev = m.group(2).strip()
                cond = m.group(3).strip()
                next_var = m.group(4).strip()
                transitions.append(
                    BitChainTransition(
                        prev_step_var=prev,
                        target_step_var=target,
                        next_step_var=next_var,
                        transition_condition=cond,
                        source_line=stmt,
                    )
                )
                continue

            # Check no-parentheses form
            m2 = self._STMT_LATCH_NO_PAREN_RE.match(stmt)
            if m2:
                target = m2.group(1).strip()
                prev = m2.group(2).strip()
                cond = m2.group(3).strip()
                next_var = m2.group(4).strip()
                transitions.append(
                    BitChainTransition(
                        prev_step_var=prev,
                        target_step_var=target,
                        next_step_var=next_var,
                        transition_condition=cond,
                        source_line=stmt,
                    )
                )

        # 2. Parse compact IF Set/Reset transitions line by line
        # Only inspect compact IF blocks (max 6 lines) to prevent runaway matching
        lines = [line.strip() for line in scl_code.splitlines()]
        num_lines = len(lines)
        i = 0
        while i < num_lines:
            line = lines[i]
            if line.upper().startswith("IF ") and " THEN" in line.upper():
                # Read up to next END_IF (max 6 lines window)
                window: list[str] = [line]
                j = i + 1
                while j < min(num_lines, i + 6):
                    window.append(lines[j])
                    if "END_IF" in lines[j].upper():
                        break
                    j += 1
                block_str = " ".join(window)
                if "END_IF" in block_str.upper():
                    m_sr = re.search(
                        r"""IF\s+([#\w".]+)\s+AND\s+([^;]+?)\s+THEN\s+([#\w".]+)\s*:=\s*(?:TRUE|1)\s*;\s*\1\s*:=\s*(?:FALSE|0)\s*;""",
                        block_str,
                        re.IGNORECASE,
                    )
                    if m_sr:
                        prev = m_sr.group(1).strip()
                        cond = m_sr.group(2).strip()
                        target = m_sr.group(3).strip()
                        transitions.append(
                            BitChainTransition(
                                prev_step_var=prev,
                                target_step_var=target,
                                next_step_var="",
                                transition_condition=cond,
                                source_line=block_str,
                            )
                        )
                        i = j + 1
                        continue
            i += 1

        if not transitions:
            return []

        return self._build_chains_from_transitions(transitions)

    def _build_chains_from_transitions(
        self,
        transitions: list[BitChainTransition],
    ) -> list[MinedBitChain]:
        """Organize transitions into directed chains and normalize to Bosch steps."""
        adj: dict[str, list[BitChainTransition]] = {}
        all_targets = set()
        all_prevs = set()

        for t in transitions:
            adj.setdefault(t.prev_step_var, []).append(t)
            all_targets.add(t.target_step_var)
            all_prevs.add(t.prev_step_var)

        starts = list(all_prevs - all_targets)
        if not starts and transitions:
            starts = [transitions[0].prev_step_var]

        chains: list[MinedBitChain] = []
        visited_nodes: set[str] = set()

        for start in starts:
            chain_nodes: list[str] = [start]
            chain_trans: list[BitChainTransition] = []
            curr = start
            visited_local = {start}

            while curr in adj:
                next_t = adj[curr][0]
                nxt = next_t.target_step_var
                chain_trans.append(next_t)
                if nxt in visited_local:
                    break
                chain_nodes.append(nxt)
                visited_local.add(nxt)
                curr = nxt

            if len(chain_nodes) >= 2:
                norm_steps: list[ExtractedStep] = []
                num_nodes = len(chain_nodes)
                step_ids: list[int] = []
                auto_idx = 10
                for node in chain_nodes:
                    node_lower = node.lower()
                    if any(k in node_lower for k in ("init", "ready", "idle")):
                        step_ids.append(1)
                    else:
                        step_ids.append(auto_idx)
                        auto_idx += 10

                for idx, node in enumerate(chain_nodes):
                    step_id = step_ids[idx]
                    next_step_id = step_ids[idx + 1] if idx + 1 < num_nodes else step_ids[0]
                    cond = "TRUE"
                    for t in chain_trans:
                        if t.prev_step_var == node:
                            cond = t.transition_condition
                            break
                    clean_name = re.sub(r"[^A-Za-z0-9_]", "_", node).strip("_").upper()
                    norm_steps.append(
                        ExtractedStep(
                            step_id=step_id,
                            name=f"STEP_{step_id}_{clean_name}",
                            description=f"Auto-mined from bit flag {node}",
                            actions=[f"// Mined from {node}"],
                            transition_condition=cond,
                            next_step_id=next_step_id,
                        )
                    )

                chains.append(
                    MinedBitChain(
                        step_variables=chain_nodes,
                        transitions=chain_trans,
                        is_circular=True,
                        normalized_steps=norm_steps,
                    )
                )
                visited_nodes |= visited_local

        return chains
