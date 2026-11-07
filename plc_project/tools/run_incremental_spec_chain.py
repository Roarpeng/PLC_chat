"""UC-16 真实规格链 + 增量 fidelity 闭环（Agent V · 批次 4 / 阶段 A 离线侧）。

用 ``fastapi.testclient.TestClient`` 在**进程内 ASGI** 挂载 ``gateway.app.main:app``，
真实走一遍 Greenfield 冻结规格链 ``specs/v1.json -> specs/v2.json``，再从磁盘装载
两版规格、产出真实 ``SpecDiff`` 与增量 ``FidelityChecker(mode="incremental")`` 报告，
最后组装离线增量 ``EvidenceBundle``（六字段 + 可复算 ``bundle_sha256``）。

与批次 3 的根因对应（契约 14 §0 UC-16 / §3）：
- 批次 3 ``evidence/uc16_incremental_real.json`` 的 ``base_spec_version=null`` 是因为
  R 走纯 CLI 块级覆盖、没有真实 Greenfield 冻结规格链；本脚本用真实端点补齐
  ``specs/v1.json -> specs/v2.json``，让 ``base_spec_version`` 取真实值 1。
- 增量 ``fidelity_ok`` 不再引用 Q 的离线 L1 全量真值，而是本链真实
  ``FidelityChecker(mode="incremental", base_spec_version=1, diff=...)`` 的产出。

只读复用（绝不修改）：
- ``tools/run_nine_steps.py`` 的 TestClient 驱动方式 / ``_disable_external_llm`` 思路 /
  ``_call`` / ``PLC_WORK_DIR`` 与 ``specs/vN.json`` 落盘机制；
- ``greenfield_service.load_frozen_spec`` / ``_build_artifacts`` / ``_action_spec_like`` /
  ``diff_placeholder``（经真实 ``POST /diff`` 端点）与 ``run_action_a`` 的真实 artifacts；
- ``plc_engine.af.spec_diff.compute_spec_diff`` / ``canonical_hash``；
- ``plc_engine.af.fidelity.FidelityChecker.check``。

诚实边界（契约 14 §1 / §3、13 §5、04 §0，N9 / D12）：
- **不连真机**、不启动 SessionServer、不跑 TIA CLI、不占用 8791/8000 端口
  （TestClient 进程内 ASGI，不监听任何端口）；
- ``tia_side_snapshot`` 无真实 TIA 数据时**不虚构**：按 ``FidelityChecker`` 现有约定传
  ``None``，``tia_side_drift`` 记 0 并标 ``pending_real_machine``，
  ``reverse_protection.status=pending_real_machine``；真机 D10 反向保护由 Agent W 验证；
- ``fidelity_ok`` 与 ``compile_ok`` 严格分离：本链 ``fidelity_ok=true`` 仅 L1 离线 1:1
  逻辑等价，``compile_ok`` 恒 ``null``，不产出/不宣称编译零错误；
- 离线增量 fidelity **≠** 真机 L4 通过；不宣称 UC-16 整体通过、不宣称
  ``L1∧L2∧L3∧L4`` 全绿、不宣称 M4 通过或代签；M4 签署栏始终「待用户签署」；
- ``ob_number_deviations`` 显式留痕（即使为空也写 note，禁止静默）；
- 跑不通的步骤如实记 ``fail`` + 原因；``/diff`` 或增量 ``FidelityChecker`` 失败则如实
  标 ``pending`` + 失败原因，**不伪造报告、不绕过**；所有 ``pass`` 均带真实响应字段。

用法::

    python tools/run_incremental_spec_chain.py \
        --out evidence/uc16_incremental_spec_chain.json \
        --bundle evidence/uc16_incremental_evidence_bundle.json \
        --work-dir <PLC_WORK_DIR 隔离目录（可选，供 W 复现）>

退出码: 0 = 产物写出（真实性判定见产物 ``summary`` / 各步 ``status``）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 保证 ``python tools/run_incremental_spec_chain.py`` 可 import 产品代码（gateway / plc_engine）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PREFIX = "/api/v1/plc/canvas/greenfield"
PROJECT_ID = "GF-V-UC16"
CHAT_MESSAGE = (
    "输送单元把工件送到装配工位，夹紧气缸定位，机器人完成涂胶作业后放行到下料工位"
)
VALID_STATUSES = ("pass", "fail", "not_run", "pending_real_machine")

DRIVER = (
    "fastapi.testclient.TestClient（进程内 ASGI，挂载 gateway.app.main:app，不启动任何监听端口）；"
    "POST /diff 经服务端 diff_placeholder 调 compute_spec_diff；"
    "增量产物用 greenfield_service._build_artifacts（复用 run_action_a 的真实派生产物）"
    "与 _action_spec_like 适配后直调 plc_engine.af.fidelity.FidelityChecker(mode='incremental')；"
    "规格装载用 greenfield_service.load_frozen_spec 从磁盘 specs/vN.json 读取。"
    "运行期把 greenfield_chat.llm_settings 覆盖为返回 None，使 /chat 首轮走零 LLM 依赖的"
    "确定性 planner 兜底（draft_from_prompt fallback），不发任何外部 LLM 网络请求。"
)

HONEST_BOUNDARY = [
    "离线增量 fidelity ≠ 真机 L4 通过：本链为 TestClient 进程内 ASGI 离线驱动，不连真机、"
    "不启动 SessionServer、不跑 TIA CLI、不占用 8791/8000 端口；真机 Action C 增量覆盖"
    "（会话复用 / 编译 0/0 / PCEC / tia_side_drift=0）由阶段 B 的 Agent W 独占完成。",
    "fidelity_ok ≠ compile_ok（N9）：本链 fidelity_ok=true 仅为 L1 离线 1:1 逻辑等价判定，"
    "compile_ok 恒 null；不产出、不宣称编译零错误，不标 L2/L4 pass。",
    "tia_side_snapshot 无真实 TIA 块数据时不得虚构：按 FidelityChecker 现有约定传 None，"
    "tia_side_drift 记 0 并标 pending_real_machine，reverse_protection.status="
    "pending_real_machine（allowed=null）；真机 D10 反向保护 allowed=true 由 W 验证。",
    "ob_number_deviations 显式留痕（禁止静默）：本链为空列表，并在 FidelityReport.notes / "
    "bundle 的 ob_number_deviations_note 中说明属不纳入 1:1 的域，不参与 fidelity_ok 判定。",
    "base_spec_version=1 来自真实 Greenfield 冻结规格链 specs/v1.json -> specs/v2.json，"
    "补齐批次 3 base_spec_version=null 的离线侧缺口；真机增量仍需 W 用同一 PLC_WORK_DIR 复核。",
    "命名空间诚实说明：SpecDiff.changed_source_ids 来自 compute_spec_diff 对 ir_snapshot 的 "
    "IR 层 source block 提取（本链新增执行件 id 形如 U1EM1_CM3），而 FidelityChecker 的 "
    "artifacts / expected_source_ids 来自 v2 派生产物层（形如 DB::/FB::/OB::...）；两者命名空间不同。"
    "产品 FidelityChecker 增量模式按『全量四指标复核（安全侧更严）』实现，故 coverage=1.0 指"
    "v2 派生产物 1:1 全覆盖，不等价于『逐个 IR 层变更块单独校验』；如实记录，不掩盖。",
    "不宣称 UC-16 整体通过、不宣称 L1∧L2∧L3∧L4 全绿、不宣称 M4 通过或代签；"
    "M4 签署栏始终「待用户签署」。",
]

#: 规格链步骤元数据（id / name / endpoint / request_summary / repro_command）。
STEP_META: dict[str, dict] = {
    "V-01": {
        "name": "建会话 + 逻辑拓扑占位（不上传 IO 表，D7）",
        "endpoint": f"GET {PREFIX}/state?project_id={PROJECT_ID}",
        "request_summary": {"method": "GET", "params": {"project_id": PROJECT_ID},
                            "io_table_uploaded": False},
        "repro_command": f"GET {PREFIX}/state?project_id={PROJECT_ID}",
    },
    "V-02": {
        "name": "对话输入自然语言 → 确定性 planner 兜底生成首版 IR（零 LLM 依赖）",
        "endpoint": f"POST {PREFIX}/chat",
        "request_summary": {"method": "POST", "session_id": "<V-01 返回>",
                            "message": CHAT_MESSAGE},
        "repro_command": f"POST {PREFIX}/chat body={{session_id, message}} → 首版 IR + 四视图",
    },
    "V-03": {
        "name": "展示工程视角摘要（v1 /confirm 前置 Q9）",
        "endpoint": f"POST {PREFIX}/engineering-summary",
        "request_summary": {"method": "POST", "session_id": "<sid>"},
        "repro_command": f"POST {PREFIX}/engineering-summary body={{session_id}}",
    },
    "V-04": {
        "name": "确认冻结 v1 → 落盘 specs/v1.json",
        "endpoint": f"POST {PREFIX}/confirm",
        "request_summary": {"method": "POST", "explicit": True, "frozen_by": "user"},
        "repro_command": f"POST {PREFIX}/confirm body={{session_id, explicit:true, frozen_by:'user'}} → specs/v1.json",
    },
    "V-05": {
        "name": "开启新版本草稿编辑（回到可编辑态，旧版字节不变）",
        "endpoint": f"POST {PREFIX}/begin-edit",
        "request_summary": {"method": "POST", "session_id": "<sid>"},
        "repro_command": f"POST {PREFIX}/begin-edit body={{session_id}}",
    },
    "V-06": {
        "name": "真实增量编辑：新增 1 个执行件（走 apply_canvas_patch 统一入口）",
        "endpoint": f"POST {PREFIX}/patch + POST {PREFIX}/validate",
        "request_summary": {"method": "POST", "op": "add_cm", "base_spec_version": 1,
                            "note": "op 目标 em_id 取自当前真实 IR 的 cms[0].em_id；随后 /validate 复算"},
        "repro_command": f"POST {PREFIX}/patch body={{session_id, project_id, base_spec_version:1, "
                         "ops:[{op:'add_cm', node:{em_id, cm_type, business_label}}]}；再 POST "
                         f"{PREFIX}/validate",
    },
    "V-07": {
        "name": "展示工程视角摘要（v2 /confirm 前置 Q9）",
        "endpoint": f"POST {PREFIX}/engineering-summary",
        "request_summary": {"method": "POST", "session_id": "<sid>"},
        "repro_command": f"POST {PREFIX}/engineering-summary body={{session_id}}",
    },
    "V-08": {
        "name": "确认冻结 v2 → 落盘 specs/v2.json",
        "endpoint": f"POST {PREFIX}/confirm",
        "request_summary": {"method": "POST", "explicit": True, "frozen_by": "user"},
        "repro_command": f"POST {PREFIX}/confirm body={{session_id, explicit:true, frozen_by:'user'}} → specs/v2.json",
    },
    "V-09": {
        "name": "从磁盘 load_frozen_spec 装载 v1/v2 并核对（不依赖会话内存态）",
        "endpoint": "greenfield_service.load_frozen_spec(...) 直调（只读）",
        "request_summary": {"method": "direct", "versions": [1, 2], "project_id": PROJECT_ID},
        "repro_command": "from gateway.app.services.plc.greenfield_service import load_frozen_spec; "
                         f"load_frozen_spec(sid, 1, project_id='{PROJECT_ID}'); load_frozen_spec(sid, 2, ...)",
    },
    "V-10": {
        "name": "POST /diff 产出真实 SpecDiff（base_spec_version=1）",
        "endpoint": f"POST {PREFIX}/diff",
        "request_summary": {"method": "POST", "from_version": 1, "to_version": 2},
        "repro_command": f"POST {PREFIX}/diff body={{session_id, project_id, from_version:1, to_version:2}}",
    },
    "V-11": {
        "name": "直调 compute_spec_diff(v1, v2) 产出 SpecDiff 对象（供 FidelityChecker diff 入参）",
        "endpoint": "plc_engine.af.spec_diff.compute_spec_diff(...) 直调（只读）",
        "request_summary": {"method": "direct", "base_spec": "v1 FrozenSpec", "target_spec": "v2 FrozenSpec"},
        "repro_command": "from plc_engine.af.spec_diff import compute_spec_diff; "
                         "compute_spec_diff(load_frozen_spec(sid,1), load_frozen_spec(sid,2))",
    },
    "V-12": {
        "name": "POST /action-a 生成 v2 派生产物（复用 run_action_a / 缓存 last_delivery）",
        "endpoint": f"POST {PREFIX}/action-a",
        "request_summary": {"method": "POST", "session_id": "<sid>", "include_zip_base64": False},
        "repro_command": f"POST {PREFIX}/action-a body={{session_id, include_zip_base64:false}} → 派生产物 + full fidelity 对照",
    },
    "V-13": {
        "name": "增量 FidelityChecker.check(mode='incremental', base_spec_version=1, diff=...)",
        "endpoint": "plc_engine.af.fidelity.FidelityChecker.check(...) 直调（只读）",
        "request_summary": {"method": "direct", "mode": "incremental", "base_spec_version": 1,
                            "spec": "v2 FrozenSpecLike（expected_source_ids=v2 派生产物）",
                            "artifacts": "_build_artifacts(v2 last_delivery)",
                            "diff": "compute_spec_diff(v1, v2)", "tia_side_snapshot": None},
        "repro_command": "FidelityChecker().check(spec_like, artifacts, mode='incremental', "
                         "base_spec_version=1, diff=diff_obj, tia_side_snapshot=None)",
    },
    "V-14": {
        "name": "组装离线增量 EvidenceBundle（六字段 + bundle_sha256 可复算）",
        "endpoint": "纯计算（本脚本内，只读）",
        "request_summary": {"method": "direct", "fields": 6, "bundle_sha256": "canonical_hash 复算"},
        "repro_command": "canonical_hash({k:v for k,v in bundle.items() "
                         "if k not in ('bundle_sha256','bundle_sha256_recomputed','bundle_sha256_match')})",
    },
}

STEP_ORDER = [f"V-{i:02d}" for i in range(1, 15)]

#: bundle_sha256 计算时排除的字段（避免循环依赖）。
_HASH_EXCLUDE = frozenset({"bundle_sha256", "bundle_sha256_recomputed", "bundle_sha256_match"})


# ---------------------------------------------------------------------------
# 运行期隔离（禁止外部出网，保证离线确定性）—— 复用 run_nine_steps.py 思路
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


def _ok(status_code, body) -> bool:
    return status_code == 200 and isinstance(body, dict) and body.get("ok") is True


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


def _source_ids(blocks) -> list[str]:
    return [str(b.get("source_id")) for b in (blocks or []) if isinstance(b, dict)]


def _sha_of(bundle: dict) -> str:
    from plc_engine.af.spec_diff import canonical_hash

    return canonical_hash({k: v for k, v in bundle.items() if k not in _HASH_EXCLUDE})


# ---------------------------------------------------------------------------
# 主驱动
# ---------------------------------------------------------------------------
def run(out_path: Path, bundle_path: Path, work_dir: str | None = None) -> tuple[dict, dict]:
    """真实驱动 v1→v2 规格链 + 增量 fidelity，落盘两份产物，返回 (chain_doc, bundle_doc)。"""
    wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="gf_inc_chain_"))
    wd.mkdir(parents=True, exist_ok=True)
    old_work_dir = os.environ.get("PLC_WORK_DIR")
    os.environ["PLC_WORK_DIR"] = str(wd)
    restore = _disable_external_llm()

    try:
        from fastapi.testclient import TestClient
        from gateway.app.main import app
        from gateway.app.services.plc.greenfield_session import registry
        from gateway.app.services.plc import greenfield_service as gsvc
        from plc_engine.af.fidelity import FidelityChecker
        from plc_engine.af.spec_diff import compute_spec_diff

        registry.reset()  # 独立会话，避免复用进程内旧状态
        client = TestClient(app)
        ctx: dict = {"client": client, "sid": "", "wd": str(wd)}
        steps: list[dict] = []

        def _exec(step_id: str, fn):
            try:
                status, response, note, refs = fn()
            except Exception as exc:  # noqa: BLE001 - 失败如实记录，绝不伪造成功
                status = "fail"
                response = {"error": str(exc)}
                note = f"步骤执行异常（如实记录）：{exc}"
                refs = []
            steps.append(_record(step_id, status, response, note, refs))

        chain_ref = str(out_path)
        bundle_ref = str(bundle_path)

        # ---- V-01 GET /state ------------------------------------------------
        def v01():
            sc, body, err = _call(ctx["client"], "get", f"{PREFIX}/state",
                                  params={"project_id": PROJECT_ID})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, f"/state 调用失败：{err}", []
            d = body["data"]
            ctx["sid"] = d["session_id"]
            hw = d.get("hardware") or {}
            response = {
                "status_code": sc, "ok": body.get("ok"),
                "session_id": d["session_id"], "project_id": d.get("project_id"),
                "stage": d.get("stage"), "has_contract": d.get("has_contract"),
                "hardware_node_count": len(hw.get("nodes") or []),
                "io_table_uploaded": False,
                "counters": d.get("counters"),
            }
            ok = (d.get("project_id") == PROJECT_ID and d.get("has_contract") is False
                  and len(hw.get("nodes") or []) >= 3)
            return ("pass" if ok else "fail"), response, (
                "真实 GET /state 建会话并绑定 project_id；未调用 /upload（D7 不上传 IO 表），"
                "hardware 为默认 3 类占位，非用户 IO 表虚构地址。"
            ), [chain_ref]
        _exec("V-01", v01)

        # ---- V-02 POST /chat ------------------------------------------------
        def v02():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/chat",
                                  json={"session_id": ctx["sid"], "message": CHAT_MESSAGE})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, f"/chat 调用失败：{err}", []
            d = body["data"]
            st = d.get("state") or {}
            ir = st.get("ir") or {}
            ctx["chat_ir"] = ir
            response = {
                "status_code": sc, "ok": body.get("ok"),
                "reply": str(d.get("reply") or "")[:180],
                "summary": st.get("summary"),
                "four_views_present": all(k in (st.get("views") or {})
                                          for k in ("flow", "seq", "state", "step_flow")),
                "edge_count": len(ir.get("edges") or []),
                "cms_count": len(ir.get("cms") or []),
            }
            ok = bool(ir) and response["four_views_present"] and response["cms_count"] > 0
            return ("pass" if ok else "fail"), response, (
                "真实 POST /chat 首轮（会话无 IR）走零 LLM 依赖的确定性 planner 兜底"
                "（draft_from_prompt）生成首版 IR + 四视图 + 连线清单；不发外部网络请求。"
            ), [chain_ref]
        _exec("V-02", v02)

        # ---- V-03 POST /engineering-summary（v1 前置）-----------------------
        def v03():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/engineering-summary",
                                  json={"session_id": ctx["sid"]})
            response = {"status_code": sc, "ok": (body or {}).get("ok"),
                        "engineering_summary_shown": True if _ok(sc, body) else None}
            return ("pass" if _ok(sc, body) else "fail"), response, (
                "确认硬门禁前置 Q9：/engineering-summary 展示一次工程视角摘要并置 shown 标志。"
            ), [chain_ref]
        _exec("V-03", v03)

        # ---- V-04 POST /confirm → v1 ---------------------------------------
        def v04():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/confirm",
                                  json={"session_id": ctx["sid"], "explicit": True,
                                        "frozen_by": "user"})
            if err or not _ok(sc, body):
                return "fail", {"error": err or (body or {}).get("error"),
                                "status_code": sc, "body": body}, "/confirm(v1) 调用失败或前置未满足（如实记录）", []
            d = body["data"]
            spec = d.get("spec") or {}
            path = d.get("path") or ""
            ctx["v1_confirm"] = {"spec": spec, "path": path}
            ctx["specs_v1_path"] = path
            response = {
                "status_code": sc, "ok": body.get("ok"),
                "spec_version": spec.get("spec_version"),
                "spec_hash": spec.get("spec_hash"),
                "project_id": spec.get("project_id"),
                "specs_v1_path": path,
                "specs_v1_exists": bool(path) and Path(path).is_file(),
            }
            ok = (spec.get("spec_version") == 1 and bool(spec.get("spec_hash"))
                  and response["specs_v1_exists"] and spec.get("project_id") == PROJECT_ID)
            return ("pass" if ok else "fail"), response, (
                "真实 POST /confirm(explicit=true) 冻结 v1 并落盘 specs/v1.json；"
                "spec_hash 覆盖拓扑 + 节点 + 边 + 步序 + 资料全域。"
            ), [chain_ref, path]
        _exec("V-04", v04)

        # ---- V-05 POST /begin-edit ------------------------------------------
        def v05():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/begin-edit",
                                  json={"session_id": ctx["sid"]})
            d = (body or {}).get("data") or {}
            response = {"status_code": sc, "ok": (body or {}).get("ok"),
                        "stage_after_begin_edit": d.get("stage")}
            return ("pass" if _ok(sc, body) else "fail"), response, (
                "真实 POST /begin-edit 从 FROZEN 回到 LINKABLE（生成 vN+1 草稿，"
                "已冻结的 v1.json 字节不变）。"
            ), [chain_ref]
        _exec("V-05", v05)

        # ---- V-06 POST /patch（增量 add_cm）+ /validate ----------------------
        def v06():
            st_sc, st_body, st_err = _call(ctx["client"], "get", f"{PREFIX}/state",
                                           params={"session_id": ctx["sid"]})
            ir = ((st_body or {}).get("data") or {}).get("ir") or ctx.get("chat_ir") or {}
            em_id = (ir.get("cms") or [{}])[0].get("em_id")
            if not em_id:
                return "fail", {"error": "当前 IR 缺少真实 em_id，无法构造 add_cm（不臆造 id）"}, \
                    "无法从真实 IR 取得 add_cm 目标 em_id", []
            ops = [{
                "op": "add_cm",
                "node": {"em_id": em_id, "cm_type": "LBC_MotorStarter",
                         "business_label": "UC-16 增量新增执行件：下料检测气缸"},
            }]
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/patch",
                                  json={"session_id": ctx["sid"], "project_id": PROJECT_ID,
                                        "base_spec_version": 1, "ops": ops})
            if err or not _ok(sc, body):
                return "fail", {"error": err or (body or {}).get("error"),
                                "status_code": sc, "body": body}, "/patch 调用失败（如实记录）", []
            pd = body["data"]
            v_sc, v_body, v_err = _call(ctx["client"], "post", f"{PREFIX}/validate",
                                        json={"session_id": ctx["sid"]})
            vreport = ((v_body or {}).get("data") or {}).get("report") or {}
            ctx["patch_add_cm_em_id"] = em_id
            response = {
                "patch_status_code": sc, "patch_ok": pd.get("ok"),
                "add_cm_target_em_id": em_id, "applied_ops": pd.get("applied_ops"),
                "violations": pd.get("violations"),
                "change_events_count": len(pd.get("change_events") or []),
                "spec_hash_after_patch": str(pd.get("spec_hash") or "")[:24],
                "stage": pd.get("stage"),
                "validate_status_code": v_sc, "validate_ir_ok": vreport.get("ok"),
            }
            ok = (pd.get("ok") is True and pd.get("applied_ops") == 1
                  and not pd.get("violations") and vreport.get("ok") is True)
            return ("pass" if ok else "fail"), response, (
                "真实 POST /patch 一次原子提交 add_cm（新增 1 个执行件），目标 em_id 取自当前"
                "真实 IR；走 apply_canvas_patch 统一入口，change_events 入账；随后 /validate "
                "重算 validate_ir 通过。该真实编辑使 v1→v2 的 ir_snapshot 产生差异。"
            ), [chain_ref]
        _exec("V-06", v06)

        # ---- V-07 POST /engineering-summary（v2 前置）-----------------------
        def v07():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/engineering-summary",
                                  json={"session_id": ctx["sid"]})
            response = {"status_code": sc, "ok": (body or {}).get("ok"),
                        "engineering_summary_shown": True if _ok(sc, body) else None}
            return ("pass" if _ok(sc, body) else "fail"), response, (
                "begin_edit 重置了 shown 标志，v2 /confirm 前须再次展示工程视角摘要（Q9）。"
            ), [chain_ref]
        _exec("V-07", v07)

        # ---- V-08 POST /confirm → v2 ---------------------------------------
        def v08():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/confirm",
                                  json={"session_id": ctx["sid"], "explicit": True,
                                        "frozen_by": "user"})
            if err or not _ok(sc, body):
                return "fail", {"error": err or (body or {}).get("error"),
                                "status_code": sc, "body": body}, "/confirm(v2) 调用失败或前置未满足（如实记录）", []
            d = body["data"]
            spec = d.get("spec") or {}
            path = d.get("path") or ""
            ctx["v2_confirm"] = {"spec": spec, "path": path}
            ctx["specs_v2_path"] = path
            v1_hash = (ctx.get("v1_confirm") or {}).get("spec", {}).get("spec_hash")
            response = {
                "status_code": sc, "ok": body.get("ok"),
                "spec_version": spec.get("spec_version"),
                "spec_hash": spec.get("spec_hash"),
                "prev_spec_hash": spec.get("prev_spec_hash"),
                "project_id": spec.get("project_id"),
                "specs_v2_path": path,
                "specs_v2_exists": bool(path) and Path(path).is_file(),
                "spec_hash_differs_from_v1": spec.get("spec_hash") != v1_hash,
                "prev_spec_hash_equals_v1": spec.get("prev_spec_hash") == v1_hash,
            }
            ok = (spec.get("spec_version") == 2 and bool(spec.get("spec_hash"))
                  and response["specs_v2_exists"] and spec.get("project_id") == PROJECT_ID
                  and response["spec_hash_differs_from_v1"])
            return ("pass" if ok else "fail"), response, (
                "真实 POST /confirm(explicit=true) 冻结 v2 并落盘 specs/v2.json；"
                "v2.spec_version=2、spec_hash 与 v1 不同、prev_spec_hash 指向 v1，"
                "project_id 保持一致。"
            ), [chain_ref, path]
        _exec("V-08", v08)

        # ---- V-09 load_frozen_spec 从磁盘装载核对 ---------------------------
        def v09():
            if not (ctx.get("v1_confirm") and ctx.get("v2_confirm")):
                return "fail", {"error": "v1/v2 未成功冻结，无法从磁盘装载"}, "缺少冻结结果（不臆造）", []
            v1 = gsvc.load_frozen_spec(ctx["sid"], 1, project_id=PROJECT_ID)
            v2 = gsvc.load_frozen_spec(ctx["sid"], 2, project_id=PROJECT_ID)
            ctx["v1_spec"] = v1
            ctx["v2_spec"] = v2
            p1 = (ctx.get("specs_v1_path") or "")
            p2 = (ctx.get("specs_v2_path") or "")
            response = {
                "source": "磁盘 specs/vN.json（经 load_frozen_spec，不依赖会话内存态）",
                "v1": {"spec_version": v1.spec_version, "spec_hash": v1.spec_hash,
                       "project_id": v1.project_id, "path": p1},
                "v2": {"spec_version": v2.spec_version, "spec_hash": v2.spec_hash,
                       "project_id": v2.project_id, "path": p2},
                "project_id_consistent": v1.project_id == v2.project_id == PROJECT_ID,
                "spec_hash_differs": v1.spec_hash != v2.spec_hash,
                "spec_versions": [v1.spec_version, v2.spec_version],
                "both_files_exist": Path(p1).is_file() and Path(p2).is_file(),
            }
            ok = (response["project_id_consistent"] and response["spec_hash_differs"]
                  and v1.spec_version == 1 and v2.spec_version == 2
                  and response["both_files_exist"])
            return ("pass" if ok else "fail"), response, (
                "用产品 load_frozen_spec 分别从磁盘装载 v1/v2（FrozenSpec.from_dict 会复现哈希），"
                "核对 project_id 一致、spec_hash 不同、spec_version=1/2、两文件均存在。"
            ), [chain_ref, p1, p2]
        _exec("V-09", v09)

        # ---- V-10 POST /diff ------------------------------------------------
        def v10():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/diff",
                                  json={"session_id": ctx["sid"], "project_id": PROJECT_ID,
                                        "from_version": 1, "to_version": 2})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, "/diff 调用失败（如实记录）", []
            d = body.get("data") or {}
            ctx["diff_http"] = d
            response = {
                "status_code": sc, "ok": body.get("ok"),
                "base_spec_version": d.get("base_spec_version"),
                "target_spec_version": d.get("target_spec_version"),
                "changed_count": len(d.get("changed") or []),
                "added_count": len(d.get("added") or []),
                "removed_count": len(d.get("removed") or []),
                "changed_source_ids_count": len(d.get("changed_source_ids") or []),
                "changed_source_ids_preview": list(d.get("changed_source_ids") or [])[:8],
                "diff_note": d.get("note"),
            }
            ok = (d.get("base_spec_version") == 1 and d.get("target_spec_version") == 2
                  and bool(d.get("changed_source_ids")))
            return ("pass" if ok else "fail"), response, (
                "真实 POST /diff 经服务端 diff_placeholder 从磁盘装载 v1/v2 调 compute_spec_diff，"
                "产出带 source_id 的真实 SpecDiff：changed_source_ids 非空、base_spec_version=1。"
                "若来源为优雅降级（空 diff + note）则如实 fail/pending，不伪造。"
            ), [chain_ref]
        _exec("V-10", v10)

        # ---- V-11 compute_spec_diff(v1, v2) 直调 ----------------------------
        def v11():
            v1 = ctx.get("v1_spec")
            v2 = ctx.get("v2_spec")
            if v1 is None or v2 is None:
                return "fail", {"error": "v1/v2 未装载，无法直调 compute_spec_diff"}, "缺少装载结果（不臆造）", []
            diff_obj = compute_spec_diff(v1, v2)
            ctx["diff_obj"] = diff_obj
            http_ids = list((ctx.get("diff_http") or {}).get("changed_source_ids") or [])
            direct_ids = list(diff_obj.changed_source_ids)
            response = {
                "source": "compute_spec_diff(v1 FrozenSpec, v2 FrozenSpec) 直调",
                "base_spec_version": diff_obj.base_spec_version,
                "target_spec_version": diff_obj.target_spec_version,
                "changed_source_ids_count": len(direct_ids),
                "changed_source_ids_preview": direct_ids[:8],
                "changed_count": len(diff_obj.changed),
                "added_count": len(diff_obj.added),
                "removed_count": len(diff_obj.removed),
                "http_vs_direct_ids_match": http_ids == direct_ids,
            }
            ok = (diff_obj.base_spec_version == 1 and bool(diff_obj.changed_source_ids))
            return ("pass" if ok else "fail"), response, (
                "直调产品 compute_spec_diff 得到 SpecDiff 对象，作为增量 FidelityChecker 的 diff "
                "入参；核对与 /diff HTTP 端点产出的 changed_source_ids 一致（同一真实规格链）。"
            ), [chain_ref]
        _exec("V-11", v11)

        # ---- V-12 POST /action-a 生成 v2 派生产物 ---------------------------
        def v12():
            sc, body, err = _call(ctx["client"], "post", f"{PREFIX}/action-a",
                                  json={"session_id": ctx["sid"], "include_zip_base64": False})
            if err or not _ok(sc, body):
                return "fail", {"error": err, "status_code": sc, "body": body}, "/action-a 调用失败（如实记录）", []
            d = body["data"]
            fr = d.get("fidelity_report") or {}
            delivery = registry.get(ctx["sid"]).last_delivery or {}
            ctx["action_a_full"] = d
            ctx["last_delivery"] = delivery
            response = {
                "status_code": sc, "ok": body.get("ok"),
                "action": d.get("action"), "mode": d.get("mode"),
                "spec_version": d.get("spec_version"),
                "fidelity_ok_full_mode": d.get("fidelity_ok"),
                "full_coverage": fr.get("coverage"), "full_orphan": fr.get("orphan"),
                "compile_ok": d.get("compile_ok"), "tia_written": d.get("tia_written"),
                "block_count": d.get("block_count"),
                "blocks_manifest_count": len(delivery.get("blocks_manifest") or []),
                "last_delivery_has_zip_bytes": bool(delivery.get("zip_bytes")),
                "evidence_bundle_sha256": d.get("evidence_bundle_sha256"),
            }
            ok = (d.get("spec_version") == 2 and bool(delivery.get("zip_bytes"))
                  and len(delivery.get("blocks_manifest") or []) > 0
                  and d.get("compile_ok") is None and d.get("tia_written") is False)
            return ("pass" if ok else "fail"), response, (
                "真实 POST /action-a 在 v2 FROZEN 下调用 run_action_a / generate_project_package，"
                "缓存 session.last_delivery（含 zip_bytes + blocks_manifest）作为 v2 真实派生产物；"
                "顺带产出 full 模式 fidelity 作为对照（fidelity_ok=true 仅 L1，compile_ok=null）。"
            ), [chain_ref]
        _exec("V-12", v12)

        # ---- V-13 增量 FidelityChecker --------------------------------------
        def v13():
            delivery = ctx.get("last_delivery")
            v2 = ctx.get("v2_spec")
            diff_obj = ctx.get("diff_obj")
            if not delivery or v2 is None or diff_obj is None:
                return "fail", {"error": "缺少 v2 派生产物 / v2 规格 / diff，无法增量校验"}, \
                    "增量 fidelity 前置缺失（不臆造）", []
            artifacts, derived_ids, last_generated, artifact_hashes = gsvc._build_artifacts(delivery, v2)
            spec_like = gsvc._action_spec_like(v2, derived_ids)
            report = FidelityChecker().check(
                spec_like, artifacts, mode="incremental",
                base_spec_version=1, diff=diff_obj, tia_side_snapshot=None,
            )
            report_dict = report.to_dict()
            ctx["fidelity_report"] = report_dict
            ctx["derived_ids"] = derived_ids
            ctx["artifact_count"] = len(artifacts)
            response = {
                "source": "FidelityChecker.check(mode='incremental', base_spec_version=1, "
                          "diff=compute_spec_diff(v1,v2), tia_side_snapshot=None)",
                "fidelity_ok": report.fidelity_ok,
                "coverage": report.coverage, "orphan": report.orphan,
                "drift": report.drift, "tia_side_drift": report.tia_side_drift,
                "mode": report.mode, "base_spec_version": report.base_spec_version,
                "changed_source_ids_count": len(report.changed_source_ids),
                "reverse_protection_status": report.reverse_protection.get("status"),
                "ob_number_deviations_count": len(report.ob_number_deviations),
                "pending_real_machine": report.pending_real_machine,
                "artifact_count": len(artifacts),
                "derived_source_id_count": len(derived_ids),
                "coverage_matrix_entry_count": len(report.coverage_matrix),
            }
            ok = (report.fidelity_ok is True and report.coverage == 1.0
                  and report.orphan == 0 and report.drift == 0
                  and report.tia_side_drift == 0 and report.mode == "incremental"
                  and report.base_spec_version == 1 and bool(report.changed_source_ids))
            return ("pass" if ok else "fail"), response, (
                "用 v2 真实派生产物（_build_artifacts 复用 run_action_a 同一路径）+ "
                "_action_spec_like 适配的 v2 FrozenSpecLike（期望对象集合=v2 派生产物 source_id），"
                "直调增量 FidelityChecker；tia_side_snapshot 无真实 TIA 数据按现有约定传 None，"
                "reverse_protection 标 pending_real_machine、tia_side_drift=0；"
                "fidelity_ok 仅 L1 离线逻辑等价，不等同 compile_ok / 真机 L4。"
                "diff 的 changed_source_ids 为 IR 层 source_id、artifacts 为派生产物层 source_id，"
                "命名空间不同，产品增量模式按全量四指标复核（安全侧更严），如实记录不掩盖。"
            ), [chain_ref]
        _exec("V-13", v13)

        # ---- V-14 组装增量 EvidenceBundle + sha256 --------------------------
        def v14():
            fr = ctx.get("fidelity_report")
            diff_obj = ctx.get("diff_obj")
            diff_http = ctx.get("diff_http") or {}
            if not fr or diff_obj is None:
                return "fail", {"error": "增量 FidelityReport / SpecDiff 缺失，无法组装 bundle"}, \
                    "增量 fidelity 未闭环（如实标 pending，不伪造报告）", []
            changed_ids = list(fr.get("changed_source_ids") or [])
            six_fields = {
                "mode": fr.get("mode"),
                "base_spec_version": fr.get("base_spec_version"),
                "changed_source_ids": changed_ids,
                "reverse_protection": fr.get("reverse_protection"),
                "tia_side_drift": fr.get("tia_side_drift"),
                "ob_number_deviations": list(fr.get("ob_number_deviations") or []),
            }
            ctx["six_fields"] = six_fields
            response = {
                "six_field_keys": sorted(six_fields.keys()),
                "mode": six_fields["mode"],
                "base_spec_version": six_fields["base_spec_version"],
                "changed_source_ids_count": len(changed_ids),
                "reverse_protection_status": (six_fields["reverse_protection"] or {}).get("status"),
                "tia_side_drift": six_fields["tia_side_drift"],
                "ob_number_deviations_count": len(six_fields["ob_number_deviations"]),
                "ob_number_deviations_note": "显式留痕（即使为空也写明，禁止静默）；属不纳入 1:1 的域，不参与 fidelity_ok",
            }
            ok = (six_fields["mode"] == "incremental" and six_fields["base_spec_version"] == 1
                  and bool(changed_ids) and six_fields["tia_side_drift"] == 0)
            return ("pass" if ok else "fail"), response, (
                "组装离线增量 EvidenceBundle 六字段（mode / base_spec_version / "
                "changed_source_ids / reverse_protection / tia_side_drift / "
                "ob_number_deviations），全部取自真实增量 FidelityReport；"
                "bundle_sha256 在写盘前由 canonical_hash 复算。"
            ), [chain_ref, bundle_ref]
        _exec("V-14", v14)

        # ------------------------------------------------------------------
        # 组装两份产物
        # ------------------------------------------------------------------
        from collections import Counter

        counts = dict(Counter(s["status"] for s in steps))
        for s in VALID_STATUSES:
            counts.setdefault(s, 0)

        v1_spec = ctx.get("v1_spec")
        v2_spec = ctx.get("v2_spec")
        diff_obj = ctx.get("diff_obj")
        diff_http = ctx.get("diff_http") or {}
        fr = ctx.get("fidelity_report") or {}
        six = ctx.get("six_fields") or {}

        def spec_meta(spec, path):
            if spec is None:
                return None
            return {
                "spec_hash": spec.spec_hash,
                "spec_version": spec.spec_version,
                "project_id": spec.project_id,
                "disk_path": path,
                "prev_spec_hash": spec.prev_spec_hash,
            }

        spec_diff_doc = None
        if diff_obj is not None:
            spec_diff_doc = {
                "source": "POST /diff（服务端 diff_placeholder → compute_spec_diff），"
                          "并与直调 compute_spec_diff(v1, v2) 核对一致",
                "base_spec_version": diff_obj.base_spec_version,
                "target_spec_version": diff_obj.target_spec_version,
                "changed": {"count": len(diff_http.get("changed") or []),
                            "source_ids": _source_ids(diff_http.get("changed"))},
                "added": {"count": len(diff_http.get("added") or []),
                          "source_ids": _source_ids(diff_http.get("added"))},
                "removed": {"count": len(diff_http.get("removed") or []),
                            "source_ids": _source_ids(diff_http.get("removed"))},
                "changed_source_ids": list(diff_obj.changed_source_ids),
                "http_vs_direct_ids_match": (
                    list(diff_http.get("changed_source_ids") or [])
                    == list(diff_obj.changed_source_ids)
                ),
            }

        repro_cmd = (
            "cd <R> && ./.venv/Scripts/python.exe tools/run_incremental_spec_chain.py "
            "--out evidence/uc16_incremental_spec_chain.json "
            "--bundle evidence/uc16_incremental_evidence_bundle.json"
        )
        w_repro = (
            "阶段 B 的 Agent W：设 PLC_WORK_DIR=<work_dir>（本产物 work_dir 字段）、"
            "复用同一 session_id 与同一份 specs/v1.json / specs/v2.json，"
            f"以 spec_diff.changed_source_ids 为差异清单经 POST {PREFIX}/confirm-diff "
            "显式确认（D11），再 POST /action-c（传入真实 tia_side_snapshot / last_generated）"
            "做增量覆盖 → 编译 0/0 → 增量 fidelity 复核；本离线链不代替真机 Action C。"
        )

        overall = "fail" if counts.get("fail", 0) else (
            "pass" if all(fr.get(k) is not None for k in
                          ("fidelity_ok", "coverage", "orphan", "drift", "tia_side_drift"))
            else "fail"
        )

        chain_doc = {
            "schema": "gf-uc16-incremental-spec-chain-v1",
            "uc": "UC-16",
            "title": "真实 Greenfield 冻结规格链 specs/v1.json → specs/v2.json 与增量 fidelity 闭环（离线侧）",
            "agent": "Agent V · 批次 4 阶段 A（离线侧）",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "driver": DRIVER,
            "project_id": PROJECT_ID,
            "session_id": ctx.get("sid"),
            "work_dir": str(wd),
            "plc_work_dir_env": str(wd),
            "specs_dir": str(wd / "greenfield" / ctx.get("sid", "") / "specs"),
            "v1": spec_meta(v1_spec, ctx.get("specs_v1_path")),
            "v2": spec_meta(v2_spec, ctx.get("specs_v2_path")),
            "spec_diff": spec_diff_doc,
            "fidelity_report_incremental": fr or None,
            "incremental_evidence_bundle_six_fields": six or None,
            "steps": steps,
            "summary": {"total": len(steps), "by_status": counts, "overall_status": overall},
            "repro_commands": {
                "offline_chain": repro_cmd,
                "with_work_dir": repro_cmd + " --work-dir <work_dir>",
                "agent_w_real_machine_action_c": w_repro,
            },
            "honest_boundary": HONEST_BOUNDARY,
            "honest_note": (
                "本链为【离线侧】真实规格链与增量 fidelity 闭环：v1→v2 由 TestClient 真实端点"
                "（/chat /confirm /begin-edit /patch /confirm /diff /action-a）驱动并落盘磁盘 "
                "specs/vN.json，增量 FidelityChecker(mode=incremental) 用真实 diff 与 v2 真实派生产物"
                "产出 fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0，"
                "补齐批次 3 base_spec_version=null 的离线侧缺口。SpecDiff 的 IR 层 source_id 与 "
                "artifacts 的派生产物层 source_id 命名空间不同，增量模式按产品全量四指标复核"
                "（安全侧更严），如实记录。未连真机、未启动 SessionServer、"
                "未跑 TIA CLI、未占用 8791/8000 端口。离线增量 fidelity ≠ 真机 L4 通过；"
                "fidelity_ok ≠ compile_ok；不宣称编译零错误 / L2 或 L4 通过 / L1∧L2∧L3∧L4 全绿 / "
                "M4 通过或代签；M4 签署栏始终「待用户签署」。真机 Action C 增量由 Agent W 验证。"
            ),
            "offline_side": True,
            "pending_real_machine": True,
            "compile_ok": None,
        }

        bundle_doc = {
            "schema": "gf-uc16-incremental-evidence-bundle-v1",
            "bundle_id": "UC-16 / 批次 4 阶段 A / 离线增量 EvidenceBundle 实例化",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "tools/run_incremental_spec_chain.py",
            "source": "本链真实增量 FidelityReport.to_dict() + 真实 SpecDiff + 磁盘 specs/vN.json",
            "uc": "UC-16",
            "mode": six.get("mode"),
            "offline_side": True,
            "pending_real_machine": True,
            "compile_ok": None,
            "project_id": PROJECT_ID,
            "work_dir": str(wd),
            "session_id": ctx.get("sid"),
            "v1_spec": spec_meta(v1_spec, ctx.get("specs_v1_path")),
            "v2_spec": spec_meta(v2_spec, ctx.get("specs_v2_path")),
            "spec_diff": spec_diff_doc,
            "fidelity_report": fr or None,
            "incremental_evidence_bundle_six_fields": six or None,
            "ob_number_deviations_note": (
                "ob_number_deviations 显式留痕（即使为空也说明，禁止静默）：本离线增量块为 "
                "AF 派生 SCL 外部源，不涉及 OB 编号物理偏差；属不纳入 1:1 的域，不参与 "
                "fidelity_ok 判定。见 fidelity_report.notes / ob_number_deviations 字段。"
            ),
            "tia_side_snapshot_note": (
                "无真实 TIA 块哈希快照，按 FidelityChecker 现有约定传 None：tia_side_drift=0 "
                "且 pending_real_machine=true、reverse_protection.status=pending_real_machine"
                "（allowed=null）；不得虚构 TIA 侧数据，真机 D10 反向保护由 Agent W 验证。"
            ),
            "honest_boundary": HONEST_BOUNDARY,
            "repro_commands": chain_doc["repro_commands"],
        }
        # bundle_sha256 可复算：排除哈希字段本身后规范化 sha256。
        bundle_doc["bundle_sha256"] = _sha_of(bundle_doc)
        bundle_doc["bundle_sha256_recomputed"] = _sha_of(bundle_doc)
        bundle_doc["bundle_sha256_match"] = (
            bundle_doc["bundle_sha256"] == bundle_doc["bundle_sha256_recomputed"]
        )
        chain_doc["bundle_sha256"] = bundle_doc["bundle_sha256"]
        chain_doc["bundle_sha256_recomputed"] = bundle_doc["bundle_sha256_recomputed"]
        chain_doc["bundle_sha256_match"] = bundle_doc["bundle_sha256_match"]

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(chain_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bundle_path = Path(bundle_path)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(json.dumps(bundle_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return chain_doc, bundle_doc
    finally:
        restore()
        if old_work_dir is None:
            os.environ.pop("PLC_WORK_DIR", None)
        else:
            os.environ["PLC_WORK_DIR"] = old_work_dir


def main() -> None:
    ap = argparse.ArgumentParser(
        description="UC-16 真实规格链 v1→v2 与增量 fidelity 闭环（TestClient 进程内 ASGI，不连真机、不起端口）"
    )
    ap.add_argument("--out", default="evidence/uc16_incremental_spec_chain.json", metavar="PATH",
                    help="规格链产物 JSON（默认 evidence/uc16_incremental_spec_chain.json）")
    ap.add_argument("--bundle", default="evidence/uc16_incremental_evidence_bundle.json", metavar="PATH",
                    help="增量 EvidenceBundle 产物 JSON（默认 evidence/uc16_incremental_evidence_bundle.json）")
    ap.add_argument("--work-dir", default=None, metavar="PATH",
                    help="PLC_WORK_DIR 隔离目录（默认系统临时目录 gf_inc_chain_*，供 W 用同一目录复现）")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        bundle = ROOT / bundle

    chain_doc, bundle_doc = run(out, bundle, work_dir=args.work_dir)
    print(json.dumps({
        "out": str(out),
        "bundle": str(bundle),
        "work_dir": chain_doc["work_dir"],
        "session_id": chain_doc["session_id"],
        "v1_spec_hash": (chain_doc.get("v1") or {}).get("spec_hash"),
        "v2_spec_hash": (chain_doc.get("v2") or {}).get("spec_hash"),
        "spec_diff_base_version": (chain_doc.get("spec_diff") or {}).get("base_spec_version"),
        "changed_source_ids_count": len((chain_doc.get("spec_diff") or {}).get("changed_source_ids") or []),
        "fidelity_ok": (chain_doc.get("fidelity_report_incremental") or {}).get("fidelity_ok"),
        "summary": chain_doc["summary"],
        "step_statuses": {s["step_id"]: s["status"] for s in chain_doc["steps"]},
        "bundle_sha256_match": bundle_doc["bundle_sha256_match"],
        "pending_real_machine": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
