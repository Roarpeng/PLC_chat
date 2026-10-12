"""ceD2 FB: empty middle network + StatementList/STL CALL (R_TRIG) in network 3."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.flgnet_fold import attach_folded, fold_network
from agents.plc.tia.kg import build_knowledge_graph
from agents.plc.tia.scl import translate_block_to_scl
from agents.plc.tia.simaticml import extract_project, parse_block_xml

LIVE = Path(r"C:\Users\vboxuser\AppData\Local\Temp\researchos_tia_export_gcnxhaun")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_ced2"


def _ced2_xml() -> Path:
    live = LIVE / "Blocks" / "ceD2.xml"
    if live.is_file():
        return live
    fixture = FIXTURE / "Blocks" / "ceD2.xml"
    assert fixture.is_file(), "ceD2.xml fixture missing"
    return fixture


def test_ced2_network3_statement_list_r_trig() -> None:
    block = parse_block_xml(_ced2_xml())
    assert block is not None
    assert block.name == "ceD2"
    assert len(block.networks) == 3

    n1, n2, n3 = block.networks
    assert n1.parts  # LAD contact/coil
    assert not n2.parts and not n2.source_text  # blank
    assert n3.source_text
    assert "R_TRIG_DB" in n3.source_text
    assert "#in2" in n3.source_text
    assert "#out2" in n3.source_text
    assert any(p.name == "R_TRIG" for p in n3.parts.values())

    folded = fold_network(n3)
    assert folded.statements
    assert any("R_TRIG_DB" in (s.target_scl or "") for s in folded.statements)

    scl = translate_block_to_scl(block)
    assert "// ---------- 网络 1 ----------" in scl
    assert "// ---------- 网络 2 ----------" in scl
    assert "// （空白网络）" in scl
    assert "// ---------- 网络 3 ----------" in scl
    assert '"R_TRIG_DB"(CLK := #in2, Q => #out2);' in scl


def test_ced2_kg_uses_r_trig_db() -> None:
    root = LIVE if (LIVE / "Blocks" / "ceD2.xml").is_file() else FIXTURE
    project = attach_folded(extract_project(root, project_name="ced2"))
    assert "ceD2" in project.blocks
    kg = build_knowledge_graph(project)
    assert "R_TRIG_DB" in kg.uses_of("ceD2")
