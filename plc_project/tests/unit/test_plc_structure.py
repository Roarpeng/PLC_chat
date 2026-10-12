"""M1 trusted structure — no silent missing blocks."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.pipeline import analyze_tia_exports
from agents.plc.tia.simaticml import extract_project
from agents.plc.tia.structure import (
    build_structure_inventory,
    load_export_journal,
    normalize_skip_reason,
    status_from_reason,
)
from gateway.app.services.plc.ingest import _block_list
from gateway.app.services import plc_jobs as plc
from gateway.app.services import store as mem

SURFACE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_openness_surface"
EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"


def test_status_vocabulary():
    assert status_from_reason("", exported=True) == "exported"
    assert status_from_reason("know_how") == "skipped"
    assert status_from_reason("inconsistent") == "failed"
    assert status_from_reason("") == "pending"
    assert normalize_skip_reason("Necessary license STEP 7 Basic is missing") == "no_license"
    assert normalize_skip_reason("IsConsistent=false") == "inconsistent"


def test_surface_inventory_includes_skipped_vendor_block():
    project = extract_project(SURFACE, project_name="OpennessSurface")
    inv = build_structure_inventory(project)
    by_name = {u["name"]: u for u in inv["units"]}
    assert "FB_Vendor" in by_name
    assert by_name["FB_Vendor"]["status"] == "skipped"
    assert by_name["FB_Vendor"]["reason"] == "know_how"
    assert "Main" in by_name
    assert by_name["Main"]["status"] == "exported"
    assert inv["counts"]["skipped"] >= 1
    assert inv["layers"]["device_tree"]
    assert inv["layers"]["program_blocks"]
    assert inv["layers"]["interface_dbs"]
    assert inv["layers"]["tags"]


def test_journal_failed_block_is_never_omitted(tmp_path: Path):
    dest = tmp_path / "plc" / "PLC_1" / "blocks"
    dest.mkdir(parents=True)
    (dest / "OB1.xml").write_text(
        '<?xml version="1.0"?><Document><SW.Blocks.OB Name="Main">'
        "<AttributeList><Name>Main</Name><Number>1</Number>"
        "<ProgrammingLanguage>LAD</ProgrammingLanguage></AttributeList>"
        "</SW.Blocks.OB></Document>",
        encoding="utf-8",
    )
    (tmp_path / "_exported.jsonl").write_text(
        '{"name":"Main","type":"OB","ok":true,"path":"plc/PLC_1/blocks/OB1.xml"}\n'
        '{"name":"FB_Broken","type":"FB","ok":false,"error":"IsConsistent=false"}\n',
        encoding="utf-8",
    )
    project = extract_project(tmp_path, project_name="JournalGaps")
    assert project.export_journal
    assert load_export_journal(tmp_path)
    inv = build_structure_inventory(project)
    by_name = {u["name"]: u for u in inv["units"]}
    assert by_name["Main"]["status"] == "exported"
    assert by_name["FB_Broken"]["status"] == "failed"
    assert by_name["FB_Broken"]["reason"] == "inconsistent"
    assert by_name["FB_Broken"]["retryable"] is True
    blocks = _block_list(project, inv)
    names = {b["name"] for b in blocks}
    assert names == {"Main", "FB_Broken"}
    broken = next(b for b in blocks if b["name"] == "FB_Broken")
    assert broken["status"] == "failed"


def test_call_graph_missing_callee_is_pending():
    project = extract_project(EXPORTS, project_name="MotorDemo")
    kg = {
        "edges": [
            {"type": "CALLS", "source": "Block::Main", "target": "Block::GhostFB"},
        ]
    }
    inv = build_structure_inventory(project, knowledge_graph=kg)
    by_name = {u["name"]: u for u in inv["units"]}
    assert by_name["GhostFB"]["status"] == "pending"
    assert inv["layers"]["call_graph"]["missing_callees"]
    assert any(e["target"] == "GhostFB" for e in inv["layers"]["call_graph"]["edges"])


def test_empty_category_is_skipped_not_silent(tmp_path: Path):
    dest = tmp_path / "plc" / "PLC_1" / "blocks"
    dest.mkdir(parents=True)
    (dest / "OB1.xml").write_text(
        '<?xml version="1.0"?><Document><SW.Blocks.OB Name="Main">'
        "<AttributeList><Name>Main</Name><Number>1</Number>"
        "<ProgrammingLanguage>LAD</ProgrammingLanguage></AttributeList>"
        "</SW.Blocks.OB></Document>",
        encoding="utf-8",
    )
    project = extract_project(tmp_path, project_name="BlocksOnly")
    inv = build_structure_inventory(project)
    cats = {u["name"]: u for u in inv["units"] if u["kind"] == "category"}
    assert "watch" in cats
    assert cats["watch"]["status"] == "skipped"
    assert cats["watch"]["reason"] == "no_export"


def test_analyze_pipeline_exposes_structure():
    result = analyze_tia_exports(str(SURFACE), project_name="OpennessSurface")
    structure = result["structure"]
    assert structure["counts"]["total"] >= 1
    assert result["coverage"]["structure"]["exported"] >= 1
    names = {u["name"] for u in structure["units"]}
    assert "FB_Vendor" in names
    assert "Main" in names


def test_ingest_job_surfaces_structure_and_skipped_block(tmp_path: Path):
    mem.store.plc_jobs.clear()
    job = plc.create_job_record(
        source_type="path",
        source_path=str(SURFACE),
        project_name="OpennessSurface",
        created_by="test",
    )
    out = plc.run_ingest_job(job["id"], publish_graph=False, result_root=str(tmp_path))
    assert out["status"] == "ready"
    assert out["structure"]["counts"]["total"] >= 1
    by_name = {b["name"]: b for b in out["blocks"]}
    assert "FB_Vendor" in by_name
    assert by_name["FB_Vendor"]["status"] == "skipped"
    assert by_name["Main"]["status"] == "exported"
    assert (tmp_path / "researchos_plc_jobs" / job["id"] / "package" / "reports" / "structure.json").is_file()
