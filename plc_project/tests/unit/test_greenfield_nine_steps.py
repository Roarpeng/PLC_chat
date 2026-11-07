"""Agent Q · §9.2 九步离线链 / UC-15 EvidenceBundle 的结构与真实性单测。

用 ``tools/run_nine_steps.py`` 的 ``run()`` 在 tmp_path 内以 TestClient（进程内 ASGI）
真跑一遍九步，验证：
- 九步结构完整、步骤 7 恒 pending_real_machine、每步有 repro_command / 原始响应关键字段；
- 产物 JSON schema（steps / summary / generated_at / driver / honest_note）；
- EvidenceBundle 的 bundle_sha256 可离线复算、12 项工件齐备情况如实、缺项不补假数据；
- 不以离线单测宣称 L2/L4 通过 / 编译零错误 / M4 通过或代签。

单测全程 mock / TestClient，不连真机、不启动 SessionServer、不占用任何端口。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import run_nine_steps as rns  # noqa: E402  (需先注入 tools 路径)
from plc_engine.af.spec_diff import canonical_hash  # noqa: E402

VALID_STATUSES = {"pass", "fail", "not_run", "pending_real_machine"}
OFFLINE_STEP_IDS = {"NINE-01", "NINE-02", "NINE-03", "NINE-04",
                    "NINE-05", "NINE-06", "NINE-08", "NINE-09"}


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    """在临时目录真跑一次九步驱动，产物不写入项目 evidence/。"""
    d = tmp_path_factory.mktemp("gf_nine")
    out = d / "nine_steps_offline_run.json"
    bundle = d / "uc15_evidence_bundle.json"
    doc = rns.run(out, bundle, work_dir=str(d / "work"))
    return {
        "doc": doc,
        "out": out,
        "bundle_path": bundle,
        "nine": json.loads(out.read_text(encoding="utf-8")),
        "bundle": json.loads(bundle.read_text(encoding="utf-8")),
    }


# ---------------------------------------------------------------------------
# 1. 九步运行产物结构
# ---------------------------------------------------------------------------
def test_nine_steps_structure_complete(artifacts):
    steps = artifacts["nine"]["steps"]
    assert len(steps) == 9
    assert [s["step_id"] for s in steps] == [f"NINE-{i:02d}" for i in range(1, 10)]
    required = ("step_id", "name", "endpoint", "request_summary", "response",
                "status", "evidence_refs", "repro_command", "note")
    for s in steps:
        for f in required:
            assert f in s, f"{s['step_id']} 缺字段 {f}"
        assert s["status"] in VALID_STATUSES
        assert s["repro_command"].strip(), f"{s['step_id']} 缺复现命令"
        assert s["endpoint"].strip()
        assert s["note"].strip()
        assert isinstance(s["response"], dict) and s["response"], (
            f"{s['step_id']} 缺原始响应关键字段"
        )


def test_step7_always_pending_real_machine_and_never_fakes_compile(artifacts):
    s7 = next(s for s in artifacts["nine"]["steps"] if s["step_id"] == "NINE-07")
    assert s7["status"] == "pending_real_machine"
    assert s7["response"]["executed"] is False
    assert s7["response"]["compile_ok"] is None
    # 绝不伪造任何编译结果字段
    for k in ("error_count", "compile_diagnostics", "warnings", "blocks", "errorCount"):
        assert k not in s7["response"]
    assert "真机" in (s7["note"] + s7["repro_command"])
    assert artifacts["nine"]["step7_pending_real_machine"] is True


def test_offline_steps_are_really_driven_not_not_run(artifacts):
    steps = {s["step_id"]: s for s in artifacts["nine"]["steps"]}
    # 离线可跑的 8 步必须被真实驱动（不是 not_run 占位）
    for sid in OFFLINE_STEP_IDS:
        assert steps[sid]["status"] != "not_run", f"{sid} 仍是 not_run 占位"
    # 步骤 5 真实留痕 fidelity_ok / evidence_bundle_sha256
    r5 = steps["NINE-05"]["response"]
    assert r5["fidelity_ok"] is True
    assert r5["compile_ok"] is None  # N9：A 不产出编译结论
    assert r5["bundle_sha256_match"] is True
    # 步骤 6 两个负例真实留痕
    r6 = steps["NINE-06"]["response"]
    assert r6["negative_a"]["fidelity_ok"] is False
    assert r6["negative_a"]["unmapped_spec_objects"]
    assert r6["negative_b"]["fidelity_ok"] is False
    assert r6["negative_b"]["orphan"] == 1
    # 步骤 8 / 9 真实哈希比对
    assert steps["NINE-08"]["response"]["evidence_bundle_sha256_equal"] is True
    assert steps["NINE-09"]["response"]["spec_hash_equal"] is True
    assert steps["NINE-09"]["response"]["ir_snapshot_equal"] is True


def test_summary_counts_consistent(artifacts):
    nine = artifacts["nine"]
    by_status = nine["summary"]["by_status"]
    assert nine["summary"]["total"] == 9
    assert sum(by_status.values()) == 9
    assert by_status.get("pending_real_machine", 0) >= 1
    actual: dict = {}
    for s in nine["steps"]:
        actual[s["status"]] = actual.get(s["status"], 0) + 1
    for k, v in actual.items():
        assert by_status.get(k, 0) == v, f"{k} 计数不一致"


def test_nine_json_schema_and_honest_note(artifacts):
    nine = artifacts["nine"]
    for key in ("schema", "uc", "generated_at", "driver", "steps", "summary",
                "honest_note", "project_id", "step7_pending_real_machine"):
        assert key in nine
    assert nine["schema"] == "gf-nine-steps-offline-run-v1"
    assert nine["uc"] == "UC-15"
    h = nine["honest_note"]
    assert "fidelity_ok" in h and "compile_ok" in h
    assert "pending_real_machine" in h
    assert "不得代签" in h or "M4 签署权归用户" in h
    assert "编译零错误" in h  # 明确声明「不得宣称」
    assert "L2" in h or "L4" in h
    d = nine["driver"]
    assert "TestClient" in d
    assert "进程内 ASGI" in d
    assert "不启动任何监听端口" in d


# ---------------------------------------------------------------------------
# 2. UC-15 EvidenceBundle 离线实例化产物
# ---------------------------------------------------------------------------
def test_evidence_bundle_schema(artifacts):
    b = artifacts["bundle"]
    for key in ("schema", "bundle_id", "generated_at", "source", "project_id",
                "fidelity_ok", "compile_ok", "bundle_sha256", "bundle_sha256_recomputed",
                "bundle_sha256_match", "artifacts", "incremental_fields",
                "missing_artifacts", "missing_incremental_fields",
                "evidence_bundle_raw", "gap_note", "honest_note"):
        assert key in b, f"EvidenceBundle 缺 {key}"
    assert b["schema"] == "gf-uc15-evidence-instance-v1"
    assert b["fidelity_ok"] is True
    assert b["compile_ok"] is None  # N9
    assert b["tia_written"] is False
    assert b["pending_real_machine"] is True
    assert b["bundle_sha256_match"] is True
    assert b["full_artifacts_expected"] == 12
    assert b["full_artifacts_present"] == 9


def test_bundle_sha256_is_recomputable(artifacts):
    b = artifacts["bundle"]
    raw = b["evidence_bundle_raw"]
    body = {k: v for k, v in raw.items()
            if k not in ("bundle_sha256", "package_zip_base64")}
    recomputed = canonical_hash(body)
    assert recomputed == b["bundle_sha256"] == raw["bundle_sha256"]
    assert recomputed == b["bundle_sha256_recomputed"]


def test_bundle_12_artifacts_and_missing_are_honest(artifacts):
    tpl = json.loads((ROOT / "evidence" / "acceptance_template.json").read_text(encoding="utf-8"))
    tpl_ids = {a["id"] for a in tpl["full_artifacts"]}
    assert len(tpl_ids) == 12
    b = artifacts["bundle"]
    assert set(b["artifacts"]) == tpl_ids
    # 3 项真机工件如实列出，不补假数据
    assert b["missing_artifacts"] == [
        "structured_compile_report", "pcec_ledger", "zap19_archive"
    ]
    for m in b["missing_artifacts"]:
        entry = b["artifacts"][m]
        assert entry["present"] is False
        assert not entry["evidence_ref"]
        assert "real_machine" in entry["source"]
    for a in tpl_ids - set(b["missing_artifacts"]):
        entry = b["artifacts"][a]
        assert entry["present"] is True
        assert entry["evidence_ref"].strip()
    # 步骤 7 真机编译报告缺口说明
    assert "R" in b["gap_note"] and ("补齐" in b["gap_note"] or "步骤 7" in b["gap_note"])


def test_bundle_incremental_fields_present_with_boundary_note(artifacts):
    b = artifacts["bundle"]
    assert set(b["incremental_fields"]) == set(rns._INCREMENTAL_MAP)
    assert len(b["incremental_fields"]) == 6
    assert b["missing_incremental_fields"] == []
    for name, entry in b["incremental_fields"].items():
        assert entry["present"] is True
        assert entry["evidence_ref"].strip()
        assert "UC-16" in entry["note"] or "非 incremental" in entry["note"]
    # 不宣称 M4 / 真机通过
    assert "不得代签" in b["honest_note"] or "不构成 M4 通过" in b["honest_note"]
    assert "编译零错误" in b["honest_note"]
