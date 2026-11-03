"""plc_engine.contract_adapters 的单元测试。

全部样本内联构造，不读外部文件；只依赖标准库 + 本仓库模块。
"""

from __future__ import annotations

import hashlib

import pytest

from plc_engine.af.af_model import (
    AfCm,
    AfEm,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)
from plc_engine.contract_adapters import (
    af_em_to_station_model,
    bundle_result_to_batch,
    contract_roundtrip_check,
    expression_to_rhs_ast,
    folded_network_to_ast,
    plan_to_writeback_result,
    project_to_bundle,
)
from plc_engine.contracts import (
    SLOT_KEYS,
    STEP_CONTRACTS,
    BoschStationAfModel,
    from_dict,
    to_dict,
)
from plc_engine.mega_source import BundleResult
from plc_engine.writeback_linter import Finding
from plc_engine.writeback_pipeline import WritebackPlan

# ---------------------------------------------------------------------------
# 样本
# ---------------------------------------------------------------------------

def _ref(access: str) -> dict:
    return {"type": "ref", "access": access}


def _coil_stmt(target: str = "Q_ST10_Out", **extra: object) -> dict:
    stmt = {
        "target": target,
        "kind": "COIL_ASSIGN",
        "value": {"type": "and", "operands": [_ref("I_Start"), _ref("I_Safe")]},
        "part_uuid": "uuid-1",
        "part_name": "Coil",
    }
    stmt.update(extra)
    return stmt


def _em(*, with_io: bool = True) -> AfEm:
    cms = [
        AfCm(
            name="cylLoader",
            cm_type="LBC_TwoWayActuator",
            description="上料气缸",
            io_mapping=(
                {"senHome": "%I0.0", "senWork": "%I0.1", "valveOut": "%Q0.0"}
                if with_io
                else {}
            ),
        ),
        AfCm(
            name="sensorPart",
            cm_type="LBC_DigitalSignal",
            io_mapping={"sig": "%I0.2"} if with_io else {},
            fallback=True,
        ),
    ]
    steps = [
        AfSequenceStep(
            step_id=10,
            name="WAIT_FOR_PART",
            description="等待工件到位",
            actions=["#cmd.enable := TRUE;"],
            transition_condition="sensorPart.sig",
            next_step_id=20,
        ),
        AfSequenceStep(
            step_id=20,
            name="CYL_EXTEND",
            description="气缸伸出",
            actions=["#cmd.extend := TRUE;"],
            transition_condition="cylLoader.senWork",
            next_step_id=0,
        ),
    ]
    return AfEm(
        em_idx=1,
        name="LoadingStation",
        description="上料工位",
        namespace="U1",
        sequence=AfSequence(initial_step=10, ready_step=1, steps=steps),
        control_modules=cms,
    )


def to_dict_af_em(em: AfEm) -> dict:
    """把 AfEm 摊平成可比较的纯数据（嵌套 list/dict 一并复制）。"""
    return {
        "em_idx": em.em_idx,
        "name": em.name,
        "description": em.description,
        "namespace": em.namespace,
        "has_unit_idx": hasattr(em, "unit_idx"),
        "sequence": {
            "initial_step": em.sequence.initial_step,
            "ready_step": em.sequence.ready_step,
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "description": s.description,
                    "actions": list(s.actions),
                    "transition_condition": s.transition_condition,
                    "next_step_id": s.next_step_id,
                }
                for s in em.sequence.steps
            ],
        },
        "control_modules": [
            {
                "name": c.name,
                "cm_type": c.cm_type,
                "io_mapping": dict(c.io_mapping),
                "parameters": dict(c.parameters),
                "fallback": c.fallback,
            }
            for c in em.control_modules
        ],
    }


# ---------------------------------------------------------------------------
# folded_network_to_ast
# ---------------------------------------------------------------------------

def test_folded_network_single_coil_assign() -> None:
    folded = {
        "network_id": 3,
        "title": "启动回路",
        "statements": [_coil_stmt()],
        "unresolved_parts": [],
        "evidence": [],
    }
    ast = folded_network_to_ast(folded, block_name="FB_Start", language="LAD")

    assert ast.block_name == "FB_Start"
    assert ast.original_language == "LAD"
    assert ast.validate() is None
    assert len(ast.networks) == 1
    net = ast.networks[0]
    assert net.network_no == 3
    assert net.title == "启动回路"
    assert len(net.assignments) == 1
    assign = net.assignments[0]
    assert assign.lhs_symbol == "Q_ST10_Out"
    assert assign.assign_type == "COIL_ASSIGN"
    assert assign.rhs_ast["op"] == "AND"
    assert ast.all_writes == ["Q_ST10_Out"]


