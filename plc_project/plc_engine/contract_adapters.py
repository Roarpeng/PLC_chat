"""七步数据契约适配层：把仓库现有模块的真实产出转成 `plc_engine.contracts` 的 DTO。

本模块只做**结构适配**（字段改名 / 重组 / 兜底），不做业务推理。契约真源是
`plc_engine.contracts`，本文件只读它、不改它；所有入参只读不改
（`AfEm` 等是可变 dataclass，适配过程只读取并复制）。

诚实分级（详见各函数 docstring 的「精确 / 占位」说明）：
- **精确语义**：字段值直接来自源模块，一一对应，无信息丢失。
  `folded_network_to_ast` / `expression_to_rhs_ast` / `bundle_result_to_batch`
  / `plan_to_writeback_result` / `contract_roundtrip_check` 属于这一类
  （除个别注明为占位的字段）。
- **结构占位**：源模块根本没有对应信息，按契约要求填出可校验、可序列化的形状，
  **不代表真实语义已还原**：`project_to_bundle` 的 `file_path`、`plc_name`，
  `af_em_to_station_model` 的 `slot4_Interlock={}`（等 LLM 填）、
  slot6 的 legacy 占位、`folded_network_to_ast` 的 `scl_statements` 简写渲染。

只依赖标准库 + 本仓库模块，不引入任何第三方包。
"""

from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path
from typing import Any

from plc_engine.af.af_model import AfCm, AfEm, AfProject
from plc_engine.contracts import (
    AfBatchSource,
    Assignment,
    BlockInterface,
    BoschStationAfModel,
    CompileErrorItem,
    NetworkAst,
    NormalizedBlockAst,
    PlcTag,
    RawProjectBundle,
    TagTable,
    TextSource,
    WritebackResult,
    from_dict,
    to_dict,
)
from plc_engine.mega_source import BundleResult
from plc_engine.writeback_contract import sha256_text
from plc_engine.writeback_pipeline import WritebackPlan

__all__ = [
    "af_em_to_station_model",
    "apply_slot_delta_to_em",
    "apply_slot_delta_to_station_model",
    "apply_station_model_to_af_blocks",
    "bundle_result_to_batch",
    "contract_roundtrip_check",
    "expression_to_rhs_ast",
    "extract_em_interlocks",
    "folded_network_to_ast",
    "generate_legacy_hmi_adapter_scl",
    "plan_to_writeback_result",
    "project_to_bundle",
    "render_em_scl_sources",
    "station_model_to_af_em",
]

_UTF8_BOM = b"\xef\xbb\xbf"
_RAW_TYPE_KEY = "_raw_type"

# folded 表达式 type -> 文档 Tab2 期望的 op 名
_TYPE_TO_OP: dict[str, str] = {
    "literal": "LITERAL",
    "ref": "REF",
    "not": "NOT",
    "and": "AND",
    "or": "OR",
    "compare": "COMPARE",
    "arith": "ARITH",
    "func": "FUNC",
    "raw": "RAW",
}

# folded kind 的默认赋值类型（契约 Assignment.assign_type）
_DEFAULT_ASSIGN_TYPE = "COIL_ASSIGN"

_LOCKED_OPMODE = "LOCKED_BOSCH_TEMPLATE"


# ---------------------------------------------------------------------------
# 小工具（模块内部）
# ---------------------------------------------------------------------------

def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _has_utf8_bom(path: str | Path) -> bool:
    """按磁盘真实字节判定 BOM；文件不存在/读不到时视为无 BOM（不抛异常）。"""
    try:
        return Path(path).read_bytes()[:3] == _UTF8_BOM
    except OSError:
        return False


def _classify_io(key: str, address: Any) -> str:
    """把 io_mapping 的一项判成 in / out / unknown。

    仅按地址前缀（%I / %Q / I0.0 / Q0.0）与键名关键词判断，**是启发式**；
    判不出来的落进 unknown，绝不冒充成输入或输出。
    """
    text = _as_text(address).strip().upper()
    if text.startswith("%I") or (text.startswith("I") and text[1:2].isdigit()):
        return "in"
    if text.startswith("%Q") or (text.startswith("Q") and text[1:2].isdigit()):
        return "out"
    lowered = key.lower()
    if "in" in lowered or "sen" in lowered or "fb" in lowered:
        return "in"
    if "out" in lowered or "act" in lowered or "valve" in lowered or "coil" in lowered:
        return "out"
    return "unknown"


