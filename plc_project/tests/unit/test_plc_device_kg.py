"""Device-layer knowledge-graph nodes/edges from the Openness surface fixture.

Fixture ``tests/fixtures/tia_openness_surface`` carries ``hardware/devices.xml``,
``plc/PLC_1/to/TO_Axis.xml`` and ``plc/PLC_1/alarms/{AlarmTexts,ProDiag}.xml``.
``project.aml`` is an AutomationML file and is intentionally not picked up by the
``*.xml`` scan — only ``devices.xml`` contributes Device nodes here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.plc.tia.kg import build_knowledge_graph
from agents.plc.tia.simaticml import extract_project

SURFACE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_openness_surface"


@pytest.fixture(scope="module")
def kg():
    project = extract_project(SURFACE, project_name="OpennessSurface")
    return build_knowledge_graph(project)


def test_device_nodes_from_hardware(kg):
    devices = [n for n in kg.nodes.values() if n.type == "Device"]
    by_name = {n.props["name"]: n for n in devices}
    assert {"PLC_1", "IM155"} <= set(by_name)

    plc = by_name["PLC_1"]
    assert plc.props["type"] == "OrderNumber:6ES7 515-2AM02-0AB0/V2.9"
    assert plc.props["address"] == "192.168.0.1"
    assert plc.props["failsafe"] is True
    assert plc.props["rack"] == "0"


def test_technology_object_node_and_kind(kg):
    tos = [n for n in kg.nodes.values() if n.type == "TechnologyObject"]
    assert len(tos) == 1
    to = tos[0]
    assert to.id == "TechnologyObject::Axis_1"
    assert to.props["kind"] == "axis"
    assert to.props["to_type"] == "TO_PositioningAxis"


def test_alarm_nodes_from_textlists_and_prodiag(kg):
    alarms = [n for n in kg.nodes.values() if n.type == "Alarm"]
    by_name = {n.props["name"]: n for n in alarms}
    assert {"AlarmTexts", "MotorSupervision"} <= set(by_name)
    assert by_name["AlarmTexts"].props["kind"] == "text_list"
    assert "Overtemp" in by_name["AlarmTexts"].props["texts"]
    assert by_name["MotorSupervision"].props["kind"] == "prodiag"


def test_device_edges_has_device_runs_to_has_alarm(kg):
    has_device = {(e.source, e.target) for e in kg.edges if e.type == "HAS_DEVICE"}
    assert has_device == {
        ("Project::OpennessSurface", "Device::PLC_1"),
        ("Project::OpennessSurface", "Device::IM155"),
    }

    runs_to = {(e.source, e.target) for e in kg.edges if e.type == "RUNS_TO"}
    assert runs_to == {("Device::PLC_1", "TechnologyObject::Axis_1")}

    has_alarm = {(e.source, e.target) for e in kg.edges if e.type == "HAS_ALARM"}
    assert has_alarm == {
        ("Device::PLC_1", "Alarm::AlarmTexts"),
        ("Device::PLC_1", "Alarm::MotorSupervision"),
    }


def test_no_fabricated_device_edges(kg):
    """Only the owning controller links to TO/alarms; unmatched devices link to none."""
    runs_to = [(e.source, e.target) for e in kg.edges if e.type == "RUNS_TO"]
    has_alarm = [(e.source, e.target) for e in kg.edges if e.type == "HAS_ALARM"]
    assert len(runs_to) == 1
    assert len(has_alarm) == 2
    assert all(src == "Device::PLC_1" for src, _ in runs_to)
    assert all(src == "Device::PLC_1" for src, _ in has_alarm)
