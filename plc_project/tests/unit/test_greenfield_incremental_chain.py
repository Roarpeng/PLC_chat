"""UC-16 真实规格链 + 增量 fidelity 闭环的离线单测（Agent V · 批次 4 阶段 A）。

覆盖（契约 14 §3 UC-16 判据 / 任务书 V3）：
- v1→v2 的 spec_hash 必须不同、project_id 一致、spec_version=1/2、磁盘 specs/vN.json 存在；
- compute_spec_diff 产出的 base_spec_version=1 且 changed_source_ids 非空；
- FidelityChecker(mode="incremental") 报告四指标与六字段齐全；
- ob_number_deviations 必须显式留痕；
- 增量 EvidenceBundle 的 bundle_sha256 可复算；
- 离线报告不得宣称真机 L4 通过 / 编译零错误（N9：fidelity_ok 与 compile_ok 严格分离）。

用 ``tmp_path + TestClient`` 在**进程内 ASGI** 真实跑一遍规格链（导入
``tools/run_incremental_spec_chain.py`` 的 ``run``），不连真机、不启动 SessionServer、
不跑 TIA CLI、不占用 8791/8000 端口；同时读取已落盘的 evidence 产物校验实例一致性。
只读 evidence/*.json 与产品只读校验器，不改任何产品代码。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import run_incremental_spec_chain as chain_mod  # noqa: E402  (需先注入 tools 路径)
from plc_engine.af.spec_diff import canonical_hash  # noqa: E402

#: 与脚本约定一致：bundle_sha256 复算时排除的哈希字段（避免循环依赖）。
_HASH_EXCLUDE = frozenset({"bundle_sha256", "bundle_sha256_recomputed", "bundle_sha256_match"})

#: 增量 FidelityReport.to_dict() 应具备的全字段（契约 §2.5）。
_FIDELITY_REPORT_KEYS = frozenset({
    "fidelity_ok", "coverage", "orphan", "drift", "tia_side_drift",
    "mode", "base_spec_version", "changed_source_ids", "reverse_protection",
    "coverage_matrix", "orphan_blocks", "drift_items", "unmapped_spec_objects",
    "ob_number_deviations", "spec_hash", "spec_version",
    "framework_baseline_version", "product_hash", "sampled_source_ids",
    "pending_real_machine", "notes",
})

#: 增量 EvidenceBundle 六字段（批次 3 six_fields 口径）。
_SIX_FIELD_KEYS = frozenset({
    "mode", "base_spec_version", "changed_source_ids", "reverse_protection",
    "tia_side_drift", "ob_number_deviations",
})


def _recompute_bundle_sha(bundle: dict) -> str:
    return canonical_hash({k: v for k, v in bundle.items() if k not in _HASH_EXCLUDE})


def _walk(obj):
    """递归产出所有 (key, value)，用于扫描禁止出现的真机/编译通过断言。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk(item)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """用 tmp_path + TestClient 真实跑一遍 v1→v2 规格链（不连真机、不起端口）。"""
    base = tmp_path_factory.mktemp("gf_inc_chain_unit")
    wd = base / "work"
    out = base / "chain.json"
    bundle_path = base / "bundle.json"
    chain_doc, bundle_doc = chain_mod.run(out, bundle_path, work_dir=str(wd))
    return {
        "chain": chain_doc,
        "bundle": bundle_doc,
        "work_dir": wd,
        "out": out,
        "bundle_path": bundle_path,
    }


