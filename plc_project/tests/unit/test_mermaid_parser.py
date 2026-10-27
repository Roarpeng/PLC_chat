"""D 线单元测试:Mermaid sequenceDiagram → AF 步序解析(docs/24 §D)。

覆盖:典型时序图(3 participant、6 步骤、1 个 alt 分支)纯文本解析正确;
participant→CM(类型按名称推断)、消息/alt/Note→AfSequenceStep(×10 步号链 +
9xx 异常分支链);plan_from_mermaid 组装完整 AfProject;af_generator 块生成;
空/非法 Mermaid → 400;端点 E2E(TestClient)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plc_engine.af.af_generator import generate_af_project_blocks
from plc_engine.af.mermaid_parser import (
    MermaidParseError,
    mermaid_participants_to_cms,
    mermaid_to_af_steps,
    parse_mermaid_sequence,
    plan_from_mermaid,
)

#: 典型 Mermaid 时序图:3 participant、6 条消息、1 个 alt 结构(alt 臂 + else 臂)
TYPICAL_MERMAID = """sequenceDiagram
    participant OPS as Operator
    participant CYL as LoadingCylinder
    participant SEN as PartSensor
    OPS->>SEN: 等待工件到位
    SEN->>CYL: 工件到位, 气缸伸出
    CYL->>OPS: 伸出到位完成
    alt 伸出超时
        CYL->>OPS: 报告气缸超时故障
    else 传感器信号异常
        SEN->>OPS: 报告传感器故障
    end
    OPS->>CYL: 气缸缩回原位
    Note over CYL: 单循环结束
"""

#: alt + else:alt_branches 应含 2 个臂(alt 臂 + else 臂)
ALT_ELSE_MERMAID = """sequenceDiagram
    participant CYL as LoadingCylinder
    participant SEN as PartSensor
    SEN->>CYL: 工件到位, 气缸伸出
    alt 伸出超时
        CYL->>SEN: 报告气缸超时
    else 传感器信号异常
        SEN->>CYL: 报告传感器故障
    end
