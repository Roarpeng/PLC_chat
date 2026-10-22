"""HMI round-trip tests: colour parsing, connection mapping, patch writeback."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from agents.plc.tia.hmi_screens import (
    normalize_color,
    parse_classic_screen_xml,
    parse_connections,
    parse_hmi_export_tree,
    parse_hmi_tag_tables,
    parse_unified_screens_json,
    resolve_hmi_to_plc_tags,
)
from plc_engine.canvas_model import CanvasHmiDevice, CanvasHmiWidget, CanvasState
from plc_engine.hmi_writeback import _set_geom, _unified_ops_from_widgets, apply_hmi_diff

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_hmi_roundtrip"
DEVICE_DIR = FIXTURES / "hmi" / "HMI_1"
SCREEN_XML = DEVICE_DIR / "screens" / "Screen_Main.xml"


def _by_name(widgets):
    return {w.source_name: w for w in widgets}


def test_fixture_parses_real_controls():
    widgets = parse_classic_screen_xml(SCREEN_XML, device="HMI_1", screen="Screen_Main")
    assert len(widgets) == 7, f"expected 7 controls, got {len(widgets)}"
    by_name = _by_name(widgets)
    assert by_name["BtnStart"].widget_type == "button"
    assert by_name["BtnStop"].widget_type == "button"
    assert by_name["LampRun"].widget_type == "indicator"
    assert by_name["GaugeSpeed"].widget_type == "gauge"
    assert by_name["LabelTitle"].widget_type == "text"
    assert by_name["RectPanel"].widget_type == "rect"
    assert by_name["AlarmBanner"].widget_type == "alarm_banner"
    assert all(w.supported for w in widgets)
    # geometry is real, not defaults
    assert (by_name["BtnStart"].x, by_name["BtnStart"].y) == (40, 60)
    assert (by_name["BtnStart"].width, by_name["BtnStart"].height) == (120, 48)


def test_classic_colours_are_normalised_and_traced():
    by_name = _by_name(parse_classic_screen_xml(SCREEN_XML, device="HMI_1", screen="Screen_Main"))
    btn = by_name["BtnStart"]
    assert btn.properties["bg_color"] == "#00FF00"  # hex string
    assert btn.properties["fg_color"] == "#000000"  # decimal 0
    assert btn.properties["border_color"] == "#FFFFFF"  # rgb tuple
    assert btn.properties["color_source"]["bg_color"] == "BackColor"
    assert btn.properties["color_raw"]["BorderColor"] == "255, 255, 255"

    lamp = by_name["LampRun"]
    assert lamp.properties["bg_color"] == "#000000"
    assert lamp.properties["fg_color"] == "#00FF00"  # decimal 65280

    text = by_name["LabelTitle"]
    assert text.properties["bg_color"] == "#FFFFFF"  # decimal 16777215
    assert text.properties["fg_color"] == "#FFFFFF"

    gauge = by_name["GaugeSpeed"]
    assert gauge.properties["bg_color"] == "#333333"
    assert gauge.properties["border_color"] == "#94A3B8"


def test_unrecognised_colour_keeps_raw_value():
    rect = _by_name(parse_classic_screen_xml(SCREEN_XML, device="HMI_1", screen="Screen_Main"))[
        "RectPanel"
    ]
    assert rect.properties["bg_color"] == "GradientBrush(1)"
    assert rect.properties["color_source"]["bg_color"] == "BackColor (raw)"
    assert rect.properties["color_raw"]["BackColor"] == "GradientBrush(1)"
    assert rect.properties["border_color"] == "#FF8000"


def test_normalize_color_shapes():
    assert normalize_color("#00ff00") == "#00FF00"
    assert normalize_color("0x00FF00") == "#00FF00"
    assert normalize_color(65280) == "#00FF00"
    assert normalize_color("65280") == "#00FF00"
    assert normalize_color("255, 0, 0") == "#FF0000"
    assert normalize_color("rgb(0, 128, 255)") == "#0080FF"
    assert normalize_color([1, 2, 3]) == "#010203"
    assert normalize_color("rgba(255,255,255,128)") == "#FFFFFF"
    assert normalize_color(-1) == "#FFFFFF"
    assert normalize_color("GradientBrush(1)") is None


def test_connection_resolves_hmi_tag_to_plc_tag():
    connections = parse_connections(DEVICE_DIR)
    assert len(connections) == 1
    assert connections[0].controller == "PLC_1"

    tag_table = parse_hmi_tag_tables(DEVICE_DIR)
    assert tag_table["HmiStartCmd"]["plc_tag"] == "PLC_1.MainDB.StartCmd"
    assert tag_table["HmiRelative"]["connection"] == "PLC_Conn"

    devices, widgets = parse_hmi_export_tree(FIXTURES)
    assert [d.name for d in devices] == ["HMI_1"]
    by_name = _by_name(widgets.values())
    assert by_name["BtnStart"].plc_tag == "PLC_1.MainDB.StartCmd"
    # relative PlcTag + declared connection → controller-qualified path
    assert by_name["BtnStop"].plc_tag == "PLC_1.MainDB.StopCmd"
    assert by_name["LampRun"].plc_tag == "PLC_1.MainDB.MotorRunning"
    assert by_name["GaugeSpeed"].plc_tag == "PLC_1.MainDB.ActualSpeed"
    assert by_name["AlarmBanner"].plc_tag == "PLC_1.MainDB.AlarmActive"
    assert by_name["BtnStart"].properties["binding_unresolved"] is False
    assert by_name["BtnStart"].properties["plc_connection"] == "PLC_Conn"
    assert by_name["BtnStart"].properties["controller"] == "PLC_1"


def test_unmapped_tag_stays_unbound():
    _, widgets = parse_hmi_export_tree(FIXTURES)
    by_name = _by_name(widgets.values())
    rect = by_name["RectPanel"]
    assert rect.hmi_tag == "HmiSpare"
    assert rect.plc_tag == ""
    assert rect.properties["binding_unresolved"] is True


def test_resolve_never_uses_hmi_tag_as_plc_tag():
    widget = CanvasHmiWidget(
        id="x",
        widget_type="button",
        title="x",
        hmi_tag="MainDB.StartCmd",
        properties={},
    )
    resolve_hmi_to_plc_tags([widget], {})
    assert widget.plc_tag == ""
    assert widget.properties["binding_unresolved"] is True


def test_unified_colours_and_binding(tmp_path):
    data = {
        "width": 800,
        "height": 480,
        "screens": [
            {
                "name": "Main",
                "startScreen": True,
                "items": [
                    {
                        "name": "BtnRun",
                        "type": "HmiButton",
                        "left": 10,
                        "top": 20,
                        "width": 90,
                        "height": 40,
                        "text": "运行",
                        "tag": "UStart",
                        "backColor": "#112233",
                        "foreColor": 16777215,
                        "borderColor": "0, 0, 255",
                    },
                    {
                        "name": "LampSpare",
                        "type": "HmiCircle",
                        "left": 60,
                        "top": 80,
                        "width": 30,
                        "height": 30,
                        "tag": "UOrphan",
                        "bgColor": "10, 20, 30",
                    },
                ],
            }
        ],
    }
    path = tmp_path / "unified_screens.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    device, widgets = parse_unified_screens_json(path, device="UP")
    assert device.kind == "unified"
    by_name = _by_name(widgets)
    btn = by_name["BtnRun"]
    assert btn.properties["bg_color"] == "#112233"
    assert btn.properties["fg_color"] == "#FFFFFF"
    assert btn.properties["border_color"] == "#0000FF"
    assert by_name["LampSpare"].properties["bg_color"] == "#0A141E"

    resolve_hmi_to_plc_tags(widgets, {"UStart": "PLC_1.MainDB.StartCmd"})
    assert btn.plc_tag == "PLC_1.MainDB.StartCmd"
    assert by_name["LampSpare"].plc_tag == ""
    assert by_name["LampSpare"].properties["binding_unresolved"] is True


def test_parse_patch_parse_keeps_geometry_and_colours(tmp_path):
    original = parse_classic_screen_xml(SCREEN_XML, device="HMI_1", screen="Screen_Main")
    assert original

    tree = ET.parse(SCREEN_XML)
    root = tree.getroot()
    expected: dict[str, tuple[int, int, str, str | None]] = {}
    for widget in original:
        new_x = widget.x + 10
        new_y = widget.y + 5
        had_text_node = bool(widget.text and widget.text != widget.source_name)
        new_text = f"{widget.text or widget.title}-改"
        _set_geom(
            root,
            widget.source_name,
            new_x,
            new_y,
            widget.width,
            widget.height,
            new_text,
            colors=widget.properties,
        )
        expected[widget.source_name] = (
            new_x,
            new_y,
            widget.properties.get("bg_color"),
            new_text if had_text_node else None,
        )

    patched = tmp_path / "Screen_Main.xml"
    tree.write(patched, encoding="utf-8", xml_declaration=True)
    reparsed = _by_name(
        parse_classic_screen_xml(patched, device="HMI_1", screen="Screen_Main")
    )

    assert set(reparsed) == set(expected)
    for name, (x, y, bg, text) in expected.items():
        got = reparsed[name]
        assert (got.x, got.y) == (x, y)
        assert got.properties.get("bg_color") == bg
        if text is not None:
            assert text in got.text


def test_unified_ops_do_not_send_unresolved_tag_as_plc_tag():
    widgets = [
        CanvasHmiWidget(
            id="new_btn",
            widget_type="button",
            title="新按钮",
            status="draft",
            supported=True,
            hmi_tag="SpareHmiTag",
            properties={"binding_unresolved": True},
        ),
        CanvasHmiWidget(
            id="new_lamp",
            widget_type="indicator",
            title="新灯",
            status="draft",
            supported=True,
            hmi_tag="HmiRunLamp",
            plc_tag="PLC_1.MainDB.MotorRunning",
            properties={"binding_unresolved": False},
        ),
    ]
    ops = _unified_ops_from_widgets("HMI_1", widgets)["ops"]
    assert ops[0]["tag"] == ""  # unresolved: no fake address
    assert ops[1]["tag"] == "PLC_1.MainDB.MotorRunning"


def test_unified_ops_carry_colours_and_round_trip_with_parser(tmp_path):
    """Unified ops payload carries colours in the parser's own key set.

    parse → properties(#RRGGBB) → ops payload(backColor/…) must be mutual
    inverses of ``_extract_colors_json``: feeding an op back as an item dict
    re-recognises the same colours. Raw values are never re-encoded.
    """
    from agents.plc.tia.hmi_screens import _extract_colors_json

    data = {
        "width": 800,
        "height": 480,
        "screens": [
            {
                "name": "Main",
                "startScreen": True,
                "items": [
                    {
                        "name": "BtnRun",
                        "type": "HmiButton",
                        "left": 10,
                        "top": 20,
                        "width": 90,
                        "height": 40,
                        "text": "运行",
                        "tag": "UStart",
                        "backColor": "0x0080FF",
                        "foreColor": 16711680,
                        "borderColor": "GradientBrush(1)",
                    }
                ],
            }
        ],
    }
    path = tmp_path / "unified_screens.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    _, widgets = parse_unified_screens_json(path, device="UP")
    btn = _by_name(widgets)["BtnRun"]
    assert btn.properties["bg_color"] == "#0080FF"
    assert btn.properties["fg_color"] == "#FF0000"
    assert btn.properties["border_color"] == "GradientBrush(1)"  # raw, kept

    btn.status = "error"  # edited → takes part in writeback
    ops = _unified_ops_from_widgets("UP", [btn])["ops"]
    op = ops[0]
    # same normalised representation as the classic chain sends
    assert op["backColor"] == "#0080FF"
    assert op["foreColor"] == "#FF0000"
    # unrecognised value is dropped, never re-encoded into an invention
    assert "borderColor" not in op

    # mutual inverse: an op dict is itself a valid parser input shape
    reparsed = _extract_colors_json(dict(op))
    assert reparsed["bg_color"] == "#0080FF"
    assert reparsed["fg_color"] == "#FF0000"


def test_unified_ops_colours_on_create_and_placeholder_stays_position_only():
    create = CanvasHmiWidget(
        id="UP/Main/NewBtn",
        widget_type="button",
        title="新按钮",
        status="draft",
        supported=True,
        screen="Main",
        properties={"bg_color": "#112233"},
    )
    placeholder = CanvasHmiWidget(
        id="UP/Main/UnknownThing",
        widget_type="placeholder",
        title="未知控件",
        status="synced",
        supported=False,
        screen="Main",
        source_name="UnknownThing",
        properties={"bg_color": "#FF0000"},
    )
    ops = _unified_ops_from_widgets("UP", [create, placeholder])["ops"]
    by_action = {op["action"]: op for op in ops}
    assert by_action["create"]["backColor"] == "#112233"
    # placeholder may only be moved: geometry yes, colours no
    placeholder_op = by_action["update"]
    assert set(placeholder_op) == {"action", "screen", "name", "left", "top"}


def test_writeback_includes_unsupported_placeholder(tmp_path):
    canvas = CanvasState(project_name="demo")
    canvas.hmi_devices = [CanvasHmiDevice(name="HMI_1", kind="classic")]
    canvas.hmi_widgets = {
        "placeholder": CanvasHmiWidget(
            id="placeholder",
            widget_type="placeholder",
            title="未知控件",
            x=10,
            y=20,
            device="HMI_1",
            screen="Screen_Main",
            status="synced",
            supported=False,
            properties={},
        ),
        "unchanged": CanvasHmiWidget(
            id="unchanged",
            widget_type="button",
            title="未改动",
            device="HMI_1",
            screen="Screen_Main",
            status="synced",
            supported=True,
            properties={},
        ),
    }
    result = apply_hmi_diff(canvas, project_path=tmp_path, compile_after=False)
    assert result["ok"] is True

    entries = [r for r in result["results"] if r.get("reason") == "no_baseline"]
    assert len(entries) == 1
    artifact = Path(entries[0]["artifact"])
    assert artifact.is_file()
    manifest = json.loads(artifact.read_text(encoding="utf-8"))
    # unsupported placeholder takes part in writeback; untouched widget does not
    assert [w["id"] for w in manifest["widgets"]] == ["placeholder"]
