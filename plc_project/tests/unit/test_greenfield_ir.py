"""T01 · 强类型 IR 内核回归（§2.1 / §7 T01 验收点）。

覆盖：往返无损、同内容同哈希、``to_af_project()`` 可构造、常量齐备、
ID 命名空间规则、Protocol 零实现体、新模块零 import 存量重构链。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from plc_engine.af import af_generator
from plc_engine.af.af_model import AfProject
from plc_engine.af.greenfield_edges import (
    ALLOWED_EDGES,
    EDGE_ERROR_CODES,
    ILLEGAL_EDGE_CATALOG,
    LEGAL_EDGE_GROUPS,
    MODE_IDS,
    NAMESPACE_RULES,
    PACKML_STATES,
    PACKML_TRANSITIONS,
    PLCOPEN_SIGNALS,
    PRIMARY_LEGAL_EDGE_KINDS,
    VIRTUAL_NODE_IDS,
    EdgeKind,
    NodeKind,
    edge_id,
    matches_namespace,
)
from plc_engine.af.greenfield_ir import (
    AF_PROFILE,
    IR_ONLY_CATALOG,
    IR_ONLY_FIELD_KEYS,
    IR_VERSION,
    GFEdge,
    GFProject,
    GFSpecMeta,
    GreenfieldIR,
    GFViews,
    build_sample_ir,
    canonical_dumps,
    sha256_prefixed,
)
from plc_engine.af.greenfield_ports import (
    DeliveryPort,
    FORBIDDEN_PREGATE_ACTIONS,
    GreenfieldStage,
    LOCKED_HINT,
    PHASE2_PIPELINE_DOC,
    STAGE_BADGES,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 存量重构 / 回写链模块名黑名单（§2.3）。AST 断言新通道源码零 import。
FORBIDDEN_MODULE_MARKERS = (
    "af.refactor", "af.af_mapper", "af.baseline", "af.bit_chain_miner",
    "af.cnf_splitter", "af.smt_verifier",
    "services.plc.af_import", "services.plc.canvas_import",
    "services.plc.refactor_pipeline", "services.plc.af_generate",
    "services.plc.compile_jobs", "services.plc.changesets",
    "plc_engine.contracts", "plc_engine.slot_context_slicer",
    "plc_engine.contract_adapters", "plc_engine.pcec",
    "plc_engine.writeback_pipeline", "plc_engine.writeback_linter",
    "plc_engine.writeback_heal", "plc_engine.writeback_contract",
    "plc_engine.mega_source", "plc_engine.dependency_closure",
    "plc_engine.scl_precheck",
    "agents.plc.tia.importer", "agents.plc.tia.decouple",
    "agents.plc.tia.flgnet_fold", "agents.plc.tia.writeback_batch",
)


def _iter_import_targets(path: Path) -> list[str]:
    """解析一个 Python 源文件的全部 import 目标（含 from-import 的模块名）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                targets.append(node.module)
    return targets


# ---------------------------------------------------------------------------
# 往返 / 哈希
# ---------------------------------------------------------------------------

def test_ir_roundtrip_is_lossless() -> None:
    ir = build_sample_ir()
    restored = GreenfieldIR.from_dict(ir.to_dict())
    assert restored.to_dict() == ir.to_dict()
    assert isinstance(restored.project, GFProject)
    assert isinstance(restored.views, GFViews)
    assert isinstance(restored.spec_meta, GFSpecMeta)
    assert all(isinstance(e, GFEdge) for e in restored.edges)
    assert restored.node_index()["U1EM1_CM1"]["kind"] == NodeKind.CM.value


def test_canonical_json_same_content_same_hash() -> None:
    a = build_sample_ir()
    b = GreenfieldIR.from_dict(a.to_dict())
    assert a.canonical_json() == b.canonical_json()
    assert a.ir_sha256() == b.ir_sha256()
    assert a.ir_sha256().startswith("sha256:")
    assert len(a.ir_sha256()) == len("sha256:") + 64
    assert a.ir_sha256() == a.ir_sha256().lower()


def test_canonical_json_excludes_volatile_fields() -> None:
    ir = build_sample_ir()
    baseline = ir.ir_sha256()
    ir.views.layout = {"U1": {"x": 12, "y": 34}}
    ir.spec_meta.spec_hash = "sha256:" + "0" * 64
    ir.spec_meta.frozen_at = "2026-11-04T03:12:44Z"
    ir.spec_meta.frozen_by = "engineer"
    ir.edges[0].created_at = "2026-11-04T03:12:44Z"
    assert ir.ir_sha256() == baseline, "布局/冻结元数据/边时间戳明确不进哈希"


