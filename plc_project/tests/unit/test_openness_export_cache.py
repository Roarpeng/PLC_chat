"""Unit tests for Openness export cache + skip-compile (mocked CLI, no TIA)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _make_complete_apxx(tmp_path: Path, name: str = "Line.ap19") -> Path:
    """Minimal complete TIA tree: .apxx + sibling folder."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = tmp_path / name
    project.write_bytes(b"fake-ap19-binary")
    (tmp_path / project.stem).mkdir(exist_ok=True)
    (tmp_path / project.stem / "marker.txt").write_text("sidecar", encoding="utf-8")
    return project


def _seed_simaticml_export(root: Path) -> Path:
    blocks = root / "Blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    xml = blocks / "OB1.xml"
    xml.write_text(
        '<?xml version="1.0"?>\n'
        "<Document><SW.Blocks.OB><Name>Main</Name></SW.Blocks.OB></Document>\n",
        encoding="utf-8",
    )
    return xml


def test_skip_compile_flag_passed_to_mocked_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.plc.tia import openness_cli as oc

    monkeypatch.setenv("RESEARCHOS_TIA_SKIP_COMPILE", "1")
    captured: list[tuple[str, ...]] = []

    def fake_cli(*args: str, timeout_s: int = 600) -> dict[str, Any]:
        captured.append(args)
        return {
            "ok": True,
            "export": {
                "message": "exported",
                "exportedCount": 1,
                "failedCount": 0,
                "compileMs": 0,
                "listMs": 5,
                "exportMs": 10,
            },
            "project": {"openMs": 20},
        }

    monkeypatch.setattr(oc, "openness_cli", fake_cli)
    project = tmp_path / "P.ap19"
    project.write_bytes(b"x")
    out = tmp_path / "export"
    path, notes, timings = oc.export_project_via_openness_cli(
        project, export_dir=out, skip_compile=True
    )
    assert path == out.resolve()
    assert captured and "--skip-compile" in captured[0]
    assert any("skip-compile" in n.lower() for n in notes)
    assert timings["openness_cli_ms"] >= 0
    assert timings.get("openness_open_ms") == 20
    assert timings.get("openness_list_ms") == 5
    assert timings.get("openness_blocks_export_ms") == 10


def test_skip_compile_retries_with_compile_on_inconsistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import openness_cli as oc

    monkeypatch.setenv("RESEARCHOS_TIA_SKIP_COMPILE", "1")
    calls: list[tuple[str, ...]] = []

    def fake_cli(*args: str, timeout_s: int = 600) -> dict[str, Any]:
        calls.append(args)
        if "--skip-compile" in args:
            return {
                "ok": False,
                "error": {
                    "code": "inconsistent_blocks",
                    "message": "Inconsistent blocks and PLC data types (UDT) cannot be exported.",
                },
            }
        return {
            "ok": True,
            "export": {
                "message": "compiled then exported",
                "exportedCount": 2,
                "failedCount": 0,
                "compileMs": 100,
                "exportMs": 50,
            },
            "project": {"openMs": 30},
        }

    monkeypatch.setattr(oc, "openness_cli", fake_cli)
    project = tmp_path / "P.ap19"
    project.write_bytes(b"x")
    _path, notes, timings = oc.export_project_via_openness_cli(
        project, export_dir=tmp_path / "out"
    )
    assert len(calls) == 2
    assert "--skip-compile" in calls[0]
    assert "--skip-compile" not in calls[1]
    assert timings.get("openness_compile_retry_ms", 0) >= 0
    assert timings["openness_cli_ms"] >= timings.get("openness_compile_retry_ms", 0)
    assert any("retry" in n.lower() for n in notes)
    assert timings.get("openness_compile_ms") == 100


def test_export_cache_hit_skips_openness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.plc.tia import importer as imp

    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "1")
    monkeypatch.setenv("RESEARCHOS_TIA_OPENNESS", "cli")

    project = _make_complete_apxx(tmp_path / "proj")
    # Seed cache as if a prior export succeeded.
    key = imp.export_cache_key(project)
    cached = imp.export_cache_root() / key
    _seed_simaticml_export(cached)

    called = {"n": 0}

    def boom(*_a: Any, **_k: Any) -> tuple[Path, list[str], dict[str, int]]:
        called["n"] += 1
        raise AssertionError("Openness CLI must not run on cache hit")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        boom,
    )

    out = tmp_path / "export_out"
    path, notes, timings = imp.export_apxx_via_openness(project, export_dir=out)
    assert called["n"] == 0
    assert path == out
    assert timings.get("openness_cache_hit") == 1
    assert "openness_cache_hit_ms" in timings
    assert timings.get("openness_cli_ms") == 0
    assert any("cache HIT" in n for n in notes)
    assert imp.has_simaticml_exports(out)
    assert (out / "Blocks" / "OB1.xml").is_file()