def test_folded_network_enable_merged_into_rhs() -> None:
    folded = {
        "network_id": "7",
        "title": "move",
        "statements": [_coil_stmt(target="#val", kind="move", enable=_ref("I_En"))],
        "unresolved_parts": [],
    }
    net = folded_network_to_ast(folded, block_name="FB_Move").networks[0]

    assert net.network_no == 7
    assign = net.assignments[0]
    assert assign.assign_type == "move"
    assert assign.rhs_ast["enable"]["op"] == "REF"
    assert assign.rhs_ast["enable"]["access"] == "I_En"


def test_folded_network_unresolved_parts_into_title() -> None:
    folded = {
        "network_id": 1,
        "title": "未知件",
        "statements": [],
        "unresolved_parts": ["MysteryBox", "WeirdPart"],
    }
    net = folded_network_to_ast(folded, block_name="FB_X").networks[0]

    assert "未知件" in net.title
    assert "MysteryBox" in net.title
    assert "WeirdPart" in net.title
    assert net.assignments == []


def test_folded_network_multiple_statements() -> None:
    folded = {
        "network_id": 2,
        "title": "多线圈",
        "statements": [
            _coil_stmt(target="Q_A"),
            _coil_stmt(target="Q_B", kind="set"),
            _coil_stmt(target="Q_C", kind="reset"),
        ],
    }
    ast = folded_network_to_ast(folded, block_name="FB_Multi")

    assert ast.all_writes == ["Q_A", "Q_B", "Q_C"]
    assert [a.assign_type for a in ast.networks[0].assignments] == [
        "COIL_ASSIGN",
        "set",
        "reset",
    ]


def test_folded_network_missing_keys_falls_back() -> None:
    ast = folded_network_to_ast({}, block_name="FB_Empty")
    net = ast.networks[0]

    assert net.network_no == 0
    assert net.title == ""
    assert net.assignments == []
    assert ast.networks[0].scl_statements == []


# ---------------------------------------------------------------------------
# expression_to_rhs_ast
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("expr", "expected_op", "check"),
    [
        ({"type": "and", "operands": [_ref("A"), _ref("B")]}, "AND", lambda r: len(r["operands"]) == 2),
        ({"type": "or", "operands": [_ref("A")]}, "OR", lambda r: r["operands"][0]["access"] == "A"),
        ({"type": "not", "operand": _ref("A")}, "NOT", lambda r: r["operands"][0]["op"] == "REF"),
        ({"type": "ref", "access": "I_Start"}, "REF", lambda r: r["access"] == "I_Start"),
        ({"type": "literal", "value": True}, "LITERAL", lambda r: r["value"] is True),
        ({"type": "compare", "op": "=", "lhs": _ref("A"), "rhs": {"type": "literal", "value": 1}},
         "COMPARE", lambda r: r["lhs"]["op"] == "REF" and r["rhs"]["op"] == "LITERAL"),
        ({"type": "func", "name": "SIN", "args": [_ref("A")]}, "FUNC", lambda r: r["args"][0]["op"] == "REF"),
        ({"type": "raw", "text": "A+B*C"}, "RAW", lambda r: r["text"] == "A+B*C"),
    ],
)
def test_expression_to_rhs_ast_all_types(expr: dict, expected_op: str, check: object) -> None:
    result = expression_to_rhs_ast(expr)

    assert result["op"] == expected_op
    assert result["_raw_type"] == expr["type"]
    assert check(result)  # type: ignore[operator]


def test_expression_roundtrip_keeps_original_keys() -> None:
    expr = {
        "type": "and",
        "operands": [
            {"type": "ref", "access": "I_A", "negated": False},
            {"type": "not", "operand": {"type": "literal", "value": False}},
        ],
        "comment": "启动条件",
    }
    result = expression_to_rhs_ast(expr)

    # 结构键（Tab2 形状）
    assert result["op"] == "AND"
    # 原始信息不丢：type 进 _raw_type，额外键原样带出，子表达式递归保留 access/value
    assert result["_raw_type"] == "and"
    assert result["comment"] == "启动条件"
    assert result["operands"][0]["access"] == "I_A"
    assert result["operands"][0]["negated"] is False
    assert result["operands"][1]["op"] == "NOT"
    assert result["operands"][1]["operands"][0]["value"] is False


