"""Linux / non-Windows Openness: never spawn powershell; HostGateway guidance."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _make_complete_apxx(tmp_path: Path, name: str = "Line.ap19") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = tmp_path / name
    project.write_bytes(b"fake-ap19-binary")
    (tmp_path / project.stem).mkdir(exist_ok=True)
    (tmp_path / project.stem / "marker.txt").write_text("sidecar", encoding="utf-8")
    return project


def _assert_hostgateway_guidance(text: str, *, project_name: str = "Line.ap19") -> None:
    assert "Start-ResearchOS.cmd HostGateway" in text
    assert "Linux cannot run TIA Openness" in text
    assert "Linux 无法运行 TIA Openness" in text
    assert ".zap" in text
    assert "SimaticML" in text or "Blocks" in text
    assert project_name.split(".")[0] in text or ".ap19" in text


def test_export_apxx_skips_powershell_on_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import importer as imp

    monkeypatch.setattr(imp, "_is_windows", lambda: False)
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "0")
    monkeypatch.setenv("RESEARCHOS_TIA_OPENNESS", "auto")

    project = _make_complete_apxx(tmp_path / "proj")
    spawned: list[list[str]] = []

    def boom(*_a: Any, **_k: Any) -> tuple[Path, list[str], dict[str, int]]:
        raise FileNotFoundError("TiaOpenness.Server.exe")

    def fake_run(cmd: list[str], *_a: Any, **_k: Any) -> Any:
        spawned.append(list(cmd))
        raise AssertionError(f"subprocess.run must not run on Linux: {cmd}")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        boom,
    )
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda p, **_k: Path(p))
    monkeypatch.setattr(imp.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as ei:
        imp.export_apxx_via_openness(project, export_dir=tmp_path / "out")
    _assert_hostgateway_guidance(str(ei.value))
    assert spawned == []


def test_export_apxx_windows_still_falls_back_to_powershell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import importer as imp

    monkeypatch.setattr(imp, "_is_windows", lambda: True)
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "0")
    monkeypatch.setenv("RESEARCHOS_TIA_OPENNESS", "auto")

    project = _make_complete_apxx(tmp_path / "proj")
    spawned: list[list[str]] = []

    def boom(*_a: Any, **_k: Any) -> tuple[Path, list[str], dict[str, int]]:
        raise FileNotFoundError("TiaOpenness.Server.exe")

    def fake_run(cmd: list[str], *_a: Any, **_k: Any) -> Any:
        spawned.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        boom,
    )
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda p, **_k: Path(p))
    monkeypatch.setattr(imp.subprocess, "run", fake_run)

    path, notes, _timings = imp.export_apxx_via_openness(
        project, export_dir=tmp_path / "out"
    )
    assert path == tmp_path / "out"
    assert spawned, "Windows auto mode must fall back to PowerShell"
    assert spawned[0][0] == "powershell"
    assert any("PowerShell" in n for n in notes)


def test_resolve_complete_zap_on_linux_does_not_spawn_powershell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import importer as imp

    monkeypatch.setattr(imp, "_is_windows", lambda: False)
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "0")
    monkeypatch.setenv("RESEARCHOS_TIA_OPENNESS", "auto")

    zap = tmp_path / "line.zap19"
    with zipfile.ZipFile(zap, "w") as zf:
        zf.writestr("Line/Line.ap19", b"fake-ap19")
        zf.writestr("Line/Line/marker.txt", b"sidecar")
        zf.writestr("Line/System/x.bin", b"sys")

    spawned: list[list[str]] = []

    def boom(*_a: Any, **_k: Any) -> tuple[Path, list[str], dict[str, int]]:
        raise FileNotFoundError("TiaOpenness.Server.exe")

    def fake_run(cmd: list[str], *_a: Any, **_k: Any) -> Any:
        spawned.append(list(cmd))
        raise AssertionError(f"subprocess.run must not run on Linux: {cmd}")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.try_retrieve_archive_via_openness_cli",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        boom,
    )
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda p, **_k: Path(p))
    monkeypatch.setattr(imp.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as ei:
        imp.resolve_project_input(zap, auto_export=True)
    text = str(ei.value)
    _assert_hostgateway_guidance(text, project_name="Line.ap19")
    assert spawned == []


def test_format_openness_failure_rewrites_powershell_errno2() -> None:
    from agents.plc.tia.openness_cli import format_openness_failure

    raw = "[Errno 2] No such file or directory: 'powershell'"
    msg = format_openness_failure(raw, project_path="C:/x/Line.ap19", action="export")
    _assert_hostgateway_guidance(msg)
    assert "Errno 2" not in msg


def test_is_windows_reads_os_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Platform check must follow os.name so CI can mock without spawning powershell."""
    from agents.plc.tia import importer as imp

    monkeypatch.setattr(imp.os, "name", "posix")
    assert imp._is_windows() is False
    monkeypatch.setattr(imp.os, "name", "nt")
    assert imp._is_windows() is True


def test_agents_plc_package_does_not_eagerly_import_node() -> None:
    """Gateway ingest must not pull TaskState / langchain_core via agents.plc."""
    repo = Path(__file__).resolve().parents[2]
    script = (
        "import agents.plc\n"
        "import sys\n"
        "assert agents.plc.__all__ == ['run']\n"
        "assert 'agents.plc.node' not in sys.modules\n"
        "assert 'runtime.researchos_runtime.state' not in sys.modules\n"
        "assert 'langchain_core' not in sys.modules\n"
    )
    env = {**os.environ, "PYTHONPATH": str(repo)}
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
