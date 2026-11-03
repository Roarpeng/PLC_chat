"""PLC_Chat V3.0 七步数据流契约（docs/plc_chat_v3_0.html Tab 2 的 Schema 级定义）。

本文件是**唯一真源**：七步每一步的输入/输出结构都在这里定义，
任何模块不得自行另立一套 DTO。契约名与文档 dataFlowSpecs 逐一对齐。

设计说明：
- 纯 dataclass + 标准库，不引入 pydantic，避免给离线管道增加依赖。
- 每个类提供 from_dict() / to_dict()，便于跨 Named Pipe / HTTP 传 JSON。
- validate() 只检查结构性必填项，不做业务语义判断。
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from typing import Any, get_type_hints

CONTRACT_VERSION = "3.0"


# ---------------------------------------------------------------------------
# 通用序列化
# ---------------------------------------------------------------------------

def to_dict(obj: Any) -> Any:
    """递归转 JSON 可序列化结构。"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(cls: type, data: dict[str, Any] | None) -> Any:
    """按 dataclass 字段声明递归构造；未知键忽略，缺失键用默认值。

    使用 get_type_hints 而非 f.type —— 本文件启用了 postponed annotations，
    否则 f.type 是字符串，嵌套 dataclass 无法被递归构造。
    """
    if data is None:
        return None
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        raw = data.get(f.name)
        hint = hints.get(f.name, f.type)
        args = getattr(hint, "__args__", ())

        if isinstance(raw, list) and args and isinstance(args[0], type) and is_dataclass(args[0]):
            raw = [from_dict(args[0], item) for item in raw]
        elif isinstance(raw, dict) and isinstance(hint, type) and is_dataclass(hint):
            raw = from_dict(hint, raw)

        if raw is None and _has_default(f):
            continue
        kwargs[f.name] = raw
    return cls(**kwargs)


def _has_default(f: Any) -> bool:
    return f.default is not MISSING or f.default_factory is not MISSING


class ContractViolation(ValueError):
    """契约结构校验失败。"""


def _require(obj: Any, *names: str) -> None:
    missing = [n for n in names if not getattr(obj, n, None)]
    if missing:
        raise ContractViolation(
            f"{type(obj).__name__} 缺少必填字段：{', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Step 1: .zap 归档解压与分类分流导出 -> RawProjectBundle
# ---------------------------------------------------------------------------

@dataclass
class PlcTag:
    name: str = ""
    data_type: str = ""
    logical_address: str = ""
    comment: str = ""


@dataclass
class TagTable:
    name: str = ""
    tags: list[PlcTag] = field(default_factory=list)


@dataclass
class TextSource:
    """SCL/STL/DB/UDT 等可直接 GenerateSource 导出的明文块。"""
    block_name: str = ""
    type: str = ""
    file_path: str = ""


@dataclass
class SimaticMlBlock:
    """LAD/FBD 等需要 Export 成 SimaticML XML 的块。"""
    block_name: str = ""
    type: str = ""
    lang: str = ""
    xml_path: str = ""
    is_know_how_protected: bool = False


@dataclass
class BlackBoxBlock:
    """F_LAD / F_FBD 安全块或 KnowHowProtected 块，只读。"""
    block_name: str = ""
    reason: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class RawProjectBundle:
    project_path: str = ""
    plc_name: str = ""
    tag_tables: list[TagTable] = field(default_factory=list)
    text_sources: list[TextSource] = field(default_factory=list)
    simatic_ml_blocks: list[SimaticMlBlock] = field(default_factory=list)
    black_box_blocks: list[BlackBoxBlock] = field(default_factory=list)

    def validate(self) -> None:
        _require(self, "project_path", "plc_name")


# ---------------------------------------------------------------------------
# Step 2: anyprogram2SCL 确定性转译 -> NormalizedBlockAst
# ---------------------------------------------------------------------------

@dataclass
class BlockInterface:
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    in_outs: list[str] = field(default_factory=list)
    statics: list[str] = field(default_factory=list)
    temps: list[str] = field(default_factory=list)


@dataclass
class Assignment:
    lhs_symbol: str = ""
    assign_type: str = "COIL_ASSIGN"
    rhs_ast: dict[str, Any] = field(default_factory=dict)


@dataclass
class NetworkAst:
    network_no: int = 0
    title: str = ""
    scl_statements: list[str] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)