def _station_id(em: AfEm, unit_idx: int) -> str:
    """station_id：优先 AfEm.unit_em_name（内部已有 hasattr 防御），失败再兜底。"""
    try:
        name = _as_text(em.unit_em_name).strip()
    except AttributeError:  # 鸭子类型/被裁剪过的对象
        name = ""
    if name:
        return name
    return f"U{unit_idx}Em{_as_int(getattr(em, 'em_idx', None), 0)}_{_as_text(getattr(em, 'name', ''))}"


# ---------------------------------------------------------------------------
# Step 2: folded_to_dict -> NormalizedBlockAst
# ---------------------------------------------------------------------------

def expression_to_rhs_ast(expr: dict) -> dict:
    """归一化 folded 表达式 dict 成 Tab2 期望的 ``{"op": ..., "operands": [...]}`` 形状。

    - 原始 ``type`` 一律保留在 ``_raw_type``；
    - and/or 的 operands 递归；not 变成 ``{"op":"NOT","operands":[x]}``；
    - ref 取 ``access``、literal 取 ``value`` 平铺到结果上；
    - compare/arith/func/raw 原样保留（lhs/rhs/args 递归归一化）；
    - 任何未识别的键原样带出，未知 type 落 ``op="UNKNOWN"`` 而非抛异常。
    """
    if not isinstance(expr, dict):
        return {"op": "RAW", "operands": [], _RAW_TYPE_KEY: "", "value": expr}

    raw = dict(expr)
    etype = raw.get("type")
    type_name = etype if isinstance(etype, str) else ""
    out: dict[str, Any] = {
        "op": _TYPE_TO_OP.get(type_name, "UNKNOWN"),
        _RAW_TYPE_KEY: type_name,
    }

    if type_name in ("and", "or"):
        out["operands"] = [expression_to_rhs_ast(item) for item in _as_list(raw.get("operands"))]
    elif type_name == "not":
        operand = raw.get("operand")
        out["operands"] = [expression_to_rhs_ast(operand)] if operand is not None else []
    elif type_name == "ref":
        out["operands"] = []
        out["access"] = _as_text(raw.get("access"))
    elif type_name == "literal":
        out["operands"] = []
        out["value"] = raw.get("value")
    else:
        # compare / arith / func / raw / 未知类型：结构原样保留并递归已知子表达式
        for key in ("lhs", "rhs"):
            if isinstance(raw.get(key), dict):
                out[key] = expression_to_rhs_ast(raw[key])
        if isinstance(raw.get("operands"), list):
            out["operands"] = [expression_to_rhs_ast(item) for item in raw["operands"]]
        elif isinstance(raw.get("args"), list):
            out["args"] = [expression_to_rhs_ast(item) for item in raw["args"]]
        else:
            out["operands"] = []

    # 未消费的原始键原样带出，保证不丢信息（已存在的同名键不覆盖）
    for key, value in raw.items():
        if key == "operands" or key == "args":
            continue
        out.setdefault(key, value)
    return out