def test_canonical_json_changes_with_content() -> None:
    ir = build_sample_ir()
    before = ir.ir_sha256()
    ir.cms[0].parameters["timeout_ms"] = 9999
    assert ir.ir_sha256() != before


def test_canonical_dumps_helpers_are_stable() -> None:
    assert canonical_dumps({"b": 1, "a": "中文"}) == '{"a":"中文","b":1}'
    assert sha256_prefixed("abc") == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


# ---------------------------------------------------------------------------
# to_af_project 瞬时派生
# ---------------------------------------------------------------------------

def test_to_af_project_constructs_usable_af_model() -> None:
    ir = build_sample_ir()
    project = ir.to_af_project()
    assert isinstance(project, AfProject)
    assert project.name == "AssemblyCell"
    assert len(project.units) == 1
    assert len(project.units[0].equipment_modules) == 3
    # AfProject 自带 to_dict/from_dict 往返无损，证明可喂既有引擎
    assert AfProject.from_dict(project.to_dict()).to_dict() == project.to_dict()
    # 生成器签名兼容（本轮不调用生成器，只验证接口契约）
    sig = inspect.signature(af_generator.generate_af_project_blocks)
    assert "project" in sig.parameters
    assert "self_contained" in sig.parameters


def test_to_af_project_is_transient_not_a_second_state_source() -> None:
    ir = build_sample_ir()
    before = ir.ir_sha256()
    project = ir.to_af_project()
    project.units[0].equipment_modules[0].control_modules.clear()
    assert ir.ir_sha256() == before
    assert len(ir.cms) == 3


# ---------------------------------------------------------------------------
# 常量齐备
# ---------------------------------------------------------------------------

def test_edge_and_rule_constants_are_complete() -> None:
    assert len(LEGAL_EDGE_GROUPS) == 12, "§3.7.1 十二类合法边规则"
    assert len(PRIMARY_LEGAL_EDGE_KINDS) == 12, "§4.1 十二类建议边"
    assert set(ALLOWED_EDGES) == {k.value for k in EdgeKind}
    assert len(ILLEGAL_EDGE_CATALOG) == 10
    assert len(EDGE_ERROR_CODES) >= 10
    assert len(PACKML_STATES) == 17
    assert "Execute->Completing" in PACKML_TRANSITIONS
    assert "Execute->Idle" not in PACKML_TRANSITIONS
    assert "Aborted->Execute" not in PACKML_TRANSITIONS
    assert PLCOPEN_SIGNALS == ("enable", "valid", "busy", "error", "status")
    assert MODE_IDS == frozenset({"MODE_AUTO", "MODE_MANUAL", "MODE_MAINTENANCE"})
    assert len(NAMESPACE_RULES) >= 12
    assert VIRTUAL_NODE_IDS["DB_UNITS"] == NodeKind.INTERFACE_DB
    assert IR_VERSION == "gf-ir-1.0"
    assert AF_PROFILE == "SIEMENS_AF_BASIC_FOLDER_V19"


def test_namespace_rules() -> None:
    assert matches_namespace("unit_id", "U1")
    assert matches_namespace("unit_id", "U9")
    assert not matches_namespace("unit_id", "Unit1")
    assert matches_namespace("em_id", "U1EM0")
    assert matches_namespace("em_id", "U1EM12")
    assert not matches_namespace("em_id", "EM1")
    assert matches_namespace("cm_id", "U1EM1_CM1")
    assert matches_namespace("control_node_id", "U1EM2_CN")
    assert matches_namespace("step_id", "U1EM2_S900")
    assert matches_namespace("job_id", "U1EM1_J1")
    assert matches_namespace("mode_id", "MODE_AUTO")
    assert matches_namespace("edge_id", edge_id(EdgeKind.E_SC_UP, "U1EM1", "DB_UNITS"))
    assert not matches_namespace("edge_id", "SC_UP_U1EM1_DB_UNITS")
    assert matches_namespace("unit_prefix", "U1_")
    assert matches_namespace("em_prefix", "U1EM12_")