@dataclass
class NormalizedBlockAst:
    block_name: str = ""
    original_language: str = ""
    interface: BlockInterface = field(default_factory=BlockInterface)
    networks: list[NetworkAst] = field(default_factory=list)

    def validate(self) -> None:
        _require(self, "block_name", "original_language")

    @property
    def all_writes(self) -> list[str]:
        return [a.lhs_symbol for n in self.networks for a in n.assignments]


# ---------------------------------------------------------------------------
# Step 3: 符号解耦与读写交叉矩阵 -> DependencyGraphMatrix
# ---------------------------------------------------------------------------

@dataclass
class PairedActuator:
    suggested_name: str = ""
    archetype: str = ""
    sen_home: str = ""
    sen_work: str = ""
    out_home: str = ""
    out_work: str = ""
    extracted_step_triggers_work: list[str] = field(default_factory=list)
    extracted_interlocks_work: list[str] = field(default_factory=list)


@dataclass
class SequenceStep:
    normalized_step_no: int = 0
    legacy_flag: str = ""
    next_step: int = 0
    trans_expr: str = ""


@dataclass
class StationCluster:
    station_prefix: str = ""
    paired_actuators: list[PairedActuator] = field(default_factory=list)
    detected_sequence_chain: list[SequenceStep] = field(default_factory=list)


@dataclass
class HmiDbRead:
    db_symbol: str = ""
    mapped_from: str = ""


@dataclass
class DependencyGraphMatrix:
    station_clusters: list[StationCluster] = field(default_factory=list)
    legacy_hmi_db_reads: list[HmiDbRead] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 4: 博世 OpCon AF 六槽位重构 -> BoschStationAfModel
# ---------------------------------------------------------------------------

SLOT_KEYS = (
    "slot1_InPeriphery",
    "slot2_OpMode",
    "slot3_SeqAuto",
    "slot4_Interlock",
    "slot5_ElementCall",
    "slot6_OutAndHmiAdapter",
)


@dataclass
class BoschStationAfModel:
    """自然语言对话的唯一基准真相源。LLM 只读写槽位，不碰底层状态机外壳。"""
    station_id: str = ""
    fb_block_name: str = ""
    idb_block_name: str = ""
    cmd_udt_name: str = ""
    slots: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require(self, "station_id", "fb_block_name")
        missing = [k for k in SLOT_KEYS if k not in self.slots]
        if missing:
            raise ContractViolation(f"缺少槽位：{', '.join(missing)}")

    def editable_slots(self) -> dict[str, Any]:
        """LLM 允许修改的槽位（Slot 3 / 4 及元件签名）。"""
        return {
            k: v for k, v in self.slots.items()
            if k in ("slot3_SeqAuto", "slot4_Interlock", "slot5_ElementCall")
        }


# ---------------------------------------------------------------------------
# Step 5: 上下文切片与 LLM 受控槽位编辑 -> PatchedSlotDelta
# ---------------------------------------------------------------------------

@dataclass
class StationContextSlice:
    user_prompt: str = ""
    target_station: str = ""
    available_elements: list[str] = field(default_factory=list)
    current_slot4_interlock: dict[str, str] = field(default_factory=dict)


@dataclass
class PatchedSlotDelta:
    station_id: str = ""
    modified_slots: list[str] = field(default_factory=list)
    patch: dict[str, str] = field(default_factory=dict)
    explanation: str = ""

    def validate(self) -> None:
        _require(self, "station_id")
        if not self.modified_slots:
            raise ContractViolation("modified_slots 不能为空")
        if not all(k in SLOT_KEYS for k in self.modified_slots):
            raise ContractViolation("modified_slots 含非法槽位名")
        if "slot2_OpMode" in self.modified_slots:
            raise ContractViolation("Slot 2 为 LOCKED_BOSCH_TEMPLATE，禁止修改")


# ---------------------------------------------------------------------------
# Step 6: 静态预检与 Mega-Source 打包 -> AfBatchSource
# ---------------------------------------------------------------------------

@dataclass
class AfBatchSource:
    path: str = ""
    sha256: str = ""
    block_names: list[str] = field(default_factory=list)
    external_dependencies: list[str] = field(default_factory=list)
    skipped_unchanged: list[str] = field(default_factory=list)
    has_utf8_bom: bool = True

    def validate(self) -> None:
        _require(self, "path", "sha256")


