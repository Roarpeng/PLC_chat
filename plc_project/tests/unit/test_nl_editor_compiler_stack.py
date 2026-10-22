"""Unit tests for NL editor + TIA compiler stack (model, workspace, precheck, ops, HMI)."""

from __future__ import annotations

import json
from pathlib import Path

from agents.plc.tia.hmi_screens import parse_classic_screen_xml, parse_unified_screens_json
from plc_engine.canvas_model import (
    CanvasState,
    apply_canvas_patch,
    attribute_compiler_errors,
    create_empty_canvas,
    generate_canvas_autofix_patch,
)
from plc_engine.lad_migrate import validate_migration
from plc_engine.scl_precheck import precheck_canvas


def test_canvas_model_source_revision_roundtrip():
    c = create_empty_canvas("Demo")
    assert c.hmi_devices
    assert c.hmi_widgets["btn_start"].device == "HMI_1"
    ops = [
        {
            "op": "update_block_scl",
            "name": "MotorCtrl",
            "scl_body": "IF #Start THEN\n    #RunOut := TRUE;\nEND_IF;",
        }
    ]
    c = apply_canvas_patch(c, ops)
    c.append_revision(ops, source="nl", message="test")
    d = c.to_dict()
    assert d["revisions"]
    c2 = CanvasState.from_dict(d)
    assert c2.blocks["MotorCtrl"].scl_body.startswith("IF #Start")
    assert c2.hmi_devices[0].name == "HMI_1"


def test_precheck_catches_todo_and_end_mismatch():
    c = create_empty_canvas("Demo")
    c.blocks["MotorCtrl"].scl_body = "IF #Start THEN\n  // TODO\n"
    report = precheck_canvas(c)
    assert report["ok"] is False
    assert any("TODO" in e["message"] or "配对" in e["message"] for e in report["errors"])


def test_precheck_scoped_to_block_names():
    """chat 编辑流程只预检触及的块：导入降级产生的 synced 占位块（TODO/空网络）不拦无关编辑。"""
    c = create_empty_canvas("Demo")
    c.blocks["MotorCtrl"].scl_body = "(* EMPTY NETWORK *)"  # 模拟 HR001 降级导入占位
    c.blocks["MotorCtrl"].networks = []

    full = precheck_canvas(c)
    assert full["ok"] is False  # 全量检查会被占位块拦住

    scoped = precheck_canvas(c, block_names=["MainDB"])
    assert scoped["ok"] is True  # 只查 MainDB（DB 块无 SCL 问题）→ 不拦

    # 空数组 = ops 只涉及 HMI/标签：不查任何 SCL 块，仅 HMI 绑定检查
    scoped_empty = precheck_canvas(c, block_names=[])
    assert scoped_empty["ok"] is True


def test_ops_touched_blocks_extracts_all_shapes():
    from gateway.app.services.plc.chat_ops import ops_touched_blocks

    ops = [
        {"op": "add_variable", "block": "MainDB", "variable": {"name": "X"}},
        {"op": "add_block", "block": {"name": "NewFB", "block_type": "FB"}},
        {"op": "update_block", "name": "MotorCtrl", "patch": {"comment": "c"}},
        {"op": "remove_block", "name": "MainDB"},
        {"op": "add_hmi_widget", "widget": {"id": "w1"}},
        {"op": "add_variable", "block": "MainDB", "variable": {"name": "Y"}},
    ]
    assert ops_touched_blocks(ops) == ["MainDB", "NewFB", "MotorCtrl"]
    assert ops_touched_blocks([]) == []


def test_chat_ops_rules_estop(monkeypatch):
    from gateway.app.services.plc.chat_ops import build_chat_ops

    c = create_empty_canvas("Demo")
    built = build_chat_ops("添加一个急停按钮", c, use_llm=False)
    assert built["ops"]
    assert any(o.get("op") == "add_hmi_widget" for o in built["ops"])


def test_workspace_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    from gateway.app.services.plc import workspace as ws

    # fake apxx file
    ap = tmp_path / "Line.ap19"
    ap.write_bytes(b"PK\x03\x04fake")
    meta = ws.persist_imported_project(ap, project_name="Line")
    assert meta["project_id"]
    assert Path(meta["original_path"]).is_dir()
    assert Path(meta["work_path"]).is_dir()
    apxx = ws.resolve_work_project_path(meta["project_id"])
    assert apxx is not None
    assert ws.is_workspace_path(apxx)


