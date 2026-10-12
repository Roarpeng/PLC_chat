"""Q1 device/sensor cards — cited meaning only, no invented process text."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.plc.tia import analyze_tia_exports
from gateway.app.services.plc.device_cards import (
    CARD_SCHEMA,
    build_device_cards,
    classify_io_type,
    clear_device_card_annotation,
    find_card_by_symbol,
    get_device_card,
    list_device_cards,
    set_device_card_annotation,
)
from gateway.app.services.plc.project_brief import (
    BRIEF_SCHEMA,
    BRIEF_SECTION_SCHEMA,
    brief_includes_device_sensor_section,
    build_project_brief,
)

EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
SURFACE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_openness_surface"


@pytest.fixture(scope="module")
def motor_job() -> dict:
    result = analyze_tia_exports(str(EXPORTS), project_name="MotorDemo")
    return {
        "id": "plc_motor_demo",
        "status": "ready",
        "project_name": "MotorDemo",
        "knowledge_graph": result["knowledge_graph"].to_json(),
        "device_card_annotations": {},
    }


@pytest.fixture(scope="module")
def surface_job() -> dict:
    result = analyze_tia_exports(str(SURFACE), project_name="OpennessSurface")
    return {
        "id": "plc_surface",
        "status": "ready",
        "project_name": "OpennessSurface",
        "knowledge_graph": result["knowledge_graph"].to_json(),
        "device_card_annotations": {},
        "hmi_index": {
            "StartCmd": [
                {"device": "HMI_1", "screen": "Screen_Main", "text": ""},
            ]
        },
    }


def test_classify_io_type_siemens_addresses() -> None:
    assert classify_io_type("%I0.0", "Bool") == "DI"
    assert classify_io_type("%Q0.1", "Bool") == "DO"
    assert classify_io_type("%IW64", "Int") == "AI"
    assert classify_io_type("%QW64", "Int") == "AO"
    assert classify_io_type("%M10.0", "Bool") == "M"
    assert classify_io_type("", "Bool") == "UNKNOWN"
    assert classify_io_type("", "Int", constant=True) == "CONSTANT"


def test_motor_tags_cite_comments_and_usages(motor_job: dict) -> None:
    cards = {c["symbol_name"]: c for c in build_device_cards(motor_job)}
    start = cards["StartCmd"]
    assert start["schema"] == CARD_SCHEMA
    assert start["id"] == "tag:StartCmd"
    assert start["address"] == "%I0.0"
    assert start["io_type"] == "DI"
    assert start["comment"] == "HMI start pushbutton"
    assert start["meaning_status"] == "cited"
    assert start["meaning_text"] == "HMI start pushbutton"
    assert start["meaning_source"] == "tag_comment"
    assert start["tag_table"] == "HMI"
    assert isinstance(start["used_by"], list)
    users = {u["block"] for u in start["used_by"]}
    assert "Main" in users or "FB_Motor" in users

    stop = cards["StopCmd"]
    assert stop["meaning_status"] == "cited"
    assert "HMI stop" in stop["meaning_text"]

    fault = cards["FaultOk"]
    assert fault["io_type"] == "DI"
    assert fault["meaning_status"] == "cited"


def test_missing_comment_is_unconfirmed_never_invented(surface_job: dict) -> None:
    start = find_card_by_symbol(surface_job, "StartCmd")
    assert start is not None
    assert start["address"] == "%I0.0"
    assert start["io_type"] == "DI"
    assert start["comment"] == ""
    assert start["meaning_status"] == "meaning_unconfirmed"
    assert start["meaning_text"] == ""
    assert start["meaning_source"] == "none"
    # HMI screen link is usage evidence, not invented process meaning
    assert any(h.get("screen") == "Screen_Main" for h in start["hmi_texts"])


def test_parser_sentinel_constant_is_not_process_meaning(surface_job: dict) -> None:
    const = find_card_by_symbol(surface_job, "MAX_SPEED")
    assert const is not None
    assert const["io_type"] == "CONSTANT"
    assert const["comment"] == "constant"
    assert const["meaning_status"] == "meaning_unconfirmed"
    assert const["meaning_text"] == ""


def test_hardware_cards_do_not_invent_process_meaning(surface_job: dict) -> None:
    plc = get_device_card(surface_job, "device:PLC_1")
    assert plc is not None
    assert plc["kind"] == "device"
    assert plc["hardware"]["address"] == "192.168.0.1"
    assert plc["meaning_status"] == "meaning_unconfirmed"
    assert plc["meaning_text"] == ""
    assert plc["data_type"]  # cited identity, not meaning


def test_annotation_overrides_cited_comment(motor_job: dict) -> None:
    job = {
        **motor_job,
        "device_card_annotations": {},
    }
    updated = set_device_card_annotation(
        job, "tag:StartCmd", text="现场启动按钮（点动）", author="eng"
    )
    assert updated["meaning_status"] == "annotated"
    assert updated["meaning_text"] == "现场启动按钮（点动）"
    assert updated["meaning_source"] == "engineer_annotation"
    assert updated["comment"] == "HMI start pushbutton"
    cleared = clear_device_card_annotation(job, "tag:StartCmd")
    assert cleared["meaning_status"] == "cited"
    assert cleared["meaning_text"] == "HMI start pushbutton"


def test_list_filters_and_brief_contract(motor_job: dict, surface_job: dict) -> None:
    listing = list_device_cards(motor_job, io_type="DI")
    assert listing["counts"]["total"] >= 3
    assert all(c["io_type"] == "DI" for c in listing["cards"])

    brief = build_project_brief(surface_job)
    assert brief["schema"] == BRIEF_SCHEMA
    assert brief_includes_device_sensor_section(brief)
    section = brief["sections"]["device_sensor_summary"]
    assert section["schema"] == BRIEF_SECTION_SCHEMA
    assert section["owned_by"] == "Q1"
    assert "device_sensor_summary" in brief["sections"]
    assert section["meaning_unconfirmed"] >= 1
    assert any("meaning_unconfirmed" in g for g in section["gaps"])
    ids = {row["id"] for row in section["cards"]}
    assert "tag:StartCmd" in ids
    assert "device:PLC_1" in ids


def test_local_interface_pins_without_address_are_not_cards(motor_job: dict) -> None:
    names = {c["symbol_name"] for c in build_device_cards(motor_job)}
    assert "#Running" not in names
    assert "#Start" not in names
    # Qualified access refs fold onto the tag-table symbol
    assert "HMI.StartCmd" not in names
