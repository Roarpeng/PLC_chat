"""T03 · 连线白名单执行器：合法边放行 / 非法边 100% 拦截 / patch 原子性。"""
from __future__ import annotations

import pytest

from plc_engine.af.greenfield_edges import (
    ALLOWED_EDGES,
    ILLEGAL_EDGE_CATALOG,
    PRIMARY_LEGAL_EDGE_KINDS,
)
from plc_engine.af.greenfield_ir import GFEdge, IRPatch, build_sample_ir
from plc_engine.af.greenfield_validator import apply_patch, validate_edge, validate_ir


@pytest.fixture()
def ir():
    return build_sample_ir()


def _edge(kind: str, src: str, dst: str, *, eid: str = "E_TEST") -> GFEdge:
    return GFEdge(
        id=eid,
        kind=kind,
        src_id=src,
        dst_id=dst,
        view_mask=["flow"],
        origin="user",
    )


def test_all_sample_edges_are_legal(ir) -> None:
    report = validate_ir(ir)
    assert report.ok, [v.to_dict() for v in report.violations]
    for edge in ir.edges:
        assert validate_edge(edge, ir) == [], f"合法边被误拦：{edge.id}"


def test_twelve_legal_edge_kinds_and_catalog(ir) -> None:
    assert len(ALLOWED_EDGES) >= 12
    assert len(ILLEGAL_EDGE_CATALOG) >= 10
    kinds = {e.kind_value() for e in ir.edges}
    for kind in PRIMARY_LEGAL_EDGE_KINDS:
        assert kind.value in kinds, f"示例 IR 缺合法边类型 {kind.value}"


@pytest.mark.parametrize(
    "name,edge",
    [
        ("CM 直连 CM", _edge("E_CN_TO_CM", "U1EM1_CM1", "U1EM2_CM3", eid="E_BAD_1")),
        ("跨工序 EM 直连", _edge("E_MSG_STEP", "U1EM1", "U1EM2", eid="E_BAD_2")),
        ("绕过控制节点", _edge("E_CN_TO_CM", "U1EM1", "U1EM1_CM1", eid="E_BAD_3")),
        ("契约写向", _edge("E_IO_READ", "DB_UNITS", "IOMAP", eid="E_BAD_4")),
        ("非法 PackML 迁移", _edge("E_PACKML_TRANSITION", "Stopped", "Execute", eid="E_BAD_5")),
        ("命名空间违规", _edge("E_HIER_UNIT_EM", "BARE_NODE", "U1EM1", eid="E_BAD_6")),
        ("设备跨层直连", _edge("E_CMD_UNIT_EM", "U1EM1_CM2", "U1EM2_CN", eid="E_BAD_7")),
    ],
)
def test_illegal_edges_are_rejected_with_location(ir, name: str, edge: GFEdge) -> None:
    violations = validate_edge(edge, ir)
    assert violations, f"非法边未被拦截：{name}"
    assert all(v.code.startswith("GF_EDGE_") for v in violations), name
    assert any(v.node_id for v in violations), f"缺少节点定位：{name}"


def test_illegal_patch_does_not_mutate_ir(ir) -> None:
    before = ir.ir_sha256()
    report = apply_patch(
        ir,
        IRPatch(op="add_edge", edge=_edge("E_CN_TO_CM", "U1EM1_CM1", "U1EM2_CM3")),
    )
    assert not report.ok
    assert ir.ir_sha256() == before, "非法 patch 不得改动 IR"


def test_unknown_patch_op_is_rejected(ir) -> None:
    before = ir.ir_sha256()
    report = apply_patch(ir, IRPatch(op="drop_database"))
    assert not report.ok
    assert ir.ir_sha256() == before


def test_ir_only_catalog_covers_all_fields(ir) -> None:
    fields = ir.ir_only_fields()
    assert len(fields) >= 10
    assert isinstance(ir.ir_only_catalog(), list)
