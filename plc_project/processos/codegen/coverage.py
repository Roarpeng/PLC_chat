"""Semantic coverage assertions — lowered code must equal contract intent.

Comment-only placeholders do not increment the counter, so a generator that
emits ``// action`` instead of a real assignment fails the assertion (R3 P0).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CoverageCounter:
    steps: int = 0
    actions: int = 0
    guards: int = 0
    timers: int = 0

    def step(self) -> None:
        self.steps += 1

    def action(self) -> None:
        self.actions += 1

    def guard(self) -> None:
        self.guards += 1

    def timer(self) -> None:
        self.timers += 1

    def as_dict(self) -> dict[str, int]:
        return {"steps": self.steps, "actions": self.actions, "guards": self.guards, "timers": self.timers}


def expected_from_sequence(sequence: list[dict]) -> dict[str, int]:
    steps = len(sequence)
    actions = 0
    guards = 0
    timers = 0
    for st in sequence:
        actions += len(st.get("entry", [])) + len(st.get("exit", []))
        if st.get("is_fault"):
            if st.get("reset_guard"):
                guards += 1
            continue
        if st.get("duration_ms"):
            timers += 1
            guards += 1
        elif st.get("guard"):
            guards += 1
            if st.get("timeout_ms"):
                timers += 1
                guards += 1
    return {"steps": steps, "actions": actions, "guards": guards, "timers": timers}