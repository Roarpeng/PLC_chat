"""T-HW · 硬件拓扑 ops 回归：挂载/卸载、绑定/解绑（步序字段还原）、增删节点、一键重置。

硬件拓扑只是逻辑级占位（物理组态在博途完成）：编辑必须可撤销——
reset_topology 清空三键并按绑定记录还原步序字段。
"""
from __future__ import annotations

import pytest

from gateway.app.services.plc import greenfield_service as svc
from gateway.app.services.plc.greenfield_session import GreenfieldSession
from plc_engine.af.greenfield_ports import GreenfieldError


@pytest.fixture()
def session() -> GreenfieldSession:
    s = GreenfieldSession()
    svc.draft_from_prompt(s, "")
    return s


def test_mount_and_unmount_cm(session):
    cm_id = session.ir.cms[0].id
    svc.update_hardware(session, {"op": "mount_cm", "cm_id": cm_id, "hw_node_id": "HW_KUKA"})
    assert session.custom_hw["cm_mounts"].get(cm_id) == "HW_KUKA"
    assert any(m["kind"] == "edit" and "挂载" in m["text"] for m in session.messages)

    svc.update_hardware(session, {"op": "unmount_cm", "cm_id": cm_id})
    assert cm_id not in (session.custom_hw.get("cm_mounts") or {})
    assert any(m["kind"] == "edit" and "卸载" in m["text"] for m in session.messages)


def test_reset_topology_restores_bound_condition(session):
    step = session.ir.steps[0]
    prev_cond = step.transition_condition
    var_key = "IO:I0_0_PartPresent"

    svc.update_hardware(session, {"op": "bind_var", "var_key": var_key, "target_id": step.id, "role": "condition"})
    # 受控 patch 原子提交会重建 IR 实体对象，断言统一从当前 session.ir 重新取。
    assert session.ir.steps[0].transition_condition == var_key.split(":", 1)[-1]
    assert session.views is not None  # 绑定即时联动视图

    svc.update_hardware(session, {"op": "reset_topology"})
    assert session.custom_hw.get("cm_mounts") == {}
    assert session.custom_hw.get("extra_nodes") == []
    assert session.custom_hw.get("var_bindings") == []
    assert session.ir.steps[0].transition_condition == prev_cond
    assert any("重置为自动推导" in m["text"] for m in session.messages)


def test_unbind_restores_appended_action(session):
    step = session.ir.steps[1]
    prev_actions = list(step.actions)
    var_key = "DB:DB1900_Communication_PC.Send.CmdStart"

    svc.update_hardware(
        session, {"op": "bind_var", "var_key": var_key, "target_id": step.id, "role": "action"}
    )
    assert var_key.split(":", 1)[-1] in session.ir.steps[1].actions

    svc.update_hardware(session, {"op": "unbind_var", "var_key": var_key, "target_id": step.id})
    assert session.ir.steps[1].actions == prev_actions


def test_bind_keeps_later_manual_edit_on_unbind(session):
    """解绑只还原仍是绑定值的字段；绑定后的手动编辑不被覆盖。"""
    step = session.ir.steps[0]
    prev_cond = step.transition_condition
    var_key = "IO:I0_0_PartPresent"

    svc.update_hardware(session, {"op": "bind_var", "var_key": var_key, "target_id": step.id, "role": "condition"})
    # 模拟后续画布/对话编辑改写条件（作用于当前 IR 实体）
    session.ir.steps[0].transition_condition = "#controlNodes.custom.status"
    svc.update_hardware(session, {"op": "unbind_var", "var_key": var_key, "target_id": step.id})
    assert session.ir.steps[0].transition_condition == "#controlNodes.custom.status"  # 未被回滚成 prev_cond


def test_remove_hw_node_only_custom(session):
    svc.update_hardware(
        session,
        {"op": "add_hw_node", "node": {"id": "HW_HMI_1", "kind": "HMI_PANEL", "label": "HMI 面板"}},
    )
    assert any(n.get("id") == "HW_HMI_1" for n in session.custom_hw["extra_nodes"])
    # 顺带挂一个 CM 到该节点，移除节点应连带清理挂载
    cm_id = session.ir.cms[0].id
    svc.update_hardware(session, {"op": "mount_cm", "cm_id": cm_id, "hw_node_id": "HW_HMI_1"})

    svc.update_hardware(session, {"op": "remove_hw_node", "hw_node_id": "HW_HMI_1"})
    assert session.custom_hw["extra_nodes"] == []
    assert cm_id not in session.custom_hw["cm_mounts"]

    # 自动推导节点（不在 extra_nodes）移除 = 无操作不报错
    svc.update_hardware(session, {"op": "remove_hw_node", "hw_node_id": "HW_CPU"})
    assert session.custom_hw["extra_nodes"] == []


def test_unknown_op_fail_closed(session):
    with pytest.raises(GreenfieldError) as excinfo:
        svc.update_hardware(session, {"op": "explode"})
    assert excinfo.value.code == "GF_HW_OP_UNKNOWN"


# ---------------------------------------------------------------------------
# WP-03 / §2.2：「绕过 patch 直接写 IR」负例必须失败
# ---------------------------------------------------------------------------

def test_bypass_patch_direct_ir_write_is_rejected(session):
    """② 运行时负例：绕过 patch 直接写 IR 后，带期望指纹的受控写入必须被拒绝。"""
    from plc_engine.af.greenfield_ir import CanvasPatch, IRPatch
    from plc_engine.af.greenfield_validator import apply_canvas_patch

    baseline = session.ir.ir_sha256()
    session.ir.cms[0].business_label = "绕过受控入口的直接写入"
    assert session.ir.ir_sha256() != baseline

    patch = CanvasPatch(
        ops=[IRPatch(
            op="set_ir_only_field",
            field_path=f"steps.{session.ir.steps[0].id}.timeout_ms",
            value=8000,
        )],
        expected_ir_sha256=baseline,
    )
    result = apply_canvas_patch(session, patch)
    assert result.ok is False
    assert "指纹漂移" in result.reason or "绕过" in result.reason
    assert result.ir_sha256 == session.ir.ir_sha256()  # 受控入口未改动 IR


def test_write_entrypoints_do_not_bypass_canvas_patch():
    """② 源码守护负例：三个写入口一旦出现「直接写 session.ir.*」本测试即失败。"""
    import inspect
    import re

    from gateway.app.services.plc import greenfield_service as svc_mod

    sources = (
        inspect.getsource(svc_mod.apply_link_patch)
        + inspect.getsource(svc_mod.update_hardware)
    )
    assert "apply_canvas_patch" in sources  # 全部收敛到统一入口
    assert not re.search(r"session\.ir\.\w+\s*=", sources), "不得直接赋值 session.ir.*"
    assert not re.search(
        r"session\.ir\.\w+\.(append|remove|clear|pop|extend|insert)\(", sources
    ), "不得就地改 session.ir.* 集合"
