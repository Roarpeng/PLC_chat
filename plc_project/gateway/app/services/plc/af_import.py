"""导入自动 AF 化——角色覆盖层服务(契约 docs/23 §0 / §2,并行线 I)。

导入链把 TIA 导出解析成画布(SCL 直译已在导入链完成),本模块在其上做
**纯逻辑层**的 AF 角色分析与标注:

- ``analyze_import(canvas)``:复用 ``plc_engine.af.af_mapper.LegacyToAfMapper``
  的 Unit/EM/CM 检测结论,映射到**现有块名**(绝不重命名/重建画布);
- ``apply_af_overlay(canvas, report)``:物理冻结铁律下只做两件事——已解析块
  挂 ``af_role``、pending 块附提示性 errors 文案;DB/UDT/OB/安全块一律
  role=global/safety 永不转换;无法证明等价的块诚实标 pending;
- ``write_report`` / ``latest_report``:报告落盘 ``PLC_WORK_DIR/af_reports/``
  (temp+rename 原子写),供 ``GET /canvas/af/report/latest`` 查询;
- ``record_pcec``:转换经 PCEC 留痕(kind=``af_import``,reviewer=
  ``auto_import``,v0/v1=pass,全程 try/except 只 warning)。

本模块**禁止**改动块的 scl_body / status(除 pending 文案外)/ 接口 / 标签 /
OB 编号与调用顺序,禁止调用 ``refactor_canvas_to_af`` 重建画布。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import CanvasState

logger = logging.getLogger(__name__)

# 契约 §2 的角色词表;pending 块在画布上标记 af_pending_manual(契约 §0)
ROLE_UNIT = "unit"
ROLE_EM = "em"
ROLE_CM = "cm"
ROLE_GLOBAL = "global"
ROLE_SAFETY = "safety"
ROLE_UNKNOWN = "unknown"
DEFINITIVE_ROLES = frozenset({ROLE_UNIT, ROLE_EM, ROLE_CM, ROLE_GLOBAL, ROLE_SAFETY})
PENDING_MARKER = "af_pending_manual"

PENDING_NOTE_PREFIX = "AF 转换待人工确认:"

PENDING_REASON_UNRESOLVED = (
    "映射引擎未能证明该块与标准结构的等价性(未识别为模式控制/步序/"
    "设备控制/安全/数据块),保留原始形态待人工确认"
)
PENDING_REASON_MAPPER_FAILED = "映射引擎分析失败,无法自动判定角色"

# af_analysis 摘要兜底(契约 §2:导入失败兜底,conformant=null)
AF_ANALYSIS_FALLBACK: dict[str, Any] = {
    "conformant": None,
    "roles_count": 0,
    "pending_count": 0,
}

# 安全块判定:块名/块头注释含安全关键词,或 F 库命名(F_/F- 前缀);
# 接口/程序体中的安全信号**引用**不视为安全块(引用≠本体)。
_SAFETY_KEYWORDS = (
    "safety", "estop", "emergency", "guard", "curtain", "interlock",
    "急停", "安全", "互锁",
)
_F_NAME_RE = re.compile(r"^f[_\-]", re.IGNORECASE)

# 导入链 ``_infer_af_role`` 的 AF 标准块名 → 架构角色(A 原生工程导入时
# 块名即 AF 标准名,直接折算,不再进映射器猜)。
_IMPORT_ROLE_TO_AF_ROLE = {
    "CallUnit": ROLE_UNIT,
    "Sequence": ROLE_EM,
    "CallEquipment": ROLE_CM,
    "ControlNodes": ROLE_CM,
    "EmNodes": ROLE_CM,
    "StepToString": ROLE_CM,
    "CollectAlarms": ROLE_GLOBAL,
    "SimulationData": ROLE_GLOBAL,
    "HmiInterface": ROLE_GLOBAL,
    "Config": ROLE_GLOBAL,
    "Alarms": ROLE_GLOBAL,
    "OB": ROLE_GLOBAL,
}


def _is_safety_block(block: Any) -> bool:
    name = str(block.name or "")
    text = f"{name} {block.comment or ''}".lower()
    if any(k in text for k in _SAFETY_KEYWORDS):
        return True
    return bool(_F_NAME_RE.match(name))


def analyze_import(canvas: CanvasState) -> dict[str, Any]:
    """分析画布并产出 AF 导入报告(纯读,不改画布)。

    返回 ``{conformant, roles, pending, coverage, ...}``:

    - ``roles``: 现有块名 -> ``unit|em|cm|global|safety|unknown``;
      判定优先级(物理冻结优先):DB/UDT -> global;OB -> global(OB 编号
      与调用顺序冻结);安全名/块头注释 -> safety;其余复用
      ``LegacyToAfMapper`` 结论——模式控制块 -> unit、步序源块 -> em、
      设备集线(CM Hub)映射 -> cm;导入链已识别的 AF 标准块名直接折算;
      都不命中 -> unknown + pending(诚实边界,绝不静默近似)。
    - ``pending``: ``[{block, reason}]``,仅 unknown 块;DB/safety 永不 pending;
    - ``conformant``: pending 为空(全部块获得明确角色);
    - ``coverage``: 明确角色块占比(0-100)。

    映射器自身异常时退化为全 pending 报告(附失败原因),不向上抛。
    """
    blocks = canvas.blocks if canvas is not None else {}
    report: dict[str, Any] = {
        "project_name": (canvas.project_name if canvas is not None else "") or "",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "conformant": False,
        "roles": {},
        "roles_count": 0,
        "pending": [],
        "pending_count": 0,
        "coverage": 0.0,
        "blocks_total": len(blocks),
        "frozen": {"global": 0, "safety": 0},
        "mapper": {},
    }
    if not blocks:
        report["conformant"] = True
        report["coverage"] = 100.0
        return report

    mode_blocks: set[str] = set()
    em_blocks: set[str] = set()
    cm_blocks: set[str] = set()
    mapper_summary: dict[str, Any] = {}
    try:
        from plc_engine.af.af_mapper import LegacyToAfMapper

        analysis = LegacyToAfMapper(canvas).analyze()
        for unit in analysis.units:
            mode_blocks.update(unit.mode_control_blocks or [])
            for em in unit.ems:
                em_blocks.update(em.source_blocks or [])
        cm_blocks = {
            name
            for name, target in (analysis.block_mapping or {}).items()
            if "CallEquipment" in str(target)
        }
        mapper_summary = {
            "units": len(analysis.units),
            "ems": sum(len(u.ems) for u in analysis.units),
            "io_total": analysis.total_ios_detected,
            "io_retained": analysis.retained_ios_count,
            "io_retention_rate": analysis.io_retention_rate,
        }
    except Exception as exc:  # noqa: BLE001 — 映射器失败退化为诚实 pending
        logger.warning("af_import: LegacyToAfMapper 分析失败,退化为全 pending: %s", exc)
        mapper_summary = {"error": str(exc)}

    roles: dict[str, str] = {}
    pending: list[dict[str, str]] = []
    for key, block in blocks.items():
        btype = str(block.block_type or "").upper()
        if btype in {"DB", "UDT"}:
            roles[key] = ROLE_GLOBAL  # DB 布局与偏移一字不动,永不转换
        elif btype == "OB":
            roles[key] = ROLE_GLOBAL  # OB 编号与调用顺序冻结
        elif _is_safety_block(block):
            roles[key] = ROLE_SAFETY  # F/安全块冻结,永不转换
        elif key in mode_blocks:
            roles[key] = ROLE_UNIT
        elif key in em_blocks:
            roles[key] = ROLE_EM
        elif key in cm_blocks:
            roles[key] = ROLE_CM
        elif _IMPORT_ROLE_TO_AF_ROLE.get(str(block.af_role or "")):
            roles[key] = _IMPORT_ROLE_TO_AF_ROLE[str(block.af_role)]
        else:
            roles[key] = ROLE_UNKNOWN
            pending.append(
                {
                    "block": key,
                    "reason": (
                        PENDING_REASON_MAPPER_FAILED
                        if mapper_summary.get("error")
                        else PENDING_REASON_UNRESOLVED
                    ),
                }
            )

    roles_count = sum(1 for r in roles.values() if r != ROLE_UNKNOWN)
    report["roles"] = roles
    report["pending"] = pending
    report["roles_count"] = roles_count
    report["pending_count"] = len(pending)
    report["conformant"] = not pending
    report["coverage"] = round(roles_count / len(blocks) * 100.0, 2)
    report["frozen"] = {
        "global": sum(1 for r in roles.values() if r == ROLE_GLOBAL),
        "safety": sum(1 for r in roles.values() if r == ROLE_SAFETY),
    }
    report["mapper"] = mapper_summary
    return report


def summarize(report: dict[str, Any] | None) -> dict[str, Any]:
    """响应摘要字段(契约 §2:``af_analysis = {conformant, roles_count, pending_count}``)。"""
    if not isinstance(report, dict):
        return dict(AF_ANALYSIS_FALLBACK)
    return {
        "conformant": report.get("conformant"),
        "roles_count": int(report.get("roles_count") or 0),
        "pending_count": int(report.get("pending_count") or 0),
    }


def apply_af_overlay(canvas: CanvasState, report: dict[str, Any]) -> CanvasState:
    """把分析报告叠加到画布(物理冻结铁律下的最小标注)。

    只做两件事,绝不触碰 scl_body / status / 接口 / 标签 / OB:

    - 已解析块(unit/em/cm/global/safety)挂 ``af_role``;
    - pending 块标 ``af_role="af_pending_manual"`` 并在 errors 追加提示性
      文案「AF 转换待人工确认:<原因>」(幂等,不重复追加;status 原样)。
    """
    roles = report.get("roles") if isinstance(report, dict) else None
    pending_reasons = {
        str(p.get("block")): str(p.get("reason") or "")
        for p in (report.get("pending") or [])
        if isinstance(p, dict) and p.get("block")
    } if isinstance(report, dict) else {}

    for key, block in canvas.blocks.items():
        role = str((roles or {}).get(key) or "")
        if role in DEFINITIVE_ROLES:
            block.af_role = role
            continue
        if key in pending_reasons:
            if block.af_role != PENDING_MARKER:
                block.af_role = PENDING_MARKER
            note = f"{PENDING_NOTE_PREFIX}{pending_reasons[key]}"
            if note not in block.errors:
                block.errors.append(note)
    return canvas


# ---------------------------------------------------------------- 报告落盘 --


def _reports_root() -> Path:
    """``PLC_WORK_DIR/af_reports``(解析顺序对齐 pcec.changes_root)。"""
    work = os.getenv("PLC_WORK_DIR", "").strip()
    base = Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"
    root = base / "af_reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(project_name: str) -> str:
    safe = re.sub(r"[^\w\-.]+", "_", str(project_name or "").strip())
    return safe.strip("_") or "project"


def write_report(project_name: str, report: dict[str, Any]) -> Path:
    """报告写到 ``PLC_WORK_DIR/af_reports/<project>-<ts>.json``(temp+rename 原子写)。"""
    path = _reports_root() / (
        f"{_safe_name(project_name)}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}.json"
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    logger.info(
        "af_import: 报告已落盘 %s(roles=%s pending=%s)",
        path.name,
        report.get("roles_count"),
        report.get("pending_count"),
    )
    return path


def latest_report(project_name: str = "") -> dict[str, Any] | None:
    """取项目最新导入分析报告;无匹配返回 None。

    ``project_name`` 为空时取目录内最新一份(任何项目)。
    """
    prefix = f"{_safe_name(project_name)}-" if str(project_name or "").strip() else ""
    candidates = [
        p
        for p in _reports_root().glob("*.json")
        if p.is_file() and (not prefix or p.name.startswith(prefix))
    ]
    if not candidates:
        return None
    try:
        data = json.loads(max(candidates, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("af_import: 最新报告读取失败: %s", exc)
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- PCEC 留痕 --


def record_pcec(
    canvas: CanvasState,
    report: dict[str, Any],
    project_path: str | Path | None = None,
) -> str | None:
    """AF 角色标注经 PCEC 留痕:kind=af_import,v0/v1=pass,reviewer=auto_import → applied。

    契约 §2:自动转换由导入动作承载——事务走 proposed→analyzed→validated→
    approved→applied,touched=已标注块,baseline=工程基线(project_path 缺省
    时为空指纹)。**全程 try/except,任何异常只 warning,绝不阻塞导入**;
    成功返回 change_id。
    """
    try:
        from plc_engine import pcec

        roles = (report or {}).get("roles") or {}
        touched = sorted(k for k, r in roles.items() if r in DEFINITIVE_ROLES)
        ops = [
            {"op": "af_annotate", "block": k, "af_role": roles[k]}
            for k in touched
        ]
        pending = (report or {}).get("pending") or []
        if pending:
            ops.append(
                {
                    "op": "af_pending_manual",
                    "blocks": sorted(str(p.get("block")) for p in pending if isinstance(p, dict)),
                    "note": "待人工确认,块体未做任何变更",
                }
            )

        baseline: dict[str, Any] = {}
        if project_path:
            baseline = pcec.project_baseline(project_path)

        change = pcec.new_change(
            "af_import",
            "导入自动AF化",
            ops=ops,
            touched_blocks=touched,
            baseline=baseline,
        )
        change["verification"]["v0_parsed"] = "pass"
        change["verification"]["v1_static"] = "pass"
        change["verification"]["detail"] = {
            "compile_job_id": "",
            "error_count": 0,
            "diagnostics": [
                (
                    f"roles={report.get('roles_count')} pending={report.get('pending_count')} "
                    f"coverage={report.get('coverage')}"
                ),
                "物理冻结:仅 af_role 标注与 pending 文案,scl/接口/标签/OB 未变",
            ],
        }
        pcec.transition(change, "analyzed", event="af_import_analyzed")
        pcec.transition(change, "validated", event="v0_v1_pass")
        change["approval"] = {
            "reviewer": "auto_import",
            "mode": "auto",
            "note": "自动转换由导入动作承载(契约 docs/23 §2)",
        }
        pcec.transition(change, "approved", event="auto_import")
        pcec.transition(change, "applied", event="af_role_overlay_applied")
        pcec.put_change(change)
        logger.info("af_import: PCEC 事务已留痕 %s(touched=%d)", change["change_id"], len(touched))
        return str(change["change_id"])
    except Exception as exc:  # noqa: BLE001 — 只 warning,绝不阻塞导入
        logger.warning("af_import: PCEC 留痕失败(不阻塞导入): %s", exc)
        return None