@pytest.fixture(scope="module")
def ev_chain() -> dict:
    return json.loads((EVIDENCE / "uc16_incremental_spec_chain.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ev_bundle() -> dict:
    return json.loads((EVIDENCE / "uc16_incremental_evidence_bundle.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 用例 1：整条离线链真实跑通（前置 sanity，失败则后续不变量无意义）
# ---------------------------------------------------------------------------
def test_chain_runs_offline_with_all_steps_pass(live):
    chain = live["chain"]
    assert chain["summary"]["overall_status"] == "pass"
    assert chain["summary"]["by_status"]["fail"] == 0
    assert chain["summary"]["total"] == 14
    assert all(s["status"] == "pass" for s in chain["steps"])
    # 每一步都带真实响应关键字段与复现命令
    for s in chain["steps"]:
        assert s["response"], f"{s['step_id']} 缺真实响应"
        assert s["repro_command"], f"{s['step_id']} 缺 repro_command"
    assert chain["offline_side"] is True
    assert chain["pending_real_machine"] is True
    assert chain["compile_ok"] is None
    # 产物文件确实由脚本写出（tmp_path 隔离）
    assert live["out"].is_file() and live["bundle_path"].is_file()


# ---------------------------------------------------------------------------
# 用例 2：v1→v2 的 spec_hash 不同、project_id 一致、版本 1/2、规格落盘
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["live", "evidence"])
def test_v1_v2_spec_hash_version_and_project_id(live, ev_chain, source):
    chain = live["chain"] if source == "live" else ev_chain
    v1, v2 = chain["v1"], chain["v2"]
    assert v1["spec_hash"] != v2["spec_hash"], "v1 与 v2 的 spec_hash 必须不同"
    assert v1["project_id"] == v2["project_id"] == chain["project_id"]
    assert v1["spec_version"] == 1
    assert v2["spec_version"] == 2
    assert v2["prev_spec_hash"] == v1["spec_hash"], "v2.prev_spec_hash 应指向 v1"
    assert v1["disk_path"] and v2["disk_path"]


def test_specs_files_landed_on_disk(live):
    """真实规格链必须把 specs/v1.json / specs/v2.json 落盘（供 W 用同一 PLC_WORK_DIR 复现）。"""
    chain = live["chain"]
    specs_dir = Path(chain["specs_dir"])
    assert specs_dir.is_dir()
    assert (specs_dir / "v1.json").is_file()
    assert (specs_dir / "v2.json").is_file()
    assert Path(chain["work_dir"]) == live["work_dir"]
    assert chain["session_id"], "session_id 必须写进产物供 W 复用"
    # 磁盘文件可被产品 load_frozen_spec 独立重建、哈希可复现
    from gateway.app.services.plc.greenfield_service import load_frozen_spec

    # run() 结束后已 restore PLC_WORK_DIR，故显式传 base_dir 指向本次 live 的 work_dir。
    s1 = load_frozen_spec(chain["session_id"], 1, base_dir=live["work_dir"],
                          project_id=chain["project_id"])
    s2 = load_frozen_spec(chain["session_id"], 2, base_dir=live["work_dir"],
                          project_id=chain["project_id"])
    assert s1.spec_hash == chain["v1"]["spec_hash"]
    assert s2.spec_hash == chain["v2"]["spec_hash"]
    assert s1.recompute_hash() == s1.spec_hash
    assert s2.recompute_hash() == s2.spec_hash


# ---------------------------------------------------------------------------
# 用例 3：compute_spec_diff 的 base_spec_version=1 且 changed_source_ids 非空
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["live", "evidence"])
def test_spec_diff_base_version_and_changed_source_ids(live, ev_chain, source):
    chain = live["chain"] if source == "live" else ev_chain
    diff = chain["spec_diff"]
    assert diff["base_spec_version"] == 1
    assert diff["target_spec_version"] == 2
    assert diff["changed_source_ids"], "changed_source_ids 必须非空"
    expected_ids = (set(diff["added"]["source_ids"]) | set(diff["changed"]["source_ids"])
                    | set(diff["removed"]["source_ids"]))
    assert set(diff["changed_source_ids"]) == expected_ids
    assert diff["http_vs_direct_ids_match"] is True, "/diff HTTP 与直调 compute_spec_diff 应一致"
    assert set(["changed", "added", "removed", "changed_source_ids", "base_spec_version"]).issubset(diff.keys())


# ---------------------------------------------------------------------------
# 用例 4：增量 FidelityReport 四指标 + 全字段齐全；六字段齐全
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["live", "evidence"])
def test_incremental_fidelity_metrics_and_full_fields(live, ev_chain, source):
    chain = live["chain"] if source == "live" else ev_chain
    fr = chain["fidelity_report_incremental"]
    # 四指标（契约 14 §3.2）
    assert fr["fidelity_ok"] is True
    assert fr["coverage"] == 1.0
    assert fr["orphan"] == 0
    assert fr["drift"] == 0
    assert fr["tia_side_drift"] == 0
    # 增量口径
    assert fr["mode"] == "incremental"
    assert fr["base_spec_version"] == 1
    assert fr["changed_source_ids"], "增量报告 changed_source_ids 必须非空"
    assert fr["pending_real_machine"] is True
    # to_dict() 全字段齐全
    assert _FIDELITY_REPORT_KEYS.issubset(fr.keys())
    # 真实 artifacts / coverage_matrix 留痕（非 mock 空跑）
    assert fr["coverage_matrix"], "coverage_matrix 应含真实派生产物映射"
    assert fr["product_hash"]
    # 增量 EvidenceBundle 六字段齐全且为真实值
    six = chain["incremental_evidence_bundle_six_fields"]
    assert set(six.keys()) == _SIX_FIELD_KEYS
    assert six["mode"] == "incremental"
    assert six["base_spec_version"] == 1
    assert six["changed_source_ids"]
    assert six["tia_side_drift"] == 0
    assert six["reverse_protection"]["status"] == "pending_real_machine"
    assert six["reverse_protection"]["allowed"] is None


# ---------------------------------------------------------------------------
# 用例 5：ob_number_deviations 必须留痕（禁止静默）
# ---------------------------------------------------------------------------
def test_ob_number_deviations_traced(live):
    fr = live["chain"]["fidelity_report_incremental"]
    assert "ob_number_deviations" in fr, "ob_number_deviations 字段不得静默移除"
    # live 为 asdict 后的 tuple；evidence 文件读回为 list，两者均为合法留痕容器。
    assert isinstance(fr["ob_number_deviations"], (list, tuple))
    notes = " ".join(fr["notes"])
    assert "ob_number_deviations" in notes, "notes 必须显式说明留痕"
    assert "不静默" in notes or "留痕" in notes
    bundle = live["bundle"]
    assert "ob_number_deviations" in bundle["incremental_evidence_bundle_six_fields"]
    assert bundle["ob_number_deviations_note"], "bundle 必须有 ob_number_deviations_note 留痕"


# ---------------------------------------------------------------------------
# 用例 6：bundle_sha256 可复算
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["live", "evidence"])
def test_bundle_sha256_recomputable(live, ev_bundle, source):
    bundle = live["bundle"] if source == "live" else ev_bundle
    recomputed = _recompute_bundle_sha(bundle)
    assert bundle["bundle_sha256"] == recomputed
    assert bundle["bundle_sha256_recomputed"] == recomputed
    assert bundle["bundle_sha256_match"] is True
    # chain 产物内的 bundle_sha256 引用一致（live）
    if source == "live":
        assert live["chain"]["bundle_sha256"] == recomputed
        assert live["chain"]["bundle_sha256_match"] is True