# ---------------------------------------------------------------------------
# Step 7: Openness 极速回写与编译闭环 -> WritebackResult
# ---------------------------------------------------------------------------

@dataclass
class CompileErrorItem:
    block_name: str = ""
    network_or_line: str = ""
    tia_description: str = ""
    block_path: str = ""
    timestamp: str = ""


@dataclass
class WritebackResult:
    success: bool = False
    elapsed_milliseconds: int = 0
    written_block_count: int = 0
    skipped_unchanged_blocks: int = 0
    errors: list[CompileErrorItem] = field(default_factory=list)

    @property
    def failed_block_names(self) -> list[str]:
        return list(dict.fromkeys(e.block_name for e in self.errors if e.block_name))


# ---------------------------------------------------------------------------
# 自愈闭环载荷（Tab 5）
# ---------------------------------------------------------------------------

@dataclass
class AvailableStructDefinition:
    type_name: str = ""
    fields: list[str] = field(default_factory=list)


@dataclass
class SelfHealRequest:
    task: str = "SELF_HEAL_COMPILE_ERROR"
    retry_attempt: int = 1
    max_retries: int = 3
    compiler_errors: list[CompileErrorItem] = field(default_factory=list)
    available_struct_definition: AvailableStructDefinition = field(
        default_factory=AvailableStructDefinition
    )
    instruction: str = ""

    def validate(self) -> None:
        if self.task != "SELF_HEAL_COMPILE_ERROR":
            raise ContractViolation("task 必须为 SELF_HEAL_COMPILE_ERROR")
        if not 1 <= self.retry_attempt <= self.max_retries:
            raise ContractViolation("retry_attempt 超出 max_retries")
        if not self.compiler_errors:
            raise ContractViolation("compiler_errors 不能为空")


# ---------------------------------------------------------------------------
# 七步索引
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepContract:
    index: int
    name: str
    module: str
    input_type: type | None
    output_type: type | None


STEP_CONTRACTS: tuple[StepContract, ...] = (
    # 注意 Step 5 -> 6 不是直接类型链接：Step 5 产出 PatchedSlotDelta，
    # 必须先「把补丁应用回 BoschStationAfModel」，Step 6 才以更新后的模型
    # 为输入渲染 SCL。这个 apply-patch 合并点由 writeback_heal.apply_slot_patch
    # 与调用方编排承担，契约索引本身不表达它。
    StepContract(1, ".zap 解压与分类分流导出", "PlcChat.Openness.IngestionService", None, RawProjectBundle),
    StepContract(2, "anyprogram2SCL 语法树确定性转译", "PlcChat.Compiler.SimaticMlToSclTranspiler", SimaticMlBlock, NormalizedBlockAst),
    StepContract(3, "符号解耦与读写交叉矩阵", "PlcChat.Compiler.DependencyAnalyzer", NormalizedBlockAst, DependencyGraphMatrix),
    StepContract(4, "博世 OpCon AF 六槽位重构", "PlcChat.BoschAf.BoschAfRefactorEngine", DependencyGraphMatrix, BoschStationAfModel),
    StepContract(5, "上下文切片与 LLM 受控槽位编辑", "PlcChat.AI.ConstrainedSlotEditor", BoschStationAfModel, PatchedSlotDelta),
    StepContract(6, "静态预检与 Mega-Source 打包", "PlcChat.Compiler.MegaSourceBundler", BoschStationAfModel, AfBatchSource),
    StepContract(7, "Openness 极速回写与编译闭环", "PlcChat.Openness.Engine.OpennessFastWritebackEngine", AfBatchSource, WritebackResult),
)


def step_contract(index: int) -> StepContract:
    for item in STEP_CONTRACTS:
        if item.index == index:
            return item
    raise KeyError(f"未知步骤 {index}，有效范围 1..7")


def contract_summary() -> list[dict[str, str]]:
    """给前端/文档用的扁平摘要。"""
    return [
        {
            "step": str(s.index),
            "name": s.name,
            "module": s.module,
            "input": s.input_type.__name__ if s.input_type else "-",
            "output": s.output_type.__name__ if s.output_type else "-",
        }
        for s in STEP_CONTRACTS
    ]
