"""G4: SourceMap N:N (canvas node <-> IR id <-> SCL line <-> TIA block)."""
from __future__ import annotations

from plc_engine.process.scl_lowering import CompilerService
from plc_engine.process.source_map import SourceMap
from tests.v2_fixtures import build_valid_demo_ir


def test_generated_source_map_is_n_to_n() -> None:
    ir = build_valid_demo_ir()
    _, source_map = CompilerService(ir.af_profile).lower(ir)
    by_ir: dict[str, list[dict]] = {}
    by_block: dict[str, set[str]] = {}
    for mapping in source_map.mappings:
        by_ir.setdefault(mapping.ir_id, []).append(mapping.to_dict())
        by_block.setdefault(mapping.tia_block, set()).add(mapping.ir_id)
    assert any(len(entries) > 1 for entries in by_ir.values())  # one IR id -> many SCL lines
    assert any(len(ids) > 1 for ids in by_block.values())  # one TIA block -> many IR ids
    assert "S2" in by_ir
    assert all(m.source_id for m in source_map.mappings)


def test_locate_from_tia_block_and_line() -> None:
    ir = build_valid_demo_ir()
    _, source_map = CompilerService(ir.af_profile).lower(ir)
    target = next(m for m in source_map.mappings if m.ir_id == "S2")
    refs = source_map.locate(target.tia_block, target.scl_line)
    assert refs
    assert all("ir_id" in r and "canvas_node_id" in r and "source_id" in r for r in refs)


def test_reverse_locate_returns_all_scl_lines_for_an_ir_id() -> None:
    ir = build_valid_demo_ir()
    _, source_map = CompilerService(ir.af_profile).lower(ir)
    refs = source_map.reverse_locate("S2")
    assert len(refs) >= 2
    assert all("scl_file" in r and "tia_block" in r for r in refs)
    assert refs == sorted(refs, key=lambda r: (r["scl_file"], r["scl_line"], r["tia_block"]))


def test_compile_error_locate_reports_canvas_nodes() -> None:
    ir = build_valid_demo_ir()
    _, source_map = CompilerService(ir.af_profile).lower(ir)
    target = next(m for m in source_map.mappings if m.ir_id == "S2")
    result = source_map.locate_compile_error(target.tia_block, target.scl_line, "unknown identifier")
    assert result["mapped"] is True
    assert result["canvas_node_ids"]
    assert result["source_ids"]
    assert result["message"] == "unknown identifier"


def test_unmapped_diagnostic_is_honest() -> None:
    source_map = SourceMap(map_id="smap_empty")
    result = source_map.locate_compile_error("FB_Unknown", 999, "error")
    assert result["mapped"] is False
    assert result["ir_refs"] == []
    assert result["canvas_node_ids"] == []


def test_source_map_roundtrip() -> None:
    ir = build_valid_demo_ir()
    _, original = CompilerService(ir.af_profile).lower(ir)
    restored = SourceMap.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.ir_ids() == original.ir_ids()


def test_nearest_preceding_line_is_used_for_line_drift() -> None:
    ir = build_valid_demo_ir()
    _, source_map = CompilerService(ir.af_profile).lower(ir)
    target = next(m for m in source_map.mappings if m.ir_id == "S2")
    refs = source_map.locate(target.tia_block, target.scl_line + 1)
    assert refs  # nearest preceding mapping in the same block
