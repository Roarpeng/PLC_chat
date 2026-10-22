"""Silent parser degradation must be visible: coverage warnings + review truncation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.plc.tia import analyze_tia_exports
from agents.plc.tia.coverage import (
    TODO_RATE_WARN_ENV,
    build_coverage_report,
    coverage_markdown,
    todo_rate_warn_threshold,
)
from agents.plc.tia.ir import Block, BlockType, Network, Part, PlcProject
from agents.plc.tia.review import format_review_markdown, run_review

PARTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_parts"


def _todo_project(todo_parts: int = 4) -> tuple[PlcProject, dict[str, str]]:
    """One LAD block with 4 contacts and ``todo_parts`` untranslated instructions."""
    project = PlcProject(name="WarnDemo", tia_version="V19")
    block = Block(
        name="FB_Warn",
        number=1,
        block_type=BlockType.FB,
        programming_language="LAD",
    )
    network = Network(id="1", title="logic")
    for uid in range(4):
        network.parts[str(uid)] = Part(name="Contact", part_type="Contact", uuid=str(uid))
    block.networks.append(network)
    project.add_block(block)
    scl = "\n".join(f"(* TODO[Mystery{uid}] uid={uid} *)" for uid in range(todo_parts))
    return project, {block.name: scl}


def _codes(coverage: dict[str, Any]) -> set[str]:
    return {str(item.get("code")) for item in coverage.get("warnings") or []}


def test_todo_rate_warning_is_human_readable() -> None:
    project, scl_sources = _todo_project()
    coverage = build_coverage_report(project, scl_sources)

    assert coverage["todo_rate"] > todo_rate_warn_threshold()
    assert coverage["translated_rate"] == round(1 - coverage["todo_rate"], 4)
    warnings = coverage["warnings"]
    todo_warn = next(w for w in warnings if w["code"] == "coverage.todo_rate_high")

    assert todo_warn["level"] == "warning"
    assert todo_warn["count"] == 1
    assert todo_warn["affected_blocks"] == ["FB_Warn"]
    assert "翻译完成度" in todo_warn["message"]
    assert "TODO" in todo_warn["message"]
    assert coverage["warning_count"] == len(warnings)

    markdown = coverage_markdown(coverage)
    assert markdown.index("解析降级告警") < markdown.index("## Status")
    assert "coverage.todo_rate_high" in markdown
    assert "FB_Warn" in markdown


def test_threshold_env_can_silence_todo_warning(monkeypatch) -> None:
    project, scl_sources = _todo_project()
    monkeypatch.setenv(TODO_RATE_WARN_ENV, "1.0")
    coverage = build_coverage_report(project, scl_sources)
    assert "coverage.todo_rate_high" not in _codes(coverage)


def test_graph_downgrade_is_explicit() -> None:
    result = analyze_tia_exports(str(PARTS), project_name="PartsKit")
    coverage = result["coverage"]

    graph = next(
        w for w in coverage["warnings"] if w["code"] == "coverage.graph_not_executable"
    )
    assert graph["level"] == "warning"
    assert "FB_Graph" in graph["affected_blocks"]
    assert "语义不等价" in graph["message"]
    assert "不能直接回写" in graph["message"]
    assert graph["count"] == len(graph["affected_blocks"])


def test_unresolved_parts_blocks_are_named() -> None:
    result = analyze_tia_exports(str(PARTS), project_name="PartsKit")
    coverage = result["coverage"]

    unresolved = next(
        w for w in coverage["warnings"] if w["code"] == "coverage.unresolved_parts"
    )
    assert unresolved["affected_blocks"] == ["FC_Unknown"]
    assert "无法折叠" in unresolved["message"]


def _double_write_job(matches: int) -> dict[str, Any]:
    folded: dict[str, list[dict[str, Any]]] = {}
    for index in range(matches):
        target = f'"Tag{index}"'
        folded[f"FB{index}"] = [
            {"network_id": "1", "statements": [{"target": target, "kind": "coil"}]},
            {"network_id": "2", "statements": [{"target": target, "kind": "coil"}]},
        ]
    return {
        "blocks": [],
        "folded_logic": folded,
        "scl_sources": {},
        "knowledge_graph": {"nodes": [], "edges": []},
    }


def test_review_truncation_is_visible() -> None:
    result = run_review(_double_write_job(60))
    rule = result["rules"]["double_write"]

    assert result["truncated"] is True
    assert result["total_count"] == 60
    assert rule == {"shown": 50, "total_count": 60, "truncated": True}

    hints = [
        f for f in result["findings"] if f.get("rule") == "double_write" and f.get("truncated")
    ]
    assert len(hints) == 1
    assert hints[0]["total_count"] == 60
    assert hints[0]["shown_count"] == 50
    assert "实际命中 60 处" in hints[0]["title"]
    assert "仅展示前 50 处" in hints[0]["title"]

    markdown = format_review_markdown(result)
    assert "报告已截断" in markdown


def test_review_without_truncation_stays_quiet() -> None:
    result = run_review(_double_write_job(2))
    assert result["truncated"] is False
    assert result["total_count"] == 2
    assert result["rules"]["double_write"] == {
        "shown": 2,
        "total_count": 2,
        "truncated": False,
    }
    assert not [f for f in result["findings"] if f.get("truncated")]
    assert "报告已截断" not in format_review_markdown(result)


def test_gateway_degradation_summary_merges_coverage_and_review() -> None:
    from gateway.app.services.plc.ingest import _degradation_summary

    job = {
        "coverage": {
            "todo_rate": 0.4,
            "translated_rate": 0.6,
            "warnings": [
                {
                    "level": "warning",
                    "code": "coverage.todo_rate_high",
                    "message": "只翻译了 60%",
                    "affected_blocks": ["FB_Warn"],
                    "count": 1,
                }
            ],
        },
        "review": run_review(_double_write_job(60)),
        "export_dir": "/tmp/plc_job",
    }
    summary = _degradation_summary(job)

    assert summary["count"] == 2
    assert {w["code"] for w in summary["warnings"]} == {
        "coverage.todo_rate_high",
        "review.truncated",
    }
    assert summary["translated_rate"] == 0.6
    assert summary["review_truncated"] is True
    assert summary["review_total_count"] == 60
    assert str(summary["coverage_path"]).replace("\\", "/").endswith("reports/coverage.json")
