"""Agent name → callable registry for LangGraph wiring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.researchos_runtime.state import TaskState

AgentFn = Callable[[TaskState], dict[str, Any]]


def get_agent_registry() -> dict[str, AgentFn]:
    def _stub(name: str) -> AgentFn:
        return lambda state: {"route": "analysis", "analysis_results": {}, "evidence": []}

    try:
        from agents.analysis.node import run as analysis_run
    except ImportError:
        analysis_run = _stub("analysis")
    try:
        from agents.citation.node import run as citation_run
    except ImportError:
        citation_run = _stub("citation")
    try:
        from agents.etl import run as etl_run
    except ImportError:
        etl_run = _stub("etl")
    try:
        from agents.failure import run as failure_run
    except ImportError:
        failure_run = _stub("failure")
    try:
        from agents.memory.node import run as memory_run
    except ImportError:
        memory_run = _stub("memory")
    try:
        from agents.motion import run as motion_run
    except ImportError:
        motion_run = _stub("motion")
    try:
        from agents.plc.node import run as plc_run
    except ImportError:
        plc_run = _stub("plc")
    try:
        from agents.research.node import run as research_run
    except ImportError:
        research_run = _stub("research")
    try:
        from agents.reviewer.node import run as reviewer_run
    except ImportError:
        reviewer_run = _stub("reviewer")
    try:
        from agents.writer.node import run as writer_run
    except ImportError:
        writer_run = _stub("writer")

    return {
        "research": research_run,
        "etl": etl_run,
        "analysis": analysis_run,
        "citation": citation_run,
        "reviewer": reviewer_run,
        "writer": writer_run,
        "memory": memory_run,
        "plc": plc_run,
        "motion": motion_run,
        "failure": failure_run,
    }


def get_agent(name: str) -> AgentFn:
    registry = get_agent_registry()
    if name not in registry:
        raise KeyError(f"unknown agent: {name}; known={sorted(registry)}")
    return registry[name]
