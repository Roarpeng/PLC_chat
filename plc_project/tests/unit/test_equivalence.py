"""行为等价性核对报告单测：IO 判定 / 逐地址 dropped / 语句计数 / 口径 caveats /
release_package 可选集成（缺省不回归）。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from gateway.app.services.plc import equivalence as eq
from gateway.app.services.plc import release_package as rpkg
from plc_engine.canvas_model import CanvasBlock, CanvasState, create_empty_canvas

# ------------------------------------------------------------------ 夹具 --


def _before_canvas() -> dict:
    """重构前画布：3 个 legacy 块（MotorCtrl / PumpCtrl / SymbolOnly）。"""
    return {
        "project_name": "DemoLine",
        "blocks": {
            # 非角色块（重构前画布常态）：AT 声明区地址 + 赋值 + 调用混合
            "MotorCtrl": {
                "name": "MotorCtrl",
                "block_type": "FB",
                "af_role": "",
                "scl_body": (
                    'FUNCTION_BLOCK "MotorCtrl"\n'
                    "VAR_INPUT\n"
                    "  bStart AT %I0.0 : BOOL;\n"
                    "END_VAR\n"
                    "VAR_OUTPUT\n"
                    "  bRun AT %Q4.1 : BOOL;\n"
                    "END_VAR\n"
                    "BEGIN\n"
                    '  #tmp := "Start_PB";\n'
                    "  IF #bStart THEN\n"
                    "    #bRun := TRUE;\n"
                    "  END_IF;\n"
                    '  "Cyl"(open := #bStart);\n'
                    "END_FUNCTION_BLOCK\n"
                ),
                "networks": [],
            },
            # 显式 legacy 角色：符号左值 + 绝对地址右值
            "PumpCtrl": {
                "name": "PumpCtrl",
                "block_type": "FB",
                "af_role": "legacy_superseded",
                "scl_body": (
                    'FUNCTION_BLOCK "PumpCtrl"\n'
                    "BEGIN\n"
                    '  "Level_High" := %IW64 > 100;\n'
                    '  "Pump_Contactor" := %Q0.0;\n'
                    "END_FUNCTION_BLOCK\n"
                ),
                "networks": [],
            },
            # 无绝对地址 → 符号 IO 兜底
            "SymbolOnly": {
                "name": "SymbolOnly",
                "block_type": "FB",
                "af_role": "af_pending_manual",
                "scl_body": (
                    'FUNCTION_BLOCK "SymbolOnly"\n'
                    "BEGIN\n"
                    '  "EStop_OK" := TRUE;\n'
                    "END_FUNCTION_BLOCK\n"
                ),
                "networks": [],
            },
        },
    }


def _after_canvas() -> dict:
    """重构后画布：2 个 AF draft 块 + 1 个仍保留的 legacy 块（不计入 af 侧）。"""
    return {
        "project_name": "DemoLine",
        "blocks": {
            # 键含 "::" 且 af_role=CallEquipment（双条件命中 AF 侧）
            "U1_DemoLine::CallEquipment": {
                "name": "U1_DemoLine::CallEquipment",
                "block_type": "FB",
                "af_role": "CallEquipment",
                "scl_body": (
                    'FUNCTION_BLOCK "U1_DemoLine::CallEquipment"\n'
                    "BEGIN\n"
                    "  bRun := %Q4.1;\n"
                    '  "Cyl"(open := %I0.0, close := FALSE);\n'
                    '  "Motor"(enable := TRUE);\n'
                    "  #speed := 1200;\n"
                    "  #ready := bRun;\n"
                    "END_FUNCTION_BLOCK\n"
                ),
                # networks[].scl_text 参与 IO/语句统计（+1 调用行，地址去重）
                "networks": [{"id": 1, "title": "fan", "scl_text": '  "Fan"(run := %Q4.1);'}],
            },
            # 小写 %iw64 → 归一为 %IW64（大小写兼容）
            "U1_DemoLine::Sequence": {
                "name": "U1_DemoLine::Sequence",
                "block_type": "FB",
                "af_role": "Sequence",
                "scl_body": (
                    'FUNCTION_BLOCK "U1_DemoLine::Sequence"\n'
                    "BEGIN\n"
                    "  #idle := FALSE;\n"
                    "  IF %iw64 > 100 THEN\n"
                    "    #cmd := %QW80;\n"
                    "  END_IF;\n"
                    "END_FUNCTION_BLOCK\n"
                ),
                "networks": [],
            },
            # 仍以 legacy 角色保留在新画布:交付侧扫描包含它(原样交付)
            "SymbolOnly": {
                "name": "SymbolOnly",
                "block_type": "FB",
                "af_role": "af_pending_manual",
                "scl_body": (
                    'FUNCTION_BLOCK "SymbolOnly"\n'
                    "BEGIN\n"
                    '  "EStop_OK" := TRUE;\n'
                    "END_FUNCTION_BLOCK\n"
                ),
                "networks": [],
            },
        },
    }


def _af_report() -> dict:
    """引擎 report：units[].ems / af_blocks_created / pending_blocks / block_mapping。"""
    return {
        "target_unit_name": "U1_DemoLine",
        "units": [{"name": "U1_DemoLine", "ems": [{"name": "EM1"}, {"name": "EM2"}]}],
        "block_mapping": {
            "MotorCtrl": "U1_DemoLine::CallEquipment (Control Modules Hub)",
            "PumpCtrl": "U1Em1_Pump::Sequence + StepToString (EM State Machine)",
            "SymbolOnly": "PENDING (无法自动映射,保留原样待人工确认)",
        },
        "af_blocks_created": ["U1_DemoLine::CallEquipment", "U1_DemoLine::Sequence"],
        "pending_blocks": ["SymbolOnly"],
        "io_retention": {"total_ios": 4, "retained_ios": 3, "percentage": 75.0, "details": []},
    }


def _read_zip_member(zip_path: str | Path, name: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name).decode("utf-8-sig")


# -------------------------------------------------------------- IO 判定 --


def test_io_addresses_matrix() -> None:
    """出现矩阵：每个 IO 键给出 legacy_in / af_in 块名清单（排序、去重）。"""
    report = eq.build_equivalence_report(_before_canvas(), _after_canvas(), _af_report())
    io = report["io_addresses"]
    assert set(io) == {"%I0.0", "%IW64", "%Q0.0", "%Q4.1", "%QW80", "sym:EStop_OK"}
    assert io["%I0.0"] == {"legacy_in": ["MotorCtrl"], "af_in": ["U1_DemoLine::CallEquipment"]}
    assert io["%IW64"] == {"legacy_in": ["PumpCtrl"], "af_in": ["U1_DemoLine::Sequence"]}
    # 新画布中仍保留的 legacy 块（SymbolOnly）计入交付侧(原样交付,地址未消失)
    assert io["sym:EStop_OK"] == {"legacy_in": ["SymbolOnly"], "af_in": ["SymbolOnly"]}


def test_io_verdict_preserved_dropped_added() -> None:
    """判定与计数：dropped 逐地址列出；io_preserved 仅当 dropped 为空。"""
    report = eq.build_equivalence_report(_before_canvas(), _after_canvas(), _af_report())
    verdict = report["io_verdict"]
    assert verdict["preserved"] == ["%I0.0", "%IW64", "%Q4.1", "sym:EStop_OK"]
    assert verdict["preserved_count"] == 4
    # 逐地址列出；%Q0.0 旧有新无(真消失);sym:EStop_OK 因 pending 块原样保留而 preserved
    assert verdict["dropped"] == ["%Q0.0"]
    assert verdict["dropped_count"] == 1
    assert verdict["added"] == ["%QW80"]
    assert verdict["added_count"] == 1
    assert verdict["io_preserved"] is False
    # 口径写进 method 字段
    assert "绝对地址" in verdict["method"] and "sym:" in verdict["method"]
    # 无绝对地址块的兜底名单如实标注
    assert verdict["symbolic_fallback_blocks"] == ["SymbolOnly"]


def test_io_preserved_when_nothing_dropped() -> None:
    """全部旧 IO 均出现在新侧 → io_preserved True。"""
    before = {"blocks": {"B1": {"name": "B1", "af_role": "", "scl_body": "x := %I0.0;\ny := %Q0.0;"}}}
    after = {"blocks": {"U::Seq": {"name": "U::Seq", "af_role": "Sequence", "scl_body": "z := %I0.0;\nw := %Q0.0;"}}}
    report = eq.build_equivalence_report(before, after, {})
    assert report["io_verdict"]["dropped"] == []
    assert report["io_verdict"]["io_preserved"] is True
    assert report["io_verdict"]["preserved_count"] == 2


def test_canvas_state_instances_supported() -> None:
    """dict 之外也兼容 CanvasState/CanvasBlock 实例（属性双通道读取）。"""
    canvas = CanvasState(project_name="X")
    canvas.blocks["MotorCtrl"] = CanvasBlock(
        name="MotorCtrl", block_type="FB", af_role="legacy_superseded", scl_body="x := %I0.0;"
    )
    canvas.blocks["U::Seq"] = CanvasBlock(
        name="U::Seq", block_type="FB", af_role="Sequence", scl_body="y := %I0.0;"
    )
    report = eq.build_equivalence_report(canvas, canvas, {})
    assert report["io_addresses"]["%I0.0"] == {"legacy_in": ["MotorCtrl"], "af_in": ["MotorCtrl", "U::Seq"]}
    assert report["io_verdict"]["io_preserved"] is True


def test_networks_scl_text_joined() -> None:
    """完整 SCL 文本 = scl_body + networks[].scl_text：networks 中的地址/语句参与统计。"""
    before = {
        "blocks": {
            "B": {
                "name": "B",
                "af_role": "",
                "scl_body": "a := %I0.0;",
                "networks": [{"id": 1, "scl_text": 'c := %M1.0;\n"Net"(x := 1);'}],
            }
        }
    }
    after = {"blocks": {"U::C": {"name": "U::C", "af_role": "CallEquipment", "scl_body": "a := %I0.0; c := %M1.0;"}}}
    report = eq.build_equivalence_report(before, after, {})
    # %M1.0 来自 networks.scl_text → 两侧都出现，preserved
    assert "%M1.0" in report["io_verdict"]["preserved"]
    # 语句计数：B = 2 赋值 + 1 调用 = 3
    assert report["statement_counts"]["legacy_blocks"] == {"B": 3}


def test_empty_canvases_vacuous_report() -> None:
    """空入参：空报告不崩、不误报（dropped=0 → io_preserved=True，delta 为 None）。"""
    report = eq.build_equivalence_report({}, {}, {})
    assert report["io_addresses"] == {}
    assert report["io_verdict"]["dropped_count"] == 0
    assert report["io_verdict"]["io_preserved"] is True
    assert report["statement_counts"]["total_legacy"] == 0
    assert report["statement_counts"]["delta_pct"] is None


# ------------------------------------------------------------ 语句计数 --


def test_statement_counts_and_delta() -> None:
    """每旧块语句数 / AF 侧合计 / delta_pct（:= 赋值 + 独立调用行，口径见 method）。"""
    report = eq.build_equivalence_report(_before_canvas(), _after_canvas(), _af_report())
    counts = report["statement_counts"]
    # MotorCtrl：#tmp/#bRun 2 个赋值 + "Cyl" 调用 = 3；PumpCtrl 2 赋值；SymbolOnly 1 赋值
    assert counts["legacy_blocks"] == {"MotorCtrl": 3, "PumpCtrl": 2, "SymbolOnly": 1}
    # CallEquipment：2 赋值 + 2 调用 + #speed + #ready = 6（networks 的 "Fan" 调用计入）；
    # Sequence：#idle + #cmd = 2（IF 行不误计）
    # 交付侧含保留的 SymbolOnly(1 语句)
    assert counts["af_blocks"] == {
        "SymbolOnly": 1,
        "U1_DemoLine::CallEquipment": 6,
        "U1_DemoLine::Sequence": 2,
    }
    assert counts["total_legacy"] == 6
    assert counts["total_af"] == 9
    assert counts["delta_pct"] == 50.0
    assert "独立调用" in counts["method"]


def test_statement_counting_details() -> None:
    """口径细节：声明区剔除、IF(…) 不计调用、调用实参 := 不重复计数。"""
    text = (
        "VAR_INPUT\n a AT %I0.0 : BOOL := FALSE;\nEND_VAR\n"
        "IF(a) THEN\n"
        '  "FB1"(x := 1, y := 2);\n'
        "END_IF;\n"
    )
    # 只有 "FB1" 调用行计 1；声明区初始值 := 与 IF(a)、实参 := 均不计
    assert eq.count_scl_statements(text) == 1


# --------------------------------------------------------- 结构与口径 --


def test_structure_from_af_report() -> None:
    """结构摘要：ems 数 / AF 块数 / pending 数来自引擎 report。"""
    report = eq.build_equivalence_report(_before_canvas(), _after_canvas(), _af_report())
    assert report["structure"] == {
        "ems_count": 2,
        "af_blocks_count": 2,
        "pending_blocks_count": 1,
        "pending_blocks": ["SymbolOnly"],
    }


def test_caveats_honest_scope() -> None:
    """caveats 必须声明：文本级核对不是行为等价性证明。"""
    report = eq.build_equivalence_report(_before_canvas(), _after_canvas(), _af_report())
    assert report["caveats"]
    joined = "\n".join(report["caveats"])
    assert "不是行为等价性证明" in joined
    assert "时序" in joined  # 无时序/语义验证


# ------------------------------------------------- release_package 集成 --


def _pkg_canvas() -> CanvasState:
    canvas = create_empty_canvas("DemoLine")
    canvas.blocks["MotorCtrl"] = CanvasBlock(name="MotorCtrl", block_type="FB", scl_body="// demo")
    return canvas


def _pkg_report() -> dict:
    return {
        "status": "success",
        "target_unit_name": "U1_DemoLine",
        "af_blocks_created": ["U1_DemoLine_EM1"],
        "pending_blocks": [],
        "io_retention": {"total_ios": 0, "retained_ios": 0, "percentage": 100.0, "details": []},
    }


def test_release_package_default_no_equivalence_member(tmp_path: Path) -> None:
    """缺省不回归：不传 equivalence_report → 包成员与历史完全一致，无该文件/小节。"""
    pkg = rpkg.build_release_package(
        _pkg_canvas(), _pkg_report(), project_name="DemoLine", out_dir=tmp_path
    )
    names = rpkg.extract_zip_names(pkg["zip_path"])
    assert "equivalence_report.json" not in names
    assert pkg["file_count"] == len(names)
    readme = _read_zip_member(pkg["zip_path"], "README.md")
    assert "等价性核对" not in readme
    assert "equivalence_report.json" not in readme


def test_release_package_with_equivalence_report(tmp_path: Path) -> None:
    """传入报告 → 包内 equivalence_report.json + README 等价性小节。"""
    equiv = eq.build_equivalence_report(_before_canvas(), _after_canvas(), _af_report())
    pkg = rpkg.build_release_package(
        _pkg_canvas(), _pkg_report(), project_name="DemoLine", out_dir=tmp_path,
        equivalence_report=equiv,
    )
    names = rpkg.extract_zip_names(pkg["zip_path"])
    assert "equivalence_report.json" in names
    assert pkg["file_count"] == len(names)

    data = json.loads(_read_zip_member(pkg["zip_path"], "equivalence_report.json"))
    assert data["io_verdict"]["dropped_count"] == 1
    assert data["statement_counts"]["delta_pct"] == 50.0

    readme = _read_zip_member(pkg["zip_path"], "README.md")
    assert "## 等价性核对（文本级）" in readme
    assert "preserved 4 / dropped 1 / added 1" in readme
    assert "语句数变化：6 → 9（+50.0%）" in readme
    assert "口径限制：" in readme
    assert "equivalence_report.json" in readme  # 成员说明补一行
