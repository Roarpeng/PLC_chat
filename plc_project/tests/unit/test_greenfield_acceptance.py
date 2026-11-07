"""WP-10 验收编排器 / 证据台账的不变量单测（Agent I · 纯离线，不连真机）。

验证范围（契约 05 §6 诚实口径 + 任务书不变量）：
- RTM 结构完整、状态词合法、状态计数正确、不得把离线项标 L2/L4 pass；
- EvidenceBundle 全量 12 项 + 增量 6 字段齐全、ob_number_deviations 必须留痕；
- pending 未清零时 M4 判定为未通过（含「台账未清零」的 fail-closed 兜底）；
- 离线模式不得把 L2/L4 标 pass、不得伪造任何执行结果；
- 九步端到端 / 六条增量用例步骤编排数量与留痕齐全；
- F 真机归档结论如实录入、已知基线既有失败排除且不得修复。

本文件只读 evidence/*.json 与 import tools/greenfield_acceptance.py（纯标准库），
不 import 任何产品代码、不启服务、不连 TIA / CLI / HTTP、不跑全量 pytest。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence"
sys.path.insert(0, str(ROOT / "tools"))
import greenfield_acceptance as ga  # noqa: E402  (需先注入 tools 路径)

#: 结构化真机报告白名单。批次 2 为 uc05 总报告；批次 3 按 UC 拆分为独立真机证据
#: 文件。扩展名单只为容纳新增的真机证据，**不放水**：任何标 pass 且非离线口径的
#: UC 仍必须提供 evidence / facts / verified_by / repro_command 四件套，且证据必须
#: 指向下列真实报告之一；离线单测证据仍恒走独立的 offline_unit_test 分支。
REAL_MACHINE_REPORT_REFS = (
    "uc05_real_machine_report.json",       # 批次 2 · Agent M 真机总报告
    "uc04_package_probe.json",             # 批次 3 · Agent R UC-04 包级探针（含真实失败）
    "uc15_step7_real.json",                # 批次 3 · Agent R UC-15 步骤 7 真机
    "uc16_incremental_real.json",          # 批次 3 · Agent R UC-16 六条增量
    "uc18_compile_feedback_real.json",     # 批次 3 · Agent R UC-18 编译回喂
    "uc15_restart_recovery.json",          # 批次 3 · 主 agent 真实服务重启恢复
)


@pytest.fixture(scope="module")
def rtm() -> dict:
    return json.loads((EVIDENCE / "rtm.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tpl() -> dict:
    return json.loads((EVIDENCE / "acceptance_template.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ledger() -> dict:
    return json.loads((EVIDENCE / "pending_real_machine.json").read_text(encoding="utf-8"))


def _all_green_layers() -> dict:
    return {
        l: {"passed": True, "layer_status": "pass", "reason": "test", "ucs": {}}
        for l in ga.FOUR_LAYERS
    }


# ---------------------------------------------------------------------------
# 1. RTM 结构完整
# ---------------------------------------------------------------------------
def test_rtm_structure_complete(rtm):
    check = ga.validate_rtm(rtm)
    assert check["complete"] is True
    assert check["case_count"] == 19
    assert check["expected_case_count"] == 19
    assert check["missing_uc"] == []
    assert check["duplicate_uc"] is False
    assert check["invalid_fields"] == []


def test_rtm_every_uc_has_required_trace_fields(rtm):
    ucs = [c["uc"] for c in rtm["cases"]]
    assert ucs == [f"UC-{i:02d}" for i in range(1, 20)]
    required = (
        "requirement", "source", "work_package", "owner", "gate", "layer",
        "evidence_artifacts", "status", "notes",
    )
    for c in rtm["cases"]:
        for f in required:
            assert f in c, f"{c['uc']} 缺字段 {f}"
        assert c["evidence_artifacts"], f"{c['uc']} 缺证据产物"
        assert c["status"] in ga.VALID_STATUSES


def test_rtm_status_counts_and_no_fake_pass(rtm):
    counts = ga.validate_rtm(rtm)["counts"]
    # 计数与 summary 必须自洽，总数恒为 19；不锁死某一轮的具体分布，
    # 否则每次真机实测后状态迁移都要改测试（收口阶段已发生一次）。
    assert sum(counts.values()) == rtm["summary"]["case_count"] == 19
    assert counts.get("fail", 0) == 0
    # counts 按实际出现的状态聚合，可能省略 0 值状态；逐项比对避免键集合差异误判
    for status, expected in rtm["summary"]["by_status"].items():
        assert counts.get(status, 0) == expected, f"{status} 计数不一致"
    # 核心防伪造：任何标 pass 的用例必须带证据 + 复现命令，杜绝「无证据冒充通过」。
    # 两类证据严格区分口径，不得互相冒充（Agent N 离线证据复核后的最小同步）：
    #   - 真机 pass：真机证据三件套 + 指向结构化真机报告（uc05_real_machine_report.json）
    #   - 离线 pass：evidence_kind=offline_unit_test + 离线单测四要素 + caveat 边界声明，
    #                且绝不允许挂真机证据（离线单测不得冒充真机 L2/L4 通过）
    for c in rtm["cases"]:
        if c["status"] != "pass":
            continue
        assert c.get("repro_command"), f"{c['uc']} 标 pass 但无复现命令"
        if c.get("evidence_kind") == "offline_unit_test":
            assert c.get("offline_evidence"), f"{c['uc']} 离线 pass 但无离线单测证据"
            assert c.get("offline_verified_by"), f"{c['uc']} 离线 pass 但无复核主体"
            caveat = c.get("caveat", "")
            assert "真机" in caveat and "M4" in caveat, (
                f"{c['uc']} 离线 pass 的 caveat 未声明『不等同真机通过 / 不使 M4 可签署』边界"
            )
            assert not c.get("real_machine_evidence"), (
                f"{c['uc']} 离线单测 pass 不得挂真机证据冒充"
            )
        else:
            assert c.get("real_machine_evidence"), f"{c['uc']} 标 pass 但无真机证据"
            assert c.get("real_machine_facts"), f"{c['uc']} 标 pass 但无真机事实"
            assert c.get("verified_by"), f"{c['uc']} 标 pass 但无验证主体"
            assert any(ref in c["real_machine_evidence"] for ref in REAL_MACHINE_REPORT_REFS), (
                f"{c['uc']} 的真机证据未指向任何结构化真机报告"
            )
    # 涉 L2/L4 但无真机证据的用例绝不允许标 pass（离线单测不得用于真机层）
    for c in rtm["cases"]:
        if ("L2" in c["layers"] or "L4" in c["layers"]) and not c.get("real_machine_evidence"):
            assert c["status"] != "pass", f"{c['uc']} 涉真机却无证据标 pass"


def test_rtm_f_real_machine_facts_are_recorded_honestly(rtm):
    facts = rtm["gate0_facts"]
    assert facts["four_piece_precheck"]["status"] == "pass"
    assert "4/4" in facts["four_piece_precheck"]["detail"]
    uc01 = facts["uc01_folder_compile"]
    assert uc01["status"] == "pass"
    assert "errorCount=0" in uc01["detail"]
    # 必须保留 F 的诚实限定：分组编译 != 端到端零错误
    assert "端到端" in uc01["caveat"] or "UC-15" in uc01["caveat"]
    # 真实编译失败不得被抹成零错误
    assert facts["uc01_ob_number_real_precedent_compile"]["status"] == "fail"
    assert "errorCount=30" in facts["uc01_ob_number_real_precedent_compile"]["detail"]
    # UC-04 K1 失败如实录入；主状态仍按 F 口径为 pending_real_machine（待复测）
    assert facts["uc04_k1_probe"]["status"] == "fail"
    assert "openness_error" in facts["uc04_k1_probe"]["detail"]
    uc04 = next(c for c in rtm["cases"] if c["uc"] == "UC-04")
    assert uc04["status"] == "pending_real_machine"
    assert any(s["status"] == "fail" for s in uc04["sub_checks"])
    assert facts["gate0_verdict"]["status"] == "conditional-go"
    assert facts["p0d_recommendation"]["status"] == "pending_user_decision"


def test_known_baseline_failure_excluded_and_not_fixed(rtm):
    ex = rtm["baseline_exclusions"]
    assert len(ex) >= 1
    e = ex[0]
    assert e["test"] == "test_af_import.py::test_hr001_real_import_roles_and_freeze"
    assert e["status"] == "preexisting_baseline_failure"
    assert "f9d4a3d" in e["evidence"]
    assert "排除" in e["policy"] and "不得修复" in e["policy"]


def test_pending_ledger_matches_rtm(rtm, ledger):
    pending = ga.collect_pending_ucs(rtm)
    assert len(pending) == rtm["summary"]["by_status"]["pending_real_machine"]
    assert pending == rtm["summary"]["pending_uc_ids"]
    assert pending, "M4 门禁要求 pending 台账在清零前必须非空"
    # 台账按 M4 门禁保留历史项（已通过的 UC 不删、cleared 仍 false），
    # 因此要求覆盖当前所有 pending UC，而非严格相等。
    assert set(pending) <= {i["id"] for i in ledger["items"]}, "台账漏记 pending UC"
    assert ledger["cleared"] is False


# ---------------------------------------------------------------------------
# 2. EvidenceBundle 字段齐全 / ob_number_deviations 必须留痕
# ---------------------------------------------------------------------------
def test_evidence_template_full_artifacts_complete(tpl):
    check = ga.validate_evidence_template(tpl)
    assert check["complete"] is True
    assert check["full_count"] == 12
    assert check["expected_full_count"] == 12
    assert check["missing_full"] == []
    ids = {a["id"] for a in tpl["full_artifacts"]}
    assert ids == set(ga.EXPECTED_FULL_ARTIFACTS)
    # .zap19 / 结构化编译报告 / PCEC / baseline_manifest / 产物哈希 必须在列
    for key in ("zap19_archive", "structured_compile_report", "pcec_ledger",
                "baseline_manifest_json", "artifact_hashes", "fidelity_report_json"):
        assert key in ids


def test_evidence_template_incremental_fields_complete(tpl):
    check = ga.validate_evidence_template(tpl)
    assert check["incremental_count"] == 6
    assert check["expected_incremental_count"] == 6
    assert check["missing_incremental"] == []
    names = [f["name"] for f in tpl["incremental_fields"]]
    assert names == list(ga.EXPECTED_INCREMENTAL_FIELDS)
    for f in tpl["incremental_fields"]:
        assert f["required"] is True


def test_ob_number_deviations_must_be_traced_not_silenced(tpl):
    check = ga.validate_evidence_template(tpl)
    assert check["ob_number_deviations_present"] is True
    assert check["ob_number_deviations_policy_ok"] is True
    policy = tpl["ob_number_deviations_policy"]
    assert "必须留痕" in policy or "禁止静默" in policy
    assert "ob_number_deviations" in policy
    # 属不纳入 1:1 的域，不得据此判 L1/L2 通过
    ob = next(f for f in tpl["incremental_fields"] if f["name"] == "ob_number_deviations")
    assert "必须留痕" in ob["note"] or "禁止静默" in ob["note"]
    assert "不纳入" in policy or "不参与" in policy


def test_n9_independence_declared(tpl):
    assert tpl["n9_independence"]
    assert "独立" in tpl["n9_independence"]


# ---------------------------------------------------------------------------
# 3. pending 未清零时 M4 判定为未通过
# ---------------------------------------------------------------------------
def test_m4_fails_when_pending_not_cleared(rtm, ledger):
    m4 = ga.evaluate_m4(
        _all_green_layers(), ga.collect_pending_ucs(rtm), ledger, evidence_complete=True
    )
    assert m4["m4_pass"] is False
    assert m4["m4_signable"] is False
    assert m4["verdict"] == "M4 未通过"
    assert any("pending" in r for r in m4["reasons"])


def test_m4_fails_when_ledger_not_cleared_even_if_no_pending_ids(ledger):
    # 防绕过：即使传入空 pending_ids，台账 cleared=false / items 非空仍必须拦住 M4
    m4 = ga.evaluate_m4(_all_green_layers(), [], ledger, evidence_complete=True)
    assert m4["m4_pass"] is False
    assert m4["pending_cleared"] is False


def test_m4_pass_only_when_all_conditions_met():
    clean_ledger = {"cleared": True, "items": []}
    m4 = ga.evaluate_m4(_all_green_layers(), [], clean_ledger, evidence_complete=True)
    assert m4["m4_pass"] is True
    assert m4["m4_signable"] is True
    assert m4["verdict"] == "M4 通过 / 可签署"


def test_check_pending_cleared_truth_table():
    assert ga.check_pending_cleared({"cleared": True, "items": []}, [])["cleared"] is True
    assert ga.check_pending_cleared({"cleared": True, "items": []}, ["UC-01"])["cleared"] is False
    assert ga.check_pending_cleared({"cleared": False, "items": []}, [])["cleared"] is False
    assert ga.check_pending_cleared({"cleared": True, "items": [{"id": "UC-01"}]}, [])["cleared"] is False


def test_offline_full_report_m4_not_pass(rtm, ledger):
    report = ga.build_report("offline", None, 1.0)
    assert report["m4"]["m4_pass"] is False
    assert report["m4"]["verdict"] == "M4 未通过"
    assert report["m4"]["pending_cleared"] is False
    assert report["pending"]["count"] == rtm["summary"]["by_status"]["pending_real_machine"]
    assert report["l1_l4_verdict"] == "未全绿"
    assert report["evidence_bundle"]["complete"] is False


# ---------------------------------------------------------------------------
# 4. 离线模式不得把 L2/L4 标 pass / 不得伪造结果
# ---------------------------------------------------------------------------
def test_offline_never_marks_l2_l4_pass(rtm):
    layers = ga.aggregate_layers(rtm, "offline")
    for l in ("L2", "L4"):
        assert layers[l]["passed"] is False
        assert layers[l]["layer_status"] == "pending_real_machine"
        assert "禁止" in layers[l]["reason"]
    # 无论 RTM 里 L2/L4 用例状态如何，离线聚合都不得出现 pass 层结论
    report = ga.build_report("offline", None, 1.0)
    assert report["l1_l4_recheck"]["L2"] is False
    assert report["l1_l4_recheck"]["L4"] is False


def test_offline_report_never_fakes_execution_results():
    report = ga.build_report("offline", None, 1.0)
    steps = report["step_records"]
    assert len(steps) == 15
    statuses = {s["status"] for s in steps}
    # 绝不允许编排步骤出现 pass / fail 这类「已执行」结论
    assert statuses <= {"not_run", "pending_real_machine"}
    assert "pass" not in statuses and "fail" not in statuses
    for s in steps:
        assert s["repro_command"].strip(), f"{s['id']} 缺复现命令"
        assert s["evidence_artifacts"]
        assert s["note"]
    # 真机步骤必须是 pending_real_machine，离线可编排步骤必须是 not_run
    for s in steps:
        if s["requires"] == "real_machine":
            assert s["status"] == "pending_real_machine"
        else:
            assert s["status"] == "not_run"


def test_offline_report_contains_no_fake_compile_numbers():
    report = ga.build_report("offline", None, 1.0)
    # 编排器绝不自行产生编译/导入结果：报告顶层不得出现任何编译结果字段
    for key in ("compile_ok", "error_count", "compile_diagnostics", "fidelity_ok", "errorCount"):
        assert key not in report
    assert report["m4"]["verdict"] == "M4 未通过"
    # 步骤描述可引用 §9.2 / §13.9 原文，但状态不得是「已执行」结论
    assert all(
        s["status"] in ("not_run", "pending_real_machine") for s in report["step_records"]
    )


# ---------------------------------------------------------------------------
# 5. 步骤编排数量与留痕
# ---------------------------------------------------------------------------
def test_step_orchestration_counts_and_ids():
    assert len(ga.NINE_STEPS) == 9
    assert len(ga.SIX_INCREMENTAL_CASES) == 6
    nine_ids = [s["id"] for s in ga.NINE_STEPS]
    inc_ids = [s["id"] for s in ga.SIX_INCREMENTAL_CASES]
    assert nine_ids == [f"NINE-{i:02d}" for i in range(1, 10)]
    assert inc_ids == [f"INC-{i:02d}" for i in range(1, 7)]
    recs = ga.build_step_records("offline", None)
    assert len(recs) == 15
    assert len({r["id"] for r in recs}) == 15
    assert {r["group"] for r in recs} == {"nine_steps", "six_incremental_cases"}
    assert all(r["uc"] == "UC-15" for r in recs if r["group"] == "nine_steps")
    assert all(r["uc"] == "UC-16" for r in recs if r["group"] == "six_incremental_cases")


# ---------------------------------------------------------------------------
# 6. 真机模式护栏（fail-closed，不连真机）
# ---------------------------------------------------------------------------
def test_validate_workdir_rejects_unsafe_paths():
    assert ga.validate_workdir(None)["allowed"] is False
    assert ga.validate_workdir(
        "C:/Users/vboxuser/Desktop/PLC_Openness_data/openness_e2e/CanvasE2E.ap19"
    )["allowed"] is False
    assert ga.validate_workdir("C:/projects/CanvasE2E.ap19")["allowed"] is False
    ok = ga.validate_workdir(
        "C:/Users/vboxuser/AppData/Local/Temp/gf_real_wp10/proj/CanvasE2E.ap19"
    )
    assert ok["allowed"] is True


def test_real_machine_mode_fail_closed_without_workdir():
    # 不带 workdir -> 直接 fail-closed 返回，绝不调用探针 / 真机
    report = ga.build_report("real_machine", None, 1.0)
    assert report.get("error")
    assert report["workdir_check"]["allowed"] is False
    assert report["m4"]["m4_pass"] is False
    assert "probe" not in report  # 未执行任何真机探针


def test_sync_ledger_is_idempotent_and_never_clears(tmp_path):
    ledger_path = tmp_path / "pending_real_machine.json"
    base = {"cleared": False, "items": []}
    ledger_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    ids = ["UC-01", "UC-02"]
    first = ga.sync_ledger(base, ids, ledger_path)
    assert first["added"] == ids
    after = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert len(after["items"]) == 2
    assert after["cleared"] is False
    second = ga.sync_ledger(after, ids, ledger_path)
    assert second["added"] == []
    assert second["written"] is False
    assert len(json.loads(ledger_path.read_text(encoding="utf-8"))["items"]) == 2


# ---------------------------------------------------------------------------
# 7. Q3 新增：--evidence-bundle / --step-run / 签署权收口（保留以上全部不变量）
# ---------------------------------------------------------------------------
def _full_mock_bundle() -> dict:
    """全项齐备的证据包（单测 mock，仅用于验证 validate_evidence_bundle 真值表）。"""
    return {
        "artifacts": {
            a: {"present": True, "evidence_ref": f"mock://full/{a}"}
            for a in ga.EXPECTED_FULL_ARTIFACTS
        },
        "incremental_fields": {
            f: {"present": True, "evidence_ref": f"mock://inc/{f}", "value": "mock"}
            for f in ga.EXPECTED_INCREMENTAL_FIELDS
        },
    }


def _write(tmp_path: Path, name: str, payload: dict) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _fake_run_doc_all_pass() -> dict:
    """伪造的 step-run：所有九步与六增量一律标 pass（用于验证真机项强制 pending）。"""
    steps = [
        {"step_id": f"NINE-{i:02d}", "status": "pass", "response": {"fake": True},
         "evidence_refs": [], "note": "fake"}
        for i in range(1, 10)
    ] + [
        {"step_id": f"INC-{i:02d}", "status": "pass", "response": {"fake": True},
         "evidence_refs": [], "note": "fake"}
        for i in range(1, 7)
    ]
    return {"steps": steps}


def test_validate_evidence_bundle_all_present_is_complete_true():
    check = ga.validate_evidence_bundle(_full_mock_bundle())
    assert check["complete"] is True
    assert check["missing_full"] == []
    assert check["missing_incremental"] == []
    assert check["full_present"] == 12
    assert check["incremental_present"] == 6


def test_validate_evidence_bundle_missing_artifact_is_false():
    bundle = _full_mock_bundle()
    del bundle["artifacts"]["zap19_archive"]
    check = ga.validate_evidence_bundle(bundle)
    assert check["complete"] is False
    assert "zap19_archive" in check["missing_full"]


def test_validate_evidence_bundle_missing_incremental_is_false():
    bundle = _full_mock_bundle()
    del bundle["incremental_fields"]["tia_side_drift"]
    check = ga.validate_evidence_bundle(bundle)
    assert check["complete"] is False
    assert "tia_side_drift" in check["missing_incremental"]


def test_validate_evidence_bundle_rejects_fake_data_without_ref():
    # 只挂 present=True 不挂真实证据引用 = 假数据，必须判缺（不放水）
    bundle = _full_mock_bundle()
    bundle["artifacts"]["zap19_archive"] = {"present": True}
    check = ga.validate_evidence_bundle(bundle)
    assert check["complete"] is False
    assert "zap19_archive" in check["missing_full"]


def test_validate_evidence_bundle_none_is_fail_closed():
    check = ga.validate_evidence_bundle(None)
    assert check["complete"] is False
    assert len(check["missing_full"]) == 12
    assert len(check["missing_incremental"]) == 6


def test_evidence_bundle_missing_drives_evidence_complete_false(tmp_path):
    bundle = _full_mock_bundle()
    del bundle["artifacts"]["structured_compile_report"]
    path = _write(tmp_path, "bundle_missing.json", bundle)
    report = ga.build_report("offline", None, 1.0, evidence_bundle_path=path)
    assert report["m4"]["evidence_complete"] is False
    assert report["m4"]["m4_pass"] is False
    assert report["m4"]["verdict"] == "M4 未通过"
    assert report["evidence_bundle"]["complete"] is False
    assert "structured_compile_report" in report["evidence_bundle"]["validation"]["missing_full"]


def test_evidence_bundle_missing_file_is_fail_closed(tmp_path):
    report = ga.build_report(
        "offline", None, 1.0,
        evidence_bundle_path=str(tmp_path / "does_not_exist.json"),
    )
    assert report["m4"]["evidence_complete"] is False
    assert report["evidence_bundle"]["validation"]["complete"] is False
    assert report["m4"]["verdict"] == "M4 未通过"


def test_evidence_bundle_all_present_evidence_complete_true_but_m4_still_not_pass(tmp_path):
    """全项齐备时 evidence_complete 才可能为 True；但 M4 仍不放行、不得代签。"""
    path = _write(tmp_path, "bundle_full.json", _full_mock_bundle())
    report = ga.build_report("offline", None, 1.0, evidence_bundle_path=path)
    assert report["m4"]["evidence_complete"] is True
    assert report["evidence_bundle"]["complete"] is True
    # pending 未清零 + L2/L4 离线强制 pending → M4 仍不得通过
    assert report["m4"]["m4_pass"] is False
    assert report["m4"]["verdict"] == "M4 未通过"
    assert report["m4"]["m4_signable"] is False
    assert report["requires_user_signoff"] is True
    assert report["l1_l4_recheck"]["L2"] is False
    assert report["l1_l4_recheck"]["L4"] is False


def test_step_run_never_marks_real_machine_steps_pass(tmp_path):
    path = _write(tmp_path, "run_all_pass.json", _fake_run_doc_all_pass())
    report = ga.build_report("offline", None, 1.0, step_run_path=path)
    recs = {r["id"]: r for r in report["step_records"]}
    # 步骤 7 与六条增量真机项恒 pending，即便 step-run 伪造 pass
    assert recs["NINE-07"]["status"] == "pending_real_machine"
    for i in range(1, 7):
        assert recs[f"INC-{i:02d}"]["status"] == "pending_real_machine"
    # 离线步骤的真实结果确实被合入（替换 not_run 占位）
    assert recs["NINE-01"]["status"] == "pass"
    assert recs["NINE-01"]["response"] == {"fake": True}
    assert report["step_summary"]["step_run_merged"]["nine_steps_merged"] == 8
    # 合入后 L2/L4 仍强制 pending、M4 仍不得通过
    assert report["l1_l4_recheck"]["L2"] is False
    assert report["l1_l4_recheck"]["L4"] is False
    assert report["m4"]["verdict"] == "M4 未通过"


def test_requires_user_signoff_always_true():
    r_off = ga.build_report("offline", None, 1.0)
    assert r_off["requires_user_signoff"] is True
    assert r_off["m4"]["m4_signable"] is False
    # real_machine 无 workdir 的 fail-closed early return 也必须带该字段
    r_rm = ga.build_report("real_machine", None, 1.0)
    assert r_rm["requires_user_signoff"] is True
    assert r_rm["m4"]["m4_signable"] is False
    assert r_rm.get("error")


def test_finalize_m4_never_signable_even_if_all_green():
    clean_ledger = {"cleared": True, "items": []}
    raw = ga.evaluate_m4(_all_green_layers(), [], clean_ledger, evidence_complete=True)
    assert raw["m4_pass"] is True  # 纯函数真值表保持不变
    out = ga.finalize_m4(raw)
    assert out["m4_signable"] is False
    assert out["requires_user_signoff"] is True
    assert out["signoff_owner"] == "用户本人"
    assert "可签署" not in out["verdict"]
    assert "待用户签署" in out["verdict"]


def test_offline_default_m4_not_pass():
    report = ga.build_report("offline", None, 1.0)
    assert report["m4"]["verdict"] == "M4 未通过"
    assert report["m4"]["m4_pass"] is False
    assert report["m4"]["evidence_complete"] is False
    assert report["m4"]["m4_signable"] is False
    assert report["requires_user_signoff"] is True
    assert report["evidence_bundle"]["complete"] is False
    # 默认不带 --step-run：步骤仍为 not_run / pending_real_machine（向后兼容）
    assert {s["status"] for s in report["step_records"]} <= {"not_run", "pending_real_machine"}


def test_print_summary_states_signoff_belongs_to_user(capsys):
    ga.print_summary(ga.build_report("offline", None, 1.0))
    err = capsys.readouterr().err
    assert "M4 签署权归用户，工具不得代签" in err
    assert "M4 未通过" in err