def test_ir_only_field_catalog_covers_ten_items() -> None:
    ir = build_sample_ir()
    assert len(ir.ir_only_fields()) == 10
    assert len(IR_ONLY_FIELD_KEYS) == 10
    assert len(IR_ONLY_CATALOG) == 10
    assert [c["key"] for c in ir.ir_only_catalog()] == list(ir.ir_only_fields())
    assert all("panel" in c and "editable" in c and "fields" in c for c in IR_ONLY_CATALOG)
    assert "views.layout" in IR_ONLY_CATALOG[9]["fields"]


def test_sample_ir_covers_all_twelve_legal_edge_kinds() -> None:
    ir = build_sample_ir()
    kinds = {e.kind_value() for e in ir.edges}
    assert all(k.value in kinds for k in PRIMARY_LEGAL_EDGE_KINDS)
    index = ir.node_index()
    assert index["U1"]["kind"] == NodeKind.UNIT.value
    assert index["DB_UNITS"]["kind"] == NodeKind.INTERFACE_DB.value
    assert index["Stopped"]["kind"] == NodeKind.PACKML_STATE.value
    assert index["CR_IO_TAG_1"]["immutable"] is True
    assert all(e.id.startswith("E_") and "__" in e.id for e in ir.edges)


# ---------------------------------------------------------------------------
# 阶段 / 接口位 / 零 import 存量重构链
# ---------------------------------------------------------------------------

def test_stage_enum_and_badges() -> None:
    assert [s.value for s in GreenfieldStage] == [
        "DRAFT", "LINKABLE", "VALIDATING", "FROZEN", "LOCKED"
    ]
    assert set(STAGE_BADGES) == set(GreenfieldStage)
    assert "AF" not in "".join(STAGE_BADGES.values())
    assert "确认" in LOCKED_HINT
    assert "generate" in FORBIDDEN_PREGATE_ACTIONS
    assert "confirm-writeback" in FORBIDDEN_PREGATE_ACTIONS
    assert "PCEC" in PHASE2_PIPELINE_DOC


def test_delivery_port_is_protocol_only() -> None:
    assert getattr(DeliveryPort, "_is_protocol", False) is True
    assert {"deliver", "assert_pcec_gate"} <= set(dir(DeliveryPort))
    ports_source = (
        PROJECT_ROOT / "plc_engine" / "af" / "greenfield_ports.py"
    ).read_text(encoding="utf-8")
    # 零实现体：不得出现任何继承 DeliveryPort 的具体类
    tree = ast.parse(ports_source)
    concrete_impls = [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Name) and base.id == "DeliveryPort")
            or (isinstance(base, ast.Attribute) and base.attr == "DeliveryPort")
            for base in node.bases
        )
    ]
    assert concrete_impls == []
    for marker in FORBIDDEN_MODULE_MARKERS:
        assert marker not in ports_source


def test_new_modules_do_not_import_legacy_refactor_chain() -> None:
    """AST 断言所有 greenfield_* 源文件的 import 闭包不出现 §2.3 禁止模块。"""
    af_dir = PROJECT_ROOT / "plc_engine" / "af"
    service_dir = PROJECT_ROOT / "gateway" / "app" / "services" / "plc"
    router = PROJECT_ROOT / "gateway" / "app" / "routers" / "greenfield.py"
    targets = sorted(af_dir.glob("greenfield_*.py")) + sorted(service_dir.glob("greenfield_*.py"))
    if router.exists():
        targets.append(router)
    assert len(targets) >= 3
    for path in targets:
        imported = _iter_import_targets(path)
        for module in imported:
            for marker in FORBIDDEN_MODULE_MARKERS:
                assert marker not in module, f"{path.name} 不得 import {marker} (实际 {module})"


def test_no_greenfield_delivery_file_created() -> None:
    """Q7：本轮不创建 Phase 2 交付实现文件，不产出任何 XML/SCL 工程源。"""
    assert not (PROJECT_ROOT / "gateway" / "app" / "services" / "plc" / "greenfield_delivery.py").exists()
    assert not list((PROJECT_ROOT / "plc_engine" / "af").glob("greenfield_*.xml"))


# ---------------------------------------------------------------------------
# WP-03 / UC-06 / UC-07：spec_hash 全域确定性与 specs/vN.json 独立重建
# ---------------------------------------------------------------------------

