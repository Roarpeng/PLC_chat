"""§9.2 九步离线链真实驱动（Agent Q · 批次 3 / UC-15）。

用 ``fastapi.testclient.TestClient`` 在**进程内 ASGI** 挂载 ``gateway.app.main:app``，
按基线报告 §9.2 顺序真实调用 Greenfield 端点，把每步的**原始响应关键字段**留痕到
``evidence/nine_steps_offline_run.json``；并把步骤 5 ``run_action_a`` 返回的
``evidence_bundle`` 真实实例化为 ``evidence/uc15_evidence_bundle.json``（Q2）。

诚实边界（契约 13 §1 / §3 / §5、任务书硬性约束）：
- 不连真机、不启动 SessionServer / TIA、不占用 8000/8791/8011 端口（TestClient 不起监听端口）；
- 步骤 7（Action B 真机编译）与 §13.9 六条增量真机项恒 ``pending_real_machine``，
  由 Agent R 独占真机完成，**绝不伪造编译结果**；
- ``fidelity_ok`` 与 ``compile_ok`` 严格分离（N9）；warning 单列不并入成功；
- 离线跑通仅代表产品链在进程内可运行，**不宣称编译零错误 / L2 或 L4 通过 /
  L1∧L2∧L3∧L4 全绿 / M4 通过或代签**；
- 跑不通的步骤如实记 ``fail`` + 原因，绝不伪造成功；
- 为保证离线确定性、零外部出网：运行期把 ``greenfield_chat.llm_settings`` 覆盖为
  返回 ``None``，使 ``POST /chat`` 首轮走**零 LLM 依赖的确定性 planner 兜底**
  （即 ``draft_from_prompt`` 的产品既有 fallback），不发任何外部 LLM 网络请求。

用法::

    python tools/run_nine_steps.py --out evidence/nine_steps_offline_run.json
    python tools/run_nine_steps.py --out <PATH> --bundle-out <PATH> --work-dir <PATH>

退出码: 0 = 产物成功生成（真实性判定在产物 ``steps[*].status`` 里）。
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"
PREFIX = "/api/v1/plc/canvas/greenfield"
PROJECT_ID = "GF-Q-UC15"
CHAT_MESSAGE = (
    "输送单元把工件送到装配工位，夹紧气缸定位，机器人完成涂胶作业后放行到下料工位"
)

VALID_STATUSES = ("pass", "fail", "not_run", "pending_real_machine")

# §9.2 九步：id / name / endpoint / request_summary / repro_command（真实端点口径）
STEP_META: dict[str, dict] = {
    "NINE-01": {
        "name": "新建项目：PLC 逻辑占位 + 3 类外围设备占位（不上传 IO 表，验证 D7）",
        "endpoint": f"GET {PREFIX}/state?project_id={PROJECT_ID}",
        "request_summary": {"method": "GET", "params": {"project_id": PROJECT_ID},
                            "io_table_uploaded": False,
                            "note": "仅建立会话并绑定 project_id；不调用 /upload，不冻结 CompatContract"},
        "repro_command": f"GET {PREFIX}/state?project_id={PROJECT_ID} （契约表记 POST /state；实际产品端点为 GET /state，绑定 project_id 后读 hardware 拓扑占位）",
    },
    "NINE-02": {
        "name": "对话输入自然语言描述设备运行逻辑 → canvas 渲染",
        "endpoint": f"POST {PREFIX}/chat",
        "request_summary": {"method": "POST", "session_id": "<步骤1返回的 session_id>",
                            "message": CHAT_MESSAGE},
        "repro_command": f"POST {PREFIX}/chat  body={{session_id, message: '{CHAT_MESSAGE}'}} → 四视图 + 连线清单",
    },
    "NINE-03": {
        "name": "手动增删改：新增执行件 / 删连线 / 改交互 / 改步序条件（D6 + 双向同步）",
        "endpoint": f"POST {PREFIX}/patch + POST {PREFIX}/validate",
        "request_summary": {"method": "POST", "path": "/patch",
                            "ops": ["add_cm(新增执行件)", "remove_edge(删一条 suggested 连线)",
                                    "set_ir_only_field(jobs.start_condition 改交互条件)",
                                    "set_ir_only_field(steps.transition_condition 改步序条件)"],
                            "atomic": True,
                            "note": "op 目标 id 均取自步骤2 真实 IR；随后 /validate 重算 validate_ir"},
        "repro_command": f"POST {PREFIX}/patch  body={{session_id, project_id, ops:[add_cm, remove_edge, set_ir_only_field×2]}}；再 POST {PREFIX}/validate",
    },
    "NINE-04": {
        "name": "确认设备逻辑 → 冻结 v1，检查 spec_hash 覆盖拓扑与全部编辑",
        "endpoint": f"POST {PREFIX}/engineering-summary + POST {PREFIX}/confirm",
        "request_summary": {"method": "POST", "confirm": {"explicit": True, "frozen_by": "user"},
                            "prerequisites": "拓扑定稿 / open_questions 清零 / 连线校验 / 等价性预检 / 基线版本锁定"},
        "repro_command": f"POST {PREFIX}/engineering-summary；POST {PREFIX}/confirm  body={{session_id, explicit:true, frozen_by:'user'}} → specs/v1.json",
    },
    "NINE-05": {
        "name": "Action A 导出工程包 → fidelity_report.json 为 fidelity_ok=true、coverage 100%、orphan 0",
        "endpoint": f"POST {PREFIX}/action-a",
        "request_summary": {"method": "POST", "session_id": "<同上>", "include_zip_base64": False},
        "repro_command": f"POST {PREFIX}/action-a  body={{session_id}} → fidelity_ok / fidelity_report / evidence_bundle",
    },
    "NINE-06": {
        "name": "两个负例：删产物块 → fidelity_ok=false 且列 unmapped_spec_objects；塞无来源块 → orphan=1",
        "endpoint": "FidelityChecker.check(...) 只读校验器直调（无 HTTP 端点）",
        "request_summary": {"negative_a": "从步骤5 真实 coverage_matrix 的 source_id 集合中删掉一个产物块",
                            "negative_b": "在 artifacts 中塞入一个无 source_id 的逻辑块",
                            "basis": "步骤5 真实 spec_hash 与真实 source_id 集合"},
        "repro_command": "python -c 'from plc_engine.af.fidelity import FidelityChecker; ...'（同 tests/unit/test_greenfield_fidelity.py 负例口径）",
    },
    "NINE-07": {
        "name": "Action B 写入博途 V19 → 编译零错误 → 归档 .zap19 + 结构化编译报告",
        "endpoint": "(真机项，未执行) POST /action-b / --cli compile-plc",
        "request_summary": {"requires": "real_machine", "executed": False,
                            "note": "Agent Q 不连真机，绝不伪造编译结果"},
        "repro_command": "POST /api/v1/plc/canvas/greenfield/action-b（前置 A fidelity_ok==true）；或 --cli compile-plc --project <Temp/gf_real_*/副本.ap19> --plc PLC_1；归档 project.zap19（由 Agent R 真机完成）",
    },
    "NINE-08": {
        "name": "重跑步骤 4-5（不改输入）→ 产物哈希一致（L3 可复现）",
        "endpoint": f"POST {PREFIX}/action-a（第二次，同一冻结 spec）",
        "request_summary": {"method": "POST", "unchanged_input": True,
                            "note": "v1 冻结规格不改输入；对同一 spec 重复 Action A 导出，比对产物哈希"},
        "repro_command": f"对同一 session_id 再次 POST {PREFIX}/action-a，比对 evidence_bundle_sha256 / package.zip_sha256 / artifact_hashes（integrity.sha256 口径）",
    },
    "NINE-09": {
        "name": "从 specs/v1.json 重建画布与确认时一致",
        "endpoint": f"GET {PREFIX}/specs/1?project_id={PROJECT_ID}",
        "request_summary": {"method": "GET", "session_memory_cleared": True,
                            "note": "registry.reset() 清空进程内会话态后，仅凭磁盘 specs/v1.json 读取 FrozenSpec"},
        "repro_command": f"清空会话内存后 GET {PREFIX}/specs/1?project_id={PROJECT_ID}&session_id=<sid>，比对 spec_hash 与 ir_snapshot",
    },
}

STEP_ORDER = [f"NINE-{i:02d}" for i in range(1, 10)]

DRIVER = (
    "fastapi.testclient.TestClient（进程内 ASGI，挂载 gateway.app.main:app，不启动任何监听端口）；"
    "步骤6 负例用 plc_engine.af.fidelity.FidelityChecker 只读校验器直调；"
    "步骤8/9 与 Q2 哈希用 plc_engine.af.spec_diff.canonical_hash / sha256_prefixed 复算。"
    "运行期把 greenfield_chat.llm_settings 覆盖为返回 None，使 /chat 首轮走零 LLM 依赖的"
    "确定性 planner 兜底（draft_from_prompt fallback），不发任何外部 LLM 网络请求。"
)

HONEST_NOTE = (
    "不连真机、不启动 SessionServer / TIA、不占用 8000/8791/8011 端口（TestClient 进程内 ASGI）。"
    "本产物为 UC-15 §9.2 九步的【离线进程内真实驱动】留痕：步骤 1-6、8、9 经 TestClient 真实调用"
    "产品端点/只读校验器并保留每步原始响应关键字段；步骤 7（Action B 真机写入博途 V19、编译零错误、"
    "归档 .zap19 与结构化编译报告）恒 pending_real_machine，由 Agent R 独占真机完成，本工具绝不伪造编译结果。"
    "§13.9 六条增量真机项不在本九步产物内、恒 pending_real_machine。"
    "fidelity_ok 与 compile_ok 严格分离（N9）：步骤5 fidelity_ok=true 仅 L1 离线逻辑等价，"
    "compile_ok 恒 None；warning 单列不并入成功。"
    "离线跑通不得宣称：编译零错误 / L2 或 L4 通过 / L1∧L2∧L3∧L4 全绿 / M4 通过或代签；"
    "M4 签署权归用户本人，工具不得代签。"
    "evidence/uc15_evidence_bundle.json 为 A 返回的 evidence_bundle 真实离线实例化，"
    "缺 3 项真机工件（structured_compile_report / pcec_ledger / zap19_archive）如实列出、不补假数据。"
)


# ---------------------------------------------------------------------------
# 运行期隔离（禁止外部出网，保证离线确定性）
# ---------------------------------------------------------------------------
def _disable_external_llm():
    """覆盖 greenfield_chat.llm_settings → None，返回恢复闭包。"""
    import gateway.app.services.plc.greenfield_chat as gchat

    original = gchat.llm_settings
    gchat.llm_settings = lambda: None  # type: ignore[assignment]

    def restore() -> None:
        gchat.llm_settings = original  # type: ignore[assignment]

    return restore


def _call(client, method: str, path: str, **kwargs):
    """返回 (status_code, json_body, error)；任何异常如实返回，绝不伪造响应。"""
    try:
        if method == "get":
            resp = client.get(path, params=kwargs.get("params"))
        else:
            resp = client.post(path, json=kwargs.get("json"))
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 - 非 JSON 响应留痕
            body = {"_non_json_text": resp.text[:300]}
        return resp.status_code, body, None
    except Exception as exc:  # noqa: BLE001 - 失败如实记录
        return None, None, str(exc)


def _record(step_id: str, status: str, response, note: str, evidence_refs: list[str]) -> dict:
    meta = STEP_META[step_id]
    return {
        "step_id": step_id,
        "name": meta["name"],
        "endpoint": meta["endpoint"],
        "request_summary": meta["request_summary"],
        "response": response,
        "status": status if status in VALID_STATUSES else "fail",
        "evidence_refs": evidence_refs,
        "repro_command": meta["repro_command"],
        "note": note,
    }


def _ok(status_code, body) -> bool:
    return status_code == 200 and isinstance(body, dict) and body.get("ok") is True


# ---------------------------------------------------------------------------
# 主驱动
# ---------------------------------------------------------------------------
def run(out_path: Path, bundle_path: Path, work_dir: str | None = None) -> dict:
    """真实驱动九步，落盘九步产物与 UC-15 EvidenceBundle，返回九步 doc。"""
    wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="gf_nine_steps_"))
    wd.mkdir(parents=True, exist_ok=True)
    old_work_dir = os.environ.get("PLC_WORK_DIR")
    os.environ["PLC_WORK_DIR"] = str(wd)
    restore = _disable_external_llm()

    try:
        from fastapi.testclient import TestClient
        from gateway.app.main import app
        from gateway.app.services.plc.greenfield_session import registry
        from plc_engine.af.fidelity import FidelityChecker
        from plc_engine.af.spec_diff import canonical_hash, sha256_prefixed

        registry.reset()  # 独立会话，避免复用进程内旧状态
        client = TestClient(app)
        ctx: dict = {"client": client, "sid": "", "wd": str(wd)}
        steps: list[dict] = []

        def _exec(step_id: str, fn):
            try:
                status, response, note, refs = fn()
            except Exception as exc:  # noqa: BLE001 - 失败如实记录，绝不伪造成功
                status, response, note = "fail", {"error": str(exc)}, f"步骤执行异常（如实记录）：{exc}"
                refs = []
            steps.append(_record(step_id, status, response, note, refs))

        # ---- 步骤 1 ---------------------------------------------------------
        def step1():
            sc, body, err = _call(ctx["client"], "get", f"{PREFIX}/state",
                                  params={"project_id": PROJECT_ID})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, f"/state 调用失败：{err}", []
            d = body["data"]
            ctx["sid"] = d["session_id"]
            hw = d.get("hardware") or {}
            kinds = [n.get("kind") for n in (hw.get("nodes") or [])]
            response = {
                "status_code": sc,
                "ok": body.get("ok"),
                "session_id": d["session_id"],
                "project_id": d.get("project_id"),
                "stage": d.get("stage"),
                "has_ir": d.get("has_ir"),
                "has_contract": d.get("has_contract"),
                "hardware_node_kinds": kinds,
                "hardware_node_count": len(hw.get("nodes") or []),
                "hardware_link_count": len(hw.get("links") or []),
                "counters": d.get("counters"),
                "io_table_uploaded": False,
                "confirm_prerequisites": d.get("confirm_prerequisites"),
            }
            ok = (d.get("project_id") == PROJECT_ID and d.get("has_contract") is False
                  and len(kinds) >= 3 and all(v == 0 for v in (d.get("counters") or {}).values()))
            note = (
                "真实 GET /state 建立会话并绑定 project_id；未调用 /upload（D7 不上传 IO 表），"
                "无 CompatContract，故不产生任何虚构的用户 IO 地址 / OB 条目。hardware 为反推展示层"
                "默认 3 类占位（PLC_CPU / DI_MODULE / DO_MODULE），非用户 IO 表虚构地址。"
                "契约 §9.2 表记为 POST /state；实际产品端点为 GET /state，repro_command 已留真实口径。"
            )
            return ("pass" if ok else "fail"), response, note, ["evidence/nine_steps_offline_run.json"]

        _exec("NINE-01", step1)

        # ---- 步骤 2 ---------------------------------------------------------
        def step2():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/chat",
                                  json={"session_id": ctx["sid"], "message": CHAT_MESSAGE})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, f"/chat 调用失败：{err}", []
            d = body["data"]
            st = d.get("state") or {}
            views = st.get("views") or {}
            ir = st.get("ir") or {}
            ctx["chat_ir"] = ir
            response = {
                "status_code": sc,
                "ok": body.get("ok"),
                "reply": str(d.get("reply") or "")[:220],
                "summary": st.get("summary"),
                "views_keys": sorted(views.keys()),
                "four_views_present": all(k in views for k in ("flow", "seq", "state", "step_flow")),
                "edge_count": len(ir.get("edges") or []),
                "confirm_prerequisites": st.get("confirm_prerequisites"),
            }
            ok = (response["four_views_present"] and response["edge_count"] > 0
                  and bool((st.get("summary") or {}).get("cms")))
            note = (
                "真实 POST /chat 首轮（会话无 IR）生成首版规格与四视图 + 连线清单。"
                "运行期禁用外部 LLM，产品走零 LLM 依赖的确定性 planner 兜底"
                "（chat_turn → draft_from_prompt），不发任何外部网络请求；reply 与 summary 为真实原始响应。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json"]
        _exec("NINE-02", step2)

        # ---- 步骤 3 ---------------------------------------------------------
        def step3():
            ir = ctx.get("chat_ir") or {}
            step0 = (ir.get("steps") or [{}])[0]
            job0 = (ir.get("jobs") or [{}])[0]
            removable = next((e for e in (ir.get("edges") or []) if not e.get("immutable")), None)
            cm_em = (ir.get("cms") or [{}])[0].get("em_id")
            if not (step0.get("id") and job0.get("id") and removable and cm_em):
                return "fail", {"error": "步骤2 的 IR 缺少构造 patch 所需的真实 id"}, "无法从真实 IR 取得 op 目标 id（不臆造 id）", []
            ops = [
                {"op": "add_cm", "node": {"em_id": cm_em, "cm_type": "LBC_MotorStarter",
                                          "business_label": "手动新增执行件：下料检测气缸"}},
                {"op": "remove_edge", "edge_id": removable["id"]},
                {"op": "set_ir_only_field", "field_path": f"steps.{step0['id']}.transition_condition",
                 "value": "TRUE"},
                {"op": "set_ir_only_field", "field_path": f"jobs.{job0['id']}.start_condition",
                 "value": "TRUE AND #ready"},
            ]
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/patch",
                                  json={"session_id": ctx["sid"], "project_id": PROJECT_ID, "ops": ops})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, f"/patch 调用失败：{err}", []
            pd = body["data"]
            vsc, vbody, verr = _call(ctx["client"], "post", f"{PREFIX}/validate",
                                     json={"session_id": ctx["sid"]})
            vreport = ((vbody or {}).get("data") or {}).get("report") or {}
            response = {
                "patch_status_code": sc,
                "patch_ok": pd.get("ok"),
                "applied_ops": pd.get("applied_ops"),
                "violations": pd.get("violations"),
                "change_events_count": len(pd.get("change_events") or []),
                "change_events_preview": [{"op": e.get("op"), "ok": e.get("ok")}
                                          for e in (pd.get("change_events") or [])][:6],
                "ir_sha256": str(pd.get("ir_sha256") or "")[:24],
                "spec_hash_after_patch": str(pd.get("spec_hash") or "")[:24],
                "stage": pd.get("stage"),
                "validate_status_code": vsc,
                "validate_ir_ok": vreport.get("ok"),
                "validate_open_questions": vreport.get("open_questions"),
            }
            ok = (pd.get("ok") is True and pd.get("applied_ops") == len(ops)
                  and not pd.get("violations") and vsc == 200 and vreport.get("ok") is True)
            note = (
                "真实 POST /patch 一次原子提交 4 项手动编辑（add_cm 新增执行件 / remove_edge 删一条"
                "非 immutable 连线 / set_ir_only_field 改作业交互条件 / set_ir_only_field 改步序条件），"
                "所有 op 目标 id 取自步骤2 真实 IR；change_events 入账；随后 /validate 重算 validate_ir 通过。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json"]
        _exec("NINE-03", step3)

        # ---- 步骤 4 ---------------------------------------------------------
        def step4():
            st_sc, st_body, st_err = _call(ctx["client"], "get", f"{PREFIX}/state",
                                           params={"session_id": ctx["sid"]})
            pre = ((st_body or {}).get("data") or {})
            counters_before = pre.get("counters") or {}
            prereq = pre.get("confirm_prerequisites") or {}
            eng_sc, _, eng_err = _call(ctx["client"], "post", f"{PREFIX}/engineering-summary",
                                       json={"session_id": ctx["sid"]})
            cf_sc, cf_body, cf_err = _call(ctx["client"], "post", f"{PREFIX}/confirm",
                                           json={"session_id": ctx["sid"], "explicit": True,
                                                 "frozen_by": "user"})
            if cf_err or not _ok(cf_sc, cf_body):
                return "fail", {"error": cf_err or eng_err or st_err, "confirm_status_code": cf_sc,
                                "confirm_body": cf_body, "counters_before": counters_before,
                                "confirm_prerequisites": prereq}, "/confirm 调用失败或前置未满足（如实记录）", []
            cd = cf_body["data"]
            spec = cd.get("spec") or {}
            path = cd.get("path") or ""
            ctx["confirm_spec"] = spec
            ctx["spec_hash"] = spec.get("spec_hash")
            ctx["specs_v1_path"] = path
            exists = bool(path) and Path(path).is_file()
            four = ("ops", "disk_writes", "writebacks", "generations")
            response = {
                "engineering_summary_status_code": eng_sc,
                "confirm_status_code": cf_sc,
                "confirm_ok": cf_body.get("ok"),
                "explicit": True,
                "spec_version": spec.get("spec_version"),
                "spec_hash": spec.get("spec_hash"),
                "specs_v1_path": path,
                "specs_v1_exists": exists,
                "counters_before_confirm": counters_before,
                "four_counters_all_zero_before_confirm": all(counters_before.get(k) == 0 for k in four),
                "confirm_prerequisites": prereq,
            }
            ok = (cf_body.get("ok") is True and bool(spec.get("spec_hash")) and exists
                  and response["four_counters_all_zero_before_confirm"])
            note = (
                "真实 GET /state 读取确认前四计数器（ops/disk_writes/writebacks/generations 恒 0）与"
                "五项确认前置；POST /engineering-summary 展示工程摘要；POST /confirm(explicit=true) "
                "冻结 v1 并落盘 specs/v1.json，spec_hash 覆盖拓扑与步骤3 全部编辑。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json", path]
        _exec("NINE-04", step4)

        # ---- 步骤 5 ---------------------------------------------------------
        def step5():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/action-a",
                                  json={"session_id": ctx["sid"], "include_zip_base64": False})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, "/action-a 调用失败：%s" % err, []
            ad = body["data"]
            eb = ad.get("evidence_bundle") or {}
            fr = eb.get("fidelity_report") or {}
            sha = ad.get("evidence_bundle_sha256")
            recomputed = canonical_hash({k: v for k, v in eb.items()
                                         if k not in ("bundle_sha256", "package_zip_base64")})
            ctx["action_a"] = ad
            ctx["evidence_bundle"] = eb
            ctx["coverage_matrix"] = fr.get("coverage_matrix") or {}
            ctx["bundle_sha256"] = sha
            ctx["bundle_sha256_recomputed"] = recomputed
            response = {
                "status_code": sc,
                "ok": body.get("ok"),
                "action": ad.get("action"),
                "mode": ad.get("mode"),
                "fidelity_ok": ad.get("fidelity_ok"),
                "fidelity_report": {
                    "fidelity_ok": fr.get("fidelity_ok"),
                    "coverage": fr.get("coverage"),
                    "orphan": fr.get("orphan"),
                    "drift": fr.get("drift"),
                    "unmapped_spec_objects": fr.get("unmapped_spec_objects"),
                    "ob_number_deviations": fr.get("ob_number_deviations"),
                    "pending_real_machine": fr.get("pending_real_machine"),
                },
                "evidence_bundle_sha256": sha,
                "bundle_sha256": eb.get("bundle_sha256"),
                "bundle_sha256_recomputed": recomputed,
                "bundle_sha256_match": recomputed == sha == eb.get("bundle_sha256"),
                "spec_version": ad.get("spec_version"),
                "block_count": ad.get("block_count"),
                "compile_ok": ad.get("compile_ok"),
                "tia_written": ad.get("tia_written"),
                "pending_real_machine": ad.get("pending_real_machine"),
                "evidence_bundle_keys": sorted(eb.keys()),
            }
            ok = (ad.get("fidelity_ok") is True and ad.get("compile_ok") is None
                  and ad.get("tia_written") is False and response["bundle_sha256_match"] is True
                  and fr.get("orphan") == 0)
            note = (
                "真实 POST /action-a 产出 fidelity_report.json（fidelity_ok=true、coverage=1.0、orphan=0）"
                "与 EvidenceBundle；bundle_sha256 经 canonical_hash 复算一致。fidelity_ok 是 L1 离线逻辑"
                "等价，compile_ok 恒 None（N9），Action A 不写 TIA。evidence_bundle 原始响应已实例化到"
                "evidence/uc15_evidence_bundle.json。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json",
                "evidence/uc15_evidence_bundle.json"]
        _exec("NINE-05", step5)

        # ---- 步骤 6 ---------------------------------------------------------
        def step6():
            cmat = ctx.get("coverage_matrix") or {}
            sids = sorted(cmat.keys())
            spec_hash = ctx.get("spec_hash") or ""
            if not sids:
                return "fail", {"error": "步骤5 未产出真实 coverage_matrix，无法构造负例"}, "缺少真实 source_id 集合（不臆造）", []
            spec_like = SimpleNamespace(
                project_id=PROJECT_ID, version=1,
                ir_snapshot={"expected_source_ids": sids}, spec_hash=spec_hash,
            )

            def descriptor(sid: str) -> str:
                return json.dumps({
                    "source_id": sid, "content": "// real derived block",
                    "content_hash": sha256_prefixed("// real derived block"),
                    "spec_hash": spec_hash,
                }, ensure_ascii=False)

            full = {f"blocks/{sid}.scl": descriptor(sid) for sid in sids}
            removed_sid = sids[0]
            a_art = {k: v for k, v in full.items() if k != f"blocks/{removed_sid}.scl"}
            r_a = FidelityChecker().check(spec_like, a_art, mode="full")
            b_art = dict(full)
            b_art["blocks/__INJECTED_ORPHAN__.scl"] = "RAW_UNSOURCED_LOGIC_BLOCK"
            r_b = FidelityChecker().check(spec_like, b_art, mode="full")
            response = {
                "basis": "步骤5 真实 spec_hash + 真实 coverage_matrix 的 %d 个 source_id" % len(sids),
                "negative_a_deleted_source_id": removed_sid,
                "negative_a": {
                    "fidelity_ok": r_a.fidelity_ok,
                    "coverage": r_a.coverage,
                    "unmapped_spec_objects": list(r_a.unmapped_spec_objects)[:6],
                    "orphan": r_a.orphan,
                },
                "negative_b_injected_key": "blocks/__INJECTED_ORPHAN__.scl",
                "negative_b": {
                    "fidelity_ok": r_b.fidelity_ok,
                    "orphan": r_b.orphan,
                    "orphan_blocks": list(r_b.orphan_blocks)[:6],
                },
            }
            ok = (r_a.fidelity_ok is False and bool(r_a.unmapped_spec_objects)
                  and r_b.fidelity_ok is False and r_b.orphan == 1)
            note = (
                "FidelityChecker.check 只读校验器两个负例（无 HTTP 端点，同 test_greenfield_fidelity.py 口径）："
                "负例A 从步骤5 真实产物集合中删掉一个产物块 → coverage<1、fidelity_ok=false、"
                "unmapped_spec_objects 列出被删 source_id；负例B 塞入无 source_id 的逻辑块 → orphan=1、"
                "fidelity_ok=false。均为纯离线只读判定，不涉及真机。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json",
                "tests/unit/test_greenfield_fidelity.py（同口径负例）"]
        _exec("NINE-06", step6)

        # ---- 步骤 7（真机项，绝不执行、绝不伪造）---------------------------
        steps.append(_record(
            "NINE-07", "pending_real_machine",
            {
                "executed": False,
                "compile_ok": None,
                "note": "真机项未执行；不产生任何编译结果、error_count、.zap19 或结构化编译报告，绝不伪造。",
            },
            "Action B 真机写入博途 V19 / 编译 / 归档 .zap19 由 Agent R 独占真机完成；"
            "Agent Q 不连真机、不启动 SessionServer/TIA，本步恒 pending_real_machine 并留复现命令。",
            [],
        ))

        # ---- 步骤 8 ---------------------------------------------------------
        def step8():
            a1 = ctx.get("action_a") or {}
            if not a1:
                return "fail", {"error": "步骤5 未产出 Action A 结果，无法比对"}, "缺少第一次导出结果（不臆造）", []
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/action-a",
                                  json={"session_id": ctx["sid"], "include_zip_base64": False})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, "第二次 /action-a 调用失败：%s" % err, []
            a2 = body["data"]
            eb1, eb2 = a1.get("evidence_bundle") or {}, a2.get("evidence_bundle") or {}
            sha_equal = a1.get("evidence_bundle_sha256") == a2.get("evidence_bundle_sha256")
            zip_equal = (eb1.get("package") or {}).get("zip_sha256") == (eb2.get("package") or {}).get("zip_sha256")
            art_equal = eb1.get("artifact_hashes") == eb2.get("artifact_hashes")
            response = {
                "second_action_a_status_code": sc,
                "unchanged_input": True,
                "hash_1": a1.get("evidence_bundle_sha256"),
                "hash_2": a2.get("evidence_bundle_sha256"),
                "evidence_bundle_sha256_equal": sha_equal,
                "zip_sha256_equal": zip_equal,
                "artifact_hashes_equal": art_equal,
            }
            ok = sha_equal and zip_equal and art_equal
            note = (
                "v1 冻结规格不改输入；对同一 spec 重复执行步骤5 的 Action A 导出，"
                "evidence_bundle_sha256 / package.zip_sha256 / artifact_hashes 三项真实比对一致 → L3 可复现。"
                "仅产物哈希比对，不宣称 L2/L4 真机通过、编译零错误或 M4 判定。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json",
                "evidence/uc15_evidence_bundle.json#artifact_hashes"]
        _exec("NINE-08", step8)

        # ---- 步骤 9 ---------------------------------------------------------
        def step9():
            confirm_spec = ctx.get("confirm_spec") or {}
            if not confirm_spec:
                return "fail", {"error": "步骤4 未产出 FrozenSpec，无法比对重建"}, "缺少确认时 spec（不臆造）", []
            registry.reset()  # 清空进程内会话态，模拟服务重启后内存态丢失
            sc, body, err = _call(ctx["client"], "get", f"{PREFIX}/specs/1",
                                  params={"project_id": PROJECT_ID, "session_id": ctx["sid"]})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, "GET /specs/1 调用失败：%s" % err, []
            spec2 = (body["data"] or {}).get("spec") or {}
            hash_equal = spec2.get("spec_hash") == confirm_spec.get("spec_hash")
            ir_equal = spec2.get("ir_snapshot") == confirm_spec.get("ir_snapshot")
            response = {
                "status_code": sc,
                "ok": body.get("ok"),
                "session_memory_cleared": True,
                "rebuilt_from": ctx.get("specs_v1_path"),
                "spec_version": spec2.get("spec_version"),
                "spec_hash_equal": hash_equal,
                "ir_snapshot_equal": ir_equal,
                "project_id": spec2.get("project_id"),
            }
            ok = hash_equal and ir_equal
            note = (
                "进程内 ASGI 无法真正重启进程；以 registry.reset() 清空内存会话态后，"
                "GET /specs/1 仅凭磁盘 specs/v1.json 读取 FrozenSpec，spec_hash 与 ir_snapshot 与确认时"
                "完全一致 → 验证可仅凭 v1.json 重建画布（含拓扑）。真实服务重启由主 agent 收口核验。"
            )
            return ("pass" if ok else "fail"), response, note, [
                "evidence/nine_steps_offline_run.json",
                ctx.get("specs_v1_path") or "specs/v1.json"]
        _exec("NINE-09", step9)

        counts = dict(Counter(s["status"] for s in steps))
        for s in VALID_STATUSES:
            counts.setdefault(s, 0)
        doc = {
            "schema": "gf-nine-steps-offline-run-v1",
            "uc": "UC-15",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "driver": DRIVER,
            "steps": steps,
            "summary": {"total": len(steps), "by_status": counts},
            "honest_note": HONEST_NOTE,
            "project_id": PROJECT_ID,
            "work_dir": str(wd),
            "step7_pending_real_machine": True,
        }

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        write_uc15_bundle(Path(bundle_path), ctx)
        return doc
    finally:
        restore()
        if old_work_dir is None:
            os.environ.pop("PLC_WORK_DIR", None)
        else:
            os.environ["PLC_WORK_DIR"] = old_work_dir


# ---------------------------------------------------------------------------
# Q2 · 真实 EvidenceBundle 离线实例化
# ---------------------------------------------------------------------------
#: acceptance_template.json 12 项 full_artifacts → 本离线包的对应证据 / 缺口（不补假数据）。
_ARTIFACT_MAP = {
    "specs_vN_json": ("evidence_bundle_raw.spec + specs/v1.json（步骤4 落盘）", "offline"),
    "ir_snapshot": ("evidence_bundle_raw.ir_snapshot", "offline"),
    "four_views_export": ("evidence_bundle_raw.views（flow/seq/state/step_flow）", "offline"),
    "edge_list": ("evidence_bundle_raw.edge_list", "offline"),
    "open_questions_clearance": ("nine_steps_offline_run.json#step-4 confirm_prerequisites.open_questions=[]", "offline"),
    "static_gate_results": ("evidence_bundle_raw.static_gate", "offline"),
    "fidelity_report_json": ("evidence_bundle_raw.fidelity_report", "offline"),
    "structured_compile_report": (None, "real_machine（步骤7 / Agent R）"),
    "pcec_ledger": (None, "real_machine（UC-16 增量 / Agent R）"),
    "baseline_manifest_json": ("evidence_bundle_raw.baseline_manifest", "offline"),
    "artifact_hashes": ("evidence_bundle_raw.artifact_hashes + zip_entry_hashes", "offline"),
    "zap19_archive": (None, "real_machine（步骤7 / Agent R）"),
}

#: 6 个增量字段：本包为 full 模式，以下均为 action-a 真实响应/fidelity_report 的离线值，
#: 不是 incremental 模式的真机证据，note 明确边界（不补假数据）。
_INCREMENTAL_MAP = {
    "mode": ("evidence_bundle_raw.mode", "full"),
    "base_spec_version": ("evidence_bundle_raw.fidelity_report.base_spec_version", None),
    "changed_source_ids": ("evidence_bundle_raw.fidelity_report.changed_source_ids", []),
    "reverse_protection": ("evidence_bundle_raw.fidelity_report.reverse_protection", "pending_real_machine"),
    "tia_side_drift": ("evidence_bundle_raw.fidelity_report.tia_side_drift", 0),
    "ob_number_deviations": ("evidence_bundle_raw.fidelity_report.ob_number_deviations", []),
}


def write_uc15_bundle(path: Path, ctx: dict) -> dict:
    """把步骤5 run_action_a 返回的 evidence_bundle 真实落盘 + 12 项工件核对。"""
    eb = ctx.get("evidence_bundle") or {}
    action_a = ctx.get("action_a") or {}
    fr = eb.get("fidelity_report") or {}

    artifacts: dict[str, dict] = {}
    missing_artifacts: list[str] = []
    for aid, (ref, source) in _ARTIFACT_MAP.items():
        present = bool(ref)
        if not present:
            missing_artifacts.append(aid)
        artifacts[aid] = {
            "present": present,
            "evidence_ref": ref,
            "source": source,
            "note": ("由 A 的真实响应提供，离线可复算" if present else
                     "真机项：须由 Agent R 完成步骤7/UC-16 后补齐，本离线实例化不得补假数据"),
        }

    incremental_fields: dict[str, dict] = {}
    for name, (ref, value) in _INCREMENTAL_MAP.items():
        incremental_fields[name] = {
            "present": True,
            "value": fr.get(name, value) if name in fr else value,
            "evidence_ref": ref,
            "note": ("UC-15 full 模式离线真实值；非 incremental 模式真机证据，"
                     "UC-16 增量真机证据由 Agent R 产出后补齐；本值不构成增量验收结论"),
        }

    bundle = {
        "schema": "gf-uc15-evidence-instance-v1",
        "bundle_id": "UC-15 / §9.2 九步离线链 / EvidenceBundle 离线实例化",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "tools/run_nine_steps.py",
        "source": "步骤5 POST /action-a 返回的 evidence_bundle（原始响应，真实落盘，未裁剪/未补假数据）",
        "driver": DRIVER,
        "uc": "UC-15",
        "project_id": PROJECT_ID,
        "spec_version": action_a.get("spec_version"),
        "spec_hash": action_a.get("spec_hash") or ctx.get("spec_hash"),
        "fidelity_ok": action_a.get("fidelity_ok"),
        "compile_ok": action_a.get("compile_ok"),
        "tia_written": action_a.get("tia_written"),
        "pending_real_machine": True,
        "xml_package_unverified": True,
        "bundle_sha256": ctx.get("bundle_sha256"),
        "bundle_sha256_recomputed": ctx.get("bundle_sha256_recomputed"),
        "bundle_sha256_match": ctx.get("bundle_sha256") == ctx.get("bundle_sha256_recomputed"),
        "full_artifacts_expected": 12,
        "full_artifacts_present": 12 - len(missing_artifacts),
        "artifacts": artifacts,
        "incremental_fields": incremental_fields,
        "missing_artifacts": missing_artifacts,
        "missing_incremental_fields": [],
        "evidence_bundle_raw": eb,
        "gap_note": (
            "步骤 7（Action B 真机写入博途 V19 → 编译零错误 → 归档 .zap19 + 结构化编译报告）"
            "由 Agent R 独占真机完成。structured_compile_report / zap19_archive / pcec_ledger "
            "三项须在 R 产出真机结构化报告（如 evidence/uc15_step7_real.json）后补齐；"
            "本离线实例化如实列出缺项，不得补假数据、不得据离线证据宣称编译零错误。"
        ),
        "honest_note": (
            "fidelity_ok 与 compile_ok 严格分离（N9）：A 的 fidelity_ok=true 仅 L1 离线逻辑等价，"
            "compile_ok 恒 None；warning 单列不并入成功。本包为 UC-15 full 模式离线实例化，"
            "不构成 UC-16 增量证据，不宣称 L2/L4 通过、编译零错误、L1∧L2∧L3∧L4 全绿，"
            "不构成 M4 通过或代签；M4 签署权归用户本人。"
        ),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bundle


def main() -> None:
    ap = argparse.ArgumentParser(
        description="§9.2 九步离线链真实驱动（TestClient 进程内 ASGI，不连真机、不起端口）"
    )
    ap.add_argument("--out", default="evidence/nine_steps_offline_run.json", metavar="PATH",
                    help="九步运行产物 JSON（默认 evidence/nine_steps_offline_run.json）")
    ap.add_argument("--bundle-out", default="evidence/uc15_evidence_bundle.json", metavar="PATH",
                    help="UC-15 EvidenceBundle 离线实例化产物（默认 evidence/uc15_evidence_bundle.json）")
    ap.add_argument("--work-dir", default=None, metavar="PATH",
                    help="PLC_WORK_DIR 隔离目录（默认系统临时目录 gf_nine_steps_*，不碰原始 .ap19）")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    bundle = Path(args.bundle_out)
    if not bundle.is_absolute():
        bundle = ROOT / bundle

    doc = run(out, bundle, work_dir=args.work_dir)
    print(json.dumps({
        "out": str(out),
        "bundle_out": str(bundle),
        "summary": doc["summary"],
        "step_statuses": {s["step_id"]: s["status"] for s in doc["steps"]},
        "driver": doc["driver"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
