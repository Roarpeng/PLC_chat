from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from gateway.app.main import create_app
from plc_engine.standalone_api import (
    StandalonePlcEngine,
    audit_block_content,
    extract_tag_table_content,
    parse_simaticml_block_content,
    translate_simaticml_to_scl,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
CE_DIR = FIXTURES_DIR / "tia_ce"
FC_CE_XML = CE_DIR / "Blocks" / "FC_ce.xml"
MAIN_XML = CE_DIR / "Blocks" / "Main.xml"
HMI_XML = FIXTURES_DIR / "tia_exports" / "TagTables" / "HMI.xml"


def test_translate_simaticml_to_scl_from_file() -> None:
    assert FC_CE_XML.is_file()
    scl = translate_simaticml_to_scl(FC_CE_XML)
    assert 'FUNCTION "ce"' in scl
    assert "BEGIN" in scl


def test_translate_simaticml_to_scl_from_string() -> None:
    xml_text = MAIN_XML.read_text(encoding="utf-8")
    scl = translate_simaticml_to_scl(xml_text)
    assert 'ORGANIZATION_BLOCK "Main"' in scl or '"Main"' in scl
    assert "BEGIN" in scl


def test_parse_simaticml_block_content() -> None:
    data = parse_simaticml_block_content(FC_CE_XML)
    assert data["name"] == "ce"
    assert data["type"] == "FC"
    assert data["networkCount"] >= 1
    assert "interfaceVariables" in data


def test_audit_block_content() -> None:
    findings = audit_block_content(FC_CE_XML)
    assert isinstance(findings, list)


def test_standalone_plc_engine_load_project(tmp_path: Path) -> None:
    engine = StandalonePlcEngine()
    project = engine.load_project(CE_DIR, project_name="TestCE")
    assert project.name == "TestCE"
    assert len(project.blocks) >= 1

    blocks = engine.get_blocks()
    assert len(blocks) >= 1
    names = [b["name"] for b in blocks]
    assert "ce" in names or "Main" in names

    scl_dict = engine.translate_to_scl()
    assert len(scl_dict) >= 1

    # Test single block query
    single_scl = engine.translate_to_scl("ce")
    assert "ce" in single_scl

    # Test knowledge graph extraction
    kg = engine.get_knowledge_graph()
    assert "nodes" in kg
    assert "edges" in kg

    # Test package export
    exported = engine.export_scl_package(tmp_path / "scl_out")
    assert len(exported) >= 1
    for f in exported:
        assert f.is_file()
        assert f.suffix == ".scl"


def test_standalone_gateway_rest_endpoints() -> None:
    app = create_app()
    client = TestClient(app)

    xml_text = FC_CE_XML.read_text(encoding="utf-8")

    # 1. Translate block endpoint
    resp = client.post("/api/v1/plc/standalone/translate-block", json={"xml": xml_text})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["ok"] is True
    assert "FUNCTION" in res_data["data"]["scl"]

    # 2. Parse block endpoint
    resp = client.post("/api/v1/plc/standalone/parse-block", json={"xml": xml_text})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["ok"] is True
    assert res_data["data"]["name"] == "ce"

    # 3. Parse tags endpoint
    if HMI_XML.is_file():
        hmi_text = HMI_XML.read_text(encoding="utf-8")
        resp = client.post("/api/v1/plc/standalone/parse-tags", json={"xml": hmi_text})
        assert resp.status_code == 200
        res_data = resp.json()
        assert res_data["ok"] is True
        assert len(res_data["data"]) >= 1

    # 4. Audit block endpoint
    resp = client.post("/api/v1/plc/standalone/audit-block", json={"xml": xml_text})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["ok"] is True
    assert isinstance(res_data["data"], list)

    # 5. Error case: empty xml
    resp = client.post("/api/v1/plc/standalone/translate-block", json={"xml": ""})
    assert resp.status_code == 400


def test_extract_tag_table_content() -> None:
    if HMI_XML.is_file():
        tags = extract_tag_table_content(HMI_XML)
        assert len(tags) >= 1
        tag_names = [t["name"] for t in tags]
        assert "StartCmd" in tag_names

