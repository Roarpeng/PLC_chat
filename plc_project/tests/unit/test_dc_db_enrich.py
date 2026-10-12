"""InstanceDB dc_DB must recover multi-instance members from FB dc logic."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.kg import build_knowledge_graph
from agents.plc.tia.scl import translate_block_to_scl
from agents.plc.tia.simaticml import extract_project

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tia_dc"
LIVE_DIR = Path(r"C:\Users\vboxuser\AppData\Local\Temp\researchos_tia_export_h0tpt8qt")


def _export_dir() -> Path:
    if (LIVE_DIR / "Blocks" / "dc_DB.xml").is_file() and (LIVE_DIR / "Blocks" / "dc.xml").is_file():
        return LIVE_DIR
    assert (FIXTURE_DIR / "Blocks" / "dc_DB.xml").is_file()
    assert (FIXTURE_DIR / "Blocks" / "dc.xml").is_file()
    return FIXTURE_DIR


def test_dc_db_recovers_multi_instance_timer() -> None:
    project = extract_project(_export_dir(), project_name="tia_dc")
    assert "dc" in project.blocks
    assert "dc_DB" in project.blocks

    dc = project.blocks["dc"]
    dc_db = project.blocks["dc_DB"]
    assert dc_db.attributes.get("InstanceOfName") == "dc"

    dc_names = {v.name for v in dc.interface}
    db_names = {v.name for v in dc_db.interface}
    assert "IEC_Timer_0_DB" in dc_names
    assert "IEC_Timer_0_DB" in db_names
    timer = next(v for v in dc_db.interface if v.name == "IEC_Timer_0_DB")
    assert timer.data_type.startswith("TON")
    assert timer.section.value == "Static"

    scl = translate_block_to_scl(dc_db)
    assert 'DATA_BLOCK "dc_DB"' in scl
    assert '类型 FB "dc"' in scl
    assert "IEC_Timer_0_DB" in scl
    assert "timePt" in scl and "timeS" in scl

    kg = build_knowledge_graph(project)
    edges = {(e.source, e.target, e.type) for e in kg.edges}
    assert ("Block::dc_DB", "Block::dc", "INSTANCE_OF") in edges
