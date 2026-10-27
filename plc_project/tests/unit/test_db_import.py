"""Unit tests for SCL DATA_BLOCK text -> canvas DB block import (docs/24 B 线)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENV", "dev")

# 真实工程文件：Send/Recv/Para 三层嵌套 Struct、172 个成员、Array/注释/初始赋值。
REAL_DB = Path(
    r"C:\Users\vboxuser\Desktop\Project\Robot\HR001\DATA_BLOCK DB1900_Communication_PC.txt"
)
requires_real_db = pytest.mark.skipif(
    not REAL_DB.exists(), reason="真实 DB1900 导出文件不在本机"
)

MIX_DB = """DATA_BLOCK "DB10_Mix"
{ S7_Optimized_Access := 'TRUE' }
VERSION : 0.1
   STRUCT
      Count : Int;   // 计数
      Names : Array[1..3] of String[20];
      Inner : Struct
         Flag : Bool := TRUE;
         Level : Real;
      END_STRUCT;
   END_STRUCT;

BEGIN
   Count := 7;
   Inner.Level := 1.5;
END_DATA_BLOCK
"""

TINY_DB = """DATA_BLOCK "DB11_Tiny"
VERSION : 0.1
   STRUCT
      Ok : Bool;   // 就绪
   END_STRUCT;
BEGIN
   Ok := TRUE;
