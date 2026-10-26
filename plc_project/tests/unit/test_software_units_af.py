from __future__ import annotations

import json
from pathlib import Path

from agents.plc.tia.writeback import plan_writeback
from gateway.app.services.plc.canvas_import import _detect_software_unit, _infer_af_role, _parse_export_tree
from plc_engine.canvas_model import CanvasBlock, CanvasNetwork, CanvasState, CanvasVariable
from plc_engine.canvas_tia_transpiler import canvas_to_tia_bundle


def test_canvas_block_software_unit_fields():
    block = CanvasBlock(
        name="CallEquipment",
        block_type="FB",
        number=10,
        software_unit="U1Em1_Conveyor",
        namespace="Siemens.AF.U1Em1",
        af_role="CallEquipment",
        interface=[CanvasVariable(name="enable", data_type="Bool", section="VAR_INPUT")],
        status="draft",
    )
    assert block.software_unit == "U1Em1_Conveyor"
    assert block.namespace == "Siemens.AF.U1Em1"
    assert block.af_role == "CallEquipment"

    state = CanvasState(project_name="AF_Project")
    state.blocks["U1Em1_Conveyor::CallEquipment"] = block
    state.software_unit_manifests["U1Em1_Conveyor"] = {
        "name": "U1Em1_Conveyor",
        "namespace": "Siemens.AF.U1Em1",
        "relations": ["Global", "Safety", "U1_Unit1"],
    }

    # Verify to_dict and from_dict
    data = state.to_dict()
    assert "U1Em1_Conveyor::CallEquipment" in data["blocks"]
    assert data["blocks"]["U1Em1_Conveyor::CallEquipment"]["software_unit"] == "U1Em1_Conveyor"
    assert data["blocks"]["U1Em1_Conveyor::CallEquipment"]["af_role"] == "CallEquipment"
    assert "U1Em1_Conveyor" in data["software_unit_manifests"]

    restored = CanvasState.from_dict(data)
    assert "U1Em1_Conveyor::CallEquipment" in restored.blocks
    b_restored = restored.blocks["U1Em1_Conveyor::CallEquipment"]
    assert b_restored.software_unit == "U1Em1_Conveyor"
    assert b_restored.af_role == "CallEquipment"

    # Helpers
    found = restored.find_block("CallEquipment", software_unit="U1Em1_Conveyor")
    assert found is not None
    assert found.name == "CallEquipment"
    assert restored.software_units() == ["U1Em1_Conveyor"]
    assert len(restored.blocks_in_unit("U1Em1_Conveyor")) == 1


def test_detect_software_unit_and_af_role():
    p1 = Path("/tmp/export/units/U1_Unit1_SCL/blocks/CallUnit.xml")
    p2 = Path("/tmp/export/units/U1Em0_Template_SCL/blocks/Sequence.xml")
    p3 = Path("/tmp/export/blocks/OB1.xml")

    assert _detect_software_unit(p1) == "U1_Unit1_SCL"
    assert _detect_software_unit(p2) == "U1Em0_Template_SCL"
    assert _detect_software_unit(p3) == ""

    assert _infer_af_role("CallUnit") == "CallUnit"
    assert _infer_af_role("CallEquipment") == "CallEquipment"
    assert _infer_af_role("Sequence") == "Sequence"
    assert _infer_af_role("ControlNodes") == "ControlNodes"
    assert _infer_af_role("EmNodes") == "EmNodes"
    assert _infer_af_role("StepToString") == "StepToString"


