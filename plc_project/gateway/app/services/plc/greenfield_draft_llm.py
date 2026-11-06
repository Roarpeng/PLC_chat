"""Greenfield 首版 LLM 结构化解析：工艺描述 → 丰富首版 IR（planner 的前置增强）。

无 IR 时的对话首版消息优先走本模块：LLM 把口语化长描述解析为结构化 spec
JSON，本地做确定性结构校验（非法 → 附错误重试 → 仍非法返回 None），再构造
``AfProject`` 并经 ``GreenfieldIR.from_af_project`` 提升为强类型 IR —— 复用
既有契约注入（compat_refs / io_bindings）、OB 编号派生与默认边逻辑，产物与
确定性 planner 路径结构同源（ID 命名空间 / 边白名单全部走同一套机制）。

fail-closed 铁律：LLM 未配置 / 输出非法 / 重试耗尽一律返回 ``(None, 原因)``
由调用方（greenfield_chat）诚实回退确定性 planner，绝不静默降级。AI 推断的
联锁标记 ``source="inferred"``，校验时自动进「待确认问题」，不冒充用户裁定。

范围铁律（legacy_guard AST 闭包）：本模块不得 import 存量重构/回写链模块。
"""
from __future__ import annotations

import json
import re
from typing import Any, get_args

from gateway.app.services.plc.llm_explain import (
    LlmNotConfigured,
    chat_completion_raw,
    llm_settings,
)
from plc_engine.af.af_model import (
    AfCm,
    AfCmType,
    AfEm,
    AfJob,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)
from plc_engine.af.greenfield_ir import GFInterlock, GreenfieldIR

#: 结构校验失败的自纠重试上限（总尝试 = 1 + 该值）。
MAX_DRAFT_RETRIES = 1

#: 合法 CM 类型全集（与 ``af_model.AfCmType`` Literal 同源，禁止手抄漂移）。
VALID_CM_TYPES: frozenset[str] = frozenset(get_args(AfCmType))

#: 规模护栏：防 LLM 输出风暴（超出即结构校验失败，触发重试/回退）。
MAX_UNITS = 9
MAX_EMS = 20
MAX_CMS = 60
MAX_STEPS = 200
#: 单工序步序上限（正常步号 10/20/… 不得侵入 9xx 异常段）。
MAX_STEPS_PER_EM = 80

#: 正常步号从 10 起、步距 10；异常段 900..989；999 为统一错误步。
_STEP_START = 10
_STEP_STRIDE = 10
_ABNORMAL_START = 900
_ABNORMAL_MAX = 989
_ERROR_STEP = 999

_BRANCH_KINDS = frozenset({"alt", "opt", "else"})

_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")

_VALID_CM_TYPES_TEXT = ", ".join(sorted(VALID_CM_TYPES))

