"""End-to-end tests — TIA Openness export -> PLC-IR -> KG -> SCL pipeline.

Fixtures in tests/fixtures/tia_exports mimic a real Openness export of a
motor-control project (FB_Motor self-holding LAD, OB1 calling it, a
background instance DB and two tag tables).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.plc.tia import analyze_tia_exports
from agents.plc.tia.ir import BlockType
from agents.plc.tia.scl import llm_prompt_for_network
from agents.plc.tia.simaticml import parse_block_xml, parse_tag_table_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"


@pytest.fixture(scope="module")
def result():
    return analyze_tia_exports(str(FIXTURES), project_name="MotorDemo")


# ---------------------------------------------------------------------------
# Extract: SimaticML -> PLC-IR
# ---------------------------------------------------------------------------

def test_extract_project_structure(result):
    project = result["project"]
    assert project.extraction_notes == []
    assert set(project.blocks) == {"FB_Motor", "Main", "MotorInst"}
    assert set(project.tag_tables) == {"HMI", "Safety"}
    assert project.summary() == {
        "FB": 1,
        "OB": 1,
        "DB": 1,
        "TagTables": 2,
        "Networks": 2,
        "SafetyBlocks": 0,
        "Hardware": 0,
        "WatchTables": 0,
        "ForceTables": 0,
        "TechnologyObjects": 0,
        "Alarms": 0,
        "ProDiag": 0,
        "CfcCharts": 0,
        "SafetyUnits": 0,
        "HmiDevices": 0,
        "OpcUaNodes": 0,
    }


def test_fb_motor_block_details(result):
    fb = result["project"].blocks["FB_Motor"]
    assert fb.block_type == BlockType.FB
    assert fb.number == 100
    assert fb.programming_language == "LAD"
    assert "self-holding" in fb.header_comment
    names = {v.name: v.section.value for v in fb.interface}
    assert names == {"Start": "Input", "Stop": "Input", "Fault": "Input", "Running": "Output"}
    assert len(fb.networks) == 1
    net = fb.networks[0]
    assert net.title == "Self-holding motor start"
    assert len(net.parts) == 5
    assert len(net.access_parts) == 5
    assert len(net.wires) == 9


def test_tag_tables_parsed(result):
    hmi = result["project"].tag_tables["HMI"]
    assert [t.name for t in hmi.tags] == ["StartCmd", "StopCmd"]
    assert hmi.tags[0].logical_address == "%I0.0"
    assert hmi.tags[0].comment == "HMI start pushbutton"
    safety = result["project"].tag_tables["Safety"]
    assert [t.name for t in safety.tags] == ["FaultOk"]


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------

def test_kg_calls_and_instance_edges(result):
    kg = result["knowledge_graph"]
    assert kg.callers_of("FB_Motor") == ["Main"]
    assert kg.callees_of("Main") == ["FB_Motor"]
    instance_edges = [
        e for e in kg.edges if e.type == "INSTANCE_OF"
    ]
    assert [(e.source, e.target) for e in instance_edges] == [
        ("Block::MotorInst", "Block::FB_Motor")
    ]


def test_kg_read_write_classification(result):
    kg = result["knowledge_graph"]
    assert kg.writers_of_tag("#Running") == ["FB_Motor"]
    assert kg.readers_of_tag("#Running") == ["FB_Motor"]
    assert kg.readers_of_tag("#Start") == ["FB_Motor"]
    assert kg.readers_of_tag("HMI.StartCmd") == ["Main"]
    # coil operands must never be classified as reads
    reads_running = [
        e for e in kg.edges if e.type == "READS" and e.target == "Tag::#Stop"
    ]
    assert [e.source for e in reads_running] == ["Block::FB_Motor"]


def test_kg_json_roundtrip(result):
    data = result["knowledge_graph"].to_json()
    assert {n["id"] for n in data["nodes"]} >= {
        "Project::MotorDemo",
        "Block::FB_Motor",
        "Block::Main",
        "Block::MotorInst",
        "TagTable::HMI",
        "Tag::StartCmd",
    }
    assert all({"source", "target", "type"} <= set(e) for e in data["edges"])


# ---------------------------------------------------------------------------
# SCL translation
# ---------------------------------------------------------------------------

def test_scl_self_holding_expression(result):
    scl = result["scl_sources"]["FB_Motor"]
    assert "#Running := ((#Start OR #Running) AND NOT (#Stop)) AND NOT (#Fault);" in scl
    assert "VAR_INPUT" in scl and "END_VAR" in scl
    assert "VAR_OUTPUT" in scl
    assert 'FUNCTION_BLOCK "FB_Motor"' in scl
    assert "END_FUNCTION_BLOCK" in scl
    assert "// 将" in scl or "// 含义" in scl


def test_scl_call_statement(result):
    scl = result["scl_sources"]["Main"]
    assert (
        '#MotorInst(Start := "HMI".StartCmd, '
        'Stop := "HMI".StopCmd, Fault := "Safety".FaultOk);' in scl
    )
    assert 'ORGANIZATION_BLOCK "Main"' in scl
    assert "END_ORGANIZATION_BLOCK" in scl


def test_scl_db_instance(result):
    scl = result["scl_sources"]["MotorInst"]
    assert 'DATA_BLOCK "MotorInst"' in scl
    assert "Start : Bool;" in scl and "END_DATA_BLOCK" in scl


def test_llm_fallback_prompt_has_full_context(result):
    fb = result["project"].blocks["FB_Motor"]
    prompt = llm_prompt_for_network(fb, fb.networks[0])
    assert "FB_Motor" in prompt
    assert "Part UId=31" in prompt
    assert "Wire UId=41" in prompt
    assert "SCL" in prompt


# ---------------------------------------------------------------------------
# Direct parser entry points + CLI
# ---------------------------------------------------------------------------

def test_parse_block_xml_returns_none_for_tag_table():
    assert parse_block_xml(FIXTURES / "TagTables" / "HMI.xml") is None
    table = parse_tag_table_xml(FIXTURES / "Blocks" / "FB_Motor.xml")
    assert table is None


def test_cli_runs_end_to_end(tmp_path, capsys):
    from agents.plc.tia_cli import main

    code = main(
        [
            "--exports",
            str(FIXTURES),
            "--project-name",
            "MotorDemo",
            "--result-dir",
            str(tmp_path / "ResearchOS_PLC_Result"),
            "--json-summary",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "#Running := ((#Start OR #Running)" in captured.out
    result_root = tmp_path / "ResearchOS_PLC_Result"
    assert (result_root / "converted_scl" / "FB_Motor.scl").exists()
    assert (result_root / "converted_scl" / "Main.scl").exists()
    assert (result_root / "plc_ir" / "project.json").exists()
    assert (result_root / "knowledge_graph" / "graph.json").exists()
    assert (result_root / "reports" / "analysis.md").exists()
    assert (result_root / "reports" / "conversion_report.json").exists()
    assert (result_root / "reports" / "coverage.json").exists()
    assert (result_root / "manifest.json").exists()


def test_analyze_plc_project_from_export_dir(tmp_path):
    from agents.plc.tia import analyze_plc_project

    result = analyze_plc_project(
        str(FIXTURES),
        project_name="MotorDemo",
        result_dir=str(tmp_path / "out"),
    )
    assert result["import"]["source_kind"] == "export_dir"
    assert result["conversion_report"]["total_blocks"] >= 3
    assert result["conversion_report"]["converted"] >= 1
    assert (tmp_path / "out" / "converted_scl" / "FB_Motor.scl").exists()


def test_classify_input_apxx():
    from agents.plc.tia.importer import classify_input

    assert classify_input(Path("C:/x/Machine.ap19")) == "apxx"
    assert classify_input(FIXTURES) == "export_dir"
    assert classify_input(FIXTURES / "Blocks" / "FB_Motor.xml") == "export_xml"
    assert classify_input(Path("C:/x/Line.zap19")) == "archive"
    assert classify_input(Path("C:/x/Line.zap")) == "archive"
    assert classify_input(Path("C:/x/pack.zip")) == "archive"


def test_extract_zap_archive_with_simaticml(tmp_path: Path):
    import zipfile

    from agents.plc.tia import analyze_plc_project
    from agents.plc.tia.importer import extract_tia_archive

    zap = tmp_path / "demo.zap19"
    with zipfile.ZipFile(zap, "w") as zf:
        xml = (FIXTURES / "Blocks" / "Main_OB1.xml").read_bytes()
        zf.writestr("Project/Blocks/Main_OB1.xml", xml)

    root = extract_tia_archive(zap, dest=tmp_path / "out")
    assert (root / "Blocks" / "Main_OB1.xml").is_file() or list(root.rglob("Main_OB1.xml"))

    result = analyze_plc_project(str(zap), project_name="ZapDemo", publish_graph=False)
    assert result["project"].blocks
    # notes may land on project.extraction_notes and/or import.notes
    notes = " ".join(
        list(result.get("import", {}).get("notes") or [])
        + list(result["project"].extraction_notes or [])
    ).lower()
    assert "extract" in notes or "archive" in notes or "zap" in notes


def test_format_openness_license_error():
    from agents.plc.tia.openness_cli import format_openness_failure, is_license_error

    raw = (
        "DB1000_StdSignal:Error when calling method 'Export' of type "
        "'Siemens.Engineering.SW.Blocks.InstanceDB'. Necessary license 'STEP 7 Basic' is missing."
    )
    assert is_license_error(raw)
    msg = format_openness_failure(raw, project_path="C:/x/Line.ap19", action="export")
    assert "STEP 7" in msg or "许可证" in msg
    assert "Automation License Manager" in msg
    assert "没有 SimaticML" not in msg


def test_format_openness_inconsistent_blocks_error():
    from agents.plc.tia.openness_cli import (
        format_openness_failure,
        is_inconsistent_export_error,
    )

    raw = (
        "ce:Error when calling method 'Export' of type 'Siemens.Engineering.SW.Blocks.FC'.\n"
        "Inconsistent blocks and PLC data types (UDT) cannot be exported.\n"
        "Exported 0 blocks; 2 failed"
    )
    assert is_inconsistent_export_error(raw)
    msg = format_openness_failure(raw, project_path="C:/x/test1.ap19", action="export")
    assert "不一致" in msg or "Inconsistent" in msg
    assert "编译" in msg
    assert ".zap" in msg


def test_pick_zap_junk_xml_prefers_apxx(tmp_path: Path):
    """Real .zap often has ConversionLog/GSD XML + .ap19 — must not treat as SimaticML."""
    import zipfile

    from agents.plc.tia.importer import (
        diagnose_extracted_tree,
        extract_tia_archive,
        has_simaticml_exports,
        openness_unavailable_guidance,
        resolve_project_input,
    )

    zap = tmp_path / "raw.zap19"
    with zipfile.ZipFile(zap, "w") as zf:
        zf.writestr("Logs/ConversionLog.xml", b"<ConversionLog><Item/></ConversionLog>")
        zf.writestr(
            "Vci/AdditionalFiles/GSD/GSDML-V2.3-demo.xml",
            b'<?xml version="1.0"?><ISO15745Profile xmlns="http://www.profibus.com/GSDML"/>',
        )
        zf.writestr("Line/Plant.ap19", b"fake-binary-ap19")

    root = extract_tia_archive(zap, dest=tmp_path / "out")
    assert root.suffix.lower() == ".ap19"
    assert not has_simaticml_exports(tmp_path / "out")
    diag = diagnose_extracted_tree(tmp_path / "out")
    assert diag["mode"] == "apxx_needs_openness"

    try:
        resolve_project_input(zap, auto_export=True)
        raise AssertionError("expected Openness failure guidance")
    except Exception as exc:
        text = str(exc)
        assert "Plant.ap19" in text or ".ap" in text
        # Incomplete sidecar tree (preferred) or classic Openness-unavailable guidance.
        assert (
            "孤立的 TIA 工程" in text
            or "Retrieve" in text
            or "Openness" in text
        )
        assert "SimaticML" in text or "整包" in text or ".zap" in text


def test_ingest_single_xml_and_publish_graph():
    from agents.plc.tia import analyze_plc_project
    from tools.plc.server import plc_tia_ingest

    xml = FIXTURES / "Blocks" / "FB_Motor.xml"
    analyzed = analyze_plc_project(str(xml), project_name="SingleFB", publish_graph=True)
    assert analyzed["import"]["source_kind"] == "export_xml"
    assert "FB_Motor" in analyzed["project"].blocks
    assert analyzed["graph_publish"]["ok"] is True
    assert analyzed["graph_publish"]["entities"] >= 1

    via_tool = plc_tia_ingest(str(FIXTURES), project_name="MotorDemo", publish_graph=True)
    assert via_tool["ok"] is True
    assert via_tool["pipeline"].startswith("XML")
    assert via_tool["graph_publish"]["ok"] is True
    assert via_tool["summary"]["Networks"] == 2


def test_mcp_client_dispatches_tia_ingest():
    from runtime.researchos_runtime.mcp_client import MCPClient
    from runtime.researchos_runtime.settings import RuntimeSettings

    client = MCPClient(RuntimeSettings())
    result = client.call_tool(
        "plc.tia.ingest",
        {"path": str(FIXTURES), "project_name": "MotorDemo", "publish_graph": True},
        task_id="t1",
    )
    assert result["ok"] is True
    assert result["result"]["ok"] is True
    assert result["result"]["graph_publish"]["entities"] >= 1


def test_cli_missing_dir_exits_nonzero():
    from agents.plc.tia_cli import main

    assert main(["--exports", str(FIXTURES.parent / "does_not_exist")]) == 2


def test_cli_empty_export_exits_nonzero(tmp_path):
    from agents.plc.tia_cli import main

    empty = tmp_path / "empty_exports"
    empty.mkdir()
    assert main(["--exports", str(empty)]) == 1
    assert main(["--exports", str(empty), "--allow-empty"]) == 0


def test_unrecognized_xml_is_noted(tmp_path):
    junk = tmp_path / "junk.xml"
    junk.write_text("<Root><DocumentType>Other.ML</DocumentType></Root>", encoding="utf-8")
    result = analyze_tia_exports(str(tmp_path))
    notes = " ".join(result["project"].extraction_notes)
    assert "unrecognized XML skipped" in notes
    assert "no PLC blocks or tag tables recognized" in notes


def test_missing_export_dir_reports_note():
    result = analyze_tia_exports(str(FIXTURES.parent / "does_not_exist"))
    assert result["project"].extraction_notes
    assert result["scl_sources"] == {}


def test_protected_block_skipped_from_scl(tmp_path):
    """Know-how protected blocks are kept original and never emitted as SCL."""
    from agents.plc.tia.ir import Block, BlockType, PlcProject
    from agents.plc.tia.package import write_result_package
    from agents.plc.tia.scl import convert_project_to_scl
    from agents.plc.tia.kg import build_knowledge_graph
    from agents.plc.tia.pipeline import interpretation_report

    xml = tmp_path / "FB_Secret.xml"
    xml.write_text(
        """<?xml version="1.0"?>
        <Document>
          <DocumentInfo><DocumentType>SimaticML.SW.Blocks.FB</DocumentType></DocumentInfo>
          <SW.Blocks.ObjectSW Name="FB_Secret">
            <AttributeList>
              <Name>FB_Secret</Name>
              <Number>100</Number>
              <ProgrammingLanguage>LAD</ProgrammingLanguage>
              <KnowHowProtection>true</KnowHowProtection>
            </AttributeList>
          </SW.Blocks.ObjectSW>
        </Document>
        """,
        encoding="utf-8",
    )
    from agents.plc.tia.simaticml import parse_block_xml

    secret = parse_block_xml(xml)
    assert secret is not None
    assert secret.is_protected() is True

    open_block = Block(
        name="FB_Open",
        block_type=BlockType.FB,
        programming_language="SCL",
        source_text="A := B;",
        attributes={},
    )
    project = PlcProject(name="ProtDemo")
    project.add_block(secret)
    project.add_block(open_block)
    scl = convert_project_to_scl(project)
    assert "FB_Secret" not in scl
    assert "FB_Open" in scl

    kg = build_knowledge_graph(project)
    report = interpretation_report(project, kg)
    out = tmp_path / "ResearchOS_PLC_Result"
    conversion = write_result_package(
        out,
        project=project,
        knowledge_graph=kg,
        scl_sources=scl,
        report_md=report,
    )
    assert conversion["protected"] == 1
    assert not (out / "converted_scl" / "FB_Secret.scl").exists()
    assert (out / "original" / "protected_blocks" / "FB_Secret.xml").exists()
    assert (out / "converted_scl" / "FB_Open.scl").exists()


def test_interface_only_fb_io_calls_and_call_param_enrichment():
    """Body-locked FB keeps open I/O; CALLS + CallInfo params enrich missing pins."""
    from agents.plc.tia.ir import (
        Block,
        BlockType,
        InterfaceSection,
        Network,
        Part,
        PlcProject,
        Variable,
    )
    from agents.plc.tia.kg import build_knowledge_graph
    from agents.plc.tia.package import classify_block
    from agents.plc.tia.scl import convert_project_to_scl

    locked = Block(
        name="FB_Locked",
        block_type=BlockType.FB,
        programming_language="LAD",
        interface=[
            Variable(name="Enable", section=InterfaceSection.INPUT, data_type="Bool"),
            Variable(name="Done", section=InterfaceSection.OUTPUT, data_type="Bool"),
            Variable(name="PT", section=InterfaceSection.INPUT, data_type="Time"),
            Variable(name="PT", section=InterfaceSection.STATIC, data_type="Time"),
        ],
        networks=[],
        attributes={},  # no KnowHow tag — still interface-only by body absence
    )
    assert locked.is_interface_only() is True
    assert locked.is_protected() is False

    caller = Block(
        name="OB1Main",
        block_type=BlockType.OB,
        programming_language="LAD",
        networks=[
            Network(
                id="1",
                title="call locked",
                parts={
                    "1": Part(
                        name="Call",
                        part_type="Call",
                        uuid="1",
                        template_values={
                            "Call": "FB_Locked",
                            "BlockType": "FB",
                            "InstanceDB": "FB_Locked_DB",
                            "__sec__Enable": "Input",
                            "__type__Enable": "Bool",
                            "__sec__Done": "Output",
                            "__type__Done": "Bool",
                            "__sec__ExtraIn": "Input",
                            "__type__ExtraIn": "Int",
                        },
                    )
                },
            )
        ],
    )
    project = PlcProject(name="IfaceOnlyDemo")
    project.add_block(locked)
    project.add_block(caller)

    scl = convert_project_to_scl(project)
    assert "FB_Locked" not in scl
    assert classify_block(locked, None)["status"] == "interface_only"

    kg = build_knowledge_graph(project)
    node = kg.nodes["Block::FB_Locked"]
    assert node.props.get("interface_only") is True
    assert node.props.get("body_available") is False

    # Homonym Input/Static PT both present
    assert "Variable::FB_Locked::Input::PT" in kg.nodes
    assert "Variable::FB_Locked::Static::PT" in kg.nodes
    assert "Variable::FB_Locked::Input::Enable" in kg.nodes

    assert "OB1Main" in kg.callers_of("FB_Locked")
    assert any(
        e.type == "CALLS" and e.source == "Block::OB1Main" and e.target == "Block::FB_Locked"
        for e in kg.edges
    )
    # Call-site pin not already on FB interface → inferred HAS_INTERFACE
    assert "Variable::FB_Locked::Input::ExtraIn" in kg.nodes
    assert any(v.name == "ExtraIn" for v in locked.interface)
