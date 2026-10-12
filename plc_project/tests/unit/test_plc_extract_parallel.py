"""XML parse overlap / thread-pool extract (no TIA Portal)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.plc.tia.extract_stream import ExportJournalExtractor, drain_export_journal
from agents.plc.tia.pipeline import analyze_tia_exports
from agents.plc.tia.simaticml import extract_project

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"


def test_drain_export_journal_skips_partial_line(tmp_path: Path) -> None:
    journal = tmp_path / "_exported.jsonl"
    journal.write_bytes(b'{"name":"OB1","ok":true,"path":"a.xml"}\n{"name":"FB')
    seen: list[dict] = []
    offset = drain_export_journal(journal, 0, seen.append)
    assert [row["name"] for row in seen] == ["OB1"]
    with journal.open("ab") as handle:
        handle.write(b'1","ok":true,"path":"b.xml"}\n')
    drain_export_journal(journal, offset, seen.append)
    assert [row["name"] for row in seen] == ["OB1", "FB1"]


def test_journal_extractor_reset_and_finalize() -> None:
    xml = next(FIXTURES.rglob("*.xml"))
    extractor = ExportJournalExtractor(FIXTURES, project_name="MotorDemo")
    extractor.submit_journal({"ok": True, "path": str(xml), "knowHow": False})
    extractor.submit_journal({"reset": True})
    assert extractor._seen == set()
    project = extractor.finalize()
    assert set(project.blocks) == {"FB_Motor", "Main", "MotorInst"}
    assert set(project.tag_tables) == {"HMI", "Safety"}


def test_parallel_extract_matches_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.plc.tia import parallel as par

    monkeypatch.setattr(par, "ingest_workers", lambda *_a, **_k: 1)
    serial = extract_project(FIXTURES, project_name="MotorDemo")
    monkeypatch.setattr(par, "ingest_workers", lambda *_a, **_k: 4)
    pooled = extract_project(FIXTURES, project_name="MotorDemo")
    assert set(serial.blocks) == set(pooled.blocks)
    assert set(serial.tag_tables) == set(pooled.tag_tables)
    for name, block in serial.blocks.items():
        other = pooled.blocks[name]
        assert block.block_type == other.block_type
        assert len(block.networks) == len(other.networks)
        assert [v.name for v in block.interface] == [v.name for v in other.interface]


def test_analyze_tia_exports_skips_extract_when_project_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = extract_project(FIXTURES, project_name="MotorDemo")
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("extract_project must not run when IR is pre-parsed")

    monkeypatch.setattr("agents.plc.tia.pipeline.extract_project", boom)
    result = analyze_tia_exports(str(FIXTURES), project_name="MotorDemo", project=project)
    assert called["n"] == 0
    assert result["timings"].get("extract_overlapped") == 1
    assert result["timings"].get("extract_ms") == 0
    assert set(result["project"].blocks) == {"FB_Motor", "Main", "MotorInst"}
