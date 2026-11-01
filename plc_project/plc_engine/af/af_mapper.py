"""AF V1.2 Legacy-to-AF Mapper and Behavior-Preserving Reverse Engineering Engine.

Reverse engineers legacy Siemens TIA projects (e.g. flat FB10xx structures,
AutoStep state machines, LAD/SCL networks, raw %I/%Q mappings) into official
Siemens Automation Framework (AF) V1.2 architecture:
- Project -> Units (U1..U9) -> EMs (EM0 General + EM1..EM99) -> CMs (LBC_*)
- Behavior preservation: 100% physical I/O retention + safety interlocks binding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from plc_engine.af.af_model import (
    AfCm,
    AfCmType,
    AfEm,
    AfEm0,
    AfJob,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)
from plc_engine.canvas_model import CanvasBlock, CanvasState, CanvasTag


@dataclass
class IoMappingEntry:
    """A physical I/O binding entry preserving hardware connections."""

    address: str              # e.g. "%I0.0", "%Q0.0"
    tag_name: str             # e.g. "I_CylLoader_WorkPos"
    data_type: str = "Bool"
    comment: str = ""
    cm_name: str = ""         # Associated CM name, e.g. "cylLoader"
    cm_type: str = ""         # e.g. "LBC_TwoWayActuator"
    cm_field: str = ""        # e.g. "workPosition", "homePosition", "signal"
    em_name: str = ""         # Associated EM name
    source_block: str = ""    # Legacy block where it was referenced
    # 兜底记账:该 IO 是被第4/5级兜底 CM(LBC_DigitalSignal /
    # LBC_SimpleActuator)收编的 —— 只证明"没丢",不证明语义映射精确。
    fallback: bool = False


@dataclass
class InterlockEntry:
    """A safety or process interlock extracted from legacy logic."""

    name: str                 # e.g. "EmergencyStop", "SafetyDoor"
    expression: str           # e.g. "NOT #EmergencyStop"
    source_block: str = ""
    associated_cms: list[str] = field(default_factory=list)
    description: str = ""


#: 无法自动映射的块统一标注(与导入侧 af_import 的 PENDING_MARKER 同一约定,
#: 两套体系互认,不再各说各话)
_PENDING_ROLE = "af_pending_manual"


@dataclass
class ExtractedStep:
    """A sequence step extracted and translated from legacy code."""

    step_id: int
    name: str
    actions: list[str] = field(default_factory=list)
    transition_condition: str = ""
    next_step_id: int = 0
    description: str = ""


@dataclass
class CandidateEm:
    """An Equipment Module candidate identified from legacy blocks."""

    em_idx: int
    name: str
    source_blocks: list[str] = field(default_factory=list)
    steps: list[ExtractedStep] = field(default_factory=list)
    control_modules: list[AfCm] = field(default_factory=list)
    interlocks: list[InterlockEntry] = field(default_factory=list)


@dataclass
class CandidateUnit:
    """A Unit candidate identified from legacy project structure."""

    unit_idx: int
    name: str
    source_blocks: list[str] = field(default_factory=list)
    mode_control_blocks: list[str] = field(default_factory=list)
    ems: list[CandidateEm] = field(default_factory=list)
    interlocks: list[InterlockEntry] = field(default_factory=list)


@dataclass
class LegacyAnalysis:
    """Complete reverse engineering and mapping analysis result."""

    project_name: str
    target_unit_name: str
    units: list[CandidateUnit]
    block_mapping: dict[str, str]   # legacy block name -> AF role / target
    io_mappings: list[IoMappingEntry]
    total_ios_detected: int
    retained_ios_count: int
    io_retention_rate: float        # Percentage e.g. 100.0
    interlocks_detected: list[InterlockEntry]
    # ---- 诚实降级记账(向后兼容默认值,旧调用方不受影响) ----
    # 完全降级:一个 EM/步序块都没识别出来,不应生成任何 AF 块
    degraded: bool = False
    # 降级原因代码(机器可读):no_sequence_block / no_interlock_detected /
    # unmapped_blocks_pending
    degrade_reasons: list[str] = field(default_factory=list)
    # 无法自动映射、保持原样待人工确认(af_pending_manual)的块名
    pending_blocks: list[str] = field(default_factory=list)
    # I/O 保留拆分:精确语义映射 vs 兜底收编(两者之和 = retained_ios_count)
    retained_direct_count: int = 0
    retained_fallback_count: int = 0


class LegacyToAfMapper:
    """Analyzes a legacy flat CanvasState and maps it to AF V1.2 architecture."""

    # Patterns for classifying actuators and sensors
    _CYL_KEYWORDS = [
        "cyl", "cylinder", "气缸", "电磁阀", "valve", "clamp", "夹紧",
        "pusher", "推料", "feed", "进料", "lift", "顶升", "gripper", "手爪",
    ]
    _WORK_KEYWORDS = ["extend", "work", "伸出", "动点", "到位", "wp", "fwd", "push", "down", "close", "合模", "前"]
    _HOME_KEYWORDS = ["retract", "home", "缩回", "原点", "初始", "hp", "back", "rev", "pull", "up", "open", "开模", "后"]

    _SENSOR_KEYWORDS = [
        "sensor", "pe", "photocell", "photo", "prox", "switch", "button",
        "part", "present", "光电", "接近", "开关", "按钮", "检测", "有料", "到位"
    ]
    _AXIS_KEYWORDS = ["axis", "motor", "servo", "drive", "vfd", "inverter", "轴", "电机", "伺服", "变频"]
    _ANALOG_KEYWORDS = ["analog", "temp", "pressure", "level", "weight", "ai_", "模拟量", "温度", "压力", "液位"]

    # 通用工艺关键词(与具体工程编号/块名无关):
    # 严禁出现 fb1000/fb1060/autostep 之类 HR001 专属字面量——通用词靠
    # 语义命中,HR001 风格命名(AutoStep/FB1000_MainControl)恰含 step/main
    # 而被覆盖,其他工程同样公平。
    _MODE_CONTROL_KEYWORDS = ["main", "mode", "state", "master", "automanual", "总控", "主循环", "模式"]
    _SEQUENCE_KEYWORDS = ["sequence", "step", "工位", "步序", "流程"]
    _SAFETY_KEYWORDS = ["safety", "estop", "emergency", "guard", "door", "curtain", "interlock", "急停", "安全", "互锁"]

    # 步序块评分阈值:块名命中(+2)/CASE+step 模式(+3)/Step=N 比较(+2)/
    # 调用出度(+1),至少 2 分才算 EM 候选——单一弱信号不再误判。
    EM_MIN_SEQUENCE_SCORE = 2

    def __init__(self, canvas: CanvasState, target_unit_name: str = "U1_Refactored") -> None:
        self.canvas = canvas
        self.target_unit_name = target_unit_name.strip() or f"U1_{canvas.project_name or 'Refactored'}"
        if not self.target_unit_name.startswith("U"):
            self.target_unit_name = f"U1_{self.target_unit_name}"

    def analyze(self) -> LegacyAnalysis:
        """Perform full reverse engineering and construct LegacyAnalysis."""
        # 1. Extract all physical I/Os
        io_entries = self._extract_all_ios()

        # 2. Extract safety interlocks(一个都没扫到时诚实记降级原因,
        #    不再凭空注入 GlobalEmergencyStop 占位联锁)
        interlocks = self._extract_interlocks()
        degrade_reasons: list[str] = []
        if not interlocks:
            degrade_reasons.append("no_interlock_detected")

        # 3. Detect and classify Control Modules (CMs)
        cms = self._detect_control_modules(io_entries, interlocks)

        # 4. Detect Sequence steps and state machines
        ems = self._detect_ems_and_sequences(cms, interlocks)

        # 5. Detect Unit and mode control
        unit = self._detect_unit(ems, interlocks)

        # 6. Build legacy block to AF mapping
        block_mapping = self._build_block_mapping(unit)
        pending_blocks = sorted(
            name for name, target in block_mapping.items() if target.startswith(_PENDING_ROLE)
        )

        # 7. Calculate I/O retention(拆分精确映射 / 兜底收编)
        total_ios = len(io_entries)
        retained_entries = [m for m in io_entries if m.cm_name]
        retained_direct = [m for m in retained_entries if not m.fallback]
        retained_fallback = [m for m in retained_entries if m.fallback]
        # If total is 0, 100% by default; otherwise calculate percentage
        retention_rate = 100.0 if total_ios == 0 else round((len(retained_entries) / total_ios) * 100.0, 2)

        # 8. 诚实降级判定:一个 EM 都没识别出来 → 完全降级,不生成模板垃圾
        degraded = not ems
        if degraded:
            degrade_reasons.append("no_sequence_block")
        elif pending_blocks:
            degrade_reasons.append("unmapped_blocks_pending")

        return LegacyAnalysis(
            project_name=self.canvas.project_name,
            target_unit_name=self.target_unit_name,
            units=[unit],
            block_mapping=block_mapping,
            io_mappings=io_entries,
            total_ios_detected=total_ios,
            retained_ios_count=len(retained_entries),
            io_retention_rate=retention_rate,
            interlocks_detected=interlocks,
            degraded=degraded,
            degrade_reasons=degrade_reasons,
            pending_blocks=pending_blocks,
            retained_direct_count=len(retained_direct),
            retained_fallback_count=len(retained_fallback),
        )

    def build_af_project(self, analysis: LegacyAnalysis) -> AfProject:
        """Convert LegacyAnalysis into an AfProject domain model."""
        units: list[AfUnit] = []
        for cand_unit in analysis.units:
            unit_name_clean = cand_unit.name
            if unit_name_clean.startswith("U") and "_" in unit_name_clean:
                unit_name_clean = unit_name_clean.split("_", 1)[1]

            em0 = AfEm0(
                name="General",
                description=f"General Module for {cand_unit.name} safety & interlocks",
            )

            equipment_modules: list[AfEm] = []
            for cand_em in cand_unit.ems:
                steps = [
                    AfSequenceStep(
                        step_id=s.step_id,
                        name=s.name,
                        description=s.description,
                        actions=s.actions,
                        transition_condition=s.transition_condition,
                        next_step_id=s.next_step_id,
                    )
                    for s in cand_em.steps
                ]
                seq = AfSequence(
                    initial_step=0,
                    ready_step=1,
                    steps=steps,
                )
                jobs = [
                    AfJob(
                        job_id=1,
                        name="AutoSequence",
                        description=f"Auto Sequence for {cand_em.name}",
                        initial_step=steps[0].step_id if steps else 10,
                    )
                ]
                equipment_modules.append(
                    AfEm(
                        em_idx=cand_em.em_idx,
                        name=cand_em.name,
                        description=f"Refactored EM {cand_em.name}",
                        jobs=jobs,
                        sequence=seq,
                        control_modules=cand_em.control_modules,
                    )
                )

            units.append(
                AfUnit(
                    unit_idx=cand_unit.unit_idx,
                    name=unit_name_clean,
                    description=f"Refactored Unit {cand_unit.name}",
                    em0=em0,
                    equipment_modules=equipment_modules,
                )
            )

        return AfProject(
            name=analysis.project_name or "RefactoredProject",
            description="AF V1.2 refactored project from legacy non-standard baseline",
            units=units,
        )

    # -------------------------------------------------------------------------
    # Internal Extraction & Recognition Steps
    # -------------------------------------------------------------------------

    def _extract_all_ios(self) -> list[IoMappingEntry]:
        """Extract all physical %I and %Q addresses from tags and blocks."""
        io_dict: dict[str, IoMappingEntry] = {}

        # 1. Inspect canvas tags
        for tag in self.canvas.tags.values():
            addr = str(tag.logical_address or "").upper().strip()
            if addr.startswith("%I") or addr.startswith("%Q"):
                io_dict[addr] = IoMappingEntry(
                    address=addr,
                    tag_name=tag.name,
                    data_type=tag.data_type or "Bool",
                    comment=tag.comment or "",
                )

        # 2. Inspect block interfaces and SCL text for unlisted %I / %Q
        io_regex = re.compile(r"%(?:I|Q)[BWD]?\d+(?:\.\d+)?", re.IGNORECASE)
        for b_name, block in self.canvas.blocks.items():
            # Check variables
            for v in block.interface:
                init_addr = io_regex.search(str(v.initial_value or ""))
                comment_addr = io_regex.search(str(v.comment or ""))
                for m in (init_addr, comment_addr):
                    if m:
                        addr = m.group(0).upper()
                        if addr not in io_dict:
                            io_dict[addr] = IoMappingEntry(
                                address=addr,
                                tag_name=v.name,
                                data_type=v.data_type or "Bool",
                                comment=v.comment or "",
                                source_block=b_name,
                            )

            # Check SCL code
            code = block.scl_body or block.get_full_scl()
            for net in block.networks:
                code += f"\n{net.scl_text}"
            for m in io_regex.finditer(code):
                addr = m.group(0).upper()
                if addr not in io_dict:
                    prefix = "I" if addr.startswith("%I") else "Q"
                    clean_tag = f"Tag_{prefix}_{addr.replace('%', '').replace('.', '_')}"
                    io_dict[addr] = IoMappingEntry(
                        address=addr,
                        tag_name=clean_tag,
                        data_type="Bool",
                        comment="Discovered in block logic",
                        source_block=b_name,
                    )

        # Sort entries by address for determinism
        return sorted(io_dict.values(), key=lambda x: x.address)

    def _extract_interlocks(self) -> list[InterlockEntry]:
        """Scan blocks and tags for safety and interlock conditions."""
        interlocks: list[InterlockEntry] = []
        seen_names: set[str] = set()

        # Check tags
        for tag in self.canvas.tags.values():
            t_lower = (tag.name + " " + tag.comment).lower()
            if any(k in t_lower for k in self._SAFETY_KEYWORDS):
                name = tag.name
                if name not in seen_names:
                    seen_names.add(name)
                    interlocks.append(
                        InterlockEntry(
                            name=name,
                            expression=f'NOT "{tag.name}"',
                            description=f"Safety interlock from tag {tag.name}: {tag.comment}",
                        )
                    )

        # Check blocks
        for b_name, block in self.canvas.blocks.items():
            b_lower = b_name.lower()
            if any(k in b_lower for k in self._SAFETY_KEYWORDS):
                for v in block.interface:
                    v_lower = (v.name + " " + v.comment).lower()
                    if any(k in v_lower for k in self._SAFETY_KEYWORDS):
                        if v.name not in seen_names:
                            seen_names.add(v.name)
                            interlocks.append(
                                InterlockEntry(
                                    name=v.name,
                                    expression=f"NOT #{v.name}",
                                    source_block=b_name,
                                    description=f"Safety condition in {b_name}: {v.comment}",
                                )
                            )

        # 联锁诚实边界:一个都没扫到就返回空列表并让上层记
        # degrade_reasons="no_interlock_detected"——绝不凭空注入
        # GlobalEmergencyStop 占位联锁(占位联锁会让报告显得"有安全兜底",
        # 实际是记账造假)。
        return interlocks

    def _detect_control_modules(
        self,
        io_entries: list[IoMappingEntry],
        interlocks: list[InterlockEntry],
    ) -> list[AfCm]:
        """Classify I/Os and group them into Control Modules (AfCm)."""
        cms: list[AfCm] = []
        assigned_ios: set[str] = set()

        # Step 1: Detect Two-Way Actuators (Cylinders / Valves)
        cyl_groups: dict[str, dict[str, IoMappingEntry]] = {}

        for entry in io_entries:
            text = (entry.tag_name + " " + entry.comment).lower()
            is_cyl = any(k in text for k in self._CYL_KEYWORDS)
            if not is_cyl:
                continue

            # Determine base name by stripping extend/retract keywords
            base = entry.tag_name
            # Remove prefixes like Q_, I_
            base = re.sub(r"^[IQ]W?_", "", base, flags=re.IGNORECASE)
            # Remove work/home suffixes
            for kw in self._WORK_KEYWORDS + self._HOME_KEYWORDS:
                base = re.sub(re.escape(kw) + r".*$", "", base, flags=re.IGNORECASE)
            base = re.sub(r"^cyl(?:inder)?_?", "", base, flags=re.IGNORECASE)
            base = base.strip("_")
            if not base:
                base_cm = "cyl"
            else:
                base_cm = self._to_camel_case(f"cyl_{base}")

            cyl_groups.setdefault(base_cm, {})
            is_work = any(k in text for k in self._WORK_KEYWORDS)
            is_home = any(k in text for k in self._HOME_KEYWORDS)

            if entry.address.startswith("%Q"):
                if is_work or not is_home:
                    cyl_groups[base_cm]["workCmd"] = entry
                else:
                    cyl_groups[base_cm]["homeCmd"] = entry
            elif entry.address.startswith("%I"):
                if is_work or not is_home:
                    cyl_groups[base_cm]["workSensor"] = entry
                else:
                    cyl_groups[base_cm]["homeSensor"] = entry

        for cm_name, roles in cyl_groups.items():
            io_map: dict[str, str] = {}
            for role, entry in roles.items():
                io_map[role] = entry.address
                io_map[f"{role}Tag"] = entry.tag_name
                entry.cm_name = cm_name
                entry.cm_type = "LBC_TwoWayActuator"
                entry.cm_field = role
                assigned_ios.add(entry.address)

            cm_interlocks = [ic.expression for ic in interlocks]
            cms.append(
                AfCm(
                    name=cm_name,
                    cm_type="LBC_TwoWayActuator",
                    description=f"Pneumatic Actuator {cm_name}",
                    io_mapping=io_map,
                    parameters={"interlocks": cm_interlocks},
                )
            )

        # Step 2: Detect Motors / Axes
        for entry in io_entries:
            if entry.address in assigned_ios:
                continue
            text = (entry.tag_name + " " + entry.comment).lower()
            if any(k in text for k in self._AXIS_KEYWORDS):
                clean_tag = re.sub(r"^[IQ]W?_", "", entry.tag_name, flags=re.IGNORECASE)
                clean_tag = re.sub(r"^(?:motor|axis)_?", "", clean_tag, flags=re.IGNORECASE).strip("_")
                cm_name = self._to_camel_case(f"motor_{clean_tag}" if clean_tag else "motor")
                entry.cm_name = cm_name
                entry.cm_type = "LBC_AxisControl"
                entry.cm_field = "command" if entry.address.startswith("%Q") else "status"
                assigned_ios.add(entry.address)
                cms.append(
                    AfCm(
                        name=cm_name,
                        cm_type="LBC_AxisControl",
                        description=f"Motor / Drive {cm_name}",
                        io_mapping={"io": entry.address, "tag": entry.tag_name},
                    )
                )

        # Step 3: Detect Analog Inputs
        for entry in io_entries:
            if entry.address in assigned_ios:
                continue
            text = (entry.tag_name + " " + entry.comment).lower()
            if any(k in text for k in self._ANALOG_KEYWORDS) or entry.address.startswith("%IW"):
                clean_tag = re.sub(r"^[IQ]W?_", "", entry.tag_name, flags=re.IGNORECASE)
                clean_tag = re.sub(r"^ai_?", "", clean_tag, flags=re.IGNORECASE).strip("_")
                cm_name = self._to_camel_case(f"analog_{clean_tag}" if clean_tag else "analogInput")
                entry.cm_name = cm_name
                entry.cm_type = "LBC_AnalogInput"
                entry.cm_field = "value"
                assigned_ios.add(entry.address)
                cms.append(
                    AfCm(
                        name=cm_name,
                        cm_type="LBC_AnalogInput",
                        description=f"Analog Input {cm_name}",
                        io_mapping={"value": entry.address, "tag": entry.tag_name},
                    )
                )

        # Step 4: Detect Digital Sensors (%I) —— 兜底级:所有剩余 %I 都被
        # LBC_DigitalSignal 收编(语义只到"这是个数字输入"),标记 fallback。
        for entry in io_entries:
            if entry.address in assigned_ios:
                continue
            text = (entry.tag_name + " " + entry.comment).lower()
            if entry.address.startswith("%I") or any(k in text for k in self._SENSOR_KEYWORDS):
                clean_tag = re.sub(r"^[IQ]W?_", "", entry.tag_name, flags=re.IGNORECASE)
                clean_tag = re.sub(r"^sensor_?", "", clean_tag, flags=re.IGNORECASE).strip("_")
                cm_name = self._to_camel_case(f"sensor_{clean_tag}" if clean_tag else "sensor")
                entry.cm_name = cm_name
                entry.cm_type = "LBC_DigitalSignal"
                entry.cm_field = "signal"
                entry.fallback = True
                assigned_ios.add(entry.address)
                cms.append(
                    AfCm(
                        name=cm_name,
                        cm_type="LBC_DigitalSignal",
                        description=f"Digital Sensor {cm_name}",
                        io_mapping={"signal": entry.address, "signalTag": entry.tag_name},
                        fallback=True,
                    )
                )

        # Step 5: Catch-all for remaining unassigned %Q points -> LBC_SimpleActuator
        # 兜底级:剩余执行器输出只证明"没丢",同样标记 fallback。
        for entry in io_entries:
            if entry.address in assigned_ios:
                continue
            if entry.address.startswith("%Q"):
                cm_name = self._to_camel_case(f"act_{entry.tag_name.replace('Q_', '')}")
                entry.cm_name = cm_name
                entry.cm_type = "LBC_SimpleActuator"
                entry.cm_field = "command"
                entry.fallback = True
                assigned_ios.add(entry.address)
                cms.append(
                    AfCm(
                        name=cm_name,
                        cm_type="LBC_SimpleActuator",
                        description=f"Actuator {cm_name}",
                        io_mapping={"command": entry.address, "commandTag": entry.tag_name},
                        fallback=True,
                    )
                )

        return cms

    def _score_sequence_block(self, b_name: str, code: str) -> int:
        """通用步序块评分(无任何工程专属字面量)。

        信号与权重:
        - 块名命中通用步序词(sequence/step/工位/步序/流程)  +2
        - CASE..OF 步进机且代码含 step 语义                   +3
        - 步号比较模式 ``Step = N``(状态机分支判定)          +2
        - 调用出度(主步序调用子步序/FB 的特征,>=1 处)        +1

        评分达到 ``EM_MIN_SEQUENCE_SCORE`` 才算 EM 候选;无命中即无 EM,
        由上层走诚实降级路径。
        """
        b_lower = b_name.lower()
        score = 0
        if any(k in b_lower for k in self._SEQUENCE_KEYWORDS):
            score += 2
        if re.search(r"\bCASE\b[\s\S]*?\bOF\b", code, re.IGNORECASE) and "step" in code.lower():
            score += 3
        if re.search(r"Step\s*=\s*\d+", code, re.IGNORECASE):
            score += 2
        if len(set(re.findall(r"#([A-Za-z_]\w*)\s*\(", code))) >= 1:
            score += 1
        return score

    def _detect_ems_and_sequences(
        self,
        cms: list[AfCm],
        interlocks: list[InterlockEntry],
    ) -> list[CandidateEm]:
        """Detect sequence logic and cluster into candidate Equipment Modules.

        识别不到任何步序块时返回**空列表**——调用方据此走诚实降级
        (全部块 pending),绝不编造 Station1 之类的模板假 EM。
        """
        ems: list[CandidateEm] = []
        em_idx = 1

        # 步序块识别:通用评分制,只看块名语义 + 代码模式 + 调用出度
        scored_blocks: list[tuple[int, str, CanvasBlock]] = []
        for b_name, block in self.canvas.blocks.items():
            if block.block_type.upper() not in {"FB", "FC"}:
                continue
            b_lower = b_name.lower()
            # Skip parameter, recipe, timer, message helper blocks
            if any(k in b_lower for k in ["parameter", "recipe", "constant", "timer", "message"]):
                continue

            code = block.scl_body or block.get_full_scl()
            for net in block.networks:
                code += f"\n{net.scl_text}"

            score = self._score_sequence_block(b_name, code)
            if score >= self.EM_MIN_SEQUENCE_SCORE:
                scored_blocks.append((score, b_name, block))

        # 评分降序、同分按块名升序(纯确定性排序;不再对任何特定名字
        # 特调顺序——HR001 的 AutoStep 之所以排 EM1,是因为它信号分最高
        # 且名字靠前,而非硬编码特判)。
        scored_blocks.sort(key=lambda item: (-item[0], item[1]))
        seq_blocks = [(b_name, block) for _, b_name, block in scored_blocks]

        if seq_blocks:
            # If multiple EMs exist, partition CMs by reference, keeping common ones in EM1
            all_claimed_cms: set[str] = set()
            em_cm_map: dict[int, list[AfCm]] = {}
            for idx_e, (b_name, block) in enumerate(seq_blocks, start=1):
                block_code = (block.scl_body or block.get_full_scl()).lower()
                for net in block.networks:
                    block_code += f"\n{net.scl_text.lower()}"

                matched_cms: list[AfCm] = []
                for cm in cms:
                    cm_tags = [cm.name.lower()] + [str(v).lower() for v in cm.io_mapping.values()]
                    if any(t in block_code for t in cm_tags if len(t) >= 3):
                        matched_cms.append(cm)
                        all_claimed_cms.add(cm.name)
                em_cm_map[idx_e] = matched_cms

            # Common / unclaimed CMs belong to EM1 (highest-scored master sequence)
            unclaimed = [cm for cm in cms if cm.name not in all_claimed_cms]
            if 1 in em_cm_map:
                em_cm_map[1] = em_cm_map[1] + [cm for cm in unclaimed if cm not in em_cm_map[1]]

            for b_name, block in seq_blocks:
                em_name = self._derive_em_name(b_name, em_idx)
                # EM 未引用到 CM 属于合法形态(纯步序 EM),不再编造
                # cyl/sensor 假 CM 模板
                assigned_cms = em_cm_map.get(em_idx) if len(seq_blocks) > 1 else list(cms)
                if assigned_cms is None:
                    assigned_cms = []
                steps = self._extract_steps_from_block(block, assigned_cms)
                cand_em = CandidateEm(
                    em_idx=em_idx,
                    name=em_name,
                    source_blocks=[b_name],
                    steps=steps,
                    control_modules=assigned_cms,
                    interlocks=interlocks,
                )
                ems.append(cand_em)
                em_idx += 1

        return ems

    def _extract_steps_from_block(self, block: CanvasBlock, cms: list[AfCm]) -> list[ExtractedStep]:
        """Extract sequence steps from SCL CASE or networks and translate to AF."""
        steps: list[ExtractedStep] = []
        code = block.scl_body or block.get_full_scl()
        for net in block.networks:
            code += f"\n{net.scl_text}"

        # 1. Try parsing SCL CASE ... OF
        case_match = re.search(r"\bCASE\s+([#A-Za-z0-9_]+)\s+OF([\s\S]*?)\bEND_CASE", code, re.IGNORECASE)
        if case_match:
            step_var = case_match.group(1)
            case_body = case_match.group(2)
            # Find branches e.g. "10: ...", "20: ..."
            branches = re.split(r"\n\s*(\d+)\s*:", "\n" + case_body)
            # branches[0] is header before first branch
            for i in range(1, len(branches), 2):
                step_num = int(branches[i])
                branch_code = branches[i + 1] if i + 1 < len(branches) else ""
                step = self._parse_single_step(step_num, branch_code, step_var, cms)
                steps.append(step)

        # 2. If no CASE branches found, try IF #Step = X THEN ...
        if not steps:
            if_matches = list(re.finditer(r"IF\s+[#A-Za-z0-9_]*Step\s*=\s*(\d+)\s+THEN([\s\S]*?)END_IF", code, re.IGNORECASE))
            for m in if_matches:
                step_num = int(m.group(1))
                branch_code = m.group(2)
                step = self._parse_single_step(step_num, branch_code, "Step", cms)
                steps.append(step)

        # 3. Default fallback steps if none parsed
        if not steps:
            steps = [
                ExtractedStep(step_id=10, name="STEP_10_WAIT", actions=["// Wait"], transition_condition="TRUE", next_step_id=20),
                ExtractedStep(step_id=20, name="STEP_20_EXEC", actions=["// Exec"], transition_condition="TRUE", next_step_id=1),
            ]

        return steps

    def _parse_single_step(
        self,
        step_id: int,
        branch_code: str,
        step_var: str,
        cms: list[AfCm],
    ) -> ExtractedStep:
        """Parse one step's actions and transition condition, translating to #controlNodes."""
        lines = [line.strip() for line in branch_code.splitlines() if line.strip()]

        # Step name from comments
        name = f"STEP_{step_id}"
        for line in lines:
            if "//" in line:
                comment_text = line.split("//", 1)[1].strip()
                clean = re.sub(r"[^A-Za-z0-9_]", "_", comment_text).strip("_").upper()
                if clean:
                    name = clean
                    break

        actions: list[str] = []
        transition_cond = ""
        next_step_id = 0

        # Look for transition IF
        trans_match = re.search(
            r"IF\s+([\s\S]*?)\s+THEN[\s\S]*?(?:#?" + re.escape(step_var.lstrip("#")) + r"|statStepNext)\s*:=\s*(\d+)[\s\S]*?END_IF",
            branch_code,
            re.IGNORECASE,
        )
        if trans_match:
            raw_cond = trans_match.group(1).strip()
            next_step_id = int(trans_match.group(2))
            transition_cond = self._translate_condition(raw_cond, cms)

        # Collect action statements outside or before the transition IF
        for line in lines:
            if line.startswith("//"):
                continue
            if re.search(r"\bIF\b", line, re.IGNORECASE) or re.search(r"\bTHEN\b", line, re.IGNORECASE) or re.search(r"\bEND_IF\b", line, re.IGNORECASE):
                continue
            if re.search(r"(?:#?" + re.escape(step_var.lstrip("#")) + r"|statStepNext)\s*:=\s*\d+", line, re.IGNORECASE):
                continue

            translated_act = self._translate_action(line, cms)
            if translated_act:
                actions.append(translated_act)

        if not transition_cond:
            transition_cond = "TRUE"
        if next_step_id == 0:
            next_step_id = step_id + 10

        return ExtractedStep(
            step_id=step_id,
            name=name,
            actions=actions,
            transition_condition=transition_cond,
            next_step_id=next_step_id,
        )

    def _translate_action(self, statement: str, cms: list[AfCm]) -> str:
        """Translate legacy direct %Q or tag assignments into #controlNodes commands."""
        stmt = statement.rstrip(";").strip()
        if not stmt:
            return ""

        # Check for assignment: target := value
        assign_match = re.match(r"^([#\"\w\.]+)\s*:=\s*([\s\S]+)$", stmt)
        if not assign_match:
            return statement if statement.endswith(";") else f"{statement};"

        target = assign_match.group(1).strip().strip('"').lstrip("#")
        val = assign_match.group(2).strip().upper()

        # Match target to CMs
        for cm in cms:
            t_lower = target.lower()
            cm_lower = cm.name.lower()
            if cm.cm_type == "LBC_TwoWayActuator":
                work_tag = (cm.io_mapping.get("workCmdTag") or "").lower()
                home_tag = (cm.io_mapping.get("homeCmdTag") or "").lower()
                is_work = any(k in t_lower for k in self._WORK_KEYWORDS) or target.lower() == work_tag
                is_home = any(k in t_lower for k in self._HOME_KEYWORDS) or target.lower() == home_tag

                if (cm_lower in t_lower or "cyl" in t_lower or target.lower() in {work_tag, home_tag}):
                    if is_work and val == "TRUE":
                        return f"#controlNodes.{cm.name}.commands.workPosition := TRUE;"
                    elif is_home and val == "TRUE":
                        return f"#controlNodes.{cm.name}.commands.homePosition := TRUE;"
                    elif is_work and val == "FALSE":
                        return f"#controlNodes.{cm.name}.commands.workPosition := FALSE;"
                    elif is_home and val == "FALSE":
                        return f"#controlNodes.{cm.name}.commands.homePosition := FALSE;"

            elif cm.cm_type == "LBC_AxisControl":
                if cm_lower in t_lower or "motor" in t_lower:
                    if val == "TRUE":
                        return f"#controlNodes.{cm.name}.commands.start := TRUE;"

        # If not matching a known CM, preserve statement with proper semicolon
        return f"{stmt};"

    def _translate_condition(self, condition: str, cms: list[AfCm]) -> str:
        """Translate legacy %I or sensor variables into #controlNodes status expressions."""
        result = condition
        for cm in cms:
            if cm.cm_type == "LBC_TwoWayActuator":
                work_sensor = cm.io_mapping.get("workSensorTag") or ""
                home_sensor = cm.io_mapping.get("homeSensorTag") or ""

                if work_sensor:
                    result = re.sub(rf'["#]?{re.escape(work_sensor)}["#]?', f"#controlNodes.{cm.name}.status.inWorkPosition", result)
                if home_sensor:
                    result = re.sub(rf'["#]?{re.escape(home_sensor)}["#]?', f"#controlNodes.{cm.name}.status.inHomePosition", result)

            elif cm.cm_type == "LBC_DigitalSignal":
                signal_tag = cm.io_mapping.get("signalTag") or ""
                if signal_tag:
                    result = re.sub(rf'["#]?{re.escape(signal_tag)}["#]?', f"#controlNodes.{cm.name}.status.signal", result)

        return result

    def _detect_unit(self, ems: list[CandidateEm], interlocks: list[InterlockEntry]) -> CandidateUnit:
        """Identify candidate Unit and mode control blocks."""
        unit_idx = 1
        source_blocks: list[str] = []
        mode_blocks: list[str] = []

        for b_name in self.canvas.blocks:
            b_lower = b_name.lower()
            if any(k in b_lower for k in self._MODE_CONTROL_KEYWORDS):
                mode_blocks.append(b_name)
            source_blocks.append(b_name)

        return CandidateUnit(
            unit_idx=unit_idx,
            name=self.target_unit_name,
            source_blocks=source_blocks,
            mode_control_blocks=mode_blocks,
            ems=ems,
            interlocks=interlocks,
        )

    def _build_block_mapping(self, unit: CandidateUnit) -> dict[str, str]:
        """Construct the legacy block to AF target role mapping table.

        无法映射的块值为 ``{_PENDING_ROLE} (…)`` 开头——上层据此把它们
        标为 af_pending_manual 保留原样,而不是笼统 superseded。
        """
        first_em = unit.ems[0].name if unit.ems else "Process"
        mapping: dict[str, str] = {}
        for b_name in self.canvas.blocks:
            b_lower = b_name.lower()
            if any(k in b_lower for k in self._MODE_CONTROL_KEYWORDS):
                mapping[b_name] = f"{unit.name}::CallUnit (Unit Mode & State Manager)"
            elif any(k in b_lower for k in self._SEQUENCE_KEYWORDS):
                mapping[b_name] = f"U1Em1_{first_em}::Sequence + StepToString (EM State Machine)"
            elif any(k in b_lower for k in self._SAFETY_KEYWORDS):
                mapping[b_name] = f"U1Em0_General (Safety Boundary & Interlocks)"
            elif any(k in b_lower for k in self._CYL_KEYWORDS + self._AXIS_KEYWORDS):
                mapping[b_name] = f"U1Em1_{first_em}::CallEquipment (Control Modules Hub)"
            elif b_name.startswith("DB"):
                mapping[b_name] = f"{unit.name}::EmNodes / U1Em1_{first_em}::ControlNodes"
            else:
                mapping[b_name] = f"{_PENDING_ROLE} (无法自动映射,保留原样待人工确认)"
        return mapping

    @staticmethod
    def _to_camel_case(text: str) -> str:
        """Convert snake_case or arbitrary string into valid camelCase identifier."""
        parts = re.split(r"[^A-Za-z0-9]", text)
        parts = [p for p in parts if p]
        if not parts:
            return "cmDefault"
        first = parts[0][:1].lower() + parts[0][1:]
        rest = "".join(p[:1].upper() + p[1:] for p in parts[1:])
        return first + rest

    @staticmethod
    def _derive_em_name(block_name: str, fallback_idx: int) -> str:
        """Derive a clean AF Equipment Module name from a legacy block name."""
        clean = re.sub(r"^(?:FB|FC)\d*_", "", block_name)
        clean = re.sub(r"[^A-Za-z0-9_]", "", clean)
        return clean or f"Station{fallback_idx}"