def test_expression_unknown_type_and_non_dict_do_not_raise() -> None:
    unknown = expression_to_rhs_ast({"type": "quantum", "qubits": 3})
    assert unknown["op"] == "UNKNOWN"
    assert unknown["_raw_type"] == "quantum"
    assert unknown["qubits"] == 3

    assert expression_to_rhs_ast(None)["op"] == "RAW"  # type: ignore[arg-type]
    assert expression_to_rhs_ast("plain")["value"] == "plain"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# af_em_to_station_model
# ---------------------------------------------------------------------------

def test_af_em_to_station_model_slots_complete_and_valid() -> None:
    model = af_em_to_station_model(_em(), unit_idx=1)

    assert all(key in model.slots for key in SLOT_KEYS)
    assert model.validate() is None
    assert model.station_id == "Em1_LoadingStation"  # 未挂 unit_idx 时的兜底
    assert model.slots["slot2_OpMode"] == "LOCKED_BOSCH_TEMPLATE"
    assert model.slots["slot4_Interlock"] == {}


def test_af_em_to_station_model_naming_and_io_split() -> None:
    em = _em()
    em.unit_idx = 2  # type: ignore[attr-defined]  # 动态挂载（生产代码里同样如此）
    model = af_em_to_station_model(em)

    assert model.station_id == "U2Em1_LoadingStation"
    assert model.fb_block_name == "FB_U2Em1_LoadingStation"
    assert model.idb_block_name == "IDB_U2Em1_LoadingStation"
    assert model.cmd_udt_name == "UDT_U2Em1_LoadingStation_Cmd"

    inputs = model.slots["slot1_InPeriphery"]["inputs"]
    outputs = model.slots["slot6_OutAndHmiAdapter"]["outputs"]
    assert inputs == {"cylLoader.senHome": "%I0.0", "cylLoader.senWork": "%I0.1", "sensorPart.sig": "%I0.2"}
    assert outputs == {"cylLoader.valveOut": "%Q0.0"}
    assert model.slots["slot1_InPeriphery"]["unclassified"] == {}


def test_af_em_to_station_model_sequence_mapping() -> None:
    model = af_em_to_station_model(_em())
    steps = model.slots["slot3_SeqAuto"]

    assert [s["stepNo"] for s in steps] == [10, 20]
    assert [s["transitions"][0]["nextStep"] for s in steps] == [20, 0]
    assert steps[0]["name"] == "WAIT_FOR_PART"
    assert steps[0]["comment"] == "等待工件到位"
    assert steps[0]["actions"] == ["#cmd.enable := TRUE;"]
    assert steps[0]["transitions"][0]["condition"] == "sensorPart.sig"

    elements = model.slots["slot5_ElementCall"]
    assert [e["name"] for e in elements] == ["cylLoader", "sensorPart"]
    assert elements[1]["cm_type"] == "LBC_DigitalSignal"
    assert elements[1]["fallback"] is True


def test_af_em_to_station_model_does_not_mutate_input() -> None:
    em = _em()
    before = to_dict_af_em(em)

    af_em_to_station_model(em, unit_idx=3)

    assert to_dict_af_em(em) == before


def test_af_em_to_station_model_result_is_json_serializable() -> None:
    model = af_em_to_station_model(_em())
    restored = from_dict(BoschStationAfModel, to_dict(model))

    assert restored.slots["slot3_SeqAuto"][0]["stepNo"] == 10
    assert restored.validate() is None


# ---------------------------------------------------------------------------
# bundle_result_to_batch
# ---------------------------------------------------------------------------

def test_bundle_result_to_batch_sha256_and_bom(tmp_path) -> None:
    text = 'FUNCTION_BLOCK "FB_A"\nEND_FUNCTION_BLOCK\n'
    result = BundleResult(
        text=text,
        block_names=["FB_A"],
        external_dependencies=["LAF_SelectJob"],
        skipped_unchanged=["FB_Old"],
    )
    bom_path = tmp_path / "with_bom.scl"
    bom_path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    batch = bundle_result_to_batch(result, str(bom_path))

    assert batch.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert batch.has_utf8_bom is True
    assert batch.block_names == ["FB_A"]
    assert batch.external_dependencies == ["LAF_SelectJob"]
    assert batch.skipped_unchanged == ["FB_Old"]
    assert batch.validate() is None


