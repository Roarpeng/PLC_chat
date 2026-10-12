"""Unit tests for PLC ingest wall-clock timing instrumentation."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.pipeline import analyze_plc_project, analyze_tia_exports
from gateway.app.services import plc_jobs as plc
from gateway.app.services import store as mem

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"


def test_analyze_tia_exports_includes_timings() -> None:
    result = analyze_tia_exports(str(FIXTURES), project_name="MotorDemo", publish_graph=False)
    timings = result.get("timings") or {}
    assert "extract_ms" in timings
    assert "kg_ms" in timings
    assert "scl_ms" in timings
    assert timings["extract_ms"] >= 0
    assert timings["kg_ms"] >= 0


def test_analyze_plc_project_includes_resolve_timings(tmp_path: Path) -> None:
    result = analyze_plc_project(
        str(FIXTURES),
        project_name="MotorDemo",
        result_dir=str(tmp_path / "pkg"),
        publish_graph=False,
    )
    timings = result.get("timings") or {}
    assert "resolve_wall_ms" in timings
    assert "extract_ms" in timings
    assert "package_ms" in timings


def test_run_ingest_job_records_progress_duration_and_timings(tmp_path: Path) -> None:
    mem.store.plc_jobs.clear()
    job = plc.create_job_record(
        source_type="path",
        source_path=str(FIXTURES),
        project_name="MotorDemo",
        created_by="test",
    )
    out = plc.run_ingest_job(
        job["id"],
        publish_graph=False,
        result_root=str(tmp_path / "work"),
    )
    assert out["status"] == "ready"
    timings = out.get("timings") or {}
    assert timings.get("total_ms", 0) >= 0
    assert "extract_ms" in timings
    assert "logic_graph_ms" in timings
    assert "enrich_ms" in timings
    assert out.get("brief_ready") is True
    assert out.get("ingest_phase") == "ready"

    steps = {p["step"]: p for p in out.get("progress") or []}
    for step in ("detect", "resolve", "structure", "bodies", "enrich", "graph", "ready"):
        assert step in steps, step
        assert "duration_ms" in steps[step], step
        assert steps[step]["status"] == "done"
    mem.store.plc_jobs.clear()
