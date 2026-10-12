"""TIA .apxx completeness / packaging rules."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from agents.plc.tia.importer import (
    incomplete_apxx_guidance,
    is_complete_tia_project,
    resolve_project_input,
    stage_tia_project_tree,
)
from gateway.app.services.plc_jobs import save_upload


def test_lone_ap19_is_incomplete(tmp_path: Path) -> None:
    ap = tmp_path / "test1.ap19"
    ap.write_bytes(b"fake")
    assert not is_complete_tia_project(ap)
    assert "孤立的 TIA 工程" in incomplete_apxx_guidance(ap)


def test_ap19_with_system_folder_is_complete(tmp_path: Path) -> None:
    ap = tmp_path / "Line.ap19"
    ap.write_bytes(b"fake")
    (tmp_path / "System").mkdir()
    (tmp_path / "System" / "x.bin").write_bytes(b"1")
    assert is_complete_tia_project(ap)


def test_ap19_with_same_stem_folder_is_complete(tmp_path: Path) -> None:
    ap = tmp_path / "Plant.ap19"
    ap.write_bytes(b"fake")
    (tmp_path / "Plant").mkdir()
    (tmp_path / "Plant" / "PEData.plf").write_bytes(b"x")
    assert is_complete_tia_project(ap)


def test_stage_copies_sidecar_tree(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    ap = src / "Line.ap19"
    ap.write_bytes(b"proj")
    (src / "System").mkdir()
    (src / "System" / "a.bin").write_bytes(b"data")
    staged = stage_tia_project_tree(ap, dest=tmp_path / "staged")
    assert staged.is_file()
    assert (staged.parent / "System" / "a.bin").is_file()


def test_resolve_rejects_lone_apxx(tmp_path: Path) -> None:
    ap = tmp_path / "orphan.ap19"
    ap.write_bytes(b"x")
    with pytest.raises(ValueError, match="孤立的 TIA 工程"):
        resolve_project_input(ap, auto_export=True)


def test_save_upload_rejects_bare_ap19() -> None:
    with pytest.raises(ValueError, match="孤立的 TIA 工程"):
        save_upload("test1.ap19", b"not-a-real-project")


def test_save_upload_accepts_zip_of_full_project(tmp_path: Path) -> None:
    class _S:
        plc_work_dir = str(tmp_path)
        plc_upload_max_mb = 200

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Line/Line.ap19", b"fake-ap")
        zf.writestr("Line/System/x.bin", b"sidecar")
    out = save_upload("line_full.zip", buf.getvalue(), settings=_S())  # type: ignore[arg-type]
    assert out.exists()
    assert is_complete_tia_project(out) or any(
        is_complete_tia_project(p) for p in out.rglob("*.ap19")
    ) or out.suffix.lower() == ".ap19"