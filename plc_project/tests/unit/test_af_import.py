"""导入自动 AF 化(角色覆盖层)单元测试——契约 docs/23 §0 / §2(并行线 I)。

主断言对象是**物理冻结铁律**:``apply_af_overlay`` 只加 ``af_role`` 与
pending 提示文案,块数 / scl_body / status / 接口 / 网络 / 标签逐字节不变;
DB/UDT/OB/安全块 role=global/safety 永不转换也永不 pending;无法判定的块
诚实进入 pending;PCEC 事务 applied;分析异常不阻塞导入。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from gateway.app.services.plc import af_import
from gateway.app.services.plc.canvas_import import import_canvas_from_path
from plc_engine.canvas_model import (
    CanvasBlock,
    CanvasState,
    CanvasTag,
    CanvasVariable,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
HR001_EXPORT = Path(
    r"C:\Users\vboxuser\Desktop\Project\Code\PLC_chat\PLC_Openness_data\hr001\export"
)

_CHANGE_ID_RE = re.compile(r"^chg-[0-9a-f]{12}$")


def _mixed_canvas() -> CanvasState:
    """5-8 块混合画布:步序 FB / 设备 FB / DB / F 安全名块 / 未知块 + 一个 OB。"""
    canvas = CanvasState(project_name="MixedDemo")

    canvas.blocks["FB1060_AutoStep"] = CanvasBlock(
        name="FB1060_AutoStep",
        block_type="FB",
        number=60,
        scl_body="CASE #Step OF\n10: #Done := TRUE;\nEND_CASE;",
        status="synced",
    )
    canvas.blocks["FB1081_ValveCall"] = CanvasBlock(
        name="FB1081_ValveCall",
        block_type="FB",
        number=81,
        interface=[CanvasVariable(name="CylWork", data_type="Bool", section="VAR_OUTPUT")],
        scl_body='"Q_Cyl_Extend" := TRUE;',
        status="synced",
    )
    canvas.blocks["OB1Main"] = CanvasBlock(
        name="OB1Main",
        block_type="OB",
        number=1,
        scl_body='"FB1060_AutoStep_DB"(Step := 10);',
        status="synced",
    )
    canvas.blocks["DB10_Data"] = CanvasBlock(
        name="DB10_Data",
        block_type="DB",
        number=10,
        interface=[CanvasVariable(name="Recipe", data_type="Int", section="VAR")],
        scl_body="Recipe := 1;",
        status="synced",
    )
    canvas.blocks["F_GuardDoor"] = CanvasBlock(
        name="F_GuardDoor",
        block_type="FB",
        number=5002,
        scl_body="// safety interlock",
        status="synced",
    )
    canvas.blocks["FB999_Mystery"] = CanvasBlock(
        name="FB999_Mystery",
        block_type="FB",
        number=999,
        scl_body="#a := #b + 1;",
        status="synced",
    )
    canvas.tags["Q_Cyl_Extend"] = CanvasTag(
        name="Q_Cyl_Extend", data_type="Bool", logical_address="%Q0.0", comment="cyl extend 电磁阀"
    )
    return canvas


# ---------------------------------------------------------------- 角色判定 --


def test_analyze_mixed_canvas_roles() -> None:
    """角色判定规则:DB/OB→global、F/安全名→safety、mapper 结论→unit/em/cm、未知→pending。"""
    report = af_import.analyze_import(_mixed_canvas())
    roles = report["roles"]

    assert set(roles) == set(_mixed_canvas().blocks)
    assert roles["FB1060_AutoStep"] == "em"       # 步序源块(mapper SEQUENCE 检测)
    assert roles["FB1081_ValveCall"] == "cm"      # 设备集线(name 含 valve → CM Hub)
    assert roles["OB1Main"] == "global"           # OB 编号与调用顺序冻结
    assert roles["DB10_Data"] == "global"         # DB 布局与偏移冻结,永不转换
    assert roles["F_GuardDoor"] == "safety"       # F/安全名块冻结,永不转换
    assert roles["FB999_Mystery"] == "unknown"    # 无法判定 → unknown

    pending_blocks = {p["block"] for p in report["pending"]}
    assert pending_blocks == {"FB999_Mystery"}
    # DB / safety / OB 永不 pending(物理冻结,无需人工确认转换)
    assert not pending_blocks & {"DB10_Data", "F_GuardDoor", "OB1Main"}
    reason = report["pending"][0]["reason"]
    assert reason and len(reason) >= 8  # 原因诚实非空

    assert report["blocks_total"] == 6
    assert report["roles_count"] == 5
    assert report["pending_count"] == 1
    assert report["conformant"] is False
    assert report["coverage"] == pytest.approx(round(5 / 6 * 100, 2))
    assert report["frozen"] == {"global": 2, "safety": 1}


def test_analyze_empty_canvas_vacuously_conformant() -> None:
    report = af_import.analyze_import(CanvasState(project_name="Empty"))
    assert report["conformant"] is True
    assert report["pending"] == []
    assert report["coverage"] == 100.0
    assert report["roles"] == {}


# ------------------------------------------------------------ 物理冻结铁律 --


def test_apply_af_overlay_physical_freeze() -> None:
    """overlay 只加 af_role 与 pending 文案;其余字段(含 scl_body)逐字节不变。"""
    canvas = _mixed_canvas()
    frozen_snapshot = copy.deepcopy(canvas.to_dict())

    overlaid = af_import.apply_af_overlay(canvas, af_import.analyze_import(canvas))

    assert overlaid is canvas
    snapshot = frozen_snapshot["blocks"]
    assert set(overlaid.blocks) == set(snapshot), "块数与块名不变"

    for key, before in snapshot.items():
        after = overlaid.blocks[key]
        assert after.scl_body == before["scl_body"], f"{key}.scl_body 必须逐字节不变"
        assert after.status == before["status"], f"{key}.status 不变"
        assert after.number == before["number"]
        assert after.comment == before["comment"]
        assert after.block_type == before["block_type"]
        assert [v.__dict__ for v in after.interface] == before["interface"]
        assert [n.__dict__ for n in after.networks] == before["networks"]

    # 标签表不动
    assert {t.name: (t.data_type, t.logical_address, t.comment) for t in overlaid.tags.values()} == {
        t["name"]: (t["data_type"], t["logical_address"], t["comment"])
        for t in frozen_snapshot["tags"].values()
    }

    # af_role 标注
    assert overlaid.blocks["FB1060_AutoStep"].af_role == "em"
    assert overlaid.blocks["FB1081_ValveCall"].af_role == "cm"
    assert overlaid.blocks["OB1Main"].af_role == "global"
    assert overlaid.blocks["DB10_Data"].af_role == "global"
    assert overlaid.blocks["F_GuardDoor"].af_role == "safety"
    assert overlaid.blocks["FB999_Mystery"].af_role == "af_pending_manual"

    # pending 文案:仅 pending 块 errors 追加提示,status 原样;其余块 errors 不动
    mystery = overlaid.blocks["FB999_Mystery"]
    assert mystery.errors and mystery.errors[0].startswith("AF 转换待人工确认:")
    assert mystery.status == "synced"
    for key, block in overlaid.blocks.items():
        if key != "FB999_Mystery":
            assert block.errors == snapshot[key]["errors"], f"{key} 不应有任何错误文案"


def test_apply_af_overlay_idempotent() -> None:
    """重复 overlay 不重复追加文案、不二次改动物理内容。"""
    canvas = _mixed_canvas()
    report = af_import.analyze_import(canvas)
    af_import.apply_af_overlay(canvas, report)
    once = copy.deepcopy(canvas.to_dict())
    af_import.apply_af_overlay(canvas, report)
    assert canvas.to_dict() == once


# ---------------------------------------------------------------- 报告落盘 --


def test_write_report_and_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    report = af_import.analyze_import(_mixed_canvas())

    path = af_import.write_report("Mixed Demo!", report)
    assert path.parent == tmp_path / "af_reports"
    assert path.name.startswith("Mixed_Demo-") and path.name.endswith(".json")

    loaded = af_import.latest_report("Mixed Demo!")
    assert loaded is not None and loaded["roles"] == report["roles"]
    # 空项目名参数取任意最新
    assert af_import.latest_report("") is not None
    assert af_import.latest_report("NoSuchProject") is None


# ---------------------------------------------------------------- PCEC 留痕 --


def test_record_pcec_transaction_applied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    canvas = _mixed_canvas()
    report = af_import.analyze_import(canvas)

    change_id = af_import.record_pcec(canvas, report, None)
    assert change_id and _CHANGE_ID_RE.match(change_id)

    change_dir = tmp_path / "changes" / change_id
    meta = json.loads((change_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["kind"] == "af_import"
    assert meta["status"] == "applied"

    change = json.loads((change_dir / "change.json").read_text(encoding="utf-8"))
    assert change["approval"]["reviewer"] == "auto_import"
    assert change["verification"]["v0_parsed"] == "pass"
    assert change["verification"]["v1_static"] == "pass"
    events = [e["event"] for e in change["events"]]
    assert "auto_import" in events and "af_role_overlay_applied" in events
    # touched = 已标注块(明确角色),pending 块不计入
    assert set(change["touched_blocks"]) == {
        k for k, r in report["roles"].items() if r != "unknown"
    }


def test_record_pcec_with_baseline_and_failure_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    canvas = _mixed_canvas()
    report = af_import.analyze_import(canvas)

    apxx = tmp_path / "Demo.ap19"
    apxx.write_bytes(b"tia-project")
    change_id = af_import.record_pcec(canvas, report, apxx)
    assert change_id
    change = json.loads(
        (tmp_path / "changes" / change_id / "change.json").read_text(encoding="utf-8")
    )
    assert change["project_baseline"]["project_hash"].startswith("sha256:")
    assert change["project_baseline"]["tia_version"] == "V19"

    # 坏工程路径 → 只 warning 返回 None,绝不抛
    assert af_import.record_pcec(canvas, report, tmp_path / "missing.ap19") is None


# ---------------------------------------------------------------- 导入接入 --


def test_import_af_analysis_summary_and_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地夹具导入:af_analysis 摘要在响应 data 上,DB/OB→global 且不 pending。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    data = import_canvas_from_path(FIXTURE_DIR, project_name="fixture_af")

    assert data["blocks_parsed"] >= 3
    af = data["af_analysis"]
    assert set(af) == {"conformant", "roles_count", "pending_count"}
    assert isinstance(af["conformant"], bool)
    assert af["roles_count"] >= 1
    assert af["pending_count"] >= 0
    assert af["roles_count"] + af["pending_count"] == len(data["canvas"]["blocks"])

    blocks = data["canvas"]["blocks"]
    assert blocks["MotorInst"]["af_role"] == "global"  # DB 型块
    assert blocks["Main"]["af_role"] == "global"       # OB 型块

    # 报告已落盘且可查最新
    report = af_import.latest_report("fixture_af")
    assert report is not None and report["project_name"] == "fixture_af"
    # PCEC 事务 applied
    metas = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (tmp_path / "changes").glob("*/meta.json")
    ]
    assert any(m["kind"] == "af_import" and m["status"] == "applied" for m in metas)


def test_import_af_failure_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """导入分析异常:导入仍成功,af_analysis 兜底 {conformant: null, ...}。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))

    def _boom(canvas: CanvasState) -> dict:
        raise RuntimeError("analyzer exploded")

    monkeypatch.setattr(af_import, "analyze_import", _boom)
    data = import_canvas_from_path(FIXTURE_DIR, project_name="fixture_af_down")

    assert data["blocks_parsed"] >= 3, "导入绝不被 AF 分析失败阻塞"
    assert data["af_analysis"] == {"conformant": None, "roles_count": 0, "pending_count": 0}
    # 无报告、无事务(分析都没成,不得伪造留痕)
    assert af_import.latest_report("fixture_af_down") is None
    assert not list((tmp_path / "changes").glob("*/meta.json"))