_DRAFT_SYSTEM_PROMPT = (
    "你是「绿地工程首版规格解析器」：把工程师的口语化工艺描述一次性解析成"
    "结构化的西门子 AF V1.2 工程规格 JSON。\n"
    "只输出一个 JSON 对象（不要 Markdown 围栏、不要解释文字），结构（字段名固定）：\n"
    "{\n"
    '  "project": {"name": "英文工程名", "business_label": "中文工位/产线名"},\n'
    '  "units": [{"name": "英文单元名", "business_label": "中文名"}],\n'
    '  "ems": [{"id": 0, "unit": 0, "name": "英文工序名", "business_label": "中文工序名"}],\n'
    '  "cms": [{"em": 0, "name": "英文设备名", "cm_type": "LBC_TwoWayActuator", "business_label": "中文设备名"}],\n'
    '  "jobs": [{"em": 0, "job_id": 1, "name": "AutoProduction"}],\n'
    '  "steps": [{"em": 0, "step_id": 10, "name": "WAIT_PART",\n'
    '             "actions": ["#controlNodes.cylClamp.commands.workPosition := TRUE;"],\n'
    '             "transition_condition": "#controlNodes.sensorPart.status.signal",\n'
    '             "timeout_ms": 5000, "next_step_id": 20, "error_step_id": 999,\n'
    '             "branch": {"kind": "alt", "condition": "可选：分支说明"}}],\n'
    '  "modes": [{"id": "MODE_AUTO", "packml_mode": "Production"},\n'
    '            {"id": "MODE_MANUAL", "packml_mode": "Manual"}],\n'
    '  "interlocks": [{"target": "设备名（如 cylClamp）", "expression": "布尔表达式"}]\n'
    "}\n"
    "解析规则：\n"
    "- ems[]：描述里的每道工序（上下料/涂胶/打磨/检测/输送…）各建一个 EM；"
    "id 为数组下标（0 起），unit 为 units 下标（缺省 0）\n"
    "- cms[]：每个物理设备一个 CM，em 为所属 EM 下标；"
    "气缸/夹爪/吸盘→LBC_TwoWayActuator，单动执行件→LBC_SimpleActuator，"
    "三位置→LBC_ThreeWayActuator，传感器/光电/急停/光幕→LBC_DigitalSignal，"
    "模拟量输入→LBC_AnalogInput，模拟量输出→LBC_AnalogOutput，伺服/轴→LBC_AxisControl，"
    "滤波→LBC_Pt1Filter，电机/输送带/泵→LBC_MotorStarter，驱动→LBC_DriveControl_StdPlc\n"
    f"- cm_type 只能取：{_VALID_CM_TYPES_TEXT}\n"
    "- steps[]：每道工序按工艺顺序展开为多步；正常步 step_id 依次 10/20/30…，"
    "异常处理步用 900/910…，999 保留为统一错误步；"
    "next_step_id 指向同工序下一步（末步回 1），error_step_id 通常为 999\n"
    "- actions 引用设备命令（如 \"#controlNodes.cylClamp.commands.workPosition := TRUE;\"），"
    "transition_condition 引用设备状态（如 \"#controlNodes.sensorPart.status.signal\"），"
    "不要直接写 %I/%Q 物理地址\n"
    "- name 用大写下划线英文标识符（如 WAIT_PART / GLUE_APPLY），中文说明放 business_label\n"
    "- 提供了 contract（只读冻结契约目录）时，设备命名与动作/条件尽量关联其中的 IO/DB 名\n"
    "- 描述含糊处按工业工程常识合理补全（等待→数字信号、执行→执行器/轴命令），"
    "不要输出空规格\n"
)


def _parse_json_object(raw: str) -> tuple[dict[str, Any] | None, str]:
    """解析 LLM 输出：容忍 ```json 围栏与前后杂文字。

    仿照 ``greenfield_chat._parse_json_object``（本模块与其互相独立，避免循环
    import；两处口径需保持一致）。
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline >= 0 else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj, ""
        return None, "顶层不是 JSON 对象"
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj, ""
        except json.JSONDecodeError:
            pass
    return None, "无法解析为 JSON 对象"


def _int(value: Any, default: int) -> int:
    """把 JSON 值还原为 int（``0`` 合法，不被 ``or default`` 吞掉）。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_identifier(name: Any, fallback_prefix: str) -> str:
    """清洗为合法 SCL 标识符（字母数字下划线，首字符为字母）。"""
    cleaned = _IDENT_RE.sub("", str(name or ""))
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"{fallback_prefix}{cleaned}" if cleaned else fallback_prefix
    return cleaned


def _step_identifier(name: Any, step_id: int) -> str:
    """步序名：大写下划线标识符，缺省 STEP_<id>。"""
    cleaned = _IDENT_RE.sub("_", str(name or "")).strip("_").upper()
    return cleaned or f"STEP_{step_id}"


def _contract_digest(contract: Any) -> dict[str, Any]:
    """契约只给名字目录（物理值只读不可改，LLM 无需细节）。"""
    io_names = [str(getattr(e, "name", "") or "") for e in getattr(contract, "io_entries", []) or []]
    dbs: list[dict[str, Any]] = []
    for d in getattr(contract, "db_structs", []) or []:
        member_names = [
            str(m.get("name") if isinstance(m, dict) else getattr(m, "name", "") or "")
            for m in (getattr(d, "members", []) or [])
        ]
        dbs.append(
            {
                "name": str(getattr(d, "name", "") or ""),
                "member_names_preview": [m for m in member_names if m][:60],
            }
        )
    symbols = [str(getattr(s, "name", "") or "") for s in getattr(contract, "symbols", []) or []]
    return {
        "immutable": True,
        "io_names": [n for n in io_names if n][:120],
        "dbs": dbs,
        "symbol_names": [n for n in symbols if n][:120],
    }


def _unit_count(spec: dict[str, Any]) -> int:
    units = spec.get("units")
    return len(units) if isinstance(units, list) and units else 1