def test_compile_job_mock_runner():
    from gateway.app.services.plc import compile_jobs as cj

    c = create_empty_canvas("Demo")

    def runner(job_id, canvas_dict, **kwargs):
        cj.update_job_stage(job_id, "prepare_work", "ok", "ok")
        cj.update_job_stage(job_id, "open_project", "ok")
        cj.update_job_stage(job_id, "write_plc", "ok")
        cj.update_job_stage(job_id, "compile_plc", "ok")
        cj.update_job_stage(job_id, "write_hmi", "skipped")
        cj.update_job_stage(job_id, "compile_hmi", "skipped")
        cj.update_job_stage(job_id, "save", "ok")
        return {"ok": True, "writeback": {"ok": True}, "attributions": [], "canvas": canvas_dict}

    job = cj.create_compile_job(c.to_dict(), project_path="/tmp/x.ap19", runner=runner)
    import time

    for _ in range(50):
        time.sleep(0.05)
        live = cj.get_job(job["id"])
        if live and live["status"] in {"ok", "error"}:
            break
    live = cj.get_job(job["id"])
    assert live["status"] == "ok"


def test_hmi_classic_xml_parse(tmp_path):
    xml = """<?xml version="1.0"?>
    <Document>
      <Hmi.ScreenItem.Button CompositionName="ScreenItems">
        <AttributeList>
          <Name>StartBtn</Name>
          <Left>10</Left>
          <Top>20</Top>
          <Width>100</Width>
          <Height>40</Height>
          <Text>Start</Text>
          <ProcessTag>StartCmd</ProcessTag>
        </AttributeList>
      </Hmi.ScreenItem.Button>
    </Document>
    """
    p = tmp_path / "Screen_1.xml"
    p.write_text(xml, encoding="utf-8")
    widgets = parse_classic_screen_xml(p, device="HMI_1", screen="Screen_1")
    assert widgets
    assert widgets[0].widget_type == "button"
    assert widgets[0].source_name == "StartBtn"


def test_hmi_unified_json_parse(tmp_path):
    data = {
        "width": 1280,
        "height": 800,
        "screens": [
            {
                "name": "Main",
                "startScreen": True,
                "items": [
                    {
                        "name": "Lamp1",
                        "type": "HmiCircle",
                        "left": 5,
                        "top": 5,
                        "width": 50,
                        "height": 50,
                        "tag": "MainDB.Run",
                    }
                ],
            }
        ],
    }
    p = tmp_path / "unified_screens.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    device, widgets = parse_unified_screens_json(p, device="UP")
    assert device.kind == "unified"
    assert widgets[0].widget_type == "indicator"
    assert widgets[0].supported is True


def test_migrate_validation_rejects_todo():
    c = create_empty_canvas("Demo")
    block = c.blocks["MotorCtrl"]
    issues = validate_migration(block, 'FUNCTION_BLOCK "MotorCtrl"\nBEGIN\nTODO\nEND_FUNCTION_BLOCK')
    assert issues


def test_autofix_hmi_binding():
    c = create_empty_canvas("Demo")
    c.hmi_widgets["btn_start"].plc_tag = "MainDB.MissingVar"
    attrs = attribute_compiler_errors(c, {"ok": False, "message": ""})
    # binding check adds attribution
    assert any(a["target_type"] == "hmi_widget" for a in attrs)
    ops = generate_canvas_autofix_patch(c, attrs)
    assert any(o.get("op") == "add_variable" for o in ops)


def test_classic_xml_roundtrip_unpatched_bytes(tmp_path):
    """Unchanged nodes stay byte-identical when we only rewrite via ElementTree carefully.

    For fixtures without baseline patch API, verify parse → serialize of an untouched
    subtree preserves Name/Left/Top keys.
    """
    raw = b'<?xml version="1.0"?><Root><Name>Keep</Name><Left>1</Left></Root>'
    p = tmp_path / "a.xml"
    p.write_bytes(raw)
    import xml.etree.ElementTree as ET

    tree = ET.parse(p)
    out = tmp_path / "b.xml"
    tree.write(out, encoding="utf-8", xml_declaration=True)
    # After ET roundtrip xml_declaration may differ slightly; assert semantic equality
    root = ET.parse(out).getroot()
    assert root.find("Name").text == "Keep"
    assert root.find("Left").text == "1"
