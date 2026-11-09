"""Regression tests for the C# TIA Openness create-project response contract.

The C# CLI prints {"ok": true, "create": {"projectPath": "<real .ap19>"}}.
These tests run offline; they do NOT start TIA Portal or compile PLC logic.
"""
from __future__ import annotations

from pathlib import Path

from gateway.app.services.plc import tia_delivery


def test_reads_nested_real_project_path() -> None:
    actual_path = r"C:\TIA\CreatedByOpenness\MyProject.ap19"
    result = {"ok": True, "create": {"ok": True, "projectPath": actual_path}}
    assert tia_delivery._created_project_path(result) == actual_path


def test_missing_path_is_not_guessed() -> None:
    assert tia_delivery._created_project_path({"ok": True, "create": {"ok": True}}) == ""
    assert tia_delivery._created_project_path({"ok": True, "project": "fabricated.ap19"}) == ""
    assert tia_delivery._created_project_path({"ok": True, "create": {"projectPath": None}}) == ""


def test_auto_delivery_uses_real_path_then_stops_if_cpu_unconfigured(
    monkeypatch, tmp_path: Path
) -> None:
    # The source root and guessed .ap19 path are deliberately different.
    actual_path = r"C:\RealOpennessOutput\LineA\LineA.ap19"
    calls: list[tuple[str, ...]] = []

    def fake_openness_cli(*args: str, **kwargs: object) -> dict:
        calls.append(args)
        return {"ok": True, "create": {"ok": True, "projectPath": actual_path}}

    from agents.plc.tia import openness_cli as cli_module

    monkeypatch.setattr(cli_module, "openness_cli", fake_openness_cli)
    monkeypatch.delenv("PLC_GREENFIELD_TIA_DEVICE_TYPE", raising=False)
    result = tia_delivery._run_openness_import_compile(
        project_name="LineA",
        package_dir=tmp_path,
        workspace=tmp_path,
        planned_text="",
        supplement={"ob_files": []},
        tia_version="V19",
    )
    assert result["status"] == "tia_error"
    assert result["project_path"] == actual_path
    assert result["steps"][0] == {
        "step": "create-project", "ok": True, "detail": actual_path
    }
    assert result["steps"][1]["step"] == "create-device"
    assert len(calls) == 1


def test_auto_delivery_refuses_success_without_real_path(monkeypatch, tmp_path: Path) -> None:
    from agents.plc.tia import openness_cli as cli_module

    monkeypatch.setattr(
        cli_module, "openness_cli",
        lambda *args, **kwargs: {"ok": True, "create": {"ok": True}},
    )
    result = tia_delivery._run_openness_import_compile(
        project_name="LineA",
        package_dir=tmp_path,
        workspace=tmp_path,
        planned_text="",
        supplement={"ob_files": []},
        tia_version="V19",
    )
    assert result["status"] == "tia_error"
    assert result.get("project_path") is None
    assert "create.projectPath" in result["error"]
    assert result["steps"][0]["ok"] is False