def test_bundle_result_to_batch_without_bom(tmp_path) -> None:
    plain = tmp_path / "plain.scl"
    plain.write_bytes(b"FUNCTION_BLOCK FB_B\n")

    batch = bundle_result_to_batch(BundleResult(text="x"), str(plain))

    assert batch.has_utf8_bom is False


# ---------------------------------------------------------------------------
# plan_to_writeback_result
# ---------------------------------------------------------------------------

def _plan(findings: list[Finding], **kwargs: object) -> WritebackPlan:
    plan = WritebackPlan(selected=["FB_A"], reasons={"FB_A": "seed"}, max_depth=1)
    plan.findings = findings
    for key, value in kwargs.items():
        setattr(plan, key, value)
    return plan


def test_plan_to_writeback_result_errors_and_counts() -> None:
    plan = _plan(
        [
            Finding(rule="R2", severity="error", block="FB_A", line=12, message="双写 %Q0.0"),
            Finding(rule="R1", severity="warning", block="FB_A", line=3, message="裸写符号"),
            Finding(rule="R4", severity="error", block="FB_B", line=None, message="类型不匹配"),
        ],
        block_names=["FB_A", "FB_B"],
        skipped_unchanged=["FB_C", "FB_D"],
    )

    result = plan_to_writeback_result(plan, elapsed_ms=1500)

    assert result.success is False
    assert result.elapsed_milliseconds == 1500
    assert result.written_block_count == 2
    assert result.skipped_unchanged_blocks == 2
    assert len(result.errors) == 2
    assert result.errors[0].block_name == "FB_A"
    assert result.errors[0].network_or_line == "12"
    assert "[R2]" in result.errors[0].tia_description
    assert "双写 %Q0.0" in result.errors[0].tia_description
    assert result.errors[1].network_or_line == ""
    assert result.failed_block_names == ["FB_A", "FB_B"]


def test_plan_to_writeback_result_clean_plan() -> None:
    plan = _plan(
        [Finding(rule="R1", severity="warning", block="FB_A", line=1, message="提示")],
        block_names=["FB_A"],
    )

    result = plan_to_writeback_result(plan, elapsed_ms=0)

    assert result.success is True
    assert result.errors == []
    assert result.written_block_count == 1
    assert result.skipped_unchanged_blocks == 0


# ---------------------------------------------------------------------------
# project_to_bundle
# ---------------------------------------------------------------------------

def test_project_to_bundle_expands_units() -> None:
    unit = AfUnit(unit_idx=1, name="AssemblyCell", equipment_modules=[_em(), _em()])
    em2 = unit.equipment_modules[1]
    em2.em_idx = 2
    em2.name = "PressStation"
    project = AfProject(name="DemoLine", units=[unit])

    bundle = project_to_bundle(project)

    assert bundle.project_path == "DemoLine"
    assert bundle.black_box_blocks == []
    assert bundle.simatic_ml_blocks == []
    # 每个 EM 一张 tag 表（表名 = station_id）
    assert [t.name for t in bundle.tag_tables] == [
        "Em1_LoadingStation",
        "Em2_PressStation",
    ]
    assert len(bundle.tag_tables[0].tags) == 4
    assert bundle.tag_tables[0].tags[0].logical_address == "%I0.0"
    # 每个 EM 三条 text source：FB / DB / UDT
    assert len(bundle.text_sources) == 6
    assert [t.type for t in bundle.text_sources[:3]] == ["FB", "DB", "UDT"]
    assert bundle.text_sources[0].block_name == "FB_Em1_LoadingStation"
    assert bundle.validate() is None


# ---------------------------------------------------------------------------
# contract_roundtrip_check
# ---------------------------------------------------------------------------

def test_contract_roundtrip_check_all_step_outputs() -> None:
    checked = 0
    for step in STEP_CONTRACTS:
        output_type = step.output_type
        assert output_type is not None
        assert contract_roundtrip_check(output_type()) is True, step.name
        checked += 1
    assert checked == 7


def test_contract_roundtrip_check_populated_instances() -> None:
    ast = folded_network_to_ast(
        {"network_id": 1, "title": "t", "statements": [_coil_stmt()]},
        block_name="FB_A",
    )
    model = af_em_to_station_model(_em())

    assert contract_roundtrip_check(ast) is True
    assert contract_roundtrip_check(model) is True
    assert contract_roundtrip_check(project_to_bundle(AfProject(name="P"))) is True


def test_contract_roundtrip_check_non_dataclass_is_false() -> None:
    assert contract_roundtrip_check({"a": 1}) is False