END_DATA_BLOCK
"""


def _vars(parsed: dict) -> dict[str, dict]:
    return {v["name"]: v for v in parsed["interface"]}


# ---------------------------------------------------------------- service 层

def test_parse_real_db1900_full() -> None:
    from gateway.app.services.plc.db_import import parse_db_scl, read_db_text

    parsed = parse_db_scl(read_db_text(REAL_DB))
    assert parsed["name"] == "DB1900_Communication_PC"
    # Send 66 + Recv 60 + Para 46 个叶子成员（Struct 容器本身不占位）
    assert len(parsed["interface"]) == 172

    variables = _vars(parsed)
    assert variables["Send.Heart"]["data_type"] == "Bool"
    assert variables["Send.Heart"]["comment"] == "心跳"
    assert variables["Send.EmmMode"]["comment"] == "急停模式"
    assert variables["Send.Spare05"]["comment"] == ""
    assert variables["Send.Spare"]["data_type"] == "Array[0..21] of Byte"
    assert variables["Recv.RobotPrigNo"]["data_type"] == "Byte"
    assert variables["Recv.RobotPrigNo"]["comment"] == "输入程序号"
    assert variables["Para.RestHours"]["data_type"] == "DInt"
    assert variables["Para.Auto_Force"]["data_type"] == "Array[1..200] of Real"
    assert variables["Para.Auto_Force"]["comment"] == "曲线力"
    assert variables["Para.ScrLen"]["data_type"] == "Real"
    # 嵌套 → 点路径；全部成员 section 固定 VAR
    assert all(v["name"].count(".") == 1 for v in parsed["interface"])
    assert all(v["section"] == "VAR" for v in parsed["interface"])

    # BEGIN 段：95 条赋值全部捕获，数组元素按原路径记录
    assert len(parsed["initial_assignments"]) == 95
    assert parsed["initial_assignments"]["Send.Z01ExtPos"] == "TRUE"
    assert parsed["initial_assignments"]["Para.ZeroPos"] == "1011.0"
    assert parsed["initial_assignments"]["Send.Spare[10]"] == "16#00"
    # 命中叶子成员的赋值回填 initial_value（不覆盖、数组元素只进 assignments）
    assert variables["Send.Z01ExtPos"]["initial_value"] == "TRUE"
    assert variables["Send.RobotProgNo"]["initial_value"] == "16#00"
    assert variables["Para.ScrLen"]["initial_value"] == "120.0"
    assert variables["Recv.DownSlabHeight"]["initial_value"] == "400"
    assert variables["Send.Spare"]["initial_value"] == ""


def test_parse_db_scl_synthetic_nested_inline_init() -> None:
    from gateway.app.services.plc.db_import import parse_db_scl

    parsed = parse_db_scl(MIX_DB)
    assert parsed["name"] == "DB10_Mix"
    assert [v["name"] for v in parsed["interface"]] == [
        "Count",
        "Names",
        "Inner.Flag",
        "Inner.Level",
    ]
    variables = _vars(parsed)
    assert variables["Names"]["data_type"] == "Array[1..3] of String[20]"
    assert variables["Count"]["comment"] == "计数"
    # 声明区行内初始值 + BEGIN 段赋值都进入 initial_value
    assert variables["Inner.Flag"]["initial_value"] == "TRUE"
    assert variables["Count"]["initial_value"] == "7"
    assert variables["Inner.Level"]["initial_value"] == "1.5"
    assert parsed["initial_assignments"] == {"Count": "7", "Inner.Level": "1.5"}


def test_parse_db_scl_rejects_non_db_text() -> None:
    from gateway.app.services.plc.db_import import DBImportRejected, parse_db_scl

    with pytest.raises(DBImportRejected) as exc_info:
        parse_db_scl("FUNCTION_BLOCK \"NoDb\"\nBEGIN\nEND_FUNCTION_BLOCK")
    assert exc_info.value.code == "DB_PARSE_FAILED"


def test_db_to_canvas_block_roundtrip() -> None:
    from gateway.app.services.plc.db_import import db_to_canvas_block, read_db_text, parse_db_scl
    from plc_engine.canvas_model import CanvasState

    block = db_to_canvas_block(parse_db_scl(read_db_text(REAL_DB)))
    assert block.name == "DB1900_Communication_PC"
    assert block.block_type == "DB"
    assert block.language == "DB"
    assert block.number == 1900
    assert block.status == "draft"
    assert len(block.interface) == 172
    assert block.interface[0].name == "Send.Heart"
    assert block.interface[0].section == "VAR"
    # scl_body 保留原始文本
    assert block.scl_body.startswith('DATA_BLOCK "DB1900_Communication_PC"')
    assert "Send.Spare[10] := 16#00;" in block.scl_body

    # 画布 payload 往返（/canvas/patch 等端点消费同一结构）
    from dataclasses import asdict

    state = CanvasState.from_dict(
        {"project_name": "P", "blocks": {block.name: asdict(block)}}
    )
    restored = state.blocks["DB1900_Communication_PC"]
    assert restored.block_type == "DB"
    assert restored.language == "DB"
    assert len(restored.interface) == 172
    assert restored.interface[0].name == "Send.Heart"


def test_multi_db_merge_single_text_and_canvas_carryover() -> None:
    from gateway.app.services.plc.db_import import import_db_text, parse_db_scl_all
    from plc_engine.canvas_model import CanvasState

    # 一段文本含多个 DATA_BLOCK → 多个 DB 块
    combined = f"{MIX_DB}\n\n{TINY_DB}"
    assert [p["name"] for p in parse_db_scl_all(combined)] == ["DB10_Mix", "DB11_Tiny"]
    first = import_db_text(combined, project_name="MergeProj")
    assert first["blocks_created"] == 2
    assert set(first["canvas"]["blocks"]) == {"DB10_Mix", "DB11_Tiny"}
    assert first["canvas"]["project_name"] == "MergeProj"

    # 多次调用合并：把上次 canvas 传回 → 旧块保留，新块追加
    state = CanvasState.from_dict(first["canvas"])
    second = import_db_text(REAL_DB.read_text(encoding="utf-8-sig"), canvas=state)
    assert second["blocks_created"] == 1
    assert set(second["canvas"]["blocks"]) == {"DB10_Mix", "DB11_Tiny", "DB1900_Communication_PC"}
    assert second["canvas"]["project_name"] == "MergeProj"
    numbers = {b["number"] for b in second["canvas"]["blocks"].values()}
    assert numbers == {10, 11, 1900}


# ------------------------------------------------------------------- API 层

@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
    if REAL_DB.exists():
        monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(REAL_DB.parent.resolve()))
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@requires_real_db
def test_api_db_import_with_db_text(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plc/canvas/db/import",
        json={"db_text": REAL_DB.read_text(encoding="utf-8-sig"), "project_name": "HR001"},
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["blocks_created"] == 1
    canvas = payload["canvas"]
    assert canvas["project_name"] == "HR001"
    block = canvas["blocks"]["DB1900_Communication_PC"]
    assert block["block_type"] == "DB"
    assert block["language"] == "DB"
    assert block["status"] == "draft"
    assert len(block["interface"]) == 172
    assert block["interface"][0]["name"] == "Send.Heart"
    assert block["interface"][0]["comment"] == "心跳"


@requires_real_db
def test_api_db_import_with_file_path(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plc/canvas/db/import",
        json={"file_path": str(REAL_DB), "project_name": "HR001"},
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["blocks_created"] == 1
    block = payload["canvas"]["blocks"]["DB1900_Communication_PC"]
    assert len(block["interface"]) == 172
    assert block["scl_body"].startswith('DATA_BLOCK "DB1900_Communication_PC"')


def test_api_db_import_merge_multiple_calls(client: TestClient) -> None:
    first = client.post(
        "/api/v1/plc/canvas/db/import", json={"db_text": MIX_DB, "project_name": "MergeAPI"}
    )
    assert first.status_code == 200
    canvas = first.json()["data"]["canvas"]

    second = client.post(
        "/api/v1/plc/canvas/db/import",
        json={"db_text": TINY_DB, "canvas": canvas},
    )
    assert second.status_code == 200
    payload = second.json()["data"]
    assert payload["blocks_created"] == 1
    assert set(payload["canvas"]["blocks"]) == {"DB10_Mix", "DB11_Tiny"}
    assert payload["canvas"]["project_name"] == "MergeAPI"


def test_api_db_import_validation_errors(client: TestClient) -> None:
    # 既无 db_text 也无 file_path → 400
    empty = client.post("/api/v1/plc/canvas/db/import", json={"project_name": "X"})
    assert empty.status_code == 400
    assert empty.json()["detail"]["code"] == "DB_TEXT_REQUIRED"

    # 非 DB 文本 → 400 DB_PARSE_FAILED
    garbage = client.post(
        "/api/v1/plc/canvas/db/import", json={"db_text": "hello world"}
    )
    assert garbage.status_code == 400
    assert garbage.json()["detail"]["code"] == "DB_PARSE_FAILED"

    # file_path 不存在 → 404
    missing = client.post(
        "/api/v1/plc/canvas/db/import",
        json={"file_path": r"C:\nonexistent\db1900.scl"},
    )
    assert missing.status_code == 404