def _validate_spec(spec: dict[str, Any]) -> str:
    """结构校验：返回错误说明（空串表示通过）。

    只做「能否安全构造 IR」的硬校验（索引越界 / 类型不符 / 枚举非法 / 规模
    超限）；工程合理性（步序逻辑、动作语义）交给后续画布与校验器。
    """
    project = spec.get("project")
    if project is not None and not isinstance(project, dict):
        return "project 必须是对象"
    if isinstance(project, dict):
        name = project.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            return "project.name 必须是非空字符串"

    n_units = _unit_count(spec)
    units = spec.get("units")
    if units is not None:
        if not isinstance(units, list) or not units:
            return "units 必须是非空数组"
        if len(units) > MAX_UNITS:
            return f"units 数量超限（>{MAX_UNITS}）"
        for i, u in enumerate(units):
            if not isinstance(u, dict) or not str(u.get("name") or u.get("business_label") or "").strip():
                return f"units[{i}] 缺 name/business_label"

    ems = spec.get("ems")
    if not isinstance(ems, list) or not ems:
        return "ems 必须是非空数组（至少一道工序）"
    if len(ems) > MAX_EMS:
        return f"ems 数量超限（>{MAX_EMS}）"
    em_idents: set[str] = set()
    for i, em in enumerate(ems):
        if not isinstance(em, dict):
            return f"ems[{i}] 必须是对象"
        if not str(em.get("name") or "").strip():
            return f"ems[{i}] 缺 name"
        unit = _int(em.get("unit"), 0)
        if not 0 <= unit < n_units:
            return f"ems[{i}].unit 越界：{unit}（units 共 {n_units} 个）"
        ident = _clean_identifier(em.get("name"), f"Em{i + 1}")
        if ident in em_idents:
            return f"ems[{i}] 工序名清洗后冲突：{ident}"
        em_idents.add(ident)

    cms = spec.get("cms")
    if not isinstance(cms, list) or not cms:
        return "cms 必须是非空数组（至少一个设备）"
    if len(cms) > MAX_CMS:
        return f"cms 数量超限（>{MAX_CMS}）"
    cm_idents: set[str] = set()
    for i, cm in enumerate(cms):
        if not isinstance(cm, dict):
            return f"cms[{i}] 必须是对象"
        em = _int(cm.get("em"), 0)
        if not 0 <= em < len(ems):
            return f"cms[{i}].em 越界：{em}（ems 共 {len(ems)} 个）"
        if not str(cm.get("name") or "").strip():
            return f"cms[{i}] 缺 name"
        cm_type = str(cm.get("cm_type") or "")
        if cm_type not in VALID_CM_TYPES:
            return f"cms[{i}].cm_type 非法：{cm_type or '(空)'}（允许 {_VALID_CM_TYPES_TEXT}）"
        ident = _clean_identifier(cm.get("name"), f"Cm{i + 1}")
        if ident in cm_idents:
            return f"cms[{i}] 设备名清洗后冲突：{ident}"
        cm_idents.add(ident)

    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        return "steps 必须是非空数组（至少一个步序）"
    if len(steps) > MAX_STEPS:
        return f"steps 数量超限（>{MAX_STEPS}）"
    steps_per_em: dict[int, int] = {}
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            return f"steps[{i}] 必须是对象"
        em = _int(st.get("em"), 0)
        if not 0 <= em < len(ems):
            return f"steps[{i}].em 越界：{em}（ems 共 {len(ems)} 个）"
        sid = st.get("step_id")
        if sid is None or isinstance(sid, bool) or _int(sid, -1) < 1:
            return f"steps[{i}].step_id 非法：{sid!r}（需 ≥1 的整数）"
        actions = st.get("actions")
        if actions is not None and (
            not isinstance(actions, list) or any(not isinstance(a, str) for a in actions)
        ):
            return f"steps[{i}].actions 必须是字符串数组"
        branch = st.get("branch")
        if branch is not None and not isinstance(branch, dict):
            return f"steps[{i}].branch 必须是对象"
        steps_per_em[em] = steps_per_em.get(em, 0) + 1
    for em, count in steps_per_em.items():
        if count > MAX_STEPS_PER_EM:
            return f"ems[{em}] 步序过多（{count} > {MAX_STEPS_PER_EM}）"

    jobs = spec.get("jobs")
    if jobs is not None:
        if not isinstance(jobs, list):
            return "jobs 必须是数组"
        for i, j in enumerate(jobs):
            if not isinstance(j, dict):
                return f"jobs[{i}] 必须是对象"
            em = _int(j.get("em"), 0)
            if not 0 <= em < len(ems):
                return f"jobs[{i}].em 越界：{em}"

    modes = spec.get("modes")
    if modes is not None and (not isinstance(modes, list) or any(not isinstance(m, dict) for m in modes)):
        return "modes 必须是对象数组"

    interlocks = spec.get("interlocks")
    if interlocks is not None and (
        not isinstance(interlocks, list) or any(not isinstance(x, dict) for x in interlocks)
    ):
        return "interlocks 必须是对象数组"
    return ""


