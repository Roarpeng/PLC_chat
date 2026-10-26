"""N 线单元测试:POST /api/v1/plc/canvas/generate-from-requirement(docs/23 §3)。

覆盖:confirmed 门禁(400 REQUIREMENT_NOT_CONFIRMED)、含设备与步骤的
confirmed 需求 → 块生成(U1_ 命名/双门禁发现可查)、IEC/AF 违规注入被
门禁捕获、空设备需求 → 合理最小 Unit、生成失败 500、零写回(canvas.source
为空,只产草稿)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gateway.app.services.plc import af_generate as af_generate_mod


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

ENDPOINT = "/api/v1/plc/canvas/generate-from-requirement"


def _card(**overrides: Any) -> dict[str, Any]:
    """契约 docs/22 §1 的完整需求卡;电机/阀(经 linked_signals)/传感器 + 工步。"""
    base: dict[str, Any] = {
        "requirement_id": "req-aabbccdd0011",
        "project_name": "WashCell-1",
        "confirmation_status": "confirmed",
        "task_kind": "improve",
        "intent_summary": "清洗工位:传感器到位后阀开、电机运行、到位停止",
        "origin_prompt": "做一个清洗工位:工件到位后清洗阀打开,泵电机运行,清洗完成停止",
        "items": [
            {"id": "it-1", "kind": "sequence", "text": "工步10: 等待工件到位传感器 sensorPartPresent", "source": "user"},
            {"id": "it-2", "kind": "sequence", "text": "工步20: 清洗阀 valveRinse 打开冲洗", "source": "user"},
            {"id": "it-3", "kind": "sequence", "text": "工步30: 泵电机 motorPump 启动运行", "source": "user"},
            {"id": "it-4", "kind": "sequence", "text": "工步40: 泵电机 motorPump 停止", "source": "user"},
        ],
        "open_questions": [],
        "linked_blocks": [],
        "linked_signals": ["sensorPartPresent", "valveRinse", "motorPump"],
    }
    base.update(overrides)
    return base


def _post(client: TestClient, body: dict[str, Any]):
    return client.post(ENDPOINT, json=body, headers=AUTH_HEADER)


# ---------------------------------------------------------------------------
# 1. confirmed 门禁:未确认 → 400 REQUIREMENT_NOT_CONFIRMED
# ---------------------------------------------------------------------------


def test_service_raises_value_error_when_not_confirmed() -> None:
    with pytest.raises(ValueError, match="REQUIREMENT_NOT_CONFIRMED"):
        af_generate_mod.generate_from_requirement(_card(confirmation_status="proposed"), "WashCell")


def test_endpoint_400_when_requirement_not_confirmed(client: TestClient) -> None:
    for bad_status in ("proposed", "rejected", "", None):
        resp = _post(
            client,
            {"requirement": _card(confirmation_status=bad_status), "project_name": "WashCell"},
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]["code"] == "REQUIREMENT_NOT_CONFIRMED"


def test_endpoint_400_when_requirement_missing(client: TestClient) -> None:
    resp = _post(client, {"project_name": "WashCell"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "REQUIREMENT_REQUIRED"


# ---------------------------------------------------------------------------
# 2. confirmed 需求 → 块生成:U1_ 命名、blocks_created>0、双门禁发现可查
# ---------------------------------------------------------------------------


def test_endpoint_generates_blocks_from_confirmed_requirement(client: TestClient) -> None:
    resp = _post(client, {"requirement": _card(), "project_name": "WashCell-1"})
    assert resp.status_code == 200, resp.text

    res = resp.json()
    assert res["ok"] is True
    data = res["data"]

    # 块生成:非空,软件单元命名 U1_<洗过的项目名>(WashCell-1 → WashCell1)
    assert data["blocks_created"] > 0
    assert data["blocks_created"] == len(data["canvas"]["blocks"])
    software_units = {b.get("software_unit") for b in data["canvas"]["blocks"].values()}
    assert "U1_WashCell1" in software_units
    assert any(su.startswith("U1_") for su in software_units)
    assert any(su.startswith("U1Em1_") for su in software_units)

    # 全部 draft 草稿、零写回信号:canvas 不携带任何工程落盘引用
    for block in data["canvas"]["blocks"].values():
        assert block["status"] == "draft"
    assert data["canvas"]["source"] is None

    # 设备进入生成块:ControlNodes DB 挂传感器/阀(执行器)/电机三类 CM
    ctrl = next(b for b in data["canvas"]["blocks"].values() if b["name"] == "ControlNodes")
    assert "sensorPartPresent" in ctrl["scl_body"]
    assert "valveRinse" in ctrl["scl_body"]
    assert "motorPump" in ctrl["scl_body"]
    cm_types = set()
    for cm in ("sensorPartPresent", "valveRinse", "motorPump"):
        for b in data["canvas"]["blocks"].values():
            if b["name"] == "CallEquipment":
                body = b["scl_body"]
                if f'inst_{cm} : "LBC_DigitalSignal"' in body and cm == "sensorPartPresent":
                    cm_types.add("sensor")
                if f'inst_{cm} : "LBC_TwoWayActuator"' in body and cm == "valveRinse":
                    cm_types.add("valve")
                if f'inst_{cm} : "LBC_MotorStarter"' in body and cm == "motorPump":
                    cm_types.add("motor")
    assert cm_types == {"sensor", "valve", "motor"}

    # 工序进入 Sequence:步号 10..40、命令严格走 #controlNodes.<cm>.commands
    seq = next(b for b in data["canvas"]["blocks"].values() if b["name"] == "Sequence")
    assert "#controlNodes.sensorPartPresent.status.signal" in seq["scl_body"]
    assert "#controlNodes.valveRinse.commands" in seq["scl_body"]
    assert "#controlNodes.motorPump.commands" in seq["scl_body"]

    # 双门禁发现结构可查(列表、可序列化、结构字段在位)
    assert isinstance(data["linter_findings"], list)
    assert isinstance(data["iec_violations"], list)
    for f in data["linter_findings"]:
        assert set(f) >= {"rule_id", "severity", "block_name", "message"}
    for v in data["iec_violations"]:
        assert set(v) >= {"target_type", "target_id", "severity", "message"}


# ---------------------------------------------------------------------------
# 3. 门禁捕获:注入 AF/IEC 违规(非法 OB 编号 + 未配对关键字)
# ---------------------------------------------------------------------------


def test_gates_capture_injected_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    from plc_engine.canvas_model import CanvasBlock

    def fake_generate(project: Any) -> dict[str, CanvasBlock]:
        return {
            # AF-04 违规:U1_Test 的 Unit OB 编号应为 1000/1001/1002,给 99
            "U1_Test::BadOb": CanvasBlock(
                name="BadOb",
                block_type="OB",
                number=99,
                software_unit="U1_Test",
                af_role="OB",
                scl_body="// bad ob\n",
                status="draft",
            ),
            # IEC/SCL 违规:Sequence 体内 IF 缺 END_IF(关键字未配对)
            "U1_Test::UnbalancedSeq": CanvasBlock(
                name="UnbalancedSeq",
                block_type="FB",
                number=1001,
                software_unit="U1_Test",
                af_role="Sequence",
                scl_body="IF TRUE THEN\n    #statStepNext := 1;",
                status="draft",
            ),
        }

    monkeypatch.setattr(af_generate_mod, "generate_af_project_blocks", fake_generate)

    result = af_generate_mod.generate_from_requirement(_card(), "WashCell-1")

    af04 = [f for f in result["linter_findings"] if f["rule_id"] == "AF-04"]
    assert af04, f"AF-04 未捕获非法 OB 编号: {result['linter_findings']}"
    assert af04[0]["severity"] == "error"
    assert "BadOb" in af04[0]["block_name"] or "BadOb" == af04[0]["block_name"]

    unbalanced = [v for v in result["iec_violations"] if "IF" in str(v.get("message", ""))]
    assert unbalanced, f"SCL 预检未捕获未配对 IF: {result['iec_violations']}"
    assert unbalanced[0]["severity"] == "error"


def test_endpoint_surfaces_gate_violations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plc_engine.canvas_model import CanvasBlock

    monkeypatch.setattr(
        af_generate_mod,
        "generate_af_project_blocks",
        lambda project: {
            "U1_Test::BadOb": CanvasBlock(
                name="BadOb",
                block_type="OB",
                number=99,
                software_unit="U1_Test",
                af_role="OB",
                scl_body="// bad ob\n",
                status="draft",
            ),
        },
    )

    resp = _post(client, {"requirement": _card(), "project_name": "WashCell-1"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert any(f["rule_id"] == "AF-04" for f in data["linter_findings"])


# ---------------------------------------------------------------------------
# 4. 空设备需求 → 合理最小 Unit(planner 兜底标准 CM,不报错不空转)
# ---------------------------------------------------------------------------


def test_empty_device_requirement_yields_minimal_unit(client: TestClient) -> None:
    card = _card(
        intent_summary="仅描述节拍约束的空工艺",
        origin_prompt="新建一个空工程,后续再补工艺",
        items=[],
        linked_signals=[],
    )
    resp = _post(client, {"requirement": card, "project_name": "EmptyStation"})
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["blocks_created"] >= 10  # Unit OBs/EmNodes/CallUnit + EM0 + EM1
    software_units = {b.get("software_unit") for b in data["canvas"]["blocks"].values()}
    assert "U1_EmptyStation" in software_units  # planner 兜底 cylActuator+sensor 最小 Unit
    assert any(b["name"] == "Sequence" for b in data["canvas"]["blocks"].values())


# ---------------------------------------------------------------------------
# 5. 生成失败 → 500 可读信息;target_dir 透传不写盘
# ---------------------------------------------------------------------------


def test_endpoint_500_on_generation_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(requirement: Any, project_name: str) -> dict[str, Any]:
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(af_generate_mod, "generate_from_requirement", boom)
    resp = _post(
        client,
        {"requirement": _card(), "project_name": "WashCell-1", "target_dir": "D:/nowhere"},
    )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "AF_GENERATION_FAILED"
    assert "planner exploded" in detail["message"]


def test_wash_project_name() -> None:
    assert af_generate_mod.wash_project_name("WashCell-1") == "WashCell1"
    assert af_generate_mod.wash_project_name("2号产线") == "Project_2"
    assert af_generate_mod.wash_project_name("装箱工位") == "AF_Project"
    assert af_generate_mod.wash_project_name("") == "AF_Project"