"""


# ---------------------------------------------------------------------------
# 1. parse_mermaid_sequence:典型图解析正确
# ---------------------------------------------------------------------------


def test_parse_typical_sequence_diagram() -> None:
    parsed = parse_mermaid_sequence(TYPICAL_MERMAID)

    # 3 个 participant,取 as 后的显示名,保持声明顺序
    assert parsed["participants"] == ["Operator", "LoadingCylinder", "PartSensor"]

    # 6 条消息步骤,seq 1..6,actor/target/action 解析正确
    steps = parsed["steps"]
    assert len(steps) == 6
    assert [s["seq"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert steps[0]["actor"] == "Operator"
    assert steps[0]["target"] == "PartSensor"
    assert steps[0]["action"] == "等待工件到位"
    assert steps[2]["actor"] == "LoadingCylinder"
    assert steps[5]["action"] == "气缸缩回原位"

    # 1 个 alt 结构 = 2 个臂(alt 臂 + else 臂):条件、臂内步骤 seq 归属正确
    assert parsed["alt_branches"] == [
        {"condition": "伸出超时", "kind": "alt", "steps": [4]},
        {"condition": "传感器信号异常", "kind": "else", "steps": [5]},
    ]
    assert steps[3]["condition"] == "伸出超时"
    assert steps[3]["branch"]["kind"] == "alt"
    assert steps[4]["condition"] == "传感器信号异常"
    assert steps[4]["branch"]["kind"] == "else"
    # 主链步骤无分支条件
    assert steps[0]["condition"] is None
    assert steps[0]["branch"] is None
    assert steps[5]["branch"] is None

    # Note over 挂到前一条消息步骤(seq 6)
    assert steps[5]["note"] == "单循环结束"


def test_parse_alt_else_yields_two_branches() -> None:
    parsed = parse_mermaid_sequence(ALT_ELSE_MERMAID)
    kinds = [(b["kind"], b["condition"], b["steps"]) for b in parsed["alt_branches"]]
    assert kinds == [
        ("alt", "伸出超时", [2]),
        ("else", "传感器信号异常", [3]),
    ]
    assert parsed["steps"][1]["condition"] == "伸出超时"
    assert parsed["steps"][2]["condition"] == "传感器信号异常"
    assert parsed["steps"][2]["branch"]["kind"] == "else"


def test_parse_implicit_participants_and_arrow_variants() -> None:
    # 未声明 participant:消息收发方按首现补进;支持 ->> / -->> / ->
    parsed = parse_mermaid_sequence(
        "sequenceDiagram\n"
        "A->>B: 启动电机 motorRun\n"
        "B-->>A: 电机运行反馈\n"
        "A->B: 停止\n"
    )
    assert parsed["participants"] == ["A", "B"]
    assert len(parsed["steps"]) == 3
    assert parsed["steps"][1]["action"] == "电机运行反馈"


def test_parse_invalid_mermaid_raises() -> None:
    # 空 / 纯空白
    with pytest.raises(MermaidParseError, match="MERMAID_EMPTY"):
        parse_mermaid_sequence("")
    with pytest.raises(MermaidParseError, match="MERMAID_EMPTY"):
        parse_mermaid_sequence("   \n  ")
    # 非 sequenceDiagram(flowchart 等)
    with pytest.raises(MermaidParseError, match="MERMAID_NOT_SEQUENCE"):
        parse_mermaid_sequence("graph TD\nA-->B\n")
    with pytest.raises(MermaidParseError, match="MERMAID_NOT_SEQUENCE"):
        parse_mermaid_sequence("随便一段文本")
    # 只有头,无参与方无步骤
    with pytest.raises(MermaidParseError, match="MERMAID_EMPTY"):
        parse_mermaid_sequence("sequenceDiagram\nautonumber\n")
    # alt 未闭合 / 多余 end
    with pytest.raises(MermaidParseError, match="MERMAID_UNBALANCED"):
        parse_mermaid_sequence("sequenceDiagram\nA->>B: x\nalt 异常\nA->>B: y\n")
    with pytest.raises(MermaidParseError, match="MERMAID_UNBALANCED"):
        parse_mermaid_sequence("sequenceDiagram\nA->>B: x\nend\n")


# ---------------------------------------------------------------------------
# 2. participant → CM(类型按名称复用 planner._classify_cm_type 推断)
# ---------------------------------------------------------------------------


def test_participants_to_cms_infers_types() -> None:
    cms = mermaid_participants_to_cms(["Operator", "LoadingCylinder", "PartSensor"])
    assert [c.name for c in cms] == ["Operator", "LoadingCylinder", "PartSensor"]
    by_name = {c.name: c.cm_type for c in cms}
    assert by_name["LoadingCylinder"] == "LBC_TwoWayActuator"  # cylinder 关键词
    assert by_name["PartSensor"] == "LBC_DigitalSignal"        # sensor 关键词


def test_participants_to_cms_chinese_names_use_keyword_prefix() -> None:
    cms = mermaid_participants_to_cms(["上料气缸", "工件传感器", "伺服轴1"])
    by_desc = {c.description: c for c in cms}
    assert by_desc["上料气缸"].name == "cyl"
    assert by_desc["上料气缸"].cm_type == "LBC_TwoWayActuator"
    assert by_desc["工件传感器"].name == "sensor"
    assert by_desc["工件传感器"].cm_type == "LBC_DigitalSignal"
    assert by_desc["伺服轴1"].cm_type == "LBC_AxisControl"


def test_participants_to_cms_dedupes_identifiers() -> None:
    cms = mermaid_participants_to_cms(["上料气缸", "压紧气缸"])
    assert [c.name for c in cms] == ["cyl", "cyl2"]


# ---------------------------------------------------------------------------
# 3. mermaid_to_af_steps:消息→action/condition,alt→异常分支,步号 ×10 链
# ---------------------------------------------------------------------------


def test_mermaid_to_af_steps_chains_x10_with_exception_branch() -> None:
    parsed = parse_mermaid_sequence(TYPICAL_MERMAID)
    steps = mermaid_to_af_steps(parsed)

    # 主链 5 步 ×10(10..50;alt 首臂视作条件主路径),else 臂 → 9xx 异常分支
    assert [s.step_id for s in steps] == [10, 20, 30, 40, 50, 900]

    main = [s for s in steps if s.step_id < 100]
    exc = [s for s in steps if s.step_id >= 100]
    # 主链 next_step_id 依序链,末步回 1(Ready)
    assert [s.next_step_id for s in main] == [20, 30, 40, 50, 1]
    # 异常链末步回 999(AF 错误步)
    assert exc[0].next_step_id == 999
    # else 臂前最后一个主步(alt 首臂,原 seq=4 → step 40)锚定异常步
    assert main[3].error_step_id == 900

    # 消息文本 → action/transition:命令严格走 #controlNodes
    assert any("workPosition := TRUE;" in a for a in main[1].actions)
    assert "inWorkPosition" in main[1].transition_condition
    assert any("homePosition := TRUE;" in a for a in main[4].actions)
    assert "inHomePosition" in main[4].transition_condition

    # else → 异常分支:description 标注条件
    assert exc[0].description.startswith("[异常分支:传感器信号异常]")

    # Note → 步骤注释 action(挂在 seq 6 = step 50)
    assert any(a.startswith("// Note: 单循环结束") for a in main[4].actions)

    # alt 首臂(主链内)description 标注分支条件
    assert main[3].description.startswith("[分支:伸出超时]")


def test_mermaid_to_af_steps_alt_else_maps_else_arms_to_exception() -> None:
    parsed = parse_mermaid_sequence(ALT_ELSE_MERMAID)
    steps = mermaid_to_af_steps(parsed)
    ids = [s.step_id for s in steps]
    # 主链 = 非else + alt 首臂 → 10/20;else 臂 → 900
    assert ids == [10, 20, 900]
    by_id = {s.step_id: s for s in steps}
    assert by_id[900].description.startswith("[异常分支:传感器信号异常]")
    # else 臂前最后一个主步(alt 首臂,step 20)锚定异常步
    assert by_id[20].error_step_id == 900


# ---------------------------------------------------------------------------
# 4. plan_from_mermaid → AfProject(复用 af_model 结构)
# ---------------------------------------------------------------------------


def test_plan_from_mermaid_builds_full_af_project() -> None:
    project = plan_from_mermaid(TYPICAL_MERMAID, "WashCell-1")

    # 工程名洗成合法标识;单 Unit U1_<工程名> + EM1
    assert project.name == "WashCell1"
    assert len(project.units) == 1
    unit = project.units[0]
    assert unit.unit_idx == 1
    assert unit.unit_name == "U1_WashCell1"
    assert len(unit.equipment_modules) == 1

    em = unit.equipment_modules[0]
    # participant → CM(有 CM)
    assert {c.name for c in em.control_modules} >= {"LoadingCylinder", "PartSensor"}
    # 消息 → 步骤(有 steps,主链 + 异常分支)
    assert len(em.sequence.steps) == 6
    assert em.sequence.steps[0].step_id == 10
    assert em.jobs and em.jobs[0].initial_step == 10


def test_plan_from_mermaid_no_messages_falls_back_to_default_steps() -> None:
    # 只有 participant、无消息 → 复用 _build_default_steps_for_cms 兜底
    project = plan_from_mermaid(
        "sequenceDiagram\n    participant CYL as LoadingCylinder\n",
        "IdleCell",
    )
    em = project.units[0].equipment_modules[0]
    assert em.control_modules
    assert em.sequence.steps  # 兜底标准工序(伸出/缩回)


# ---------------------------------------------------------------------------
# 5. 块生成:AfProject → generate_af_project_blocks
# ---------------------------------------------------------------------------


def test_generate_blocks_from_mermaid_plan() -> None:
    project = plan_from_mermaid(TYPICAL_MERMAID, "WashCell-1")
    blocks = generate_af_project_blocks(project)

    assert len(blocks) >= 10  # Unit OBs/EmNodes/CallUnit + EM0 + EM1 全套
    ctrl = next(b for b in blocks.values() if b.name == "ControlNodes")
    assert "LoadingCylinder" in ctrl.scl_body
    assert "PartSensor" in ctrl.scl_body

    seq = next(b for b in blocks.values() if b.name == "Sequence")
    # 主链 + 9xx 异常分支步都进 Sequence FB;命令走 #controlNodes
    assert "#controlNodes.LoadingCylinder.commands" in seq.scl_body
    assert "900:" in seq.scl_body
    assert "999:" in seq.scl_body


# ---------------------------------------------------------------------------
# 6. 端点 E2E:POST /api/v1/plc/canvas/generate-from-mermaid
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app
    from gateway.app.services import store as mem

    mem.store.plc_jobs.clear()

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
    mem.store.plc_jobs.clear()


AUTH_HEADER = {"X-API-Key": "ros_ak_test_key"}
ENDPOINT = "/api/v1/plc/canvas/generate-from-mermaid"


def _post(client: TestClient, body: dict[str, Any]):
    return client.post(ENDPOINT, json=body, headers=AUTH_HEADER)


def test_endpoint_generates_canvas_from_mermaid(client: TestClient) -> None:
    resp = _post(client, {"mermaid": TYPICAL_MERMAID, "project_name": "WashCell-1"})
    assert resp.status_code == 200, resp.text

    res = resp.json()
    assert res["ok"] is True
    data = res["data"]

    # 块生成:非空、与画布一致、全部 draft 草稿
    assert data["blocks_created"] > 0
    assert data["blocks_created"] == len(data["canvas"]["blocks"])
    for block in data["canvas"]["blocks"].values():
        assert block["status"] == "draft"

    # 软件单元命名:U1_<洗过的工程名> / U1Em1_ProcessStation
    software_units = {b.get("software_unit") for b in data["canvas"]["blocks"].values()}
    assert "U1_WashCell1" in software_units
    assert any(su.startswith("U1Em1_") for su in software_units)

    # participant 进入生成块;步序进入 Sequence(含 9xx 异常分支)
    ctrl = next(b for b in data["canvas"]["blocks"].values() if b["name"] == "ControlNodes")
    assert "LoadingCylinder" in ctrl["scl_body"]
    seq = next(b for b in data["canvas"]["blocks"].values() if b["name"] == "Sequence")
    assert "#controlNodes.LoadingCylinder.commands" in seq["scl_body"]
    assert "900:" in seq["scl_body"]

    # linter 静态预检发现可查(列表、可序列化、结构字段在位)
    assert isinstance(data["linter_findings"], list)
    for f in data["linter_findings"]:
        assert set(f) >= {"rule_id", "severity", "block_name", "message"}


def test_endpoint_400_on_empty_or_invalid_mermaid(client: TestClient) -> None:
    # 缺 mermaid 字段
    resp = _post(client, {"project_name": "WashCell-1"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "MERMAID_REQUIRED"

    # 空 mermaid
    resp = _post(client, {"mermaid": "   \n", "project_name": "WashCell-1"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "MERMAID_EMPTY"

    # 非 sequenceDiagram
    resp = _post(client, {"mermaid": "graph TD\nA-->B", "project_name": "WashCell-1"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "MERMAID_NOT_SEQUENCE"

    # alt 未闭合
    resp = _post(
        client,
        {"mermaid": "sequenceDiagram\nA->>B: x\nalt 异常\nA->>B: y", "project_name": "X"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "MERMAID_UNBALANCED"