def _normalize_branch(branch: Any) -> dict[str, Any]:
    """归一 branch 为 {kind: alt|opt|else, condition: str}。"""
    if not isinstance(branch, dict) or not branch:
        return {}
    kind = str(branch.get("kind") or "alt").strip().lower()
    if kind not in _BRANCH_KINDS:
        kind = "alt"
    return {"kind": kind, "condition": str(branch.get("condition") or "").strip()}


def _normalize_steps(raw_steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, int]]:
    """步号规范化：正常步重排 10/20/…，异常段 900..989，999 唯一错误步。

    返回 (规范化后的步序列表, 旧步号→新步号映射)；next/error 引用经映射改写，
    悬空跳转收敛回就绪步 1 / 错误步 999（与 build_sample_ir 的取值风格一致）。
    """
    normal: list[tuple[int, dict[str, Any]]] = []
    abnormal: list[tuple[int, dict[str, Any]]] = []
    terminal: list[dict[str, Any]] = []
    for st in raw_steps:
        sid = _int(st.get("step_id"), 0)
        if sid >= _ERROR_STEP:
            terminal.append(st)
        elif sid >= _ABNORMAL_START:
            abnormal.append((sid, st))
        else:
            normal.append((sid, st))

    id_map: dict[int, int] = {}
    out: list[dict[str, Any]] = []
    next_id = _STEP_START
    for sid, st in normal:
        id_map[sid] = next_id
        out.append(dict(st, step_id=next_id))
        next_id += _STEP_STRIDE
    if next_id >= _ABNORMAL_START:
        raise ValueError("单工序正常步序过多，步号侵入 9xx 异常段")

    cursor = _ABNORMAL_START
    for sid, st in abnormal:
        new_sid = sid if cursor <= sid <= _ABNORMAL_MAX else cursor
        id_map[sid] = new_sid
        out.append(dict(st, step_id=new_sid))
        cursor = new_sid + _STEP_STRIDE
    if terminal:
        # 只保留一个显式 999 错误步；多余的并入该步。
        for st in terminal:
            id_map[_int(st.get("step_id"), _ERROR_STEP)] = _ERROR_STEP
        out.append(dict(terminal[0], step_id=_ERROR_STEP))

    # 缺失 next_step_id 时按顺序链接，末步回就绪步 1。
    for i, st in enumerate(out):
        if st.get("next_step_id") in (None, ""):
            st["next_step_id"] = out[i + 1]["step_id"] if i + 1 < len(out) else 1

    known = {st["step_id"] for st in out} | {1, _ERROR_STEP}

    def _remap(ref: int, *, error: bool) -> int:
        mapped = id_map.get(ref, ref)
        if mapped in known:
            return mapped
        return _ERROR_STEP if error else 1

    for st in out:
        st["next_step_id"] = _remap(_int(st.get("next_step_id"), 1), error=False)
        st["error_step_id"] = _remap(_int(st.get("error_step_id"), _ERROR_STEP), error=True)
        timeout = _int(st.get("timeout_ms"), 5000)
        st["timeout_ms"] = timeout if timeout > 0 else 5000
    return out, id_map


def _resolve_interlock_target(
    target: str, ir: GreenfieldIR, cm_name_to_id: dict[str, str]
) -> str | None:
    """联锁目标解析：设备名/设备 ID/业务名 → CM 或 EM 的 IR 节点 id。"""
    cm_id = cm_name_to_id.get(target)
    if cm_id:
        return cm_id
    for cm in ir.cms:
        if cm.id == target or (cm.business_label and cm.business_label == target):
            return cm.id
    for em in ir.ems:
        if target in (em.id, em.name, em.business_label):
            return em.id
    return None


