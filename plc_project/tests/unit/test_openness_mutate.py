"""Openness mutate surface — classify, F-write refuse, retrieve fallback (no Portal)."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.changeset import PlcChangeOp, PlcChangeSet
from agents.plc.tia.coverage import build_category_coverage
from agents.plc.tia.simaticml import extract_project
from agents.plc.tia.surface import classify_xml_kind, xml_looks_like_safety
from agents.plc.tia.writeback import execute_writeback, prepare_writeback

SURFACE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_openness_surface"
PARTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_parts"


def test_classify_xml_kind_udt_tag_watch():
    udt = (SURFACE / "plc" / "PLC_1" / "types" / "UDT_Motor.xml").read_text(encoding="utf-8")
    tags = (SURFACE / "plc" / "PLC_1" / "tags" / "DefaultTagTable.xml").read_text(encoding="utf-8")
    watch = (SURFACE / "plc" / "PLC_1" / "watch" / "Watch_Main.xml").read_text(encoding="utf-8")
    assert classify_xml_kind("types/UDT_Motor.xml", udt) == "type"
    assert classify_xml_kind("tags/DefaultTagTable.xml", tags) == "tag"
    assert classify_xml_kind("watch/Watch_Main.xml", watch) == "watch"


def test_xml_looks_like_safety_refuses_f_block():
    fxml = PARTS / "FB_FSafety.xml"
    assert xml_looks_like_safety(fxml)
    assert not xml_looks_like_safety(SURFACE / "plc" / "PLC_1" / "types" / "UDT_Motor.xml")


def test_coverage_empty_category_is_not_silent(tmp_path: Path):
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
    cats = build_category_coverage(project)
    for name in ("watch", "force", "cfc", "opcua", "hmi"):
        reasons = {r["reason"] for r in cats[name]["skipped_reasons"]}
        assert "no_export" in reasons, name


def test_hardware_parses_network_interface():
    project = extract_project(SURFACE, project_name="OpennessSurface")
    nics = [nic for d in project.hardware for nic in (d.network_interfaces or [])]
    assert "X1" in nics


def test_writeback_routes_udt_and_skips_f_xml(tmp_path: Path, monkeypatch):
    bundle_root = tmp_path / "export"
    udt = SURFACE / "plc" / "PLC_1" / "types" / "UDT_Motor.xml"
    fxml = PARTS / "FB_FSafety.xml"
    cs = PlcChangeSet(
        id="wb-udt",
        ops=[
            PlcChangeOp(kind="stage_xml_import", payload={"xml_path": str(udt)}),
            PlcChangeOp(kind="stage_xml_import", payload={"xml_path": str(fxml)}),
        ],
    )
    bundle = prepare_writeback(bundle_root, cs, [])
    kinds: list[str] = []

    def fake_xml(*_a, **_k):
        raise AssertionError("block import should not run for UDT")

    def fake_import_xml(project_path, xml_path, **kwargs):
        kinds.append(str(kwargs.get("kind")))
        return {"ok": True, "import": {"ok": True, "kind": kwargs.get("kind")}}

    def fake_compile(project_path, **_k):
        return {"ok": True, "compile": {"ok": True, "apiAvailable": True, "errorCount": 0}}

    monkeypatch.setattr("agents.plc.tia.writeback.import_block_via_openness_cli", fake_xml)
    monkeypatch.setattr("agents.plc.tia.writeback.import_xml_via_openness_cli", fake_import_xml)
    monkeypatch.setattr("agents.plc.tia.writeback.compile_plc_via_openness_cli", fake_compile)

    project = tmp_path / "Line.ap19"
    project.write_bytes(b"fake")
    result = execute_writeback(project, bundle, plc_name="PLC_1")
    assert "type" in kinds
    assert result["import_ok"] is False
    skipped = [row for row in result["results"] if (row.get("result") or {}).get("skipReason") == "safety_block"]
    assert skipped, "F-block XML must be skipped"


def test_retrieve_falls_back_to_unzip_when_openness_missing(tmp_path: Path, monkeypatch):
    from agents.plc.tia import importer as imp

    zap = tmp_path / "demo.zap19"
    import zipfile

    with zipfile.ZipFile(zap, "w") as zf:
        zf.writestr(
            "Blocks/OB1.xml",
            '<?xml version="1.0"?><Document><SW.Blocks.OB Name="Main">'
            "<AttributeList><Name>Main</Name><Number>1</Number>"
            "<ProgrammingLanguage>LAD</ProgrammingLanguage></AttributeList>"
            "</SW.Blocks.OB></Document>",
        )

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.try_retrieve_archive_via_openness_cli",
        lambda *a, **k: None,
    )
    resolved = imp.resolve_project_input(zap, auto_export=False)
    assert resolved.export_dir is not None
    xmls = list(Path(resolved.export_dir).rglob("*.xml"))
    assert xmls


def test_retrieve_cli_wrapper_mocked(tmp_path: Path, monkeypatch):
    from agents.plc.tia import openness_cli as oc

    ap = tmp_path / "Line.ap19"
    ap.write_bytes(b"ap")
    monkeypatch.setattr(
        oc,
        "openness_cli",
        lambda *a, **k: {
            "ok": True,
            "retrieve": {"ok": True, "projectPath": str(ap), "api": "Projects.Retrieve(FileInfo, DirectoryInfo)"},
        },
    )
    got = oc.retrieve_archive_via_openness_cli(tmp_path / "x.zap19", out=tmp_path / "out")
    assert got == ap


def test_generate_source_from_block_wrapper_mocked(tmp_path: Path, monkeypatch):
    from agents.plc.tia import openness_cli as oc

    monkeypatch.setattr(
        oc,
        "openness_cli",
        lambda *a, **k: {
            "ok": True,
            "generate": {
                "ok": True,
                "blockName": "FB_Motor",
                "api": "GenerateSourceFromBlocks(FileInfo)",
            },
        },
    )
    result = oc.generate_source_from_block_via_openness_cli(tmp_path / "Line.ap19", "FB_Motor")
    assert result["ok"] is True