@pytest.mark.skipif(not HR001_EXPORT.exists(), reason="HR001 真机导出不在本机")
def test_hr001_real_import_roles_and_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HR001 真实夹具:roles 覆盖/DB 与 safety 不动/pending 诚实/二次 overlay 逐字节不变。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    data = import_canvas_from_path(HR001_EXPORT, project_name="hr001")

    assert data["blocks_parsed"] >= 50
    af = data["af_analysis"]
    assert af["conformant"] is False  # 47+ 未知块诚实 pending
    assert af["roles_count"] >= 30
    assert af["pending_count"] >= 10
    assert af["roles_count"] + af["pending_count"] == len(data["canvas"]["blocks"])

    roles = {}
    for key, block in data["canvas"]["blocks"].items():
        roles[key] = block["af_role"]
    assert roles["FB1060_AutoStep"] == "em"          # 主步序
    assert roles["FB1061_RobotAutoStep"] == "em"
    assert roles["FB1001_SysMode"] == "unit"         # 模式控制
    assert roles["FB1081_ValveCall"] == "cm"         # 阀/气缸设备集线
    assert roles["FB5002_SafetyDoorV1"] == "safety"  # 安全门 F 库块
    assert roles["DB1060_AutoStep"] == "global"      # DB 布局冻结(即使名字带 AutoStep)
    assert roles["OB1Main"] == "global"              # OB 调用顺序冻结

    # 全量不变量:DB/OB/UDT 型块一律 global 且永不 pending;safety 块永不 pending
    report = af_import.latest_report("hr001")
    assert report is not None
    pending_blocks = {p["block"] for p in report["pending"]}
    for key, block in data["canvas"]["blocks"].items():
        if block["block_type"] in {"DB", "UDT", "OB"}:
            assert roles[key] == "global"
            assert key not in pending_blocks
        if roles[key] == "safety":
            assert key not in pending_blocks
        if key in pending_blocks:
            assert roles[key] == "af_pending_manual"  # pending 诚实标注
    assert all(p["reason"] for p in report["pending"])
    # 已标注块在报告 roles 中均为明确角色
    definitive = {k for k, r in report["roles"].items() if r != "unknown"}
    assert len(definitive) == af["roles_count"]

    # 物理冻结证明:对已 overlay 的画布再分析+overlay 一遍,除 af_role/errors 外逐字节不变
    before = copy.deepcopy(data["canvas"])
    state = CanvasState.from_dict(data["canvas"])
    second_report = af_import.analyze_import(state)
    state = af_import.apply_af_overlay(state, second_report)
    after = state.to_dict()
    assert set(after["blocks"]) == set(before["blocks"])
    for key, b0 in before["blocks"].items():
        b1 = after["blocks"][key]
        assert b1["scl_body"] == b0["scl_body"], f"{key}.scl_body 必须逐字节不变"
        assert b1["status"] == b0["status"]
        assert b1["interface"] == b0["interface"]
        assert b1["networks"] == b0["networks"]
        assert b1["number"] == b0["number"]
    assert after["tags"] == before["tags"]
    assert len(after["revisions"]) == len(before["revisions"])

    # PCEC 事务样例存在
    metas = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (tmp_path / "changes").glob("*/meta.json")
    ]
    assert any(m["kind"] == "af_import" and m["status"] == "applied" for m in metas)


# ---------------------------------------------------------------- API 路由 --


def test_af_report_latest_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from gateway.app.main import create_app

    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    client = TestClient(create_app())

    r404 = client.get("/api/v1/plc/canvas/af/report/latest", params={"project": "ghost"})
    assert r404.status_code == 404
    assert r404.json()["detail"]["code"] == "AF_REPORT_NOT_FOUND"

    report = af_import.analyze_import(_mixed_canvas())
    af_import.write_report("RouterDemo", report)

    ok = client.get("/api/v1/plc/canvas/af/report/latest", params={"project": "RouterDemo"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["data"]["roles"]["DB10_Data"] == "global"
    assert body["data"]["frozen"] == {"global": 2, "safety": 1}