def _build_ir(
    spec: dict[str, Any],
    prompt: str,
    contract: Any | None,
    fallback_project_name: str,
) -> GreenfieldIR:
    """已校验 spec → AfProject → ``GreenfieldIR.from_af_project`` → IR-only 回填。"""
    project = spec.get("project") if isinstance(spec.get("project"), dict) else {}
    proj_label = str(project.get("business_label") or "").strip()
    proj_name = _clean_identifier(
        str(project.get("name") or "").strip() or fallback_project_name, "Project"
    )
    units_spec = [u for u in (spec.get("units") or []) if isinstance(u, dict)]
    if not units_spec:
        units_spec = [{"name": proj_name, "business_label": proj_label or proj_name}]
    n_units = len(units_spec)

    ems_spec = spec["ems"]
    steps_by_em: dict[int, list[dict[str, Any]]] = {}
    for st in spec.get("steps") or []:
        steps_by_em.setdefault(_int(st.get("em"), 0), []).append(st)
    cms_by_em: dict[int, list[dict[str, Any]]] = {}
    for cm in spec.get("cms") or []:
        cms_by_em.setdefault(_int(cm.get("em"), 0), []).append(cm)
    jobs_by_em: dict[int, list[dict[str, Any]]] = {}
    for j in spec.get("jobs") or []:
        jobs_by_em.setdefault(_int(j.get("em"), 0), []).append(j)

    branch_backfill: list[tuple[str, int, dict[str, Any]]] = []
    # CM 编号镜像 from_af_project 的全局递增口径（U1EM1_CM1 / U1EM1_CM2 / …），
    # 用于把 LLM 的设备名解析回 IR 节点 id。
    cm_name_to_id: dict[str, str] = {}
    cm_counter = 0

    af_units: list[AfUnit] = []
    for u_idx in range(n_units):
        positions = [
            pos for pos, em in enumerate(ems_spec) if _int(em.get("unit"), 0) == u_idx
        ]
        af_ems: list[AfEm] = []
        for local_idx, pos in enumerate(positions, start=1):
            em = ems_spec[pos]
            em_id = f"U{u_idx + 1}EM{local_idx}"
            em_name = _clean_identifier(em.get("name"), f"Em{pos + 1}")
            em_label = str(em.get("business_label") or "").strip() or em_name

            norm_steps, _id_map = _normalize_steps(steps_by_em.get(pos) or [])
            af_steps: list[AfSequenceStep] = []
            for st in norm_steps:
                sid = st["step_id"]
                af_steps.append(
                    AfSequenceStep(
                        step_id=sid,
                        name=_step_identifier(st.get("name"), sid),
                        description=str((st.get("branch") or {}).get("condition") or ""),
                        actions=[str(a) for a in (st.get("actions") or [])],
                        transition_condition=str(st.get("transition_condition") or "").strip() or "TRUE",
                        next_step_id=st["next_step_id"],
                        timeout_ms=st["timeout_ms"],
                        error_step_id=st["error_step_id"],
                    )
                )
                branch = _normalize_branch(st.get("branch"))
                if branch:
                    branch_backfill.append((em_id, sid, branch))
            min_sid = min((s.step_id for s in af_steps), default=_STEP_START)

            af_cms: list[AfCm] = []
            for cm in cms_by_em.get(pos) or []:
                cm_name = _clean_identifier(cm.get("name"), f"Cm{cm_counter + 1}")
                af_cms.append(
                    AfCm(
                        name=cm_name,
                        cm_type=str(cm.get("cm_type")),  # type: ignore[arg-type]  # 已过枚举校验
                        description=str(cm.get("business_label") or "").strip() or cm_name,
                    )
                )
                cm_counter += 1
                cm_name_to_id[cm_name] = f"{em_id}_CM{cm_counter}"

            job_specs = jobs_by_em.get(pos) or []
            if job_specs:
                af_jobs = [
                    AfJob(
                        job_id=max(1, _int(j.get("job_id"), 1)),
                        name=_clean_identifier(str(j.get("name") or "AutoProduction"), "Job"),
                        description=str(j.get("business_label") or ""),
                        initial_step=min_sid,
                    )
                    for j in job_specs
                ]
            else:
                af_jobs = [AfJob(job_id=1, name="AutoProduction", initial_step=min_sid)]

            af_ems.append(
                AfEm(
                    em_idx=local_idx,  # 恒 ≥1：EM0 是公共联锁位，首版不占
                    name=em_name,
                    description=em_label,
                    jobs=af_jobs,
                    sequence=AfSequence(initial_step=min_sid, ready_step=1, steps=af_steps),
                    control_modules=af_cms,
                )
            )
        if af_ems:
            uspec = units_spec[u_idx]
            af_units.append(
                AfUnit(
                    unit_idx=u_idx + 1,
                    name=_clean_identifier(
                        str(uspec.get("name") or f"Unit{u_idx + 1}"), f"Unit{u_idx + 1}"
                    ),
                    description=str(uspec.get("business_label") or "").strip() or proj_name,
                    equipment_modules=af_ems,
                )
            )
    if not af_units:
        raise ValueError("解析结果没有任何单元/工序")

    af_project = AfProject(
        name=proj_name, description=proj_label or proj_name, units=af_units, global_constants={}
    )
    ir = GreenfieldIR.from_af_project(af_project, prompt=prompt, contract=contract)

    # ---- IR-only 字段回填（AfProject 表达不了、from_af_project 固定清空的部分）----
    # 1) 步序分支语义（alt/else/opt）：else 步进时序图异常臂（与 build_sample_ir 一致）。
    step_index = {(s.em_id, s.step_id): s for s in ir.steps}
    for em_id, sid, branch in branch_backfill:
        step = step_index.get((em_id, sid))
        if step is not None:
            step.branch = branch
    # 2) 模式 PackML 口径微调（只认 MODE_AUTO / MODE_MANUAL 两个既有模式）。
    for m in spec.get("modes") or []:
        if not isinstance(m, dict):
            continue
        packml = str(m.get("packml_mode") or "").strip()
        for mode in ir.modes:
            if mode.id == str(m.get("id") or "") and packml:
                mode.packml_mode = packml
    # 3) 联锁：AI 推断来源 → source="inferred"，校验时自动进「待确认问题」；
    #    目标解析不到节点时诚实挂起（进待确认问题），不静默丢弃也不冒充用户裁定。
    for n, il in enumerate(
        [x for x in (spec.get("interlocks") or []) if isinstance(x, dict)], start=1
    ):
        target = str(il.get("target") or "").strip()
        expression = str(il.get("expression") or "").strip()
        if not target or not expression:
            continue
        resolved = _resolve_interlock_target(target, ir, cm_name_to_id)
        if resolved is None:
            ir.spec_meta.open_questions.append(
                f"AI 解析联锁目标 {target!r} 未能关联任何设备/工序，已忽略该联锁"
            )
            continue
        ir.interlocks.append(
            GFInterlock(
                id=f"IL_{n}",
                target_id=resolved,
                expression=expression,
                source="inferred",
                applies_to=[],
            )
        )
    return ir


