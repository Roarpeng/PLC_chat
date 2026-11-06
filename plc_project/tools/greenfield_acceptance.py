"""WP-10 全量验收编排器（Agent I / 纯新增工具，不改任何产品代码）。

职责（契约 05 §2/§4/§5/§6、Plan §3 M4 / §7 / §9.3 / 基线报告 §9.2 / §13.9）：
- 读取 ``evidence/rtm.json`` / ``acceptance_template.json`` / ``pending_real_machine.json``；
- 编排 §9.2 九步端到端与 §13.9 六条增量用例的步骤，逐步留痕（状态 + 复现命令 + 证据产物）；
- 汇总 ``L1 ∧ L2 ∧ L3 ∧ L4`` 复核结论与 M4 是否可签署；
- 内置 pending 台账累计与清零检查：**pending 清零前 M4 必须保持未通过**。

诚实口径（硬约束，不得违反）：
- ``--offline`` 只跑可离线的静态检查，明确标注 **L2/L4 = pending_real_machine**；
  不连真机、不启动产品链、不 import 产品代码、不产生任何编译/导入结果；
- ``--real-machine`` 必须显式指定 ``--workdir`` 且只允许 ``AppData/Local/Temp/gf_real_*`` 临时副本；
  检测到 ``PLC_Openness_data`` 原始路径即 fail-closed 拒绝；
- 能调现有 CLI/HTTP 就调，不能则留 ``not_run`` + 复现命令；**绝不伪造结果、绝不编造真机编译数字**；
- 真机逐条实测由主 agent 收口执行，本编排器不代跑产品链、不把 pending 视为通过；
- ``fidelity_ok`` 与 ``compile_ok`` 独立（N9）；D12 hard refuse 全程约束。

用法::

    python tools/greenfield_acceptance.py --offline
    python tools/greenfield_acceptance.py --offline --out evidence/offline_run.json
    python tools/greenfield_acceptance.py --real-machine --workdir C:/.../Temp/gf_real_*/副本.ap19

退出码: 默认 ``0`` = 报告成功生成（判定结果在输出的 ``m4`` 字段里）；
``--strict`` 且 M4 未通过时返回 ``1``；fail-closed 拒绝（workdir 非法）返回 ``2``。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
EVIDENCE_DIR = ROOT / "evidence"
PROBE_EXE = (
    ROOT / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server"
    / "bin" / "Release" / "net481" / "TiaOpenness.Server.exe"
)

FOUR_LAYERS = ("L1", "L2", "L3", "L4")
REAL_MACHINE_LAYERS = ("L2", "L4")  # 涉真机层：离线模式一律不判 pass
VALID_STATUSES = frozenset({
    "pass", "fail", "pending_real_machine", "not_run", "preexisting_baseline_failure",
})

# EvidenceBundle 期望清单（Plan §7.2 / 基线报告 §9.3 / §13.6）—— 用于模板结构校验
EXPECTED_FULL_ARTIFACTS = (
    "specs_vN_json", "ir_snapshot", "four_views_export", "edge_list",
    "open_questions_clearance", "static_gate_results", "fidelity_report_json",
    "structured_compile_report", "pcec_ledger", "baseline_manifest_json",
    "artifact_hashes", "zap19_archive",
)
EXPECTED_INCREMENTAL_FIELDS = (
    "mode", "base_spec_version", "changed_source_ids", "reverse_protection",
    "tia_side_drift", "ob_number_deviations",
)

# §9.2 九步端到端（基线报告 v2.1 §9.2）
NINE_STEPS = [
    {
        "id": "NINE-01", "uc": "UC-15",
        "name": "新建项目：选 PLC 逻辑占位 + 3 类外围设备占位（不上传 IO 表，验证 D7）",
        "requires": "offline",
        "repro_command": "POST /api/v1/plc/canvas/greenfield/state + /hardware（project_id 绑定会话/拓扑）；不上传 IO 表",
        "evidence_artifacts": ["specs/vN.json", "ir_snapshot"],
        "note": "验证无上传资料时也能完成拓扑与逻辑确认，产物不虚构地址/OB 条目。",
    },
    {
        "id": "NINE-02", "uc": "UC-15",
        "name": "对话输入自然语言描述设备运行逻辑 → canvas 渲染",
        "requires": "offline",
        "repro_command": "POST /api/v1/plc/canvas/greenfield/chat（注入已定拓扑作约束，绑定 project_id）",
        "evidence_artifacts": ["四视图导出", "连线清单"],
        "note": "对话结果不得与已定拓扑矛盾。",
    },
    {
        "id": "NINE-03", "uc": "UC-15",
        "name": "手动：新增 1 个执行件、删除 1 条连线、修改 1 条工站交互、改 1 处步序条件（D6 + 双向同步）",
        "requires": "offline",
        "repro_command": "POST /api/v1/plc/canvas/greenfield/patch（收敛到 apply_canvas_patch，禁止直接写 session.ir.*）",
        "evidence_artifacts": ["四视图导出", "变更事件入账记录"],
        "note": "原子拒绝、validate_ir 通过后才提交。",
    },
    {
        "id": "NINE-04", "uc": "UC-15",
        "name": "确认设备逻辑 → 冻结 v1，检查 spec_hash 覆盖拓扑与全部编辑",
        "requires": "offline",
        "repro_command": "POST /api/v1/plc/canvas/greenfield/confirm（前置：拓扑定稿 / open_questions 清零 / 连线校验 / 等价性预检 / 基线版本锁定）",
        "evidence_artifacts": ["specs/vN.json", "open_questions 清零记录", "spec_hash"],
        "note": "确认前 ops/disk_writes/writebacks/generations 恒 0。",
    },
    {
        "id": "NINE-05", "uc": "UC-15",
        "name": "Action A 导出工程包 → fidelity_report.json 为 fidelity_ok=true、coverage 100%、orphan 0",
        "requires": "offline",
        "repro_command": "POST /api/v1/plc/canvas/greenfield/action-a（契约 05 §3.2；可离线校验、不改 TIA）",
        "evidence_artifacts": ["fidelity_report.json", "EvidenceBundle", "静态门禁结果"],
        "note": "fidelity_ok 与 compile_ok 独立（N9），Action A 不得据编译结论。",
    },
    {
        "id": "NINE-06", "uc": "UC-15",
        "name": "两个负例：人为删除一个产物块 → fidelity_ok=false 且列 unmapped_spec_objects；人为塞入无来源逻辑块 → orphan=1",
        "requires": "offline",
        "repro_command": "FidelityChecker.check(...) 负例（tests/unit/test_greenfield_fidelity.py）",
        "evidence_artifacts": ["负例报告", "fidelity_report.json"],
        "note": "纯只读校验器可覆盖。",
    },
    {
        "id": "NINE-07", "uc": "UC-15",
        "name": "Action B 写入博途 V19 → 编译零错误 → 归档 .zap19 + 结构化编译报告",
        "requires": "real_machine",
        "repro_command": "POST /api/v1/plc/canvas/greenfield/action-b（前置 A 的 fidelity_ok==true）；或 --cli compile-plc --project <Temp/gf_real_*/副本.ap19> --plc PLC_1；归档 project.zap19",
        "evidence_artifacts": [".zap19", "结构化编译报告", "PCEC 账本"],
        "note": "真机编译结论必须是真实 CLI/HTTP 返回（error_count / warnings / blocks / elapsed_ms / tia_version / project_path）；禁止 mock、禁止编造零错误。",
    },
    {
        "id": "NINE-08", "uc": "UC-15",
        "name": "重跑步骤 4-5（不改任何输入）→ 产物哈希一致（L3）",
        "requires": "offline",
        "repro_command": "同 spec_hash 重跑冻结与 Action A 导出，比对产物哈希（artifact_hashes.json / integrity.sha256）",
        "evidence_artifacts": ["reproducibility 记录", "产物哈希"],
        "note": "L3 可复现。",
    },
    {
        "id": "NINE-09", "uc": "UC-15",
        "name": "服务重启 → 从 specs/v1.json 恢复画布，与确认时完全一致",
        "requires": "offline",
        "repro_command": "GET /api/v1/plc/canvas/greenfield/specs/1?project_id= 后重启服务并重建画布",
        "evidence_artifacts": ["重启恢复记录", "specs/v1.json"],
        "note": "FrozenSpec 必须可仅凭 specs/vN.json 完整重建画布（含拓扑），不依赖会话内存态。",
    },
]

# §13.9 六条增量验收用例（基线报告 v2.1 §13.9）
SIX_INCREMENTAL_CASES = [
    {
        "id": "INC-01", "uc": "UC-16",
        "name": "/open 一次，记录会话与项目路径",
        "requires": "real_machine",
        "repro_command": "SessionServer /open 一次并保持会话（D9）；后续迭代不再 open、不再 create-project",
        "evidence_artifacts": ["会话句柄复用记录", "PCEC 账本"],
        "note": "会话句柄在同一进程/同一 HTTP 会话内复用。",
    },
    {
        "id": "INC-02", "uc": "UC-16",
        "name": "改 1 个 EM 步序 → 差异清单确认 → 覆盖 → 编译 → fidelity_ok",
        "requires": "real_machine",
        "repro_command": "/diff → /confirm-diff（confirmed=true，D11）→ /fast-writeback → /compile-plc → 增量 fidelity；每次成功增量写 1 条 PCEC",
        "evidence_artifacts": ["增量 fidelity_report", "PCEC 账本"],
        "note": "确认前四计数器恒 0；fidelity_ok 且 error_count==0 且 tia_side_drift==0。",
    },
    {
        "id": "INC-03", "uc": "UC-16",
        "name": "新增 1 个 CM → 同上；改 1 条工站交互连线 → 同上（共 3 次增量）",
        "requires": "real_machine",
        "repro_command": "同 INC-02，连续 3 次；项目不关闭 / 不重载 / 不新建",
        "evidence_artifacts": ["增量 fidelity_report", "PCEC 账本 3 条"],
        "note": "三次增量 = PCEC 3 条。",
    },
    {
        "id": "INC-04", "uc": "UC-16",
        "name": "全程校验项目未关闭/未重载、会话句柄复用、PCEC 账本三条记录",
        "requires": "real_machine",
        "repro_command": "核对 session_handle 复用、project_path 不变、PCEC 条数==3",
        "evidence_artifacts": ["会话句柄复用记录", "PCEC 账本"],
        "note": "P0-G 验收不等于 L4 通过；完整 L4 还需 fidelity_ok 与 tia_side_drift==0。",
    },
    {
        "id": "INC-05", "uc": "UC-16",
        "name": "负例 D10：在 TIA 侧手工改动一个无关块 → 第 4 次增量被阻止并提示，不得覆盖",
        "requires": "real_machine",
        "repro_command": "reverse_guard.allowed==false / tia_side_drift>0 时 Action C 在 §13.5 步骤 3 被阻止（fail-closed）",
        "evidence_artifacts": ["阻止记录", "reverse_protection / tia_side_drift 报告"],
        "note": "禁止先覆盖再提示。",
    },
    {
        "id": "INC-06", "uc": "UC-16",
        "name": "回滚演练：触发一次失败导入，验证项目回到调用前状态且备份可恢复",
        "requires": "real_machine",
        "repro_command": "写前备份 sha256 + 失败导入 + 回滚钩子（writeback_safety.py / FastWriteback.cs）",
        "evidence_artifacts": ["回滚记录", "写前备份 sha256"],
        "note": "失败时项目回滚到调用前状态。",
    },
]


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_evidence(evidence_dir: Path | None = None) -> tuple[dict, dict, dict]:
    """加载三份证据台账（UTF-8 JSON）。缺文件即显式抛错，不静默降级。"""
    d = evidence_dir or EVIDENCE_DIR
    rtm = json.loads((d / "rtm.json").read_text(encoding="utf-8"))
    tpl = json.loads((d / "acceptance_template.json").read_text(encoding="utf-8"))
    ledger = json.loads((d / "pending_real_machine.json").read_text(encoding="utf-8"))
    return rtm, tpl, ledger


# ---------------------------------------------------------------------------
# 纯函数（供单测直接调用，不连真机）
# ---------------------------------------------------------------------------
def validate_rtm(rtm: dict) -> dict:
    """RTM 结构完整性：19 个 UC 编号唯一、必需字段齐全、状态词合法。"""
    cases = rtm.get("cases", [])
    ucs = [c.get("uc") for c in cases]
    expected = [f"UC-{i:02d}" for i in range(1, 20)]
    missing_uc = [u for u in expected if u not in ucs]
    duplicate_uc = len(ucs) != len(set(ucs))
    required = (
        "uc", "scenario", "requirement", "source", "work_package", "owner",
        "gate", "layer", "evidence_artifacts", "status", "notes",
    )
    invalid: list[str] = []
    for c in cases:
        for f in required:
            if f not in c:
                invalid.append(f"{c.get('uc')}:missing:{f}")
        if c.get("status") not in VALID_STATUSES:
            invalid.append(f"{c.get('uc')}:bad_status:{c.get('status')}")
    counts = dict(Counter(c.get("status") for c in cases))
    return {
        "complete": (
            len(cases) == 19 and not missing_uc and not duplicate_uc and not invalid
        ),
        "case_count": len(cases),
        "expected_case_count": 19,
        "missing_uc": missing_uc,
        "duplicate_uc": duplicate_uc,
        "invalid_fields": invalid,
        "counts": counts,
    }


def validate_evidence_template(tpl: dict) -> dict:
    """EvidenceBundle 结构完整性：全量 12 项 + 增量 6 字段 + ob_number_deviations 留痕策略。"""
    full_ids = [a.get("id") for a in tpl.get("full_artifacts", [])]
    inc_names = [f.get("name") for f in tpl.get("incremental_fields", [])]
    missing_full = [x for x in EXPECTED_FULL_ARTIFACTS if x not in full_ids]
    missing_inc = [x for x in EXPECTED_INCREMENTAL_FIELDS if x not in inc_names]
    policy = tpl.get("ob_number_deviations_policy", "") or ""
    ob_present = "ob_number_deviations" in inc_names
    ob_policy_ok = ("必须留痕" in policy or "禁止静默" in policy) and ob_present
    return {
        "complete": not missing_full and not missing_inc and ob_policy_ok,
        "full_count": len(full_ids),
        "expected_full_count": len(EXPECTED_FULL_ARTIFACTS),
        "incremental_count": len(inc_names),
        "expected_incremental_count": len(EXPECTED_INCREMENTAL_FIELDS),
        "missing_full": missing_full,
        "missing_incremental": missing_inc,
        "ob_number_deviations_present": ob_present,
        "ob_number_deviations_policy_ok": ob_policy_ok,
        "n9_independence_stated": bool(tpl.get("n9_independence")),
    }


def collect_pending_ucs(rtm: dict) -> list[str]:
    """累计 RTM 中所有 pending_real_machine 用例 id（台账累计来源）。"""
    return [c["uc"] for c in rtm.get("cases", []) if c.get("status") == "pending_real_machine"]


def aggregate_layers(rtm: dict, mode: str) -> dict:
    """按 RTM 用例状态聚合 L1-L4。

    offline 模式下 L2/L4 强制不通过并标注 pending_real_machine（禁止离线单测标 L2/L4 pass）。
    """
    out: dict = {}
    for layer in FOUR_LAYERS:
        ucs = [c for c in rtm.get("cases", []) if layer in c.get("layers", [])]
        statuses = {c["uc"]: c["status"] for c in ucs}
        if mode == "offline" and layer in REAL_MACHINE_LAYERS:
            out[layer] = {
                "passed": False,
                "layer_status": "pending_real_machine",
                "reason": "涉真机：离线模式明确标注 L2/L4 为 pending_real_machine，禁止以离线单测标 pass",
                "ucs": statuses,
            }
        elif not ucs:
            out[layer] = {
                "passed": False, "layer_status": "not_run",
                "reason": "该层无绑定用例", "ucs": {},
            }
        else:
            all_pass = all(s == "pass" for s in statuses.values())
            out[layer] = {
                "passed": all_pass,
                "layer_status": "pass" if all_pass else (
                    "pending_real_machine" if "pending_real_machine" in statuses.values() else "not_run"
                ),
                "reason": "该层所有 UC 均 pass" if all_pass else "该层存在非 pass 用例，需收口逐条核验",
                "ucs": statuses,
            }
    return out


def check_pending_cleared(ledger: dict, pending_ids: list[str]) -> dict:
    """pending 清零检查：pending 非空 / ledger.cleared!=true / items 非空 均视为未清零。"""
    reasons: list[str] = []
    if pending_ids:
        reasons.append(
            f"pending_real_machine 未清零：仍有 {len(pending_ids)} 项（{', '.join(pending_ids)}）"
        )
    if not ledger.get("cleared"):
        reasons.append("台账 cleared != true（禁止以离线单测 / mock / 人工观感清零）")
    items = ledger.get("items") or []
    if items:
        reasons.append(f"台账仍有 {len(items)} 条 items 未经逐条真机核验")
    cleared = (not pending_ids) and bool(ledger.get("cleared")) and (not items)
    return {"cleared": cleared, "reasons": reasons, "ledger_item_count": len(items)}


def evaluate_m4(
    layers: dict,
    pending_ids: list[str],
    ledger: dict,
    evidence_complete: bool = False,
) -> dict:
    """M4 = (L1 AND L2 AND L3 AND L4) 全绿 AND pending 清零 AND 证据包完整。

    纯函数：pending 未清零前必定返回 m4_pass=False（契约 05 §1.4 / §6）。
    """
    reasons: list[str] = []
    missing_layers = [l for l in FOUR_LAYERS if not layers.get(l, {}).get("passed", False)]
    if missing_layers:
        reasons.append("L1∧L2∧L3∧L4 未全绿，未通过层：" + ", ".join(missing_layers))
    clear = check_pending_cleared(ledger, pending_ids)
    reasons.extend(clear["reasons"])
    if not evidence_complete:
        reasons.append("EvidenceBundle 尚未完整归档（真实证据包由主 agent 收口实测时实例化）")
    m4_pass = (not missing_layers) and clear["cleared"] and evidence_complete
    return {
        "m4_pass": m4_pass,
        "m4_signable": m4_pass,
        "verdict": "M4 通过 / 可签署" if m4_pass else "M4 未通过",
        "reasons": reasons,
        "layer_states": {l: bool(layers.get(l, {}).get("passed", False)) for l in FOUR_LAYERS},
        "pending_cleared": clear["cleared"],
        "pending_count": len(pending_ids),
        "evidence_complete": evidence_complete,
    }


def build_step_records(mode: str, workdir: str | None) -> list[dict]:
    """九步端到端 + 六条增量用例的步骤编排与证据留痕。

    offline：真机步骤标 pending_real_machine，其余标 not_run；全部留复现命令，不代跑、不伪造。
    real_machine：仍不代跑产品链（真机逐条实测由主 agent 收口），仅补 workdir 提示。
    """
    records: list[dict] = []
    for group, items in (("nine_steps", NINE_STEPS), ("six_incremental_cases", SIX_INCREMENTAL_CASES)):
        for s in items:
            r = dict(s)
            r["group"] = group
            if s["requires"] == "real_machine":
                r["status"] = "pending_real_machine"
                extra = "真机项：仅编排步骤并留复现命令，收口实测时按复现命令执行并留真实结构化证据；本编排器不代跑、不伪造结果。"
            else:
                r["status"] = "not_run"
                extra = "离线可校验项：本编排器只做步骤编排与复现命令留痕，不启动产品链 / 不连真机 / 不代跑 / 不伪造结果；收口时由主 agent 核验。"
            r["note"] = ((s.get("note", "") or "") + " " + extra).strip()
            if mode == "real_machine" and workdir:
                r["workdir_hint"] = str(workdir)
                r["note"] += "（--real-machine 模式下仍不代跑产品链；真机逐条实测由主 agent 收口执行）"
            records.append(r)
    return records


# ---------------------------------------------------------------------------
# 真机模式护栏与探针
# ---------------------------------------------------------------------------
def validate_workdir(workdir: str | None) -> dict:
    """真机护栏：必须显式指定 Temp/gf_real_* 副本，禁止 PLC_Openness_data 原始路径（fail-closed）。"""
    if not workdir:
        return {
            "allowed": False, "path": None,
            "reasons": ["未指定 --workdir：真机项必须显式指定临时副本路径（契约 05 §1.1，fail-closed）"],
        }
    norm = str(workdir).replace("\\", "/")
    reasons: list[str] = []
    if "PLC_Openness_data" in norm:
        reasons.append("指向 PLC_Openness_data 原始项目：禁止打开/写回原始 .ap19/.zap19")
    if "gf_real_" not in norm:
        reasons.append("路径不含 gf_real_ 标记：真机操作只允许在 AppData/Local/Temp/gf_real_* 临时副本上进行")
    if ("Temp" not in norm) and ("temp" not in norm) and ("/tmp" not in norm):
        reasons.append("路径不在系统临时目录下")
    return {
        "allowed": not reasons, "path": str(workdir),
        "reasons": reasons or ["路径符合临时副本约束"],
        "note": "原始 .ap19/.zap19 仅可 cp 读取，从未打开、从未 SaveProject() 写回（Agent F 同口径）",
    }


def run_probe(exe: Path, timeout: float) -> dict:
    """真实调用一次 --cli status 探针；不存在/失败留 not_run，绝不伪造探测结果。"""
    rec: dict = {"command": f"{exe} --cli status", "timeout_s": timeout}
    if not Path(exe).exists():
        rec["status"] = "not_run"
        rec["reason"] = "探针 exe 不存在（fail-closed，不伪造探测结果）"
        return rec
    try:
        proc = subprocess.run(
            [str(exe), "--cli", "status"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        rec["exit_code"] = proc.returncode
        payload = None
        for line in out.splitlines():
            s = line.strip().lstrip("\ufeff")
            if s.startswith("{"):
                try:
                    payload = json.loads(s)
                except json.JSONDecodeError as exc:
                    rec["parse_error"] = str(exc)
                break
        rec["status"] = "called" if payload is not None else "not_run"
        rec["payload"] = payload
        if payload is None:
            rec["reason"] = "探针未返回可解析 JSON（留痕，不伪造）"
    except subprocess.TimeoutExpired:
        rec["status"] = "not_run"
        rec["reason"] = f"探针超时 {timeout}s（fail-closed，留痕）"
    except OSError as exc:
        rec["status"] = "not_run"
        rec["reason"] = f"探针启动失败：{exc}（fail-closed，留痕）"
    return rec


def sync_ledger(ledger: dict, pending_ids: list[str], path: Path) -> dict:
    """把 RTM 聚合出的 pending 集合累计进台账（按 id 去重、幂等）。清零仍需人工收口。"""
    existing = {i["id"] for i in ledger.get("items", [])}
    added = []
    for uc in pending_ids:
        if uc not in existing:
            ledger.setdefault("items", []).append({
                "id": uc,
                "reason": "由 RTM 状态聚合累计（--sync-ledger）；真机证据齐备后由主 agent 逐条核验清零",
                "owner": "主 agent 收口",
                "requires": "real_machine",
            })
            added.append(uc)
    if added:
        ledger["cleared"] = False
        path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"added": added, "already_present": len(pending_ids) - len(added), "written": bool(added)}


# ---------------------------------------------------------------------------
# 报告组装
# ---------------------------------------------------------------------------
def build_report(mode: str, workdir: str | None, timeout: float) -> dict:
    rtm, tpl, ledger = load_evidence()
    report: dict = {
        "tool": "greenfield_acceptance",
        "wp": "WP-10 全量验收与证据链（Agent I）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "branch": rtm.get("branch"),
        "baseline": rtm.get("baseline"),
        "fail_closed": True,
        "honest_rules": rtm.get("hard_rules", []),
        "l1_l4_expression": "L1 ∧ L2 ∧ L3 ∧ L4",
    }

    # 1) 静态检查（纯离线可判定）
    rtm_check = validate_rtm(rtm)
    tpl_check = validate_evidence_template(tpl)
    report["static_checks"] = {"rtm": rtm_check, "evidence_template": tpl_check}

    # 2) pending 台账累计与清零检查
    pending_ids = collect_pending_ucs(rtm)
    clear = check_pending_cleared(ledger, pending_ids)
    report["pending"] = {
        "ids": pending_ids,
        "count": len(pending_ids),
        "ledger_items": len(ledger.get("items") or []),
        "cleared": clear["cleared"],
        "reasons": clear["reasons"],
    }

    # 3) L1-L4 复核
    layers = aggregate_layers(rtm, mode)
    report["layers"] = layers
    report["l1_l4_recheck"] = {l: bool(layers[l]["passed"]) for l in FOUR_LAYERS}
    report["l1_l4_verdict"] = (
        "全绿" if all(layers[l]["passed"] for l in FOUR_LAYERS) else "未全绿"
    )

    # 4) 步骤编排与证据留痕
    report["step_records"] = build_step_records(mode, workdir)
    report["step_summary"] = {
        "nine_steps": len(NINE_STEPS),
        "six_incremental_cases": len(SIX_INCREMENTAL_CASES),
        "note": "--offline 下所有步骤均为 not_run / pending_real_machine + 复现命令，绝不伪造执行结果。",
    }

    # 5) 真机模式护栏 + 真实探针（不代跑产品链）
    if mode == "real_machine":
        wd = validate_workdir(workdir)
        report["workdir_check"] = wd
        if not wd["allowed"]:
            report["error"] = "fail-closed：真机模式被拒绝，未执行任何真机项"
            report["m4"] = evaluate_m4(layers, pending_ids, ledger, evidence_complete=False)
            return report
        report["probe"] = run_probe(PROBE_EXE, timeout)
        report["real_machine_scope_note"] = (
            "本编排器在 --real-machine 下仅做临时副本护栏校验与一次真实 status 探针；"
            "九步/六条的产品链逐条实测由主 agent 收口执行，本工具不代跑、不伪造编译/导入结果。"
        )

    # 6) EvidenceBundle 完整性（本工具不实例化真实证据包）
    report["evidence_bundle"] = {
        "complete": False,
        "note": "真实 EvidenceBundle 由主 agent 收口实测时按 acceptance_template.json 实例化归档；当前为模板校验通过。",
        "template_check": tpl_check["complete"],
    }

    # 7) M4 判定（pending 清零前必定未通过）
    report["m4"] = evaluate_m4(layers, pending_ids, ledger, evidence_complete=False)
    return report


def print_summary(report: dict) -> None:
    """人类可读摘要输出到 stderr（stdout 保持纯 JSON）。"""
    rtm = report["static_checks"]["rtm"]
    m4 = report["m4"]
    layers = report["l1_l4_recheck"]
    p = report["pending"]
    w = sys.stderr.write
    w("\n" + "=" * 68 + "\n")
    w(f"WP-10 全量验收报告 | mode={report['mode']} | branch={report['branch']}\n")
    w("=" * 68 + "\n")
    c = rtm["counts"]
    w(f"RTM: {rtm['case_count']} UC | pass={c.get('pass', 0)} fail={c.get('fail', 0)} "
      f"pending_real_machine={c.get('pending_real_machine', 0)} not_run={c.get('not_run', 0)} "
      f"(基线排除另计)\n")
    w(f"L1∧L2∧L3∧L4 复核: {report['l1_l4_verdict']} | "
      + " ".join(f"{k}={'pass' if v else 'not_pass'}" for k, v in layers.items()) + "\n")
    w(f"L2/L4 离线口径: {report['layers']['L2']['layer_status']} / "
      f"{report['layers']['L4']['layer_status']}（禁止离线单测标 pass）\n")
    w(f"pending 台账: {p['count']} 项未清零 (cleared={p['cleared']})\n")
    w(f"九步端到端: {report['step_summary']['nine_steps']} 步 | "
      f"六条增量用例: {report['step_summary']['six_incremental_cases']} 条 "
      f"-> 全部 not_run / pending_real_machine + 复现命令\n")
    w("-" * 68 + "\n")
    w(f"M4 判定: {m4['verdict']}（m4_pass={m4['m4_pass']}, m4_signable={m4['m4_signable']}）\n")
    for r in m4["reasons"]:
        w(f"  - {r}\n")
    w("-" * 68 + "\n")
    w("诚实口径: 未以离线单测宣称 L2/L4 通过或编译零错误；pending 清零前 M4 保持未通过；\n")
    w("          真机结论只引用 Agent F 归档或真实运行结果，绝不编造真机编译数字。\n")
    w("=" * 68 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="WP-10 全量验收编排器（fail-closed，绝不伪造真机结果）"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--offline", action="store_true", help="只跑可离线的检查，明确标注 L2/L4 pending")
    g.add_argument("--real-machine", action="store_true", help="真机模式（必须显式指定 --workdir 临时副本路径）")
    ap.add_argument(
        "--workdir", default=None, metavar="AP19",
        help="真机临时副本路径（AppData/Local/Temp/gf_real_*；禁止 PLC_Openness_data 原始路径）",
    )
    ap.add_argument("--out", default=None, metavar="PATH", help="把结构化报告另存为 JSON（默认只打印，不改台账）")
    ap.add_argument("--sync-ledger", action="store_true", help="把 RTM pending 累计进 pending_real_machine.json（幂等）")
    ap.add_argument("--timeout", type=float, default=180.0, help="真机探针子进程超时秒数（默认 180）")
    ap.add_argument("--strict", action="store_true", help="M4 未通过时返回退出码 1（供 CI 用）")
    args = ap.parse_args()

    mode = "offline" if args.offline else "real_machine"
    report = build_report(mode, args.workdir, args.timeout)

    if args.sync_ledger:
        _, _, ledger = load_evidence()
        rtm = json.loads((EVIDENCE_DIR / "rtm.json").read_text(encoding="utf-8"))
        report["ledger_sync"] = sync_ledger(
            ledger, collect_pending_ucs(rtm), EVIDENCE_DIR / "pending_real_machine.json"
        )

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print_summary(report)

    if report.get("error"):
        sys.exit(2)
    if args.strict and not report["m4"]["m4_pass"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
