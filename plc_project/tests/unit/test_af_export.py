"""Bug2 回归:导出必须走 AF 架构重构,且数据引用完全冻结。

背景:导入链(af_import overlay)只给块挂 af_role 元数据,SCL 仍是原始
直译;导出(canvas_to_tia_bundle)此前原样打包 staged SCL,导致"导出未走
AF 架构重构"。本文件锁定三条铁律:

1. af_role ∈ {unit, em, cm} 的待写回块 → staged SCL 必须重排为 AF
   Unit/EM/CM 结构(AF 软件单元标识 + CallUnit/CallEquipment/Sequence
   调用分层特征);
2. 数据引用冻结:原 SCL 中的 #变量 / "DB名"/"符号名" / %I %Q 地址在
   重排后逐字保留、语句顺序不变;接口(变量声明)逐字保留;
3. 加密块(protected,并行线加标志,getattr 防御)绝不触碰:不重排、
   不写回;synced 块仍不写回;global(DB/OB)/safety/空角色 → 原样输出;
   重排是非破坏式的(画布本体不被改动),且可关(af_refactor=False)。
"""

from __future__ import annotations

import json
from pathlib import Path

from plc_engine.af.refactor import (
    af_software_unit_for_role,
    extract_scl_data_references,
)
from plc_engine.canvas_model import CanvasBlock, CanvasState, CanvasVariable
from plc_engine.canvas_tia_transpiler import canvas_to_tia_bundle


def _unit_block() -> CanvasBlock:
    """非 AF 的模式控制块(overlay 判定 af_role=unit),引用 DB/符号/IO。"""
    return CanvasBlock(
        name="FB1000_Master",
        block_type="FB",
        number=1000,
        af_role="unit",
        status="draft",
        interface=[
            CanvasVariable(name="CmdMode", data_type="Int", section="VAR_INPUT"),
            CanvasVariable(name="StartCmd", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="statRunning", data_type="Bool", section="VAR_STAT"),
        ],
        scl_body=(
            "// Unit mode control\n"
            '"DB1000_Global".mode := #CmdMode;\n'
            'IF "I_EStop" AND #StartCmd THEN\n'
            '    "DB1000_Global".running := TRUE;\n'
            "END_IF;\n"
            '"Q_FaultLamp" := %I0.3;'
        ),
    )


def _em_block() -> CanvasBlock:
    """非 AF 的步序块(overlay 判定 af_role=em),CASE 步序 + 设备 IO。"""
    return CanvasBlock(
        name="FB1060_Loader",
        block_type="FB",
        number=1060,
        af_role="em",
        status="draft",
        interface=[
            CanvasVariable(name="Step", data_type="DInt", section="VAR_STAT"),
        ],
        scl_body=(
            "// Loader sequence\n"
            "CASE #Step OF\n"
            "    10:\n"
            '        "Q_CylExtend" := TRUE;\n'
            '        IF "I_CylExtended" THEN\n'
            "            #Step := 20;\n"
            "        END_IF;\n"
            "    20:\n"
            '        "Q_CylRetract" := TRUE;\n'
            "END_CASE;"
        ),
    )


def _build_canvas() -> CanvasState:
    canvas = CanvasState(project_name="LegacyExport")

    canvas.blocks["FB1000_Master"] = _unit_block()
    canvas.blocks["FB1060_Loader"] = _em_block()

    # 安全块:只读,绝不能被重排
    canvas.blocks["FB8000_Safety"] = CanvasBlock(
        name="FB8000_Safety",
        block_type="FB",
        number=8000,
        af_role="safety",
        status="draft",
        interface=[CanvasVariable(name="EStopOk", data_type="Bool", section="VAR_INPUT")],
        scl_body='IF NOT "I_EStop" THEN\n    "Q_FaultLamp" := TRUE;\nEND_IF;',
    )

    # 全局 DB:数据布局冻结,draft 会被写回但 SCL 必须原样
    canvas.blocks["DB9000_Global"] = CanvasBlock(
        name="DB9000_Global",
        block_type="DB",
        number=9000,
        af_role="global",
        status="draft",
        interface=[
            CanvasVariable(name="mode", data_type="Int"),
            CanvasVariable(name="running", data_type="Bool"),
        ],
    )

    # synced DB:最小破坏原则,不写回
    canvas.blocks["DB9001_Synced"] = CanvasBlock(
        name="DB9001_Synced",
        block_type="DB",
        number=9001,
        af_role="global",
        status="synced",
        interface=[CanvasVariable(name="K", data_type="Int")],
    )

    # 加密块(并行线加 protected 标志;CanvasBlock 尚无该字段,动态挂上,
    # 导出侧必须 getattr 防御):绝不触碰——不重排、不写回
    secret = CanvasBlock(
        name="FB9001_Secret",
        block_type="FB",
        number=9001,
        af_role="unit",
        status="draft",
        scl_body='"Q_Secret" := TRUE;',
    )
    secret.protected = True  # type: ignore[attr-defined]
    canvas.blocks["FB9001_Secret"] = secret

    # af_role 为空的普通块:原样输出
    canvas.blocks["FB1020_Helper"] = CanvasBlock(
        name="FB1020_Helper",
        block_type="FB",
        number=1020,
        af_role="",
        status="draft",
        interface=[CanvasVariable(name="Enable", data_type="Bool", section="VAR_INPUT")],
        scl_body='"Q_Buzz" := #Enable;',
    )
    return canvas


