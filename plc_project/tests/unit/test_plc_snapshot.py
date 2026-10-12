"""Corpus snapshot regression — every tia_* fixture in, stable digests out.

Locks the full deterministic pipeline (SimaticML extract → safety flags →
fold → KG → SCL → report) so any parser change that alters output shows up
as a diff against ``tests/snapshots/plc/<fixture>.json``.

Regenerate baselines after an intentional change:

    UPDATE_PLC_SNAPSHOTS=1 python -m pytest tests/unit/test_plc_snapshot.py

Digests are computed over key-sorted JSON, and ``map_parallel`` preserves
input order, so runs are byte-stable on the same fixture set.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots" / "plc"

_TODO_RE = re.compile(r"\(\*\s*TODO\[([^\]]+)\]")


def _fixture_projects() -> list[Path]:
    projects = sorted(
        path
        for path in FIXTURE_ROOT.iterdir()
        if path.is_dir() and path.name.startswith("tia_")
    )
    assert projects, f"no tia_* fixture projects under {FIXTURE_ROOT}"
    return projects


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _todo_histogram(scl_sources: dict[str, str]) -> dict[str, int]:
    histogram: dict[str, int] = {}
    for text in scl_sources.values():
        for token in _TODO_RE.findall(text):
            token = token.strip()
            histogram[token] = histogram.get(token, 0) + 1
    return dict(sorted(histogram.items()))


def _artifact_view(project_dir: Path) -> dict[str, Any]:
    from agents.plc.tia.pipeline import analyze_tia_exports

    result = analyze_tia_exports(str(project_dir), project_name=project_dir.name)
    project = result["project"]
    kg = result["knowledge_graph"].to_json()
    nodes = sorted(
        (str(n.get("id")), str(n.get("type"))) for n in kg.get("nodes") or []
    )
    edges = sorted(
        (
            str(e.get("source")),
            str(e.get("target")),
            str(e.get("type")),
            json.dumps(e.get("props") or {}, sort_keys=True, default=str),
        )
        for e in kg.get("edges") or []
    )
    scl_sources = dict(sorted((result.get("scl_sources") or {}).items()))
    folded = {
        str(block): list(networks)
        for block, networks in sorted((result.get("folded_logic") or {}).items())
    }
    graph_networks = sum(
        1
        for block in project.blocks.values()
        for network in block.networks
        if getattr(network, "graph_steps", None)
    )
    return {
        "fixture": project_dir.name,
        "summary": dict(sorted(project.summary().items())),
        "extraction_notes": list(project.extraction_notes or []),
        "kg": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes_digest": _digest(nodes),
            "edges_digest": _digest(edges),
        },
        "scl": {
            "block_count": len(scl_sources),
            "digest": _digest(scl_sources),
            "todo_histogram": _todo_histogram(scl_sources),
        },
        "folded": {
            "block_count": len(folded),
            "digest": _digest(folded),
        },
        "graph_step_networks": graph_networks,
    }


@pytest.mark.parametrize("project_dir", _fixture_projects(), ids=lambda p: p.name)
def test_fixture_snapshot(project_dir: Path) -> None:
    view = _artifact_view(project_dir)
    baseline = SNAPSHOT_DIR / f"{project_dir.name}.json"
    if os.getenv("UPDATE_PLC_SNAPSHOTS", "").strip() in {"1", "true", "yes", "on"}:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pytest.skip("baseline updated; re-run without UPDATE_PLC_SNAPSHOTS")
    assert baseline.is_file(), (
        f"missing snapshot {baseline}; regenerate with "
        "UPDATE_PLC_SNAPSHOTS=1 python -m pytest tests/unit/test_plc_snapshot.py"
    )
    expected = json.loads(baseline.read_text(encoding="utf-8"))
    for key in ("summary", "kg", "scl", "folded"):
        assert view[key] == expected[key], (
            f"{project_dir.name}: {key} drifted from snapshot {baseline}.\n"
            f"  new: {json.dumps(view[key], sort_keys=True, default=str)}\n"
            f"  old: {json.dumps(expected[key], sort_keys=True, default=str)}\n"
            "If intentional, regenerate with UPDATE_PLC_SNAPSHOTS=1."
        )
    assert view["graph_step_networks"] == expected.get(
        "graph_step_networks", view["graph_step_networks"]
    )
