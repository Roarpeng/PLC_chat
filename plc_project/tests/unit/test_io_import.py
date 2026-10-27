"""IO 表导入(契约 docs/24 · A 线)单元 + 集成测试.

覆盖:xlsx 解析(真实 HR001 文件)/ CSV 解析 / CanvasTag 生成 /
canvas 合并(同名不覆盖、blocks 不动)/ API 200 与 400/403/404。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENV", "dev")

from gateway.app.services.plc.io_import import (  # noqa: E402
    IoImportRejected,
    import_io_table,
    io_entries_to_canvas_tags,
    parse_plctags_csv,
    parse_plctags_xlsx,
)
from plc_engine.canvas_model import CanvasBlock, CanvasState, CanvasTag  # noqa: E402

# 真机导出的 IO 表:114 行 = 1 表头 + 113 数据行(sheet "PLC Tags",
# 列 Name/Path/Data Type/Logical Address/Comment + 5 列 HMI 元数据)。
REAL_XLSX = Path(r"C:\Users\vboxuser\Desktop\Project\Robot\HR001\PLCTags.xlsx")
requires_real_xlsx = pytest.mark.skipif(
    not REAL_XLSX.is_file(), reason=f"real HR001 IO table not present: {REAL_XLSX}"
)

CSV_TEXT = (
    "Name,Path,Data Type,Logical Address,Comment\r\n"
    "Start_PB,PLC_IO,Bool,%I0.0,启动按钮\r\n"
    ",PLC_IO,Bool,%I0.1,空名行应被丢弃\r\n"
    "Motor_Cmd,PLC_IO,Bool,%Q0.0,电机命令\r\n"
    "Speed_Set,PLC_IO,Int,%QW10,速度设定\r\n"
)
API_KEY = {"X-API-Key": "ros_ak_test_key"}
IO_IMPORT_URL = "/api/v1/plc/canvas/io/import"


# ---------------------------------------------------------------------------
# 解析层
# ---------------------------------------------------------------------------


@requires_real_xlsx
def test_parse_plctags_xlsx_real_hr001_file() -> None:
    entries = parse_plctags_xlsx(REAL_XLSX)

    assert len(entries) == 113  # 114 行含表头
    first = entries[0]
    assert first["name"] == "IDoor3Unlocked"
    assert first["path"] == "PLC_IO"
    assert first["data_type"] == "Bool"
    assert first["logical_address"] == "%I2.0"
    assert "门锁未锁定" in first["comment"]
    names = [e["name"] for e in entries]
    assert len(set(names)) == len(names)  # 无重名
    assert all(e["logical_address"].startswith("%") for e in entries)
    assert {e["name"]: e["data_type"] for e in entries}["ISp077"] == "Bool"


def test_parse_plctags_csv_text_drops_nameless_rows() -> None:
    entries = parse_plctags_csv(CSV_TEXT)

    assert [e["name"] for e in entries] == ["Start_PB", "Motor_Cmd", "Speed_Set"]
    start = entries[0]
    assert start["data_type"] == "Bool"
    assert start["logical_address"] == "%I0.0"
    assert start["comment"] == "启动按钮"
    assert entries[2]["data_type"] == "Int"


def test_parse_plctags_csv_from_file(tmp_path: Path) -> None:
    csv_file = tmp_path / "PLCTags.csv"
    csv_file.write_bytes(CSV_TEXT.encode("utf-8-sig"))  # TIA/Excel 常带 BOM

    via_path = parse_plctags_csv(str(csv_file))
    via_posix = parse_plctags_csv(csv_file)

    assert [e["name"] for e in via_path] == ["Start_PB", "Motor_Cmd", "Speed_Set"]
    assert via_path == via_posix


def test_parse_plctags_csv_semicolon_delimiter() -> None:
    entries = parse_plctags_csv(
        "Name;Data Type;Logical Address;Comment\nCyl1_Ext;Bool;%I1.0;伸出\n"
    )
    assert entries[0]["name"] == "Cyl1_Ext"
    assert entries[0]["logical_address"] == "%I1.0"


# ---------------------------------------------------------------------------
# 标签生成 + 合并语义
# ---------------------------------------------------------------------------


def test_io_entries_to_canvas_tags_maps_fields_as_draft() -> None:
    entries = parse_plctags_csv(CSV_TEXT)

    tags = io_entries_to_canvas_tags(entries)

    assert set(tags) == {"Start_PB", "Motor_Cmd", "Speed_Set"}
    assert all(isinstance(t, CanvasTag) for t in tags.values())
    assert all(t.status == "draft" for t in tags.values())  # 只有 draft 才回写 TIA
    assert tags["Speed_Set"].data_type == "Int"
    assert tags["Speed_Set"].logical_address == "%QW10"
    assert tags["Start_PB"].comment == "启动按钮"


def test_import_io_table_merge_keeps_existing_tags_and_blocks() -> None:
    canvas = CanvasState(project_name="existing")
    canvas.blocks["FB_Motor"] = CanvasBlock(name="FB_Motor", block_type="FB", number=1)
    canvas.tags["Start_PB"] = CanvasTag(
        name="Start_PB", data_type="Bool", logical_address="%I9.9",
        comment="已有标签", status="synced",
    )

    result = import_io_table(csv_text=CSV_TEXT, canvas=canvas, project_name="merged")

    assert result["tags_created"] == 2  # Motor_Cmd + Speed_Set
    assert result["tags_skipped"] == 1  # Start_PB 已存在
    # 不覆盖:同名标签保持原地址/注释/status
    kept = canvas.tags["Start_PB"]
    assert (kept.logical_address, kept.status, kept.comment) == ("%I9.9", "synced", "已有标签")
    # 新标签 draft,blocks 不动,project_name 以显式参数为准
    assert canvas.tags["Motor_Cmd"].status == "draft"
    assert set(canvas.blocks) == {"FB_Motor"}
    assert canvas.project_name == "merged"
    assert result["tags_total"] == 3
    assert result["canvas"]["tags"]["Motor_Cmd"]["status"] == "draft"


def test_import_io_table_idempotent_second_run_skips_all() -> None:
    first = import_io_table(csv_text=CSV_TEXT, project_name="io_demo")
    canvas = CanvasState.from_dict(first["canvas"])

    second = import_io_table(csv_text=CSV_TEXT, canvas=canvas)

    assert second["tags_created"] == 0
    assert second["tags_skipped"] == 3
    assert second["tags_total"] == 3


def test_import_io_table_reject_codes(tmp_path: Path) -> None:
    with pytest.raises(IoImportRejected) as exc:
        import_io_table()
    assert exc.value.code == "IO_SOURCE_REQUIRED"

    bad_txt = tmp_path / "io.txt"
    bad_txt.write_text("Name,Data Type\nX,Bool\n", encoding="utf-8")
    with pytest.raises(IoImportRejected) as exc:
        import_io_table(source=bad_txt)
    assert exc.value.code == "IO_SOURCE_UNSUPPORTED"

    with pytest.raises(IoImportRejected) as exc:
        import_io_table(csv_text="foo,bar\n1,2\n")
    assert exc.value.code == "IO_TABLE_HEADER_MISSING"

    with pytest.raises(IoImportRejected) as exc:
        import_io_table(csv_text="Name,Data Type,Logical Address\n")
    assert exc.value.code == "IO_NO_ENTRIES"

    bad_xlsx = tmp_path / "broken.xlsx"
    bad_xlsx.write_bytes(b"not-a-zip-xlsx")
    with pytest.raises(IoImportRejected) as exc:
        import_io_table(source=bad_xlsx)
    assert exc.value.code == "IO_XLSX_UNREADABLE"


# ---------------------------------------------------------------------------
# API:POST /api/v1/plc/canvas/io/import
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _make(allowlist: str | Path) -> TestClient:
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
        monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(allowlist))
        monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
        from gateway.app.config import get_settings

        get_settings.cache_clear()
        from gateway.app.main import create_app

        return TestClient(create_app())

    yield _make
    from gateway.app.config import get_settings

    get_settings.cache_clear()


def test_api_io_import_csv_text_200(make_client) -> None:
    with make_client(Path.cwd()) as client:
        resp = client.post(
            IO_IMPORT_URL,
            json={"file_content": CSV_TEXT, "project_name": "io_api"},
            headers=API_KEY,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["tags_created"] == 3
    canvas = data["canvas"]
    assert canvas["project_name"] == "io_api"
    assert canvas["tags"]["Start_PB"] == {
        "name": "Start_PB", "data_type": "Bool",
        "logical_address": "%I0.0", "comment": "启动按钮", "status": "draft",
    }
    assert canvas["blocks"] == {}  # 只写 tags,不动 blocks


@requires_real_xlsx
def test_api_io_import_real_xlsx_200(make_client) -> None:
    with make_client(REAL_XLSX.parent) as client:
        resp = client.post(
            IO_IMPORT_URL,
            json={"file_path": str(REAL_XLSX), "project_name": "HR001"},
            headers=API_KEY,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tags_created"] == 113
    assert data["tags_skipped"] == 0
    tags = data["canvas"]["tags"]
    assert tags["IDoor3Unlocked"]["logical_address"] == "%I2.0"
    assert tags["IDoor3Unlocked"]["status"] == "draft"
    assert "垂直击打门锁未锁定" in tags["IDoor3Unlocked"]["comment"]


def test_api_io_import_merges_into_passed_canvas(make_client) -> None:
    existing_canvas = {
        "project_name": "existing",
        "tags": {
            "Start_PB": {
                "name": "Start_PB", "data_type": "Bool",
                "logical_address": "%I9.9", "comment": "已有", "status": "synced",
            }
        },
    }
    with make_client(Path.cwd()) as client:
        resp = client.post(
            IO_IMPORT_URL,
            json={
                "file_content": CSV_TEXT,
                "project_name": "after_merge",
                "canvas": existing_canvas,
            },
            headers=API_KEY,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tags_created"] == 2
    assert data["tags_skipped"] == 1
    assert data["tags_total"] == 3
    tags = data["canvas"]["tags"]
    assert tags["Start_PB"]["logical_address"] == "%I9.9"  # 未被覆盖
    assert tags["Start_PB"]["status"] == "synced"
    assert tags["Motor_Cmd"]["status"] == "draft"


def test_api_io_import_400_403_404(make_client, tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        # 400:既无 file_path 也无 file_content
        empty = client.post(IO_IMPORT_URL, json={}, headers=API_KEY)
        assert empty.status_code == 400
        assert empty.json()["detail"]["code"] == "IO_SOURCE_REQUIRED"

        # 400:CSV 文本没有可识别表头
        headerless = client.post(
            IO_IMPORT_URL, json={"file_content": "foo,bar\n1,2\n"}, headers=API_KEY
        )
        assert headerless.status_code == 400
        assert headerless.json()["detail"]["code"] == "IO_TABLE_HEADER_MISSING"

        # 400:表头可识别但零数据行
        header_only = client.post(
            IO_IMPORT_URL,
            json={"file_content": "Name,Data Type,Logical Address\n"},
            headers=API_KEY,
        )
        assert header_only.status_code == 400
        assert header_only.json()["detail"]["code"] == "IO_NO_ENTRIES"

        # 400:allowlist 内但不支持的扩展名
        bad_suffix = tmp_path / "io_table.txt"
        bad_suffix.write_text(CSV_TEXT, encoding="utf-8")
        unsupported = client.post(
            IO_IMPORT_URL, json={"file_path": str(bad_suffix)}, headers=API_KEY
        )
        assert unsupported.status_code == 400
        assert unsupported.json()["detail"]["code"] == "IO_SOURCE_UNSUPPORTED"

        # 404:allowlist 内但路径不存在
        missing = client.post(
            IO_IMPORT_URL, json={"file_path": str(tmp_path / "nope.xlsx")}, headers=API_KEY
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "PLC_PATH_NOT_FOUND"

        # 403:allowlist 外且真实存在的服务器路径(paths.py 先查存在性再查沙箱)
        denied = client.post(
            IO_IMPORT_URL, json={"file_path": str(Path(__file__).resolve())}, headers=API_KEY
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "PLC_PATH_DENIED"