def _staged(bundle: Path) -> list[dict]:
    return json.loads((bundle / "staged_scls.json").read_text(encoding="utf-8"))


def _staged_scl(bundle: Path, block_name: str) -> str:
    entry = next(e for e in _staged(bundle) if e["block_name"] == block_name)
    return Path(entry["path"]).read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# 1. AF 架构重构特征
# ---------------------------------------------------------------------------


def test_export_restructures_unit_and_em_blocks_to_af(tmp_path: Path) -> None:
    canvas = _build_canvas()
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")

    staged_names = [e["block_name"] for e in _staged(bundle)]
    # unit/em 参与写回且被重排;synced 与 protected 不写回
    assert "FB1000_Master" in staged_names
    assert "FB1060_Loader" in staged_names
    assert "DB9001_Synced" not in staged_names
    assert "FB9001_Secret" not in staged_names

    unit_scl = _staged_scl(bundle, "FB1000_Master")
    em_scl = _staged_scl(bundle, "FB1060_Loader")

    # AF 结构特征:U1_ 软件单元前缀 + CallUnit/CallEquipment 调用模式
    assert "U1_" in unit_scl, "unit 块 staged SCL 缺 AF 软件单元标识"
    assert "CallUnit" in unit_scl
    assert "af_role = unit" in unit_scl
    assert "U1Em1_" in em_scl, "em 块 staged SCL 缺 AF 软件单元标识"
    assert "CallEquipment" in em_scl
    assert "Sequence" in em_scl
    assert "af_role = em" in em_scl

    # manifest 追加 AF 元数据(writeback 只消费 path/software_unit/block_name)
    unit_entry = next(e for e in _staged(bundle) if e["block_name"] == "FB1000_Master")
    assert unit_entry["af_role"] == "unit"
    assert unit_entry["af_software_unit"].startswith("U1_")
    em_entry = next(e for e in _staged(bundle) if e["block_name"] == "FB1060_Loader")
    assert em_entry["af_software_unit"].startswith("U1Em1_")
    helper_entry = next(e for e in _staged(bundle) if e["block_name"] == "FB1020_Helper")
    assert helper_entry["af_software_unit"] == ""


def test_protected_block_has_no_staged_file(tmp_path: Path) -> None:
    canvas = _build_canvas()
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")

    assert not (bundle / "external_sources" / "FB9001_Secret.scl").exists()
    assert not (bundle / "external_sources" / "DB9001_Synced.scl").exists()
    # protected 块本体在画布上仍完好(只是不导出)
    assert canvas.blocks["FB9001_Secret"].scl_body == '"Q_Secret" := TRUE;'


# ---------------------------------------------------------------------------
# 2. 数据引用冻结
# ---------------------------------------------------------------------------


