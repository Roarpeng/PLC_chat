"""T03 · 三视图确定性投影与结构层 roundtrip（§3.6 / §7 T03 验收点）。"""
from __future__ import annotations

import pytest

from plc_engine.af.greenfield_edges import (
    ALL_VIEWS,
    PRIMARY_LEGAL_EDGE_KINDS,
    VIEW_FLOW,
    VIEW_SEQ,
    VIEW_STATE,
)
from plc_engine.af.greenfield_ir import GreenfieldIR, build_sample_ir
from plc_engine.af.greenfield_ports import ViewProjectionError
from plc_engine.af.greenfield_validator import validate_ir
from plc_engine.af.greenfield_views import (
    DEFAULT_VISIBLE_STATES,
    assert_roundtrip,
    inspect_external_mermaid,
    project_views,
    render_export_md,
    render_flow,
    render_sequence,
    render_state,
)


@pytest.fixture()
def sample() -> tuple[GreenfieldIR, object]:
    ir = build_sample_ir()
    return ir, project_views(ir)


def test_three_views_are_syntactically_valid(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    assert views.flow.mermaid.startswith("flowchart TB")
    assert views.seq.mermaid.startswith("sequenceDiagram")
    assert views.state.mermaid.startswith("stateDiagram-v2")
    assert "autonumber" in views.seq.mermaid
    assert "alt " in views.seq.mermaid and "else " in views.seq.mermaid
    assert "opt " in views.seq.mermaid
    assert views.seq.mermaid.count("\n    end") == 2, "alt / opt 各配一个 end"
    assert "[*] --> Stopped" in views.state.mermaid
    assert "note right of Execute" in views.state.mermaid
    assert "end note" in views.state.mermaid
    assert "state \"停机 Stopped\" as Stopped" in views.state.mermaid


def test_views_match_first_mermaid_sample_ids(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    flow_nodes = set(views.flow.node_ids)
    for node_id in ("U1", "U1EM0", "U1EM1", "U1EM2", "U1EM1_CM1", "U1EM1_CM2",
                    "U1EM2_CM3", "U1EM1_CN", "U1EM2_CN", "DB_UNITS", "IOMAP"):
        assert node_id in flow_nodes, f"首版 flowchart 缺节点 {node_id}"
    assert "MODE_AUTO" in set(views.state.node_ids)
    assert "Stopped" in set(views.state.node_ids)
    assert "OP" in set(views.seq.node_ids)
    # 虚线只读边与实线层级边同时存在
    assert "-.->|E_IO_READ" in views.flow.mermaid
    assert "-->|E_HIER_UNIT_EM 骨架|" in views.flow.mermaid


def test_three_views_share_one_id_namespace(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    index = ir.node_index()
    for view in ALL_VIEWS:
        snapshot = views.snapshot(view)
        assert set(snapshot.node_ids) <= set(index), f"{view} 出现命名空间外节点"
        assert set(snapshot.edge_ids) == {
            e.id for e in ir.edges if view in e.view_mask
        }, f"{view} 边 ID 未与 IR.edges[view_mask] 对齐"
    assert views.shared_id_namespace is True
    # 同一条边可投影到多个视图（view_mask 联动机制）
    multi = [e for e in ir.edges if len(e.view_mask) > 1]
    assert multi
    for edge in multi:
        for view in edge.view_mask:
            assert edge.id in set(views.snapshot(view).edge_ids)


def test_all_twelve_edge_kinds_projected(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    projected = set()
    for view in ALL_VIEWS:
        projected |= set(views.snapshot(view).edge_ids)
    for kind in PRIMARY_LEGAL_EDGE_KINDS:
        assert any(
            e.kind_value() == kind.value and e.id in projected for e in ir.edges
        ), f"{kind.value} 未被投影到任何视图"


def test_roundtrip_passes_and_is_deterministic(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    assert_roundtrip(ir, views)
    again = project_views(ir)
    assert again.to_dict() == views.to_dict()
    assert render_flow(ir) == views.flow.mermaid
    assert render_sequence(ir) == views.seq.mermaid
    assert render_state(ir) == views.state.mermaid
    # 布局坐标是纯 UI 态：传入后不影响三份文本
    with_layout = project_views(ir, layout={"U1": {"x": 7, "y": 9}})
    assert with_layout.flow.mermaid == views.flow.mermaid
    assert with_layout.layout == {"U1": {"x": 7, "y": 9}}


def test_roundtrip_detects_text_snapshot_drift(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    views.flow.mermaid = views.flow.mermaid.replace('    U1["', '    U9["')
    with pytest.raises(ViewProjectionError) as caught:
        assert_roundtrip(ir, views)
    assert caught.value.code == "GF_VIEW_PROJECTION"
    assert caught.value.details["view"] == VIEW_FLOW


def test_roundtrip_detects_edge_id_drift(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    views.flow.edge_ids.append("E_FAKE_U1__U9")
    with pytest.raises(ViewProjectionError):
        assert_roundtrip(ir, views)


def test_roundtrip_detects_unbalanced_sequence_branches(sample: tuple[GreenfieldIR, object]) -> None:
    ir, views = sample
    ir.views = views  # 让 validate_ir 检查步序视图结构
    assert validate_ir(ir).ok is True
    ir.views.seq.mermaid = ir.views.seq.mermaid.replace("    end", "    %% end", 1)
    report = validate_ir(ir)
    assert report.ok is False
    assert any(v.code == "GF_EDGE_BRANCH_UNBALANCED" for v in report.violations)


def test_export_md_contains_three_views_and_ten_ir_only_groups(
    sample: tuple[GreenfieldIR, object]
) -> None:
    ir, views = sample
    md = render_export_md(ir, views, frozen_note="测试留痕")
    assert "flowchart TB" in md and "sequenceDiagram" in md and "stateDiagram-v2" in md
    assert md.count("```mermaid") == 3
    for item in ir.ir_only_catalog():
        assert item["label"] in md
    assert "确认前零写盘" in md
    assert "测试留痕" in md


def test_external_mermaid_never_overwrites_ir(sample: tuple[GreenfieldIR, object]) -> None:
    ir, _ = sample
    before = ir.ir_sha256()
    external = """sequenceDiagram
    participant A as 工位
    participant B as 设备
    A->>B: 启动
    alt 正常
        B-->>A: 完成
    else 异常
        B-->>A: 报警
    end
"""
    suggestion = inspect_external_mermaid(external)
    assert suggestion["parseable"] is True
    assert suggestion["applies_to_ir"] is False
    assert suggestion["unresolved"], "不可表达字段须进入待确认问题"
    assert ir.ir_sha256() == before, "外部 Mermaid 绝不反向覆盖 IR"
    broken = inspect_external_mermaid("这不是一张图")
    assert broken["parseable"] is False
    assert broken["applies_to_ir"] is False


def test_default_visible_states_are_subset_of_packml_17() -> None:
    from plc_engine.af.greenfield_edges import PACKML_STATES

    assert len(PACKML_STATES) == 17
    assert set(DEFAULT_VISIBLE_STATES) <= set(PACKML_STATES)
    assert "Suspending" not in DEFAULT_VISIBLE_STATES  # 保留在 IR，不上首版图


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