def llm_draft_ir(
    prompt: str,
    contract: Any | None = None,
    *,
    project_name: str = "AssemblyCell",
) -> tuple[GreenfieldIR | None, str]:
    """工艺描述 → (首版 IR, 失败原因)。

    成功返回 ``(ir, "")``；LLM 未配置 / 调用失败 / 输出连续未通过结构校验
    返回 ``(None, 可读原因)``，由调用方回退确定性 planner（fail-closed）。
    """
    settings = llm_settings()
    if settings is None:
        return None, "LLM 未配置"
    payload: dict[str, Any] = {"message": prompt}
    if contract is not None:
        payload["contract"] = _contract_digest(contract)

    feedback = ""
    last_err = ""
    for _attempt in range(1 + MAX_DRAFT_RETRIES):
        if feedback:
            payload["feedback"] = feedback
        messages = [
            {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            raw, _usage = chat_completion_raw(
                messages, settings, timeout_s=90, max_tokens=4096, json_mode=True
            )
        except LlmNotConfigured as exc:
            return None, str(exc)
        except RuntimeError as exc:  # 端点不可达 / HTTP 错误：不空转重试，直接回退
            return None, f"LLM 调用失败：{exc}"

        obj, err = _parse_json_object(raw)
        if err:
            last_err = err
            feedback = f"上次输出无法解析：{err}。请只输出规定结构的 JSON 对象。"
            continue
        err = _validate_spec(obj)
        if err:
            last_err = err
            feedback = f"上次输出结构不合规：{err}。请按 schema 修正后重新输出。"
            continue
        try:
            ir = _build_ir(obj, prompt, contract, project_name)
        except Exception as exc:  # noqa: BLE001 - 构造异常同样走回退，不半途安装
            last_err = f"IR 构造失败：{exc}"
            feedback = f"上次输出无法构造工程规格：{exc}。请修正后重新输出。"
            continue
        if not ir.units or not ir.steps:
            last_err = "解析结果为空规格"
            feedback = "解析结果没有任何单元或步序，请按 schema 给出完整规格。"
            continue
        return ir, ""
    return None, f"输出连续 {1 + MAX_DRAFT_RETRIES} 次未通过结构校验：{last_err}"