def test_af_refactor_freezes_every_data_reference(tmp_path: Path) -> None:
    canvas = _build_canvas()
    originals = {
        name: block.get_full_scl()
        for name, block in canvas.blocks.items()
        if name in ("FB1000_Master", "FB1060_Loader")
    }
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")

    for name, original in originals.items():
        staged = _staged_scl(bundle, name)
        # 冻结铁律 1:原 SCL 的每一个数据引用 token 逐字保留
        missing = set(extract_scl_data_references(original)) - set(
            extract_scl_data_references(staged)
        )
        assert not missing, f"{name} 重排后丢失数据引用: {sorted(missing)}"
        # 冻结铁律 2:带引号的 DB/符号名集合完全一致(重排不新增符号指向)
        orig_quoted = {t for t in extract_scl_data_references(original) if t.startswith('"')}
        new_quoted = {t for t in extract_scl_data_references(staged) if t.startswith('"')}
        assert orig_quoted == new_quoted, f"{name} 引号符号名集合被改动"

    unit_scl = _staged_scl(bundle, "FB1000_Master")
    em_scl = _staged_scl(bundle, "FB1060_Loader")

    # 逐一字符串断言:DB 名 / 符号名 / IO 地址 / #变量
    for ref in ('"DB1000_Global"', "#CmdMode", "#StartCmd", '"I_EStop"', '"Q_FaultLamp"', "%I0.3"):
        assert ref in unit_scl, f"unit 块丢失原始引用 {ref}"
    for ref in ('"Q_CylExtend"', '"Q_CylRetract"', '"I_CylExtended"', "#Step"):
        assert ref in em_scl, f"em 块丢失原始引用 {ref}"

    # 接口(变量声明)逐字冻结 → #变量 绑定不变
    assert "CmdMode : Int;" in unit_scl
    assert "StartCmd : Bool;" in unit_scl
    assert "Step : DInt;" in em_scl

    # 可执行语句逐字保留且顺序不变(取函数体内语句行,按下标递增出现)
    def _body_statements(full_scl: str) -> list[str]:
        lines = full_scl.splitlines()
        begin = max((i for i, ln in enumerate(lines) if ln.strip() == "BEGIN"), default=-1)
        end = next(
            (i for i, ln in enumerate(lines) if ln.strip() == "END_FUNCTION_BLOCK"),
            len(lines),
        )
        return [
            ln.strip()
            for ln in lines[begin + 1 : end]
            if ln.strip() and not ln.strip().startswith("//")
        ]

    for name, original in originals.items():
        staged = _staged_scl(bundle, name)
        cursor = -1
        for stmt in _body_statements(original):
            idx = staged.find(stmt)
            assert idx > cursor, f"{name} 语句顺序被打乱: {stmt}"
            cursor = idx


def test_af_refactor_does_not_mutate_canvas(tmp_path: Path) -> None:
    """非破坏式:重排只落在 staged 文件,画布本体一字不动。"""
    canvas = _build_canvas()
    before = {
        key: (block.scl_body, block.status, block.af_role, block.software_unit)
        for key, block in canvas.blocks.items()
    }
    before_full = {key: b.get_full_scl() for key, b in canvas.blocks.items()}

    canvas_to_tia_bundle(canvas, tmp_path / "bundle")

    after = {
        key: (block.scl_body, block.status, block.af_role, block.software_unit)
        for key, block in canvas.blocks.items()
    }
    assert before == after
    assert {key: b.get_full_scl() for key, b in canvas.blocks.items()} == before_full


# ---------------------------------------------------------------------------
# 3. 不参与重排的角色:safety / global(DB/OB) / 空 → 原样输出
# ---------------------------------------------------------------------------


def test_safety_global_and_unknown_blocks_keep_original_scl(tmp_path: Path) -> None:
    canvas = _build_canvas()
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle")

    staged_names = [e["block_name"] for e in _staged(bundle)]
    assert "FB8000_Safety" in staged_names
    assert "DB9000_Global" in staged_names
    assert "FB1020_Helper" in staged_names

    # DB 布局/安全块/空角色块:staged SCL 与画布渲染逐字节一致(原样输出)
    assert _staged_scl(bundle, "FB8000_Safety") == canvas.blocks["FB8000_Safety"].get_full_scl()
    assert _staged_scl(bundle, "DB9000_Global") == canvas.blocks["DB9000_Global"].get_full_scl()
    assert _staged_scl(bundle, "FB1020_Helper") == canvas.blocks["FB1020_Helper"].get_full_scl()


def test_af_refactor_can_be_disabled(tmp_path: Path) -> None:
    canvas = _build_canvas()
    bundle = canvas_to_tia_bundle(canvas, tmp_path / "bundle", af_refactor=False)

    for name in ("FB1000_Master", "FB1060_Loader"):
        assert _staged_scl(bundle, name) == canvas.blocks[name].get_full_scl(), (
            f"af_refactor=False 时 {name} 必须原样输出"
        )
    entry = next(e for e in _staged(bundle) if e["block_name"] == "FB1000_Master")
    assert entry["af_software_unit"] == ""


# ---------------------------------------------------------------------------
# 4. 命名/引用提取辅助函数
# ---------------------------------------------------------------------------


def test_af_software_unit_naming() -> None:
    assert af_software_unit_for_role("FB1000_Master", "unit", 1) == "U1_Master"
    assert af_software_unit_for_role("FB1060_Loader", "em", 1) == "U1Em1_Loader"
    assert af_software_unit_for_role("FB2000_Valve", "cm", 3) == "U1Em1CM03_Valve"
    assert af_software_unit_for_role("奇怪的名字!", "unit", 2) == "U2_Module"


def test_extract_scl_data_references_tokens() -> None:
    scl = '"DB1".x := #Cmd OR "I_EStop" AND %I0.3 OR %QW10;'
    assert set(extract_scl_data_references(scl)) == {
        '"DB1"',
        "#Cmd",
        '"I_EStop"',
        "%I0.3",
        "%QW10",
    }
