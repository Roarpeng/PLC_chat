"""G4: deterministic SCL lowering, import order, golden hash, error mapping."""
from __future__ import annotations

import json
from pathlib import Path

from plc_engine.canonical import sha256_prefixed
from plc_engine.process.scl_lowering import CompilerService, assert_deterministic
from tests.v2_fixtures import build_valid_demo_ir

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "v2"


def test_golden_manifest_and_file_hashes_match() -> None:
    ir = build_valid_demo_ir()
    golden = json.loads((SNAPSHOTS / "manifest.golden.json").read_text(encoding="utf-8"))
    manifest, source_map = CompilerService(ir.af_profile).lower(ir)
    assert manifest.sha256 == golden["manifest_sha256"]
    assert {f.path: f.sha256 for f in manifest.files} == golden["file_hashes"]
    assert manifest.import_order == golden["import_order"]
    assert len(source_map.mappings) == golden["source_map_entries"]
    assert golden["deterministic"] is True


def test_generated_scl_matches_golden_files_byte_for_byte() -> None:
    ir = build_valid_demo_ir()
    manifest, _ = CompilerService(ir.af_profile).lower(ir)
    for file in manifest.files:
        golden = (SNAPSHOTS / f"{file.tia_block}.golden.scl").read_text(encoding="utf-8")
        assert file.content == golden, file.path
        assert file.sha256 == sha256_prefixed(file.content)


def test_import_order_is_udt_fb_db_ob() -> None:
    ir = build_valid_demo_ir()
    manifest, _ = CompilerService(ir.af_profile).lower(ir)
    roles = [manifest.file_index()[path].role for path in manifest.import_order]
    assert roles == ["UDT", "FB", "FB", "DB", "OB"]
    assert manifest.validate_import_order() == []
    assert manifest.dependencies[manifest.import_order[-1]]


def test_second_generation_is_identical() -> None:
    ir = build_valid_demo_ir()
    result = assert_deterministic(ir)
    assert result["deterministic"] is True
    assert result["manifest_sha256"] == result["second_manifest_sha256"]


def test_ui_layout_change_does_not_regenerate_semantics() -> None:
    ir = build_valid_demo_ir()
    first, _ = CompilerService(ir.af_profile).lower(ir)
    ir.views["layout"] = {"S2": {"x": 123, "zoom": 9}}
    second, _ = CompilerService(ir.af_profile).lower(ir)
    assert first.sha256 == second.sha256
    assert {f.path: f.sha256 for f in first.files} == {f.path: f.sha256 for f in second.files}


def test_hold_1s_to_2s_updates_scl_constant() -> None:
    ir = build_valid_demo_ir()
    first, _ = CompilerService(ir.af_profile).lower(ir)
    assert "T#1000ms" in first.file_index()["scl/FB_Sequence.scl"].content
    ir.process.step_index()["S2"].min_duration_ms = 2000
    ir.refresh_hash()
    second, _ = CompilerService(ir.af_profile).lower(ir)
    assert "T#2000ms" in second.file_index()["scl/FB_Sequence.scl"].content
    assert second.sha256 != first.sha256


def test_no_block_numbers_are_invented() -> None:
    ir = build_valid_demo_ir()
    manifest, _ = CompilerService(ir.af_profile).lower(ir)
    assert all(file.block_number is None for file in manifest.files)
    # FB name is explicit, never inferred from a DB suffix.
    assert any("FB_Sequence" in file.content for file in manifest.files if file.tia_block == "DB_Sequence")


def test_compile_errors_map_back_to_ir_nodes() -> None:
    ir = build_valid_demo_ir()
    manifest, source_map = CompilerService(ir.af_profile).lower(ir)
    sequence = manifest.file_index()["scl/FB_Sequence.scl"].content.splitlines()
    line = next(i for i, text in enumerate(sequence, start=1) if "source_id: S2" in text)
    mapped = CompilerService.compile_errors_to_ir(
        [{"block": "FB_Sequence", "line": line, "message": "syntax error"}], source_map
    )
    assert mapped[0]["mapped"] is True
    assert "S2" in mapped[0]["ir_refs"][0]["ir_id"] or "S2" in mapped[0]["canvas_node_ids"]


def test_source_id_annotations_are_present() -> None:
    ir = build_valid_demo_ir()
    manifest, _ = CompilerService(ir.af_profile).lower(ir)
    for file in manifest.files:
        assert "source_id:" in file.content, file.path