def test_export_cache_miss_stores_after_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import importer as imp

    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "1")
    monkeypatch.setenv("RESEARCHOS_TIA_OPENNESS", "cli")

    project = _make_complete_apxx(tmp_path / "proj")
    key = imp.export_cache_key(project)
    assert not (imp.export_cache_root() / key).exists()

    def fake_export(
        project_path: str | Path,
        *,
        export_dir: str | Path,
        **_kwargs: Any,
    ) -> tuple[Path, list[str], dict[str, int]]:
        out = Path(export_dir)
        _seed_simaticml_export(out)
        return out, ["cli ok"], {"openness_cli_ms": 42, "openness_open_ms": 7}

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        fake_export,
    )
    # Avoid heavy tree copy in unit test — stage returns same path.
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda p, **_k: Path(p))

    out = tmp_path / "export_out"
    path, notes, timings = imp.export_apxx_via_openness(project, export_dir=out)
    assert path == out
    assert timings.get("openness_cli_ms") == 42
    assert any("cache MISS" in n for n in notes)
    assert any("cache STORED" in n for n in notes)
    cached = imp.export_cache_root() / key
    assert imp.has_simaticml_exports(cached)

    # Second call should hit without invoking CLI.
    called = {"n": 0}

    def boom(*_a: Any, **_k: Any) -> tuple[Path, list[str], dict[str, int]]:
        called["n"] += 1
        raise AssertionError("should be cache hit")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        boom,
    )
    out2 = tmp_path / "export_out2"
    _path2, notes2, timings2 = imp.export_apxx_via_openness(project, export_dir=out2)
    assert called["n"] == 0
    assert timings2.get("openness_cache_hit") == 1
    assert timings2.get("openness_cli_ms") == 0
    assert any("cache HIT" in n for n in notes2)


def test_export_cache_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.plc.tia import importer as imp

    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "0")
    monkeypatch.setenv("RESEARCHOS_TIA_OPENNESS", "cli")

    project = _make_complete_apxx(tmp_path / "proj")
    # Even with a seeded cache, disabled mode must call CLI.
    key = imp.export_cache_key(project)
    _seed_simaticml_export(imp.export_cache_root() / key)

    calls = {"n": 0}

    def fake_export(
        project_path: str | Path,
        *,
        export_dir: str | Path,
        **_kwargs: Any,
    ) -> tuple[Path, list[str], dict[str, int]]:
        calls["n"] += 1
        out = Path(export_dir)
        _seed_simaticml_export(out)
        return out, ["cli"], {"openness_cli_ms": 11}

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli",
        fake_export,
    )
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda p, **_k: Path(p))

    _path, notes, timings = imp.export_apxx_via_openness(
        project, export_dir=tmp_path / "out"
    )
    assert calls["n"] == 1
    assert timings.get("openness_cli_ms") == 11
    assert any("cache disabled" in n.lower() for n in notes)
    assert "openness_cache_hit" not in timings


def test_export_cache_key_stable_across_unzip_paths(tmp_path: Path) -> None:
    """Same Siemens tree in two temp dirs must share a cache key (no absolute path)."""
    import os
    import shutil
    import time

    from agents.plc.tia import importer as imp

    project_a = _make_complete_apxx(tmp_path / "unzip_a")
    dest_b = tmp_path / "unzip_b"
    shutil.copytree(project_a.parent, dest_b)
    project_b = dest_b / project_a.name
    # Different mtimes (extract-to-temp) must not change the key.
    later = time.time() + 3600
    os.utime(project_b, (later, later))
    os.utime(dest_b / project_b.stem / "marker.txt", (later, later))
    assert imp.export_cache_key(project_a) == imp.export_cache_key(project_b)
    assert Path(project_a).resolve() != Path(project_b).resolve()


def test_export_cache_key_changes_with_content(tmp_path: Path) -> None:
    from agents.plc.tia import importer as imp

    project_a = _make_complete_apxx(tmp_path / "a", name="Line.ap19")
    project_b = _make_complete_apxx(tmp_path / "b", name="Line.ap19")
    key_same = imp.export_cache_key(project_a)
    assert key_same == imp.export_cache_key(project_b)
    project_b.write_bytes(b"fake-ap19-binary-changed")
    assert imp.export_cache_key(project_a) != imp.export_cache_key(project_b)
