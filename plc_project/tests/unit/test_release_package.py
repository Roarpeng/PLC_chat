"""交付包生成器单测：zip 内容 / 诚实收据 / IO 矩阵字段自适应 / 文件名净化。"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from gateway.app.services.plc import release_package as rpkg
from plc_engine.canvas_model import CanvasBlock, CanvasState, create_empty_canvas


def _canvas() -> CanvasState:
    """小画布：既有默认块 + 一个含非法文件名字符的块（考验净化）。"""
    canvas = create_empty_canvas("DemoLine")
    canvas.blocks["A/B::C"] = CanvasBlock(
        name="A/B::C", block_type="FB", scl_body="// demo block with odd name"
    )
    return canvas


def _report() -> dict:
    return {
        "status": "success",
        "target_unit_name": "U1_DemoLine",
        "af_blocks_created": ["U1_DemoLine_EM1"],
        "pending_blocks": ["MotorCtrl"],
        "degraded": False,
        "degrade_reasons": [],
        "io_retention": {
            "total_ios": 2,
            "retained_ios": 2,
            "percentage": 100.0,
            "details": [
                {
                    "address": "%I0.0",
                    "tag_name": "Start_PB",
                    "data_type": "Bool",
                    "cm_name": "Cyl",
                    "cm_type": "CM",
                    "cm_field": "open",
                    "em_name": "EM1",
                    "fallback": False,
                },
                # 字段自适应：第二行带引擎新字段 zz_extra
                {"address": "%Q0.0", "tag_name": "Motor_Contactor", "zz_extra": "x"},
            ],
        },
    }


def _build(tmp_path: Path, compile_info=None) -> dict:
    return rpkg.build_release_package(
        _canvas(),
        _report(),
        project_name="DemoLine",
        compile_info=compile_info,
        out_dir=tmp_path,
    )


def _read_zip_member(zip_path: str | Path, name: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        # utf-8-sig：剥掉 CSV 的 Excel BOM，其余成员无 BOM 时等价 utf-8
        return zf.read(name).decode("utf-8-sig")


def test_package_zip_members_and_layout(tmp_path: Path) -> None:
    """zip 成员齐全：SCL 按块分文件（文件名=净化后的块名）+ 四个固定成员。"""
    pkg = _build(tmp_path)
    zip_path = Path(pkg["zip_path"])
    assert zip_path.is_file()
    assert zip_path.parent == tmp_path  # 只写给定目录，无硬编码路径
    assert pkg["size_bytes"] == zip_path.stat().st_size

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "refactored_scl_sources/MotorCtrl.scl" in names
    assert "refactored_scl_sources/MainDB.scl" in names
    assert "refactored_scl_sources/A_B_C.scl" in names  # A/B::C → A_B_C.scl
    for member in ("refactor_report.json", "io_retention_matrix.csv", "compile_receipt.json", "README.md"):
        assert member in names
    # file_count = zip 内文件数
    assert pkg["file_count"] == len(names)

    # SCL 文件内容 = get_full_scl 渲染结果
    scl = _read_zip_member(zip_path, "refactored_scl_sources/MotorCtrl.scl")
    assert "FUNCTION_BLOCK" in scl

    # 报告原样透传（含引擎新字段）
    report = json.loads(_read_zip_member(zip_path, "refactor_report.json"))
    assert report["pending_blocks"] == ["MotorCtrl"]
    assert report["io_retention"]["details"][1]["zz_extra"] == "x"


def test_io_matrix_csv_field_adaptive(tmp_path: Path) -> None:
    """io_retention_matrix.csv：字段随 detail 行自适应（含 zz_extra），逐行导出。"""
    pkg = _build(tmp_path)
    text = _read_zip_member(pkg["zip_path"], "io_retention_matrix.csv")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[0]["address"] == "%I0.0"
    assert rows[0]["cm_field"] == "open"
    assert rows[1]["zz_extra"] == "x"


def test_io_matrix_empty_details_still_valid_csv(tmp_path: Path) -> None:
    """无 io_retention.details：产出带兜底表头的空 CSV（成员完整、合法）。"""
    report = _report()
    report["io_retention"]["details"] = []
    pkg = rpkg.build_release_package(_canvas(), report, project_name="DemoLine", out_dir=tmp_path)
    text = _read_zip_member(pkg["zip_path"], "io_retention_matrix.csv")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows == []
    assert "address" in text  # 兜底表头仍在


def test_receipt_honest_when_not_compiled(tmp_path: Path) -> None:
    """诚实收据：没编译 → {"compiled": false, "reason": ...}，绝不伪造 0 错误。"""
    pkg = _build(tmp_path, compile_info=None)
    receipt = json.loads(_read_zip_member(pkg["zip_path"], "compile_receipt.json"))
    assert receipt["compiled"] is False
    assert receipt.get("reason")
    # 未编译时不得出现可被误读为「通过」的字段
    assert "errors" not in receipt
    assert "ok" not in receipt
    assert "0 错误" not in json.dumps(receipt, ensure_ascii=False)

    # skipped_reason 透传为 reason
    pkg2 = _build(
        tmp_path,
        compile_info={"compiled": False, "skipped_reason": "本机无 TIA Openness 环境", "errors": []},
    )
    receipt2 = json.loads(_read_zip_member(pkg2["zip_path"], "compile_receipt.json"))
    assert receipt2["compiled"] is False
    assert receipt2["reason"] == "本机无 TIA Openness 环境"


def test_receipt_compiled_with_errors(tmp_path: Path) -> None:
    """编译跑过且有错误：ok=false、错误清单/警告计数如实落收据。"""
    pkg = _build(
        tmp_path,
        compile_info={
            "compiled": True,
            "errors": ["块 [MotorCtrl] 行 4 未定义变量", "块 [MainDB] 接口不一致"],
            "warnings_count": 3,
        },
    )
    receipt = json.loads(_read_zip_member(pkg["zip_path"], "compile_receipt.json"))
    assert receipt["compiled"] is True
    assert receipt["ok"] is False
    assert receipt["error_count"] == 2
    assert receipt["errors"] == ["块 [MotorCtrl] 行 4 未定义变量", "块 [MainDB] 接口不一致"]
    assert receipt["warnings_count"] == 3
    assert receipt["mode"] == "temp_copy"


def test_receipt_compiled_clean(tmp_path: Path) -> None:
    pkg = _build(tmp_path, compile_info={"compiled": True, "errors": [], "warnings_count": 1})
    receipt = json.loads(_read_zip_member(pkg["zip_path"], "compile_receipt.json"))
    assert receipt == {
        "compiled": True,
        "ok": True,
        "error_count": 0,
        "errors": [],
        "warnings_count": 1,
        "inconsistent_blocks": [],
        "mode": "temp_copy",
        "generated_at": receipt["generated_at"],
    }


def test_readme_generated_content(tmp_path: Path) -> None:
    """README：工程名/块数/pending/degraded/编译状态/生成时间。"""
    pkg = _build(tmp_path, compile_info=None)
    readme = _read_zip_member(pkg["zip_path"], "README.md")
    assert "DemoLine" in readme
    assert "U1_DemoLine" in readme
    assert "待人工确认（pending）：1" in readme
    assert "降级（degraded）：否" in readme
    assert "编译验证：未执行" in readme
    assert "生成时间：" in readme


def test_readme_counts_blocks(tmp_path: Path) -> None:
    """README 块数 = 画布块数（create_empty_canvas 2 块 + 追加 1 块 = 3）。"""
    pkg = _build(tmp_path)
    readme = _read_zip_member(pkg["zip_path"], "README.md")
    assert f"画布块数：{len(_canvas().blocks)}" in readme


def test_one_liner_description() -> None:
    """一句话交付文案（ChatDock 展示用）。"""
    text = rpkg.describe_package_one_liner(
        {"file_count": 7, "size_bytes": 2048, "zip_path": "x/DemoLine.zip"}, project_name="DemoLine"
    )
    assert "DemoLine" in text and "7 个文件" in text


def test_build_compile_receipt_factory() -> None:
    """收据工厂独立可测：None / 缺省 dict / 编译错误形态。"""
    assert rpkg.build_compile_receipt(None)["compiled"] is False
    assert rpkg.build_compile_receipt({})["compiled"] is False
    ok = rpkg.build_compile_receipt({"compiled": True, "errors": [], "warnings_count": 0})
    assert ok["ok"] is True