def folded_network_to_ast(
    folded: dict,
    *,
    block_name: str,
    language: str = "LAD",
) -> NormalizedBlockAst:
    """把 `flgnet_fold.folded_to_dict()` 的**一个网络**转成 NormalizedBlockAst。

    映射（精确）：
      statements[].target -> Assignment.lhs_symbol
      statements[].kind   -> Assignment.assign_type
      statements[].value  -> Assignment.rhs_ast（经 expression_to_rhs_ast 归一化）
      statements[].enable -> rhs_ast["enable"]（仅当存在）
      statements[].part_uuid / part_name -> rhs_ast 的同名键（溯源用）
      unresolved_parts    -> 记进 NetworkAst.title 后缀，不丢

    占位：NetworkAst.scl_statements 是 ``"target := kind"`` 的简写渲染，
    不是真 SCL（真 SCL 由 flgnet_fold.stmt_to_scl 负责，此处不反向依赖它）；
    interface 留空，因为单个网络无法推出块接口。
    """
    source = _as_dict(folded)

    title = _as_text(source.get("title"))
    unresolved = _as_list(source.get("unresolved_parts"))
    if unresolved:
        suffix = "[unresolved_parts: " + ", ".join(_as_text(item) for item in unresolved) + "]"
        title = f"{title} {suffix}".strip()

    assignments: list[Assignment] = []
    scl_statements: list[str] = []
    for statement in _as_list(source.get("statements")):
        if not isinstance(statement, dict):
            continue
        target = _as_text(statement.get("target"))
        kind = _as_text(statement.get("kind")) or _DEFAULT_ASSIGN_TYPE
        rhs = expression_to_rhs_ast(statement.get("value"))
        if statement.get("enable") is not None:
            rhs["enable"] = expression_to_rhs_ast(statement.get("enable"))
        for provenance in ("part_uuid", "part_name"):
            value = _as_text(statement.get(provenance))
            if value:
                rhs[provenance] = value
        assignments.append(Assignment(lhs_symbol=target, assign_type=kind, rhs_ast=rhs))
        scl_statements.append(f"{target} := {kind}")

    network = NetworkAst(
        network_no=_as_int(source.get("network_id")),
        title=title,
        scl_statements=scl_statements,
        assignments=assignments,
    )
    return NormalizedBlockAst(
        block_name=block_name,
        original_language=language,
        interface=BlockInterface(),
        networks=[network],
    )


# ---------------------------------------------------------------------------
# Step 4: AfEm -> BoschStationAfModel
# ---------------------------------------------------------------------------

def af_em_to_station_model(em: AfEm, *, unit_idx: int = 1) -> BoschStationAfModel:
    """AfEm -> 博世 OpCon AF 六槽位模型（六个 SLOT_KEYS 全部填齐，validate() 可通过）。

    入参只读：不修改 `em`，列表/字典一律复制。

    精确：slot1/slot6 来自各 CM 的 io_mapping（按地址前缀分类，判不出进 unknown）；
    slot3 来自 sequence.steps（step_id/name/description/actions/transition_condition/
    next_step_id 一一对应）；slot5 来自 control_modules 的 name/cm_type/fallback。
    占位：slot2 恒为 LOCKED_BOSCH_TEMPLATE（契约要求禁止 LLM 修改）；
    slot4 恒为 {}（等 LLM 填互锁）；slot6.hmi 为空、legacy 为标记占位；
    fb/idb/cmd UDT 名字按 ``FB_/IDB_/UDT_..._Cmd + station_id`` 规则生成，
    是命名规则推导，不是从既有块表查出来的真名。
    """
    station_id = _station_id(em, unit_idx)

    inputs: dict[str, str] = {}
    outputs: dict[str, str] = {}
    unclassified: dict[str, str] = {}
    elements: list[dict[str, Any]] = []

    for cm in _as_list(getattr(em, "control_modules", None)):
        if not isinstance(cm, AfCm):
            continue
        elements.append(
            {"name": cm.name, "cm_type": cm.cm_type, "fallback": bool(cm.fallback)}
        )
        for key, address in _as_dict(getattr(cm, "io_mapping", None)).items():
            bucket = _classify_io(key, address)
            sink = inputs if bucket == "in" else outputs if bucket == "out" else unclassified
            sink[f"{cm.name}.{key}"] = _as_text(address)

    steps: list[dict[str, Any]] = []
    sequence = getattr(em, "sequence", None)
    for step in _as_list(getattr(sequence, "steps", None)):
        steps.append(
            {
                "stepNo": _as_int(getattr(step, "step_id", None)),
                "name": _as_text(getattr(step, "name", "")),
                "comment": _as_text(getattr(step, "description", ""))
                or _as_text(getattr(step, "name", "")),
                "actions": list(_as_list(getattr(step, "actions", None))),
                "transitions": [
                    {
                        "condition": _as_text(getattr(step, "transition_condition", "")),
                        "nextStep": _as_int(getattr(step, "next_step_id", None)),
                    }
                ],
            }
        )

    slots: dict[str, Any] = {
        "slot1_InPeriphery": {"inputs": inputs, "unclassified": unclassified},
        "slot2_OpMode": _LOCKED_OPMODE,
        "slot3_SeqAuto": steps,
        "slot4_Interlock": extract_em_interlocks(em),
        "slot5_ElementCall": elements,
        "slot6_OutAndHmiAdapter": {
            "outputs": outputs,
            "hmi": {},
            "legacy": {
                "placeholder": False,
                "adapterBlockName": f"FC_{station_id}_HmiAdapter",
                "mappings": [
                    {
                        "legacyTarget": f'"DB_HMI_Old".{station_id}_Step',
                        "afSource": "#statStepAuto",
                    }
                ],
            },
        },
    }
    return BoschStationAfModel(
        station_id=station_id,
        fb_block_name=f"FB_{station_id}",
        idb_block_name=f"IDB_{station_id}",
        cmd_udt_name=f"UDT_{station_id}_Cmd",
        slots=slots,
    )


