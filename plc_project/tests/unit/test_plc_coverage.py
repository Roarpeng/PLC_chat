"""Per-job conversion coverage.json — honest Part / TODO histogram."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia import analyze_tia_exports
from agents.plc.tia.coverage import build_coverage_report, coverage_markdown
from agents.plc.tia.package import write_result_package

EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
PARTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_parts"


def test_motor_demo_coverage_no_todos():
    result = analyze_tia_exports(str(EXPORTS), project_name="MotorDemo")
    cov = result["coverage"]
    assert cov["total_blocks"] == 3
    assert cov["todo_count"] == 0
    assert cov["todo_rate"] == 0
    assert "LAD" in cov["language_histogram"]
    assert cov["part_histogram"].get("Contact") or cov["part_histogram"].get("Coil")
    md = coverage_markdown(cov)
    assert "Conversion coverage" in md
    assert "Top untranslated" in md


def test_coverage_json_written_in_package(tmp_path: Path):
    result = analyze_tia_exports(str(EXPORTS), project_name="MotorDemo")
    write_result_package(
        tmp_path / "out",
        project=result["project"],
        knowledge_graph=result["knowledge_graph"],
        scl_sources=result["scl_sources"],
        report_md=result["report"],
    )
    cov_path = tmp_path / "out" / "reports" / "coverage.json"
    assert cov_path.is_file()
    text = cov_path.read_text(encoding="utf-8")
    assert "todo_rate" in text
    assert "part_histogram" in text
    assert (tmp_path / "out" / "reports" / "coverage.md").is_file()


def test_parts_kit_histogram_names_unknown():
    result = analyze_tia_exports(str(PARTS), project_name="PartsKit")
    cov = result["coverage"]
    assert cov["todo_histogram"]["MysteriousBox"] >= 1
    assert cov["safety_block_count"] >= 1
    assert cov["hardware_devices"] >= 1
    rebuilt = build_coverage_report(result["project"], result["scl_sources"])
    assert rebuilt["todo_count"] == cov["todo_count"]