def test_spec_hash_is_deterministic_and_covers_full_domain() -> None:
    """① 同一画布状态两次序列化 spec_hash 一致；拓扑/节点/边/步序/资料均进哈希。"""
    from plc_engine.af.greenfield_spec import freeze
    from plc_engine.af.greenfield_views import project_views

    ir = build_sample_ir()
    ir.project_id = "PRJ_HASH"
    ir.hw_nodes = [{"id": "LHW_1", "kind": "LOGICAL_PLC", "label": "控制器逻辑占位"}]
    ir.hw_links = [{"id": "L1", "src_hw_id": "LHW_1", "dst_hw_id": "LHW_2"}]
    ir.cm_mounts = {"U1EM1_CM1": "LHW_1"}
    ir.var_bindings = [{"var_key": "IO:X", "target_id": "U1EM1_S10"}]
    baseline = ir.spec_hash()

    a = GreenfieldIR.from_dict(ir.to_dict())
    b = GreenfieldIR.from_dict(a.to_dict())
    assert a.spec_hash() == b.spec_hash() == baseline
    assert a.canonical_json() == b.canonical_json()

    # 同一份画布两次 freeze（含视图/契约投影）哈希一致
    views = project_views(ir)
    s1 = freeze(ir, views, None, spec_version=1, project_id="PRJ_HASH",
                frozen_at="2026-01-01T00:00:00Z")
    s2 = freeze(ir, views, None, spec_version=1, project_id="PRJ_HASH",
                frozen_at="2026-01-01T00:00:00Z")
    assert s1.spec_hash == s2.spec_hash

    # 任一类域变化都改变全域哈希（拓扑 / 节点 / 步序 / 项目标识）
    def _add_hw(x: GreenfieldIR) -> None:
        x.hw_nodes.append({"id": "LHW_9", "kind": "LOGICAL_GENERIC", "label": "x"})

    def _edit_cm(x: GreenfieldIR) -> None:
        x.cms[0].parameters["timeout_ms"] = 9999

    def _edit_step(x: GreenfieldIR) -> None:
        x.steps[0].actions.append("// new")

    def _edit_project(x: GreenfieldIR) -> None:
        x.project_id = "OTHER"

    for mutate in (_add_hw, _edit_cm, _edit_step, _edit_project):
        changed = GreenfieldIR.from_dict(ir.to_dict())
        mutate(changed)
        assert changed.spec_hash() != baseline


def test_specs_vn_json_rebuilds_canvas_including_topology(tmp_path) -> None:
    """③ 仅凭 specs/vN.json 完整重建画布（含逻辑拓扑），不依赖会话内存态。"""
    from plc_engine.af.greenfield_spec import freeze, write_spec, load_spec
    from plc_engine.af.greenfield_views import project_views, assert_roundtrip

    ir = build_sample_ir()
    ir.project_id = "PRJ_REBUILD"
    ir.hw_nodes = [
        {"id": "LHW_1", "kind": "LOGICAL_PLC", "label": "控制器"},
        {"id": "LHW_2", "kind": "LOGICAL_ROBOT", "label": "机器人"},
    ]
    ir.hw_links = [{"id": "L1", "src_hw_id": "LHW_1", "dst_hw_id": "LHW_2"}]
    ir.cm_mounts = {"U1EM1_CM1": "LHW_1", "U1EM2_CM3": "LHW_2"}
    ir.var_bindings = [
        {"var_key": "DB:DB720.Ack", "target_id": "U1EM1_S10", "role": "condition"}
    ]
    views = project_views(ir)
    spec = freeze(ir, views, None, session_id="S_REBUILD", spec_version=1,
                  project_id="PRJ_REBUILD")
    path = write_spec(spec, tmp_path, "S_REBUILD")

    loaded = load_spec(path, project_id="PRJ_REBUILD")
    rebuilt = loaded.rebuild_ir()
    assert rebuilt.to_dict() == ir.to_dict()
    assert rebuilt.hw_nodes == ir.hw_nodes
    assert rebuilt.hw_links == ir.hw_links
    assert rebuilt.cm_mounts == ir.cm_mounts
    assert rebuilt.var_bindings == ir.var_bindings
    assert rebuilt.project_id == "PRJ_REBUILD"
    assert rebuilt.ir_sha256() == ir.ir_sha256()
    assert loaded.spec_hash == spec.spec_hash
    # 四视图亦可由快照确定性重建
    assert_roundtrip(rebuilt, loaded.rebuild_views())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
