"""Contract tests for the PLC service and evidence compatibility facades."""

from __future__ import annotations

import pytest

from gateway.app.services import plc_jobs as plc
from gateway.app.services.plc import chat_evidence


def test_router_facing_plc_service_symbols_are_callable() -> None:
    symbols = [
        "analyze_job",
        "answer_block_chat",
        "build_project_brief",
        "append_chat_turn",
        "build_device_cards",
        "build_export_zip",
        "build_project_brief",
        "list_device_cards",
        "set_device_card_annotation",
        "confirm_job_writeback",
        "create_job_record",
        "delete_job",
        "get_job",
        "list_jobs",
        "propose_job_changeset",
        "propose_job_optimize",
        "query_job_graph",
        "refresh_logic_graph",
        "resolve_allowed_path",
        "retry_structure_export",
        "run_ingest_job",
        "save_upload",
    ]
    for name in symbols:
        assert callable(getattr(plc, name))


def test_chat_evidence_symbols_resolve_from_both_facades() -> None:
    symbols = [
        "_block_meta",
        "_describe_block_function",
        "_format_block_runtime_explain",
        "_format_signal_trace",
        "_lookup_instance_entity",
        "_resolve_block_focus",
        "_resolve_block_scl_text",
    ]
    for name in symbols:
        assert getattr(chat_evidence, name) is getattr(plc, name)


def test_confirm_writeback_uses_plc_jobs_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_confirm(job, **kwargs):
        calls.append(kwargs)
        return {"scope": f"block:{kwargs['block_name']}", "skipped": True}

    monkeypatch.setattr(plc, "confirm_job_writeback", fake_confirm)
    job = {"changeset": {"id": "cs", "ops": []}}
    text = plc._format_confirm_writeback_chat(job, "FB_A")

    assert len(calls) == 1
    assert calls[0]["block_name"] == "FB_A"
    assert "**确认反写**" in text


def test_propose_changeset_uses_plc_jobs_optimize_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = {"id": "optimized"}
    calls: list[dict[str, object]] = []

    def fake_optimize(job, **kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(plc, "propose_job_optimize", fake_optimize)
    result = plc.propose_job_changeset({}, "优化SCL", "FB_A")

    assert result is sentinel
    assert calls == [{"block_name": "FB_A", "message": "优化SCL"}]