# ---------------------------------------------------------------------------
# 用例 7：离线报告不得宣称真机 L4 通过 / 编译零错误（N9）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["live", "evidence"])
def test_offline_report_never_claims_l4_or_compile_ok(live, ev_chain, ev_bundle, source):
    if source == "live":
        docs = [live["chain"], live["bundle"]]
    else:
        docs = [ev_chain, ev_bundle]
    for doc in docs:
        # 明确的状态字段：离线口径恒为 pending / compile_ok=null
        assert doc.get("compile_ok") is None
        assert doc.get("pending_real_machine") is True
        assert doc.get("offline_side") is True
        # 扫描禁止出现的真机/编译通过断言（只查状态字段，不误伤诚实边界里的否定措辞）
        forbidden_true = {"compile_ok", "m4_signable", "l1_l2_l3_l4_all_green"}
        forbidden_pass = {"l2_status", "l4_status", "layer_status"}
        for key, value in _walk(doc):
            assert not (key in forbidden_true and value is True), f"禁止出现 {key}=True"
            assert not (key in forbidden_pass and value == "pass"), f"禁止出现 {key}=pass"
        # 诚实边界必须明确两条口径
        hb = " ".join(doc.get("honest_boundary") or [])
        assert "离线增量 fidelity" in hb and "真机 L4 通过" in hb
        assert "fidelity_ok" in hb and "compile_ok" in hb
    # 步骤状态词合法，不得出现 l2/l4 pass 之类
    for s in docs[0]["steps"]:
        assert s["status"] in ("pass", "fail", "not_run", "pending_real_machine")


# ---------------------------------------------------------------------------
# 用例 8：repro_commands / work_dir 供 Agent W 复现（接线信息齐全）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["live", "evidence"])
def test_repro_commands_and_w_handoff(live, ev_chain, source):
    chain = live["chain"] if source == "live" else ev_chain
    repro = chain["repro_commands"]
    assert "offline_chain" in repro and "run_incremental_spec_chain.py" in repro["offline_chain"]
    assert "with_work_dir" in repro and "--work-dir" in repro["with_work_dir"]
    assert "agent_w_real_machine_action_c" in repro
    w = repro["agent_w_real_machine_action_c"]
    assert "PLC_WORK_DIR" in w and "/action-c" in w and "confirm-diff" in w
    assert chain["work_dir"] and chain["specs_dir"] and chain["session_id"]
