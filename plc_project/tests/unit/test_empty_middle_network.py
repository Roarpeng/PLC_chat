"""Empty middle network must not drop later StructuredText / LAD networks."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.flgnet_fold import fold_network
from agents.plc.tia.scl import translate_block_to_scl
from agents.plc.tia.simaticml import parse_block_xml

LIVE_DC = Path(r"C:\Users\vboxuser\AppData\Local\Temp\researchos_tia_export_8m8x37te\Blocks\dc.xml")
FIXTURE_DC = Path(__file__).resolve().parents[1] / "fixtures" / "tia_dc" / "Blocks" / "dc.xml"


def _dc_path() -> Path:
    if LIVE_DC.is_file():
        return LIVE_DC
    assert FIXTURE_DC.is_file(), "dc.xml fixture missing"
    return FIXTURE_DC


def test_empty_middle_network_keeps_structured_text_network() -> None:
    block = parse_block_xml(_dc_path())
    assert block is not None
    assert block.name == "dc"
    assert len(block.networks) == 3

    n1, n2, n3 = block.networks
    assert n1.parts  # LAD contact/coil
    assert not n2.parts and not n2.source_text  # blank
    assert n3.source_text  # StructuredText SCL
    assert "TON" in n3.source_text
    assert "Tag_4" in n3.source_text
    assert "END_IF" in n3.source_text

    for net in block.networks:
        net.folded = fold_network(net)
    assert n3.folded is not None and n3.folded.statements

    scl = translate_block_to_scl(block)
    assert "// ---------- 网络 1 ----------" in scl
    assert "// ---------- 网络 2 ----------" in scl
    assert "// （空白网络）" in scl
    assert "// ---------- 网络 3 ----------" in scl
    assert '"IEC_Timer_0_DB".TON' in scl
    assert 'IF "Tag_4" THEN' in scl
    assert "END_IF;" in scl
