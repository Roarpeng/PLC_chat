"""作业式重构流水线：refactor → auto_fix → compile(临时副本) → fix_loop → package。

前端「重构」指令从一次性 ``POST /canvas/refactor`` 升级为可轮询的作业流水线
（``POST /canvas/refactor-pipeline`` + ``GET .../{job_id}``），全程分阶段推进，
产出一句话可触达的交付包（zip 由 ``GET .../{job_id}/package`` 伺服）。

作业模型对齐 ``compile_jobs.py``：进程内注册表 + ThreadPoolExecutor + 阶段
快照 + TTL（1h）清理；作业字典只存可 JSON 化的纯数据。

五阶段语义（阶段状态 = 「该阶段执行得怎么样」，编译质量在
result.compile.errors / 交付收据里如实呈现）：

1. ``refactor``  调 ``plc_engine.af.refactor.refactor_canvas_to_af``（引擎已落地
   ``self_contained`` kwarg，自举模式）；调用仍先带 kwarg、``TypeError`` 则降级
   为无 kwarg 调用并记 warning「引擎未支持自举模式」。target 命名沿用
   ``U1_{project_name}`` 规则（见 routers/plc.py 既有 /canvas/refactor 写法）。
   报告中的 ``pending_blocks`` / ``degraded`` / ``degrade_reasons`` 等字段原样
   透传。**引擎完全降级**（``report.status=="degraded"``，零 AF 块生成）时：
   auto_fix/compile/fix_loop 三段直接 skipped（"引擎诚实降级,无可编译的重构产
   物"），degrade_reasons 与 pending_blocks 转入 warnings，照常走 package 段，
   流水线整体记 ok（由 warnings 表达降级）；部分降级（degraded=false 但
   pending_blocks 非空）照常走完整五段。
2. ``auto_fix``  ``auto_fix=true`` 时把规则补丁应用到画布草稿块 SCL。规则库为
   ``plc_engine.canvas_model.generate_canvas_autofix_patch``（fix_loop 同源），
   返回 ``AutofixPatch``（``list[dict]`` 子类）——ops 含
   ``add_variable``/``update_block_scl``/``update_network``（有可执行 op 时末尾
   追加 ``clear_errors``），``.diagnostics`` 属性经 getattr 防御读取转 warnings；
   应用走 ``apply_canvas_patch``（fix_loop 已验证的消费方式）；无规则可用则
   skipped。
3. ``compile``   ``do_compile=true`` 时做**诚实且非破坏**的临时副本编译：把
   项目源复制到临时目录 → 画布写进**副本** → Openness 编译 → 弃置副本。本机
   无 Openness（TiaOpenness.Server.exe 不存在且无可 dotnet run 的工程）或拿
   不到项目源路径时记 ``skipped`` + ``skipped_reason``，流水线继续。**绝不写
   用户真实工作副本**（人工确认门是产品铁律）。
4. ``fix_loop``  仅当请求了编译且错误非空：跑一轮**不调 LLM** 的规则修复
   （``run_fix_loop(use_llm=False)``，注入临时副本编译 runner），修复后再编译
   一次，剩余错误如实记录；不可用/无进展只记 warning，不失败。
5. ``package``   ``release_package.build_release_package`` 生成交付目录并 zip
   （存临时目录，路径记到作业上供下载端点伺服）。

PCEC 记账（契约 docs/19 §4 同款立场：记账员不做新故障点，全程 try/except 只
warning）：refactor 阶段开一笔 ``kind="refactor_pipeline"`` 的事务（chg- 前缀、
touched=AF 新块+被取代旧块），收尾按流水线结果收敛（ok→applied，失败→rejected，
取消不动账本）。``plc_engine.pcec.new_change`` 的 kind 是自由字符串（无枚举刚
性），无需改动引擎。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import CanvasState

logger = logging.getLogger("researchos.gateway.plc.refactor_pipeline")

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="refactor-pipeline")
_TTL_S = 3600.0

#: 固定五段阶段名（与前端契约一字不差）
STAGES = ["refactor", "auto_fix", "compile", "fix_loop", "package"]

#: 引擎完全降级（report.status=="degraded"，零 AF 块）时中间三段的统一跳过说明
DEGRADED_SKIP_REASON = "引擎诚实降级，无可编译的重构产物"

#: result.compile.errors 上限（截断到 50 条）
_ERRORS_LIMIT = 50
#: result.warnings 上限
_WARNINGS_LIMIT = 20
#: 自动修复 diagnostics 转入 warnings 的条数上限
_DIAGNOSTICS_LIMIT = 5
#: 临时副本编译的墙钟上限(秒)。execute_canvas_writeback 由多次 openness_cli
#: 调用组成,单调用超时不构成总护栏(compile_jobs 的 900s 硬超时不覆盖本路径);
#: 到点放弃等待并如实记超时,被放弃的底层线程由其自身调用超时收尾。
#: 默认 2700s 按 V4 真机实测校准(VirtualBox 上 TIA 冷启动+写 73 源+全量编译
#: 耗时 30-40 分钟;900s 会掐死正常编译——V5 教训),可用环境变量覆盖。
_TEMP_COMPILE_TIMEOUT_S = int(os.environ.get("PLC_REFACTOR_COMPILE_TIMEOUT_S", "2700"))

#: TIA 工程根专有目录（与 workspace.persist_imported_project 同一套判定词表）
_TIA_ROOT_DIRS = ("System", "IM", "TMP", "bin", "pe")
_Apxx_SUFFIXES = {".ap17", ".ap18", ".ap19", ".ap20"}

#: PCEC 事务终态（与 compile_jobs._TERMINAL_CHANGE_STATUSES 同义；本地复制避免跨模块私有依赖）
_TERMINAL_CHANGE_STATUSES = {"applied", "failed", "expired", "rejected", "rolled_back"}


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# 作业注册表（对齐 compile_jobs：锁内清理 TTL / 读写均出 deepcopy 快照）
# ---------------------------------------------------------------------------


def _purge_locked() -> None:
    cutoff = _now() - _TTL_S
    dead = [k for k, v in _jobs.items() if float(v.get("updated_at") or 0) < cutoff]
    for k in dead:
        _jobs.pop(k, None)


def get_refactor_pipeline_job(job_id: str) -> dict[str, Any] | None:
    """内部形态作业快照（含 package_path 等）；不存在返回 None。"""
    with _lock:
        _purge_locked()
        job = _jobs.get(job_id)
        return deepcopy(job) if job else None


def refactor_job_view(job_id: str) -> dict[str, Any] | None:
    """GET 端点的契约视图：``{id, status, stage, stages:[{name,status,detail?}], result?}``。"""
    job = get_refactor_pipeline_job(job_id)
    if not job:
        return None
    view: dict[str, Any] = {
        "id": job["id"],
        "status": job["status"],
        "stage": job.get("stage") or "",
        "stages": [
            {"name": s["name"], "status": s["status"], **({"detail": s["detail"]} if s.get("detail") else {})}
            for s in job["stages"]
        ],
        "error": job.get("error"),
    }
    if job.get("result") is not None:
        view["result"] = job["result"]
    return view


def cancel_refactor_pipeline_job(job_id: str) -> dict[str, Any] | None:
    """请求取消：置 cancel_requested，由阶段边界守卫落地为 cancelled。"""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job["status"] == "running":
            job["cancel_requested"] = True
            job["updated_at"] = _now()
        return deepcopy(job)


def _set_stage(job_id: str, name: str, status: str, detail: str = "") -> None:
    """推进阶段并刷新作业当前阶段指针。"""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for stage in job["stages"]:
            if stage["name"] == name:
                stage["status"] = status
                if detail:
                    stage["detail"] = detail
                break
        job["stage"] = name
        job["updated_at"] = _now()


def _mark_remaining(job_id: str, names: list[str], status: str, detail: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for stage in job["stages"]:
            if stage["name"] in names and stage["status"] == "pending":
                stage["status"] = status
                stage["detail"] = detail
        job["updated_at"] = _now()


def _is_cancelled(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job.get("cancel_requested"))


def _mark_cancelled(job_id: str, remaining: list[str]) -> None:
    """取消落地：剩余阶段 skipped，作业 cancelled（PCEC 不动账本）。"""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for stage in job["stages"]:
            if stage["name"] in remaining and stage["status"] in {"pending", "running"}:
                stage["status"] = "skipped"
                stage["detail"] = "已取消，未执行"
        job["status"] = "cancelled"
        job["error"] = "cancelled by user"
        job["updated_at"] = _now()


def _cancel_guard(job_id: str, remaining: list[str]) -> bool:
    if not _is_cancelled(job_id):
        return False
    _mark_cancelled(job_id, remaining)
    logger.info("refactor pipeline cancelled id=%s", job_id)
    return True


def _set_terminal_error(job_id: str, message: str) -> None:
    """异常收敛：当前 running 阶段 error、未执行阶段 skipped、作业 error。"""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for stage in job["stages"]:
            if stage["status"] == "running":
                stage["status"] = "error"
                stage["detail"] = message[:300]
            elif stage["status"] == "pending":
                stage["status"] = "skipped"
                stage["detail"] = "流水线异常终止，未执行"
        job["status"] = "error"
        job["error"] = message
        job["updated_at"] = _now()


# ---------------------------------------------------------------------------
# PCEC 记账（kind=refactor_pipeline；异常只 warning，绝不阻塞流水线）
# ---------------------------------------------------------------------------


def _pcec() -> Any | None:
    """惰性加载 plc_engine.pcec；不可用返回 None（与 compile_jobs 同策略）。"""
    try:
        from plc_engine import pcec

        return pcec
    except Exception:  # noqa: BLE001 - 引擎缺失/损坏时静默降级为不记账
        return None


def open_refactor_change(
    canvas: CanvasState,
    report: dict[str, Any],
    *,
    target: str,
    project_path: str = "",
) -> str:
    """refactor 阶段开账：kind="refactor_pipeline"，touched=AF 新块+被取代旧块。

    proposed → analyzed（v0_parsed=pass）；返回 change_id，异常只 warning 返回空串。
    """
    try:
        pcec = _pcec()
        if pcec is None:
            return ""
        af_created = [str(b) for b in (report.get("af_blocks_created") or [])]
        legacy = sorted(canvas.blocks)
        touched = sorted(set(af_created) | set(legacy))
        baseline: dict[str, Any] = {}
        if project_path and Path(project_path).exists():
            try:
                baseline = pcec.project_baseline(project_path)
            except Exception:  # noqa: BLE001 - 基线采集失败不影响记账本体
                baseline = {}
        change = pcec.new_change(
            "refactor_pipeline",
            f"重构流水线 target={target}（AF 新块 {len(af_created)} / 被取代旧块 {len(legacy)}）",
            ops=[
                {
                    "op": "refactor_to_af",
                    "target_unit": target,
                    "af_blocks": len(af_created),
                    "legacy_superseded": len(legacy),
                }
            ],
            touched_blocks=touched,
            baseline=baseline,
        )
        change["verification"]["v0_parsed"] = "pass"
        pcec.transition(change, "analyzed", event="pipeline_refactored")
        pcec.put_change(change)
        change_id = str(change.get("change_id") or "")
        if change_id:
            logger.info("pcec refactor_pipeline change opened id=%s touched=%d", change_id, len(touched))
        return change_id
    except Exception as exc:  # noqa: BLE001 - 记账失败不阻塞流水线
        logger.warning("pcec open_refactor_change skipped: %s", exc)
        return ""


def settle_refactor_change(
    change_id: str,
    *,
    ok: bool,
    detail: dict[str, Any] | None = None,
) -> None:
    """收尾关账：ok→validated→approved(auto)→applied；失败→rejected。异常吞掉。

    画布级交付不写用户工程，approval 如实标注 mode=auto / 未写工程；编译证据
    （错误数/收据摘要）进 verification.detail。
    """
    if not change_id:
        return
    try:
        pcec = _pcec()
        if pcec is None:
            return
        change = pcec.get_change(change_id)
        if change is None or change.get("status") in _TERMINAL_CHANGE_STATUSES:
            return
        change["verification"]["v1_static"] = "pass" if ok else "fail"
        merged_detail = dict(change["verification"].get("detail") or {})
        merged_detail.update(detail or {})
        change["verification"]["detail"] = merged_detail
        pcec.transition(change, "validated", event="v1_static")
        if ok:
            change["approval"] = {
                "reviewer": "refactor_pipeline",
                "mode": "auto",
                "note": "画布级重构交付，未写用户工程（人工确认门未触发）",
            }
            pcec.transition(change, "approved", event="auto_pipeline")
            pcec.transition(change, "applied", event="pipeline_delivered")
        else:
            pcec.transition(change, "rejected", event="pipeline_failed")
        pcec.put_change(change)
        logger.info("pcec refactor_pipeline change settled id=%s ok=%s", change_id, ok)
    except Exception as exc:  # noqa: BLE001 - 收尾记账失败不影响作业终态
        logger.warning("pcec settle_refactor_change skipped: %s", exc)


# ---------------------------------------------------------------------------
# 阶段 1：refactor（引擎调用 + self_contained 兜底）
# ---------------------------------------------------------------------------


def _stage_refactor(canvas: CanvasState, target: str) -> tuple[CanvasState, dict[str, Any], list[str]]:
    """调重构引擎；``self_contained`` kwarg 未支持时降级并记 warning。

    返回 (新画布, 引擎报告, warnings)；报告原样透传（pending_blocks/degraded
    等新字段不需要在这里认识，逐字交给 result.report）。
    """
    from plc_engine.af.refactor import refactor_canvas_to_af

    warnings: list[str] = []
    try:
        new_canvas, report = refactor_canvas_to_af(canvas, target, self_contained=True)
    except TypeError:
        # 引擎智能体正在加 self_contained kwarg；未支持时降级为无 kwarg 调用。
        # （若降级调用本身仍 TypeError，说明引擎真坏了，异常照常向上抛。）
        warnings.append("引擎未支持自举模式（self_contained），已降级为普通重构调用")
        new_canvas, report = refactor_canvas_to_af(canvas, target)
    if not isinstance(report, dict):
        report = {"status": "degraded", "raw": str(report)}
    return new_canvas, report, warnings


def _refactor_summary(report: dict[str, Any]) -> str:
    io = report.get("io_retention") if isinstance(report.get("io_retention"), dict) else {}
    return (
        f"重构完成：AF 新块 {len(report.get('af_blocks_created') or [])} 个，"
        f"物理 IO 保留 {io.get('percentage', 0)}%"
    )


def _report_degraded(report: dict[str, Any]) -> bool:
    """完全降级判定（引擎契约）：``report.status=="degraded"`` 或 ``degraded=True``
    ——此时零 AF 块生成、旧块原样保留（af_role=af_pending_manual）。"""
    if str(report.get("status") or "") == "degraded":
        return True
    return bool(report.get("degraded"))


def _degrade_warnings(report: dict[str, Any]) -> list[str]:
    """降级证据转 warnings：degrade_reasons + pending_blocks 清单（部分降级不在此列）。"""
    out: list[str] = []
    reasons = [str(r) for r in (report.get("degrade_reasons") or []) if str(r).strip()]
    if reasons:
        out.append(f"引擎降级原因：{'、'.join(reasons)}")
    pending = [str(b) for b in (report.get("pending_blocks") or []) if str(b).strip()]
    if pending:
        head = ",".join(pending[:10]) + ("…" if len(pending) > 10 else "")
        out.append(f"待人工确认块（{len(pending)}）：{head}")
    return out


# ---------------------------------------------------------------------------
# 阶段 2：auto_fix（规则补丁应用到画布草稿块 SCL）
# ---------------------------------------------------------------------------


def _load_autofix() -> tuple[Callable[..., Any], Callable[..., Any]] | None:
    """加载 (生成补丁, 应用补丁) 一对函数。

    ``generate_canvas_autofix_patch`` 物理位置在 ``plc_engine/canvas_model.py``
    （fix_loop.py 同源引用），返回 ``AutofixPatch``（``list[dict]`` 子类，带
    ``.diagnostics`` 属性）；应用补丁走 ``apply_canvas_patch``（fix_loop 已验证
    零改动兼容的消费方式），不另造 apply 逻辑。
    """
    try:
        from plc_engine.canvas_model import apply_canvas_patch, generate_canvas_autofix_patch

        return generate_canvas_autofix_patch, apply_canvas_patch
    except Exception:  # noqa: BLE001 - 规则库不可用时阶段 skipped
        return None


def _normalize_patch_result(result: Any) -> tuple[list[Any], list[str]]:
    """把规则库返回值归一为 (patches, diagnostics)。

    契约：返回 ``AutofixPatch``（``list[dict]`` 子类，``.diagnostics`` 属性）——
    list 分支按 ``getattr(result, "diagnostics")`` 防御读取；同时兼容裸 list 与
    ``{"patches"|"ops": [...], "diagnostics": [...]}`` 字典形态。
    """
    if isinstance(result, dict):
        patches = result.get("patches") or result.get("ops") or []
        diagnostics = result.get("diagnostics") or []
    elif isinstance(result, list):
        patches = result
        diagnostics = getattr(result, "diagnostics", None) or []
    else:
        patches = getattr(result, "patches", None) or getattr(result, "ops", None) or []
        diagnostics = getattr(result, "diagnostics", None) or []
    diag_texts = [str(d)[:200] for d in list(diagnostics)[:_DIAGNOSTICS_LIMIT] if str(d).strip()]
    return list(patches), diag_texts


def _call_autofix(
    fn: Callable[..., Any],
    canvas: CanvasState,
    evidence_dir: str = "",
) -> Any | None:
    """防御式调用规则库：主签名 ``(canvas, attributions, evidence_dir)``
    （证据驱动 R2-full/R4），``TypeError`` 时回退 ``(canvas, attributions)``
    （fix_loop 同款）、再回退单参 ``(canvas)``；仍 TypeError 返回 None。
    """
    if evidence_dir:
        try:
            return fn(canvas, [], evidence_dir)
        except TypeError:
            pass
    try:
        return fn(canvas, [])
    except TypeError:
        pass
    try:
        return fn(canvas)
    except TypeError:
        return None


def _effective_patch_count(patches: list[Any]) -> int:
    """有效补丁数：剔除 ``clear_errors`` 这类纯清账操作。"""
    count = 0
    for p in patches:
        if isinstance(p, dict) and str(p.get("op") or "") == "clear_errors":
            continue
        count += 1
    return count


def _probe_evidence_dir(canvas: CanvasState) -> str:
    """无显式 evidence_dir 时探测工作区 baseline(块级 XML 基线)作证据源。"""
    pid = str(getattr(canvas.source, "project_id", "") or "") if canvas.source else ""
    if not pid:
        return ""
    try:
        from gateway.app.services.plc import workspace as ws

        meta = ws.load_meta(pid) or {}
        base = Path(str(meta.get("baseline_path") or ""))
        if not base.is_dir():
            return ""
        for sub in (base, base / "Blocks", base / "blocks"):
            if sub.is_dir() and any(sub.glob("*.xml")):
                return str(sub)
    except Exception:  # noqa: S110, BLE001 - 探测失败静默,退回无证据模式
        pass
    return ""


def _stage_auto_fix(
    canvas: CanvasState,
    *,
    evidence_dir: str = "",
) -> tuple[CanvasState, int, list[str], str]:
    """跑规则自动修复；返回 (画布, 应用数, diagnostics, 说明)。

    说明为 ``skipped:<原因>`` 时表示未应用任何补丁。evidence_dir 提供时启用
    XML 证据驱动规则（R2-full 数组下标 / R4 接口对账）。
    """
    loaded = _load_autofix()
    if loaded is None:
        return canvas, 0, [], "skipped:自动修复规则库不可用"
    gen, apply = loaded
    effective_dir = evidence_dir or _probe_evidence_dir(canvas)
    result = _call_autofix(gen, canvas, effective_dir)
    if result is None:
        return canvas, 0, [], "skipped:自动修复规则签名不兼容"
    patches, diagnostics = _normalize_patch_result(result)
    effective = _effective_patch_count(patches)
    if not patches or effective == 0:
        note = "skipped:无可用自动修复规则"
        if effective_dir:
            note += f"（已启用 XML 证据：{effective_dir}）"
        return canvas, 0, diagnostics, note
    try:
        canvas = apply(canvas, patches)
        canvas.append_revision(
            patches,
            source="autofix",
            message=f"重构流水线自动修复（{effective} 条规则补丁）",
        )
    except Exception as exc:  # noqa: BLE001 - 应用失败不阻塞流水线
        return canvas, 0, diagnostics + [f"自动修复补丁应用失败：{exc}"], "skipped:补丁应用失败"
    note = f"应用规则补丁 {effective} 条"
    if effective_dir:
        note += f"（XML 证据驱动：{Path(effective_dir).name}）"
    return canvas, effective, diagnostics, note


# ---------------------------------------------------------------------------
# 阶段 3：compile（诚实且非破坏的临时副本编译）
# ---------------------------------------------------------------------------


def _openness_available() -> tuple[bool, str]:
    """本机 Openness 侧车可用性（已构建 exe 或可 dotnet run 的 csproj）。"""
    try:
        from agents.plc.tia.openness_cli import find_openness_exe, openness_server_project

        if find_openness_exe() is not None or openness_server_project().is_file():
            return True, ""
        return False, "本机无 TIA Openness 环境（未找到 TiaOpenness.Server.exe，也无可用 dotnet 工程）"
    except Exception as exc:  # noqa: BLE001
        return False, f"Openness 可用性检查失败：{exc}"


def _find_apxx(root: Path) -> Path | None:
    """在目录里找 .ap1x 工程描述文件（与 workspace._find_apxx 同语义，本地实现避免跨模块私有依赖）。"""
    if root.is_file() and root.suffix.lower() in _Apxx_SUFFIXES:
        return root
    candidates = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _Apxx_SUFFIXES)
    return candidates[0] if candidates else None


def _resolve_project_source(canvas: CanvasState) -> str:
    """定位项目源（画布 source 的工程路径，或工作区 work 副本）。"""
    src = canvas.source
    path = str(getattr(src, "project_path", "") or "") if src else ""
    if path and Path(path).is_file():
        return path
    project_id = str(getattr(src, "project_id", "") or "") if src else ""
    if project_id:
        try:
            from gateway.app.services.plc import workspace as ws

            resolved = ws.resolve_work_project_path(project_id)
            if resolved:
                return str(resolved)
        except Exception as exc:  # noqa: BLE001
            logger.warning("resolve work copy failed: %s", exc)
    return ""


def _copy_project_to_temp(project_path: str) -> tuple[Path, Path] | None:
    """把项目源复制到临时目录；返回 (临时根, 副本中的 .apxx)。

    - ``.apxx`` 文件：同级有 TIA 工程根目录（System/IM/TMP/bin/pe）则整树拷贝
      （只拷描述文件 TIA Open 会报路径无效），否则只拷描述文件；
    - 目录：整树拷贝后在副本内找 .apxx。
    """
    src = Path(project_path)
    tmp_root = Path(tempfile.mkdtemp(prefix="refactor_compile_"))
    try:
        if src.is_file():
            tia_root = any((src.parent / n).is_dir() for n in _TIA_ROOT_DIRS)
            if tia_root:
                dest = tmp_root / src.parent.name
                shutil.copytree(src.parent, dest, dirs_exist_ok=True)
                apxx = dest / src.name
            else:
                apxx = tmp_root / src.name
                shutil.copy2(src, apxx)
        elif src.is_dir():
            dest = tmp_root / src.name
            shutil.copytree(src, dest, dirs_exist_ok=True)
            apxx = _find_apxx(dest) or (dest / f"{src.name}.ap19")
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)
            return None
        if not apxx.is_file():
            shutil.rmtree(tmp_root, ignore_errors=True)
            return None
        return tmp_root, apxx
    except Exception as exc:  # noqa: BLE001 - 复制失败按不可编译处理
        logger.warning("copy project to temp failed: %s", exc)
        shutil.rmtree(tmp_root, ignore_errors=True)
        return None


def _extract_compile_errors(
    writeback: dict[str, Any],
    attributions: list[dict[str, Any]],
) -> tuple[list[str], int]:
    """从写回/编译结果提取 (错误字符串列表, 警告数)。

    错误按归因 message 汇总（无归因时回退写回结果错误文案），去重保序、
    截断到 50 条；警告按归因 severity≈warning 计数。
    """
    errors: list[str] = []
    warnings_count = 0
    for att in attributions:
        if not isinstance(att, dict):
            continue
        msg = str(att.get("message") or "").strip()
        if not msg:
            continue
        if "warn" in str(att.get("severity") or "").lower():
            warnings_count += 1
        elif msg not in errors:
            errors.append(msg)
    if not errors and not writeback.get("ok"):
        fallback = str(writeback.get("message") or writeback.get("error") or "")
        if isinstance(writeback.get("error"), dict):
            fallback = str(writeback["error"].get("message") or fallback)
        # 设备级编译失败:诊断在 compile 子载荷里(State/errors/inconsistentBlocks
        # ——C# CompilePlcSoftwareStrict 已序列化),顶层往往无 message。
        # 形态是双层嵌套:writeback["compile"] = CLI 外层结果,其内层
        # ["compile"] 才是 {state,errorCount,inconsistentBlocks,message,error}
        comp = writeback.get("compile") if isinstance(writeback.get("compile"), dict) else {}
        inner = comp.get("compile") if isinstance(comp.get("compile"), dict) else comp
        if not fallback and inner:
            cmsg = str(inner.get("message") or comp.get("message") or "")
            cerr = inner.get("error") or comp.get("error")
            if isinstance(cerr, dict):
                cmsg = f"{cmsg} {cerr.get('message') or ''}".strip()
            if cmsg:
                fallback = cmsg
            for blk in inner.get("inconsistentBlocks") or []:
                if isinstance(blk, str) and blk.strip():
                    errors.append(f"编译不一致块：{blk.strip()}")
        if not fallback:
            fallback = "编译失败：博图未返回具体原因"
        errors.append(fallback)
    return errors[:_ERRORS_LIMIT], warnings_count


def _compile_write_scope(canvas: CanvasState) -> tuple[CanvasState, list[str]]:
    """编译写集裁剪：已取代旧块与含翻译期 TODO 的 pending 块视为 synced。

    - 取代块（af_role=legacy_superseded）：原内容已在源工程里（重构只标注
      不删除），不该再写进编译副本；且被 autofix 触碰过的取代块会变 draft
      并可能残留翻译期 TODO，混入写集会让预检 fail-closed 拦停整批
      （实测 FB720_KuKa_MainCtrl 案例）。
    - pending 块（af_pending_manual）：R5 接口重建会使其变 draft；body 含
      翻译期 TODO/空网络占位的（scl_precheck 同款口径）移出写集——TODO 是
      诚实占位（未翻译的 LAD 元素），删掉或硬送编译器都不诚实，保持
      synced 原样交付、由 warnings 报告（实测 FB1142/FC2100 系案例）。
    其余 pending 块保留 draft——它们未被取代，autofix 的修复要随包交付。
    """
    scoped = deepcopy(canvas)
    excluded: list[str] = []
    for name, block in list(scoped.blocks.items()):
        role = getattr(block, "af_role", "")
        if getattr(block, "status", "") != "draft":
            continue
        text = "\n".join(
            [str(block.scl_body or "")]
            + [str(getattr(n, "scl_text", "") or "") for n in (block.networks or [])]
        ).upper()
        has_placeholder = "TODO" in text or "(* EMPTY NETWORK *)" in text
        if role == "legacy_superseded" or (role == "af_pending_manual" and has_placeholder):
            block.status = "synced"
            excluded.append(name)
    return scoped, excluded


def _temp_compile(
    canvas: CanvasState,
    *,
    project_source: str,
    plc_name: str = "",
) -> dict[str, Any]:
    """临时副本编译（非破坏铁律的唯一编译通道）。

    流程：写集裁剪 → Openness 可用性 → 复制项目源到临时目录 → **在副本上**
    执行画布写回 + 编译（``execute_canvas_writeback``，deepcopy 画布防 synced
    污染）→ 弃置副本。返回::

        {"ran": bool, "skipped_reason": str, "ok": bool,
         "errors": [str], "warnings_count": int, "attributions": [...],
         "excluded_superseded": [str]}

    ``ran=False`` 表示没编译（skipped_reason 给原因）；真实工程目录全程只读。
    """
    empty = {
        "ran": False,
        "skipped_reason": "",
        "ok": False,
        "errors": [],
        "warnings_count": 0,
        "attributions": [],
        "excluded_superseded": [],
    }
    scoped, excluded = _compile_write_scope(canvas)
    empty["excluded_superseded"] = excluded
    available, reason = _openness_available()
    if not available:
        empty["skipped_reason"] = reason
        return empty

    # 本地静态预检（复用 compile_jobs 导出的 writeback_precheck，同一「待写回块」
    # 语义）：预检有 error 时不启动 Openness——错误就是错误，如实记入 errors。
    from gateway.app.services.plc.compile_jobs import writeback_precheck

    pre, _pending = writeback_precheck(scoped)
    pre_errors = [
        str(f.get("message") or f) for f in (pre.get("errors") or []) if str(f.get("message") or f).strip()
    ]
    if pre_errors:
        empty["skipped_reason"] = "本地静态预检未通过，未启动 Openness 编译"
        empty["errors"] = pre_errors[:_ERRORS_LIMIT]
        empty["attributions"] = [
            f if isinstance(f, dict) else {"target_type": "block", "target_id": "", "severity": "error", "message": str(f)}
            for f in (pre.get("errors") or [])[:_ERRORS_LIMIT]
        ]
        return empty

    copied = _copy_project_to_temp(project_source)
    if copied is None:
        empty["skipped_reason"] = f"项目源复制失败或不可读：{project_source}"
        return empty
    tmp_root, temp_apxx = copied

    try:
        from plc_engine.canvas_tia_transpiler import execute_canvas_writeback

        # deepcopy：execute_canvas_writeback 成功时会把画布块标 synced——那是
        # 「已写进工程」的状态，这里写的是临时副本，绝不能污染交付画布。
        # 墙钟看门狗:with 块的 shutdown(wait=True) 会等被放弃的任务,反而失去
        # 看门狗意义,故用手动 shutdown(wait=False, cancel_futures=True)。
        watchdog = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refactor-compile")
        try:
            future = watchdog.submit(
                execute_canvas_writeback,
                deepcopy(scoped),
                project_path=temp_apxx,
                plc_name=plc_name,
                compile_after=True,
            )
            try:
                writeback, attributions = future.result(timeout=_TEMP_COMPILE_TIMEOUT_S)
            except TimeoutError:
                empty["skipped_reason"] = (
                    f"临时副本编译超过 {_TEMP_COMPILE_TIMEOUT_S}s 墙钟上限"
                    "(真机 TIA 全量编译耗时超出预期,已放弃等待)"
                )
                return empty
        finally:
            watchdog.shutdown(wait=False, cancel_futures=True)
        errors, warnings_count = _extract_compile_errors(writeback, attributions)
        if errors and errors == ["编译失败：博图未返回具体原因"]:
            # 提取层兜底命中:把 compile 载荷原文落日志,供形状修正(不再盲猜)
            import json as _json

            logger.warning(
                "temp compile opaque failure, raw compile payload: %s",
                _json.dumps(writeback.get("compile"), ensure_ascii=False, default=str)[:3000],
            )
        # 不一致块名单(TIA IsConsistent 巡检):编译 API 不给逐条错误文本,
        # 这是宿主归属的唯一通道——透出到 result/收据,不再只留内部载荷
        _comp_env = writeback.get("compile") if isinstance(writeback.get("compile"), dict) else {}
        _inner = _comp_env.get("compile") if isinstance(_comp_env.get("compile"), dict) else _comp_env
        _inconsistent = [
            str(n)
            for n in (_inner.get("inconsistentBlocks") or [])
            if isinstance(n, str) and n.strip()
        ]
        return {
            "ran": True,
            "skipped_reason": "",
            "ok": bool(writeback.get("ok")) and not errors,
            "errors": errors,
            "warnings_count": warnings_count,
            "attributions": attributions,
            "inconsistent_blocks": _inconsistent,
        }
    except Exception as exc:  # noqa: BLE001 - Openness 启动/运行失败 → 如实 skipped
        logger.warning("temp compile failed: %s", exc)
        empty["skipped_reason"] = f"临时副本编译执行失败：{exc}"
        return empty
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _make_temp_compile_runner(
    project_source: str,
    plc_name: str,
) -> Callable[..., dict[str, Any]]:
    """给 ``run_fix_loop`` 注入的编译 runner：default_compile_runner 同形返回，
    但写回/编译只发生在临时副本上（project_path 形参仅作信息，不落盘真实工程）。
    """

    def runner(
        job_id: str,
        canvas_dict: dict[str, Any],
        *,
        project_path: str = "",
        plc_name: str = "",
        compile_plc: bool = True,
        compile_hmi: bool = True,
        save_on_success: bool = False,
        reset_work: bool = False,
    ) -> dict[str, Any]:
        canvas = CanvasState.from_dict(canvas_dict)
        info = _temp_compile(canvas, project_source=project_source, plc_name=plc_name or "")
        error_text = "" if info["ok"] else ("；".join(info["errors"][:3]) or "compile failed")
        return {
            "ok": bool(info["ran"] and info["ok"]),
            "writeback": {
                "ok": bool(info["ok"]),
                "note": "refactor_pipeline_temp_copy",
                **({"error": error_text} if error_text else {}),
                **({"skipped_reason": info["skipped_reason"]} if info["skipped_reason"] else {}),
            },
            "attributions": info["attributions"],
            # 真实工程没被写过，画布原样返回（绝无 synced 污染）
            "canvas": canvas.to_dict(),
            "degraded": False,
            "precheck": None,
        }

    return runner


# ---------------------------------------------------------------------------
# 阶段 4：fix_loop（一轮规则修复 + 复检，不调 LLM）
# ---------------------------------------------------------------------------


def _fix_loop_round(
    canvas: CanvasState,
    attributions: list[dict[str, Any]],
    *,
    project_source: str,
    plc_name: str,
) -> tuple[CanvasState, list[str], bool, str]:
    """跑一轮不调 LLM 的规则修复循环。

    返回 (修复后画布, 剩余错误, 是否执行了, 说明)；不可用/异常时是否执行了=False
    （调用方记 warning 不失败）。
    """
    try:
        from gateway.app.services.plc.fix_loop import run_fix_loop
    except Exception as exc:  # noqa: BLE001
        return canvas, [], False, f"fix_loop 不可用：{exc}"

    try:
        result = run_fix_loop(
            canvas,
            attributions,
            project_path=project_source,
            plc_name=plc_name,
            max_rounds=1,
            use_llm=False,  # 流水线内修复只走规则，绝不调 LLM
            auto=True,
            compile_runner=_make_temp_compile_runner(project_source, plc_name),
        )
    except Exception as exc:  # noqa: BLE001 - 修复循环失败只 warning，不失败
        return canvas, [], False, f"fix_loop 执行异常：{exc}"

    fixed_canvas = CanvasState.from_dict(result.get("canvas") or canvas.to_dict())
    remaining = _extract_compile_errors(
        {"ok": bool(result.get("ok"))}, list(result.get("attributions") or [])
    )[0]
    rounds = result.get("rounds") or []
    if result.get("ok"):
        note = "修复循环 1 轮后编译通过"
    elif rounds and rounds[-1].get("stopped") == "no_ops":
        note = "无可自动修复项（规则库无匹配）"
    elif remaining:
        note = f"修复后剩余 {len(remaining)} 个错误（原始 {len(attributions)} 条归因）"
    else:
        note = "修复循环未取得编译结论"
    return fixed_canvas, remaining, True, note


# ---------------------------------------------------------------------------
# 作业入口
# ---------------------------------------------------------------------------


def create_refactor_pipeline_job(
    canvas_dict: dict[str, Any],
    *,
    project_name: str = "",
    do_compile: bool = True,
    auto_fix: bool = True,
    evidence_dir: str = "",
) -> dict[str, Any]:
    """创建并调度重构流水线作业；立即返回作业快照（后台线程执行）。

    ``do_compile`` 默认 True（请求编译验证，环境不可用时阶段内诚实 skipped）；
    ``auto_fix`` 默认 True。target 命名 ``U1_{project_name}``（缺省取画布名）。
    ``evidence_dir`` 可选（Openness XML 导出目录,启用证据驱动的数组/接口修复;
    缺省时探测工作区 baseline,再无则退回无证据模式）。
    """
    job_id = uuid.uuid4().hex[:16]
    stages = [{"name": name, "status": "pending", "detail": ""} for name in STAGES]
    job = {
        "id": job_id,
        "status": "running",
        "stage": STAGES[0],
        "stages": stages,
        "result": None,
        "error": None,
        "package_path": "",
        "cancel_requested": False,
        "created_at": _now(),
        "updated_at": _now(),
        "request": {
            "project_name": str(project_name or ""),
            "do_compile": bool(do_compile),
            "auto_fix": bool(auto_fix),
            "evidence_dir": str(evidence_dir or ""),
        },
    }
    with _lock:
        _purge_locked()
        _jobs[job_id] = job

    _pool.submit(
        _run_job,
        job_id,
        canvas_dict,
        project_name=str(project_name or ""),
        do_compile=bool(do_compile),
        auto_fix=bool(auto_fix),
        evidence_dir=str(evidence_dir or ""),
    )
    return get_refactor_pipeline_job(job_id) or job


def _run_job(
    job_id: str,
    canvas_dict: dict[str, Any],
    *,
    project_name: str,
    do_compile: bool,
    auto_fix: bool,
    evidence_dir: str = "",
) -> None:
    """流水线编排：五个阶段顺序推进，阶段边界检查取消，全程不泄漏线程。"""
    warnings: list[str] = []
    change_id = ""
    # 等价性报告的"重构前"快照(阶段 5 生成报告用;deepcopy 防阶段间共享引用)
    before_canvas_dict = deepcopy(canvas_dict or {})
    try:
        canvas = CanvasState.from_dict(canvas_dict or {})
        effective_name = (str(project_name or "").strip() or canvas.project_name or "Refactored").strip()
        target = f"U1_{effective_name}"

        # —— 阶段 1：refactor ——
        if _cancel_guard(job_id, list(STAGES)):
            return
        _set_stage(job_id, "refactor", "running", f"执行 AF V1.2 重构（target={target}）…")
        canvas, report, stage_warnings = _stage_refactor(canvas, target)
        warnings.extend(stage_warnings)
        # 引擎完全降级（零 AF 块）：中间三段照契约跳过，降级证据转 warnings，
        # 流水线整体仍 ok（由 warnings 表达降级），package 段收据如实呈现。
        degraded = _report_degraded(report)
        summary = _refactor_summary(report)
        if degraded:
            summary += f"（{DEGRADED_SKIP_REASON}）"
            warnings.extend(_degrade_warnings(report))
        _set_stage(job_id, "refactor", "ok", summary)

        # PCEC 开账（touched 覆盖 AF 新块 + 被取代旧块；降级时 AF 新块为空，touched=旧块全集）
        source_path = _resolve_project_source(canvas)
        change_id = open_refactor_change(canvas, report, target=target, project_path=source_path)
        with _lock:
            live = _jobs.get(job_id)
            if live is not None:
                live["change_id"] = change_id

        # —— 阶段 2：auto_fix ——
        if _cancel_guard(job_id, STAGES[1:]):
            return
        if degraded:
            _set_stage(job_id, "auto_fix", "skipped", DEGRADED_SKIP_REASON)
        elif not auto_fix:
            _set_stage(job_id, "auto_fix", "skipped", "未请求自动修复（auto_fix=false）")
        else:
            _set_stage(job_id, "auto_fix", "running", "应用规则自动修复…")
            canvas, _applied, diagnostics, note = _stage_auto_fix(canvas, evidence_dir=evidence_dir)
            warnings[:0] = diagnostics  # diagnostics 转入 warnings 前若干条
            if note.startswith("skipped:"):
                _set_stage(job_id, "auto_fix", "skipped", note[len("skipped:"):])
            else:
                _set_stage(job_id, "auto_fix", "ok", note)

        # —— 阶段 3：compile（临时副本，非破坏）——
        if _cancel_guard(job_id, STAGES[2:]):
            return
        compile_info: dict[str, Any]
        compile_attributions: list[dict[str, Any]] = []
        if degraded:
            compile_info = {
                "compiled": False,
                "skipped_reason": DEGRADED_SKIP_REASON,
                "errors": [],
                "warnings_count": 0,
            }
            _set_stage(job_id, "compile", "skipped", DEGRADED_SKIP_REASON)
        elif not do_compile:
            compile_info = {
                "compiled": False,
                "skipped_reason": "未请求编译验证（do_compile=false）",
                "errors": [],
                "warnings_count": 0,
            }
            _set_stage(job_id, "compile", "skipped", "未请求编译验证（do_compile=false）")
        else:
            _set_stage(job_id, "compile", "running", "临时副本编译验证（不写真实工程）…")
            if not source_path:
                compile_info = {
                    "compiled": False,
                    "skipped_reason": "画布/会话拿不到项目源路径（canvas.source 未携带工程且工作区无该工程）",
                    "errors": [],
                    "warnings_count": 0,
                }
            else:
                plc_name = str(getattr(canvas.source, "plc_name", "") or "") if canvas.source else ""
                info = _temp_compile(canvas, project_source=source_path, plc_name=plc_name)
                excluded_superseded = list(info.get("excluded_superseded") or [])
                if excluded_superseded:
                    warnings.append(
                        "已取代旧块不参与编译写集（"
                        f"{len(excluded_superseded)} 个，如 {', '.join(excluded_superseded[:4])}）"
                    )
                compile_attributions = list(info["attributions"] or [])
                if not info["ran"]:
                    compile_info = {
                        "compiled": False,
                        "skipped_reason": info["skipped_reason"] or "编译未执行",
                        "errors": list(info["errors"] or []),
                        "warnings_count": 0,
                    }
                else:
                    compile_info = {
                        "compiled": True,
                        "errors": list(info["errors"] or []),
                        "warnings_count": int(info["warnings_count"] or 0),
                        # TIA 指认的不一致块名单(编译 API 不给逐条错误文本,
                        # IsConsistent 巡检是唯一宿主归属通道;如实入 result/收据)
                        "inconsistent_blocks": list(info.get("inconsistent_blocks") or []),
                    }
            detail = (
                f"编译通过（0 错误 / {compile_info['warnings_count']} 警告）"
                if compile_info["compiled"] and not compile_info["errors"]
                else (
                    f"临时副本编译发现 {len(compile_info['errors'])} 个错误"
                    if compile_info["compiled"]
                    else f"跳过编译：{compile_info.get('skipped_reason')}"
                )
            )
            if compile_info.get("compiled") and compile_info.get("inconsistent_blocks"):
                detail += f"（不一致块：{'、'.join(compile_info['inconsistent_blocks'][:6])}）"
            if compile_info["compiled"]:
                _set_stage(job_id, "compile", "ok", detail)
            else:
                _set_stage(job_id, "compile", "skipped", detail)

        # —— 阶段 4：fix_loop（仅当请求了编译且错误非空）——
        if _cancel_guard(job_id, STAGES[3:]):
            return
        errors_now: list[str] = list(compile_info.get("errors") or [])
        if degraded:
            _set_stage(job_id, "fix_loop", "skipped", DEGRADED_SKIP_REASON)
        elif not do_compile:
            _set_stage(job_id, "fix_loop", "skipped", "未请求编译，跳过修复循环")
        elif not compile_info.get("compiled") and not errors_now:
            reason = str(compile_info.get("skipped_reason") or "")
            _set_stage(
                job_id,
                "fix_loop",
                "skipped",
                "编译未执行，跳过修复循环" + (f"：{reason}" if reason else ""),
            )
        elif not errors_now:
            _set_stage(job_id, "fix_loop", "skipped", "编译通过（无错误），无需修复循环")
        else:
            _set_stage(job_id, "fix_loop", "running", f"规则修复 1 轮（{len(errors_now)} 个错误）…")
            plc_name = str(getattr(canvas.source, "plc_name", "") or "") if canvas.source else ""
            canvas, remaining, executed, note = _fix_loop_round(
                canvas,
                compile_attributions,
                project_source=source_path,
                plc_name=plc_name,
            )
            if not executed:
                warnings.append(note)
                _set_stage(job_id, "fix_loop", "skipped", note)
            else:
                if len(remaining) >= len(errors_now):
                    warnings.append(f"修复循环无进展：剩余错误 {len(remaining)}/{len(errors_now)}")
                # 剩余错误如实覆盖 result.compile.errors(修复后复编译的结论);
                # 无可修复项(stopped=no_ops)时没有复编译——保留原编译错误清单,
                # 覆盖成空列表会把 9 错吞成 1 条空回退(V19 实测的记账 bug)
                if remaining or note.startswith("修复循环") or "剩余" in note:
                    compile_info["errors"] = remaining[:_ERRORS_LIMIT]
                _set_stage(job_id, "fix_loop", "ok", note)

        # —— 阶段 5：package ——
        if _cancel_guard(job_id, STAGES[4:]):
            return
        _set_stage(job_id, "package", "running", "生成交付包…")
        from gateway.app.services.plc import equivalence, release_package

        # 等价性核对报告(重构前快照 vs 交付画布+引擎report)随包交付
        equivalence_report: dict[str, Any] | None = None
        try:
            equivalence_report = equivalence.build_equivalence_report(
                before_canvas_dict, canvas.to_dict(), report
            )
        except Exception as exc:  # noqa: BLE001 - 报告失败不阻塞交付,warning 如实记
            warnings.append(f"等价性核对报告生成失败：{exc}")

        pkg = release_package.build_release_package(
            canvas,
            report,
            project_name=effective_name,
            compile_info=compile_info,
            equivalence_report=equivalence_report,
        )
        with _lock:
            live = _jobs.get(job_id)
            if live is not None:
                live["package_path"] = pkg["zip_path"]
        _set_stage(
            job_id,
            "package",
            "ok",
            f"交付包已生成（{pkg['file_count']} 个文件 / {pkg['size_bytes']} 字节）",
        )

        eq_verdict = (equivalence_report or {}).get("io_verdict", {})
        result = {
            "canvas": canvas.to_dict(),
            "report": report,
            "compile": compile_info,
            "equivalence": (
                {
                    "io_preserved": bool(eq_verdict["io_preserved"]),
                    "preserved_count": int(eq_verdict["preserved_count"]),
                    "dropped_count": int(eq_verdict["dropped_count"]),
                    "added_count": int(eq_verdict["added_count"]),
                    "dropped": list(eq_verdict["dropped"])[:_WARNINGS_LIMIT],
                    "statement_delta_pct": equivalence_report.get("statement_counts", {}).get("delta_pct"),
                }
                if equivalence_report is not None
                else None
            ),
            "package": {"size_bytes": int(pkg["size_bytes"]), "file_count": int(pkg["file_count"])},
            "warnings": [w for w in warnings if w][:_WARNINGS_LIMIT],
        }
        with _lock:
            live = _jobs.get(job_id)
            if live is None:
                return
            live["result"] = result
            live["status"] = "ok"
            live["updated_at"] = _now()
        settle_refactor_change(
            change_id,
            ok=True,
            detail={
                "pipeline_job_id": job_id,
                "compile": {
                    "compiled": bool(compile_info.get("compiled")),
                    "error_count": len(compile_info.get("errors") or []),
                    "skipped_reason": compile_info.get("skipped_reason", ""),
                },
                "package": {"file_count": pkg["file_count"], "size_bytes": pkg["size_bytes"]},
                "diagnostics": [str(e)[:300] for e in (compile_info.get("errors") or [])[:20]],
            },
        )
        logger.info(
            "refactor pipeline ok id=%s target=%s compile=%s errors=%d files=%d",
            job_id,
            target,
            compile_info.get("compiled"),
            len(compile_info.get("errors") or []),
            pkg["file_count"],
        )
    except Exception as exc:  # noqa: BLE001 - 任何阶段异常收敛为作业 error，线程正常归还线程池
        message = f"{type(exc).__name__}: {exc}"
        logger.error("refactor pipeline failed id=%s: %s\n%s", job_id, exc, traceback.format_exc())
        _set_terminal_error(job_id, message)
        settle_refactor_change(
            change_id,
            ok=False,
            detail={"pipeline_job_id": job_id, "error": message},
        )


__all__ = [
    "STAGES",
    "cancel_refactor_pipeline_job",
    "create_refactor_pipeline_job",
    "get_refactor_pipeline_job",
    "open_refactor_change",
    "refactor_job_view",
    "settle_refactor_change",
]
