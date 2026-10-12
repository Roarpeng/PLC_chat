"""M2 Project Brief — structure-first shape, status enum, device hook."""

from __future__ import annotations

from gateway.app.services.plc.brief import (
    TIMING_ASSUMPTIONS,
    build_project_brief,
    device_sensor_summary,
    persist_structure_snapshot,
    refresh_brief_artifacts,
)
from gateway.app.services.plc.citations import resolve_export_status
from gateway.app.services.plc.handover import handover_prompts, wants_handover_hardware


def _job() -> dict:
    return {
        "id": "plc_brief_demo",
        "project_name": "MotorLine",
        "status": "running",
        "brief_ready": True,
        "ingest_phase": "bodies_queued",
        "summary": {"OB": 1, "FB": 2},
        "blocks": [
            {
                "name": "Main",
                "type": "OB",
                "number": 1,
                "comment": "cyclic scan",
                "networks": 1,
                "body_available": True,
                "export_status": "converted",
            },
            {
                "name": "FB_Motor",
                "type": "FB",
                "comment": "self-holding",
                "networks": 1,
                "body_available": True,
            },
            {
                "name": "FB_Locked",
                "type": "FB",
                "interface_only": True,
                "body_available": False,
                "networks": 0,
            },
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::Main", "type": "Block", "props": {"name": "Main"}},
                {"id": "Block::FB_Motor", "type": "Block", "props": {"name": "FB_Motor"}},
                {"id": "Device::CPU1516", "type": "Device", "props": {"name": "CPU1516"}},
            ],
            "edges": [
                {
                    "source": "Block::Main",
                    "target": "Block::FB_Motor",
                    "type": "CALLS",
                    "props": {"network": "Network::Main::1", "evidence": "xml_call"},
                }
            ],
        },
        "logic_graph": {
            "edges": [
                {"source": "Block::Main", "target": "Block::FB_Motor", "type": "CALLS"}
            ]
        },
        "scl_sources": {
            "Main": 'ORGANIZATION_BLOCK "Main"\nBEGIN\n    #Motor();\nEND_ORGANIZATION_BLOCK',
            "FB_Motor": 'FUNCTION_BLOCK "FB_Motor"\nBEGIN\n    #Run := #Start;\nEND_FUNCTION_BLOCK',
        },
        "hardware": [
            {"name": "CPU1516", "device_type": "PLC", "address": "192.168.0.1", "comment": "main rack"}
        ],
        "tag_tables": [
            {
                "name": "IO",
                "tags": [
                    {
                        "name": "Temp_Sensor",
                        "logical_address": "%IW10",
                        "comment": "温度传感器",
                    }
                ],
            }
        ],
        "body_pull_queue": [{"block": "FB_Locked", "reason": "interface_only"}],
        "timings": {"extract_ms": 800, "kg_ms": 200, "scl_ms": 12000},
    }


def test_brief_has_required_fields_and_prompts():
    brief = build_project_brief(_job())
    assert brief["brief_ready"] is True
    assert brief["main_ob"] == "Main"
    assert "Main" in brief["purpose"] or "cyclic" in brief["purpose"]
    assert brief["block_counts_by_status"]["converted"] >= 1
    assert brief["block_counts_by_status"]["interface_only"] == 1
    assert any(c["callee"] == "FB_Motor" for c in brief["top_level_calls"])
    assert "Main" in brief["run_logic_entry"]
    assert any(g["block"] == "FB_Locked" for g in brief["export_gaps"])
    ids = {p["id"] for p in brief["engineer_prompts"]}
    assert ids == {"q1_hardware", "q2_run_logic", "q3_hitl_adjust"}
    assert brief["timing"]["assumptions"]["brief_target_minutes"].startswith("1–3")
    assert "全文翻译" in TIMING_ASSUMPTIONS["full_translate"]


def test_export_status_consumes_m1_and_degrades():
    job = _job()
    locked = next(b for b in job["blocks"] if b["name"] == "FB_Locked")
    assert resolve_export_status(locked, job) == "interface_only"
    assert resolve_export_status({"name": "X", "export_status": "not_exported"}, job) == "not_exported"
    assert resolve_export_status({"name": "Y", "m1_export_status": "not_indexed"}, job) == "not_indexed"


def test_device_sensor_hook_without_m1_cards():
    summary = device_sensor_summary(_job())
    assert summary["available"] is True
    assert summary["source"] == "hardware_xml"
    assert any(d["name"] == "CPU1516" for d in summary["devices"])
    assert any(s["name"] == "Temp_Sensor" for s in summary["sensors"])


def test_device_sensor_hook_consumes_m1_cards():
    job = _job()
    job["device_cards"] = [{"name": "ET200SP", "device_type": "IO", "address": "192.168.0.10"}]
    summary = device_sensor_summary(job)
    assert summary["source"] == "m1_device_cards"
    assert any(d["name"] == "ET200SP" for d in summary["devices"])


def test_refresh_brief_artifacts_sets_ready_phase():
    job = _job()
    job["status"] = "ready"
    refresh_brief_artifacts(job)
    assert job["ingest_phase"] == "ready"
    assert job["brief_ready"] is True
    stubs = {s["block"]: s for s in job["block_stubs"]}
    assert "Main" in stubs
    assert "duty" in stubs["Main"]


def test_handover_prompt_detects_q1():
    assert wants_handover_hardware("这个工程有哪些硬件和传感器？")
    prompts = handover_prompts()
    assert all("写回" not in p["prompt"] or "不要自动" in p["prompt"] for p in prompts)


class _FakeProject:
    name = "Snap"
    extraction_notes = []
    hardware = []
    tag_tables = {}

    def summary(self):
        return {"OB": 1}


def test_persist_structure_snapshot_marks_brief_ready():
    job = {
        "id": "plc_x",
        "blocks": [{"name": "Main", "type": "OB", "number": 1, "body_available": True}],
        "knowledge_graph": {"nodes": [], "edges": []},
    }
    persist_structure_snapshot(job, _FakeProject(), {"nodes": [], "edges": []}, phase="structure")
    assert job["brief_ready"] is True
    assert job["ingest_phase"] == "structure"
    assert isinstance(job.get("body_pull_queue"), list)