def test_parse_export_tree_with_software_units(tmp_path: Path):
    # Setup mock export tree with two Software Units having blocks with identical names
    u1_dir = tmp_path / "units" / "U1_Unit1" / "blocks"
    u1_dir.mkdir(parents=True)
    em0_dir = tmp_path / "units" / "U1Em0_General" / "blocks"
    em0_dir.mkdir(parents=True)

    # Unit manifest
    (tmp_path / "units" / "U1_Unit1" / "unit_manifest.json").write_text(
        json.dumps({"name": "U1_Unit1", "namespace": "Siemens.AF.U1", "relations": ["Global"]}),
        encoding="utf-8",
    )

    # Minimal SimaticML XML for CallUnit in U1_Unit1
    xml_call_unit = """<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4">
  <Engineering version="V19" />
  <SW.Blocks.FB ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4"><Section Name="Input" /></Sections></Interface>
      <Name>CallUnit</Name>
      <Number>1000</Number>
      <ProgrammingLanguage>SCL</ProgrammingLanguage>
    </AttributeList>
    <ObjectList>
      <MultilingualText ID="1" CompositionName="Comment">
        <ObjectList><MultilingualTextItem ID="2" CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text /></AttributeList></MultilingualTextItem></ObjectList>
      </MultilingualText>
    </ObjectList>
  </SW.Blocks.FB>
</Document>"""
    (u1_dir / "CallUnit.xml").write_text(xml_call_unit, encoding="utf-8")

    # Main OB in U1_Unit1
    xml_main_u1 = """<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4">
  <Engineering version="V19" />
  <SW.Blocks.OB ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4"><Section Name="Input" /></Sections></Interface>
      <Name>Main</Name>
      <Number>1001</Number>
      <ProgrammingLanguage>SCL</ProgrammingLanguage>
    </AttributeList>
    <ObjectList />
  </SW.Blocks.OB>
</Document>"""
    (u1_dir / "Main.xml").write_text(xml_main_u1, encoding="utf-8")

    # Same named Main OB in U1Em0_General!
    xml_main_em0 = """<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4">
  <Engineering version="V19" />
  <SW.Blocks.OB ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v4"><Section Name="Input" /></Sections></Interface>
      <Name>Main</Name>
      <Number>1006</Number>
      <ProgrammingLanguage>SCL</ProgrammingLanguage>
    </AttributeList>
    <ObjectList />
  </SW.Blocks.OB>
</Document>"""
    (em0_dir / "Main.xml").write_text(xml_main_em0, encoding="utf-8")

    canvas_dict = _parse_export_tree(tmp_path, "TestAFImport")
    canvas = CanvasState.from_dict(canvas_dict["canvas"])

    # Verify both Main blocks exist with their distinct compound keys
    assert "U1_Unit1::Main" in canvas.blocks
    assert "U1Em0_General::Main" in canvas.blocks
    assert "U1_Unit1::CallUnit" in canvas.blocks

    b_main1 = canvas.blocks["U1_Unit1::Main"]
    b_main0 = canvas.blocks["U1Em0_General::Main"]
    assert b_main1.number == 1001
    assert b_main1.software_unit == "U1_Unit1"
    assert b_main0.number == 1006
    assert b_main0.software_unit == "U1Em0_General"

    # Verify manifest was loaded
    assert "U1_Unit1" in canvas.software_unit_manifests
    assert canvas.software_unit_manifests["U1_Unit1"]["namespace"] == "Siemens.AF.U1"


def test_bundle_and_plan_writeback_with_software_units(tmp_path: Path):
    canvas = CanvasState(project_name="TestAF")
    block = CanvasBlock(
        name="FB_Sequence",
        block_type="FB",
        number=1020,
        software_unit="U1Em1_Station",
        scl_body="// logic\n#state := 10;",
        status="draft",  # draft blocks get staged
    )
    canvas.blocks["U1Em1_Station::FB_Sequence"] = block

    out_bundle = tmp_path / "bundle"
    canvas_to_tia_bundle(canvas, out_bundle)

    manifest_file = out_bundle / "staged_scls.json"
    assert manifest_file.is_file()
    staged = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert len(staged) == 1
    assert staged[0]["software_unit"] == "U1Em1_Station"
    assert staged[0]["block_name"] == "FB_Sequence"

    # Now verify plan_writeback carries the software_unit
    fake_proj = tmp_path / "project.ap19"
    fake_proj.touch()
    planned = plan_writeback(fake_proj, out_bundle, compile_after=True)

    gen_entries = [p for p in planned if p["action"] == "generate_from_source"]
    assert len(gen_entries) == 1
    assert gen_entries[0]["software_unit"] == "U1Em1_Station"
    assert gen_entries[0]["block"] == "U1Em1_Station_FB_Sequence"