# ---------------------------------------------------------------------------
# Step 6: BundleResult -> AfBatchSource
# ---------------------------------------------------------------------------

def bundle_result_to_batch(result: BundleResult, path: str) -> AfBatchSource:
    """BundleResult + 落盘路径 -> AfBatchSource（精确语义）。

    sha256 用与文档 ComputeSha256 一致的 `sha256_text(result.text)`；
    has_utf8_bom 由 path 的真实前 3 字节判定（文件不存在则 False）。
    """
    return AfBatchSource(
        path=_as_text(path),
        sha256=sha256_text(getattr(result, "text", "") or ""),
        block_names=list(_as_list(getattr(result, "block_names", None))),
        external_dependencies=list(_as_list(getattr(result, "external_dependencies", None))),
        skipped_unchanged=list(_as_list(getattr(result, "skipped_unchanged", None))),
        has_utf8_bom=_has_utf8_bom(path),
    )


# ---------------------------------------------------------------------------
# Step 7: WritebackPlan -> WritebackResult
# ---------------------------------------------------------------------------

def plan_to_writeback_result(plan: WritebackPlan, elapsed_ms: int) -> WritebackResult:
    """WritebackPlan -> WritebackResult（精确语义）。

    门禁 findings 中 severity=error 的转成 CompileErrorItem（rule 前缀进
    tia_description，line 进 network_or_line，block_path/timestamp 源里没有故留空）；
    written_block_count = len(plan.block_names)；skipped 取 plan.skipped_unchanged。
    success 定义为「门禁未拦截」，即没有 error finding。
    """
    errors: list[CompileErrorItem] = []
    for finding in _as_list(getattr(plan, "findings", None)):
        if getattr(finding, "severity", "") != "error":
            continue
        line = getattr(finding, "line", None)
        errors.append(
            CompileErrorItem(
                block_name=_as_text(getattr(finding, "block", "")),
                network_or_line="" if line is None else str(line),
                tia_description=f"[{_as_text(getattr(finding, 'rule', ''))}] "
                f"{_as_text(getattr(finding, 'message', ''))}",
                block_path="",
                timestamp="",
            )
        )
    return WritebackResult(
        success=not errors,
        elapsed_milliseconds=_as_int(elapsed_ms),
        written_block_count=len(_as_list(getattr(plan, "block_names", None))),
        skipped_unchanged_blocks=len(_as_list(getattr(plan, "skipped_unchanged", None))),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# 反向映射：AfProject -> RawProjectBundle（Step 4 目标态 -> Step 1 形状）
# ---------------------------------------------------------------------------

def project_to_bundle(project: AfProject) -> RawProjectBundle:
    """AfProject（目标态模型）反向整理成 Step1 的 RawProjectBundle 资产清单。

    精确：每个 EM 一张 TagTable（表名=station_id，tag=各 CM 的 io_mapping 项，
    logical_address 为原地址，comment 记 CM 名）；每个 EM 三条 TextSource
    （FB / IDB / cmd UDT，块名用与 af_em_to_station_model 相同的命名规则）。

    占位：project_path 用 project.name；plc_name 恒为 "PLC_1"（AfProject 里没有
    PLC 站名信息）；file_path 留空（没有真实导出路径）；black_box_blocks 与
    simatic_ml_blocks 留空。这些字段只保证契约形状可校验，不代表真实资产。
    """
    tag_tables: list[TagTable] = []
    text_sources: list[TextSource] = []

    for unit in _as_list(getattr(project, "units", None)):
        for em in _as_list(getattr(unit, "equipment_modules", None)):
            station_id = _station_id(em, _as_int(getattr(unit, "unit_idx", None), 1))
            tags: list[PlcTag] = []
            for cm in _as_list(getattr(em, "control_modules", None)):
                for key, address in _as_dict(getattr(cm, "io_mapping", None)).items():
                    tags.append(
                        PlcTag(
                            name=f"{cm.name}.{key}",
                            data_type="",
                            logical_address=_as_text(address),
                            comment=f"{cm.name} ({cm.cm_type})",
                        )
                    )
            if tags:
                tag_tables.append(TagTable(name=station_id, tags=tags))
            text_sources.extend(
                [
                    TextSource(block_name=f"FB_{station_id}", type="FB", file_path=""),
                    TextSource(block_name=f"IDB_{station_id}", type="DB", file_path=""),
                    TextSource(block_name=f"UDT_{station_id}_Cmd", type="UDT", file_path=""),
                ]
            )

    return RawProjectBundle(
        project_path=_as_text(getattr(project, "name", "")),
        plc_name="PLC_1",
        tag_tables=tag_tables,
        text_sources=text_sources,
        simatic_ml_blocks=[],
        black_box_blocks=[],
    )


# ---------------------------------------------------------------------------
# CI 校验：契约可序列化往返
# ---------------------------------------------------------------------------

def contract_roundtrip_check(value: Any) -> bool:
    """to_dict -> from_dict(type(value), ...) -> to_dict，两次结果必须相等。

    非 dataclass 实例或任何异常一律返回 False（供 CI 逐条断言，不抛异常）。
    """
    cls = type(value)
    if not is_dataclass(cls) or isinstance(value, type):
        return False
    try:
        first = to_dict(value)
        return to_dict(from_dict(cls, first)) == first
    except Exception:  # noqa: BLE001  契约结构不闭合时按 False 处理，交由 CI 报错
        return False

# ---------------------------------------------------------------------------
# 博世 AF 槽位受控修改与反向生成器
# ---------------------------------------------------------------------------

def extract_em_interlocks(em: AfEm) -> dict[str, str]:
    """从 AfEm 提取所有 Control Module 相关的互锁条件。"""
    interlocks: dict[str, str] = {}
    for cm in _as_list(getattr(em, "control_modules", None)):
        cm_name = _as_text(getattr(cm, "name", "")).strip()
        params = _as_dict(getattr(cm, "parameters", None))
        for k, v in params.items():
            if k == "interlock" and isinstance(v, dict):
                for ik, iv in v.items():
                    if isinstance(iv, str) and iv.strip():
                        interlocks[f"{cm_name}.{ik}"] = iv.strip()
            elif k == "interlocks" and isinstance(v, list):
                for idx, iv in enumerate(v):
                    if isinstance(iv, str) and iv.strip():
                        interlocks[f"{cm_name}.interlock_{idx+1}"] = iv.strip()
            elif (k.startswith("release") or k.startswith("interlock")) and isinstance(v, str) and v.strip():
                interlocks[f"{cm_name}.{k}"] = v.strip()
    return interlocks


def apply_slot_delta_to_em(em: AfEm, delta: Any) -> AfEm:
    """把 PatchedSlotDelta 受控补丁应用到 AfEm（不污染原对象）。"""
    import copy
    new_em = copy.deepcopy(em)
    modified = set(_as_list(getattr(delta, "modified_slots", None)))
    patch = _as_dict(getattr(delta, "patch", None))

    if "slot4_Interlock" in modified:
        for full_key, expr in patch.items():
            if "." in full_key:
                cm_name, param_name = full_key.split(".", 1)
                for cm in new_em.control_modules:
                    if cm.name == cm_name:
                        if not isinstance(cm.parameters, dict):
                            cm.parameters = {}
                        if "interlock" in cm.parameters and isinstance(cm.parameters["interlock"], dict):
                            cm.parameters["interlock"][param_name] = str(expr)
                        cm.parameters[param_name] = str(expr)

    if "slot3_SeqAuto" in modified and getattr(new_em, "sequence", None):
        steps = _as_list(getattr(new_em.sequence, "steps", None))
        for key, val in patch.items():
            if key.startswith("step_"):
                parts = key.split(".", 1)
                try:
                    s_id = int(parts[0].replace("step_", ""))
                except ValueError:
                    continue
                attr = parts[1] if len(parts) > 1 else ""
                for s in steps:
                    if s.step_id == s_id:
                        if attr == "transition":
                            s.transition_condition = str(val)
                        elif attr == "actions":
                            s.actions = [str(x) for x in val] if isinstance(val, list) else [str(val)]
                        elif attr == "name":
                            s.name = str(val)

    return new_em


def apply_slot_delta_to_station_model(model: BoschStationAfModel, delta: Any) -> BoschStationAfModel:
    """把 PatchedSlotDelta 受控补丁直接应用到 BoschStationAfModel。"""
    import copy
    new_model = copy.deepcopy(model)
    modified = _as_list(getattr(delta, "modified_slots", None))
    patch = _as_dict(getattr(delta, "patch", None))
    for slot_name in modified:
        if slot_name in new_model.slots and isinstance(new_model.slots[slot_name], dict):
            new_model.slots[slot_name].update(patch)
    return new_model


def station_model_to_af_em(model: BoschStationAfModel, unit_idx: int = 1) -> AfEm:
    """从 BoschStationAfModel 还原出 AfEm 领域模型。"""
    from plc_engine.af.af_model import AfCm, AfEm, AfSequence, AfSequenceStep
    import re
    station_id = model.station_id
    em_idx = 1
    m = re.search(r"Em(\d+)", station_id)
    if m:
        try:
            em_idx = int(m.group(1))
        except ValueError:
            pass

    slots = model.slots
    slot1 = _as_dict(slots.get("slot1_InPeriphery"))
    slot3 = slots.get("slot3_SeqAuto")
    slot4 = _as_dict(slots.get("slot4_Interlock"))
    slot5 = _as_list(slots.get("slot5_ElementCall"))
    slot6 = _as_dict(slots.get("slot6_OutAndHmiAdapter"))

    in_ios = _as_dict(slot1.get("inputs"))
    out_ios = _as_dict(slot6.get("outputs"))
    all_ios = {**in_ios, **out_ios}

    cms: list[AfCm] = []
    for raw_cm in slot5:
        if isinstance(raw_cm, dict):
            cm_name = _as_text(raw_cm.get("name"))
            cm_type = _as_text(raw_cm.get("cm_type") or raw_cm.get("type") or "LBC_TwoWayActuator")
            cm_io: dict[str, str] = {}
            for tag_key, addr in all_ios.items():
                if tag_key.startswith(f"{cm_name}."):
                    pin = tag_key.split(".", 1)[1]
                    cm_io[pin] = addr
            
            params: dict[str, Any] = {}
            for ik, iv in slot4.items():
                if ik.startswith(f"{cm_name}."):
                    param_name = ik.split(".", 1)[1]
                    params[param_name] = iv
            
            cms.append(
                AfCm(
                    name=cm_name,
                    cm_type=cm_type,
                    description=_as_text(raw_cm.get("desc")),
                    io_mapping=cm_io,
                    parameters=params,
                    fallback=bool(raw_cm.get("fallback")),
                )
            )

    steps: list[AfSequenceStep] = []
    raw_steps = slot3 if isinstance(slot3, list) else _as_list(_as_dict(slot3).get("steps"))
    for s in raw_steps:
        if isinstance(s, dict):
            transitions = _as_list(s.get("transitions"))
            trans_cond = "TRUE"
            next_step = 0
            if transitions and isinstance(transitions[0], dict):
                trans_cond = _as_text(transitions[0].get("condition", "TRUE"))
                next_step = _as_int(transitions[0].get("nextStep", 0))
            steps.append(
                AfSequenceStep(
                    step_id=_as_int(s.get("stepNo") or s.get("id")),
                    name=_as_text(s.get("name")),
                    description=_as_text(s.get("comment") or s.get("desc")),
                    actions=[str(a) for a in _as_list(s.get("actions"))],
                    transition_condition=trans_cond,
                    next_step_id=next_step,
                )
            )

    seq = AfSequence(initial_step=10, ready_step=1, steps=steps)
    res_em = AfEm(
        em_idx=em_idx,
        name=station_id,
        control_modules=cms,
        sequence=seq,
    )
    res_em.unit_idx = unit_idx
    return res_em


def generate_legacy_hmi_adapter_scl(station_model: BoschStationAfModel) -> str:
    """生成博世规范的 FC_{station_id}_HmiAdapter 适配块代码。

    消除 Slot 6.2 的 placeholder 占位，保持原项目触摸屏旧 DB 变量与地址不变，
    将新 AF 内部状态同步回旧 DB，实现上位机/触摸屏零改动。
    """
    station_id = station_model.station_id
    legacy_info = _as_dict(
        _as_dict(station_model.slots.get("slot6_OutAndHmiAdapter")).get("legacy")
    )
    adapter_name = legacy_info.get("adapterBlockName") or f"FC_{station_id}_HmiAdapter"
    mappings = legacy_info.get("mappings") or [
        {"legacyTarget": f'"DB_HMI_Old".{station_id}_Step', "afSource": "#statStepAuto"}
    ]

    lines = [
        f'FUNCTION "{adapter_name}" : Void',
        "{ S7_Optimized_Access := 'TRUE' }",
        "VERSION : 0.1",
        "VAR_INPUT",
        "   i_stStepAuto : Int;",
        "END_VAR",
        "BEGIN",
        "   // [SLOT 6.2: LEGACY HMI ADAPTER] 兼容原项目触摸屏旧 DB 变量（保护现有画面不崩）",
    ]
    for m in mappings:
        target = m.get("legacyTarget", "")
        if target:
            lines.append(f"   {target} := #i_stStepAuto;")
    lines.append("END_FUNCTION")
    return "\n".join(lines)


def apply_station_model_to_af_blocks(
    model: BoschStationAfModel,
    unit_idx: int = 1,
    self_contained: bool = False,
) -> dict[str, Any]:
    """把 BoschStationAfModel 编译为博世 AF CanvasBlock 集合。"""
    from plc_engine.af.af_generator import generate_af_project_blocks
    from plc_engine.af.af_model import AfEm0, AfProject, AfUnit
    from plc_engine.canvas_model import CanvasBlock, CanvasNetwork

    em = station_model_to_af_em(model, unit_idx=unit_idx)
    unit = AfUnit(
        unit_idx=unit_idx,
        name=f"U{unit_idx}",
        em0=AfEm0(name="General"),
        equipment_modules=[em],
    )
    proj = AfProject(name="RefactoredProject", units=[unit])
    blocks = generate_af_project_blocks(proj, self_contained=self_contained)

    su = f"U{unit_idx}"
    for k, b in list(blocks.items()):
        if k.endswith("::Sequence") or k.endswith("Sequence"):
            blocks["Sequence.scl"] = b
            blocks["Sequence"] = b
        if k.endswith("::CallEquipment") or k.endswith("CallEquipment"):
            blocks["CallEquipment.scl"] = b
            blocks["CallEquipment"] = b
        if k.endswith("::Main") or k.endswith("Main"):
            blocks["Main.scl"] = b
            blocks["Main"] = b

    legacy = _as_dict(_as_dict(model.slots.get("slot6_OutAndHmiAdapter")).get("legacy"))
    if not legacy.get("placeholder", True):
        adapter_scl = generate_legacy_hmi_adapter_scl(model)
        adapter_name = legacy.get("adapterBlockName") or f"FC_{model.station_id}_HmiAdapter"
        blocks[f"{su}::{adapter_name}"] = CanvasBlock(
            name=adapter_name,
            block_type="FC",
            language="SCL",
            scl_body=adapter_scl,
            software_unit=su,
            af_role="HmiInterface",
            networks=[
                CanvasNetwork(
                    id=1,
                    title="Legacy HMI DB Adapter",
                    language="SCL",
                    scl_text=adapter_scl,
                )
            ],
        )
        blocks[f"{adapter_name}.scl"] = blocks[f"{su}::{adapter_name}"]
        blocks[adapter_name] = blocks[f"{su}::{adapter_name}"]

    return blocks


def render_em_scl_sources(
    model: BoschStationAfModel,
    unit_idx: int = 1,
    self_contained: bool = False,
) -> dict[str, str]:
    """把 BoschStationAfModel 直接渲染为 SCL 源码文本字典。"""
    blocks = apply_station_model_to_af_blocks(model, unit_idx=unit_idx, self_contained=self_contained)
    out: dict[str, str] = {}
    for name, blk in blocks.items():
        if hasattr(blk, "get_full_scl"):
            out[name] = blk.get_full_scl()
        elif hasattr(blk, "scl_body"):
            out[name] = blk.scl_body
    return out

