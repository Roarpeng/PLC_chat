"""单文件 Mega-Source 批次回写适配器测试（全内联构造，不读真实博途文件）。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.plc.tia.writeback_batch import (
    BATCH_FILE_NAME,
    execute_batch_writeback,
    from_bundle_dir,
    prepare_batch_writeback,
)
from plc_engine.contracts import CompileErrorItem, WritebackResult
from plc_engine.mega_source import CycleError
from plc_engine.writeback_contract import BlockArtifact, sha256_text

UDT_SRC = """TYPE "UDT_ST10_AutoCmd"
VERSION : 0.1
   STRUCT
      xHome : Bool;
      xWork : Bool;
   END_STRUCT;
END_TYPE
"""

FB_SRC = """FUNCTION_BLOCK "FB_ST10_Main"
{ S7_Optimized_Access := 'TRUE' }
VAR
   statStep : Int := 10;
   statCmd : "UDT_ST10_AutoCmd";
END_VAR
BEGIN
   #statStep := 20;
END_FUNCTION_BLOCK
"""

IDB_SRC = """DATA_BLOCK "IDB_ST10_Main"
"FB_ST10_Main"
BEGIN
END_DATA_BLOCK
"""

OB_SRC = """ORGANIZATION_BLOCK "OB1_Main"
BEGIN
   "IDB_ST10_Main"();
END_ORGANIZATION_BLOCK
"""

# R2 违规：物理输出直接出现在 := 左侧
BAD_SRC = """FUNCTION_BLOCK "FB_Bad"
VAR
   xGo : Bool;
END_VAR
BEGIN
   "Q_Test_Valve" := #xGo;
END_FUNCTION_BLOCK
"""

CYCLE_A_SRC = """FUNCTION_BLOCK "FB_A"
VAR
   statX : Int;
END_VAR
BEGIN
   #statX := 1;
END_FUNCTION_BLOCK
"""

CYCLE_B_SRC = """FUNCTION_BLOCK "FB_B"
VAR
   statY : Int;
END_VAR
BEGIN
   #statY := 2;
END_FUNCTION_BLOCK
"""


def _blocks() -> list[BlockArtifact]:
    return [
        BlockArtifact(name="UDT_ST10_AutoCmd", kind="UDT", source=UDT_SRC, interface_changed=True),
        BlockArtifact(
            name="FB_ST10_Main", kind="FB", source=FB_SRC, dependencies=["UDT_ST10_AutoCmd"]
        ),
        BlockArtifact(
            name="IDB_ST10_Main", kind="INSTANCE_DB", source=IDB_SRC, dependencies=["FB_ST10_Main"]
        ),
        BlockArtifact(name="OB1_Main", kind="OB", source=OB_SRC, dependencies=["IDB_ST10_Main"]),
    ]


def _cache_of(blocks: list[BlockArtifact]) -> dict[str, str]:
    return {b.name: b.sha256() for b in blocks}


# --------------------------------------------------------------------------- #
# prepare_batch_writeback
# --------------------------------------------------------------------------- #
def test_prepare_writes_one_bom_scl(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path)

    assert plan.blocked is False
    assert plan.block_count == 4
    assert plan.skipped_count == 0
    assert plan.bundle_path == str(tmp_path / BATCH_FILE_NAME)
    assert [p.name for p in tmp_path.glob("*.scl")] == [BATCH_FILE_NAME]

    raw = Path(plan.bundle_path).read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"  # 真实字节头，不是硬编码
    assert plan.af_batch.has_utf8_bom is True
    text = raw.decode("utf-8-sig")
    # 拓扑序：UDT 先于 FB 先于 OB
    assert text.index("TYPE") < text.index("FUNCTION_BLOCK") < text.index("ORGANIZATION_BLOCK")


def test_af_batch_contract_validates(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path, seeds=["UDT_ST10_AutoCmd"])

    plan.af_batch.validate()  # path + sha256 均非空
    assert plan.af_batch.block_names == [
        "UDT_ST10_AutoCmd",
        "FB_ST10_Main",
        "IDB_ST10_Main",
        "OB1_Main",
    ]
    assert plan.af_batch.skipped_unchanged == []
    assert plan.af_batch.path == plan.bundle_path
    assert plan.af_batch.sha256 == sha256_text(
        Path(plan.bundle_path).read_text(encoding="utf-8-sig")
    )


def test_sha256_matches_written_text(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path)
    raw = Path(plan.bundle_path).read_bytes()

    assert plan.af_batch.sha256 == sha256_text(raw.decode("utf-8-sig"))
    # 与"连 BOM 一起算"的字节哈希不同：证明哈希对象是解码后的最终文本
    assert plan.af_batch.sha256 != hashlib.sha256(raw).hexdigest()


def test_gate_blocks_and_writes_nothing(tmp_path: Path) -> None:
    blocks = [BlockArtifact(name="FB_Bad", kind="FB", source=BAD_SRC), *_blocks()]
    plan = prepare_batch_writeback(blocks, output_dir=tmp_path, seeds=["FB_Bad"])

    assert plan.blocked is True
    assert plan.blocking_findings, "blocking_findings 不能为空"
    assert {f.rule for f in plan.blocking_findings} == {"R2"}
    assert plan.bundle_path == ""
    assert list(tmp_path.glob("*.scl")) == [], "门禁失败时不允许落任何 .scl"


def test_second_prepare_skips_everything(tmp_path: Path) -> None:
    blocks = _blocks()
    first = prepare_batch_writeback(blocks, output_dir=tmp_path / "first")
    second = prepare_batch_writeback(
        blocks, output_dir=tmp_path / "second", cache=_cache_of(blocks)
    )

    assert first.block_count == 4
    assert second.blocked is False
    assert second.block_count == 0
    assert second.skipped_count == 4
    assert second.bundle_path == "", "全量命中缓存时不该产出批次路径"
    assert list((tmp_path / "second").glob("*.scl")) == [], (
        "全量命中缓存时绝不落盘仅含 BOM 的空 .scl，否则会被 staged_files 捡到触发空 IPC"
    )
    assert set(second.af_batch.skipped_unchanged) == {
        "UDT_ST10_AutoCmd",
        "FB_ST10_Main",
        "IDB_ST10_Main",
        "OB1_Main",
    }


def test_cycle_is_raised_not_swallowed(tmp_path: Path) -> None:
    blocks = [
        BlockArtifact(name="FB_A", kind="FB", source=CYCLE_A_SRC, dependencies=["FB_B"]),
        BlockArtifact(name="FB_B", kind="FB", source=CYCLE_B_SRC, dependencies=["FB_A"]),
    ]
    with pytest.raises(CycleError) as excinfo:
        prepare_batch_writeback(blocks, output_dir=tmp_path)

    message = str(excinfo.value)
    assert "FB_A" in message and "FB_B" in message
    assert list(tmp_path.glob("*.scl")) == []


# --------------------------------------------------------------------------- #
# execute_batch_writeback
# --------------------------------------------------------------------------- #
def test_blocked_plan_never_calls_worker(tmp_path: Path) -> None:
    blocks = [BlockArtifact(name="FB_Bad", kind="FB", source=BAD_SRC), *_blocks()]
    plan = prepare_batch_writeback(blocks, output_dir=tmp_path, seeds=["FB_Bad"])
    worker = MagicMock(return_value={"success": True, "errors": [], "elapsedMilliseconds": 1})

    out = execute_batch_writeback(plan, worker_call=worker, dry_run=False)

    assert worker.call_count == 0
    assert out["success"] is False
    assert out["refused"] == "gate_blocked"
    assert out["result"]["success"] is False
    assert out["blockingFindings"], "拒绝结果要带上拦截原因"


def test_dry_run_never_calls_worker(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path)
    worker = MagicMock(return_value={"success": True, "errors": [], "elapsedMilliseconds": 1})

    out = execute_batch_writeback(plan, worker_call=worker)  # dry_run 默认 True

    assert worker.call_count == 0
    assert out["dryRun"] is True
    assert out["written"] is False
    assert out["success"] is True
    assert out["bundlePath"] == plan.bundle_path
    assert out["blockCount"] == 4


def test_real_run_without_worker_call_is_refused(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path)

    out = execute_batch_writeback(plan, dry_run=False)

    assert out["success"] is False
    assert out["refused"] == "no_worker_call"
    assert out["written"] is False


def test_worker_success_maps_to_writeback_result(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path)
    calls: list[str] = []

    def worker(path: str) -> dict:
        calls.append(path)
        return {
            "success": True,
            "errors": [],
            "elapsedMilliseconds": 4321,
            "backupPath": r"D:\backup\2026\proj",
        }

    out = execute_batch_writeback(plan, worker_call=worker, dry_run=False)

    assert calls == [plan.bundle_path], "worker 只被喂单个批次文件（一次 IPC）"
    assert out["success"] is True
    assert out["written"] is True
    assert out["dryRun"] is False
    assert out["result"]["elapsed_milliseconds"] == 4321
    assert out["result"]["written_block_count"] == 4
    assert out["result"]["errors"] == []
    assert "restore_from_backup" in out["backupHint"]

    typed = out["writebackResult"]
    assert isinstance(typed, WritebackResult)
    assert typed.success is True
    assert typed.failed_block_names == []


def test_worker_errors_map_to_compile_error_items(tmp_path: Path) -> None:
    plan = prepare_batch_writeback(_blocks(), output_dir=tmp_path)

    def worker(_path: str) -> dict:
        return {
            "success": False,
            "elapsedMilliseconds": 2500,
            "errors": [
                {
                    "blockName": "FB_ST10_Main",
                    "networkOrLine": "N3",
                    "tiaDescription": "接口时间戳不一致",
                },
                {"block_name": "OB1_Main", "network_or_line": "L7", "tia_description": "未知块"},
            ],
        }

    out = execute_batch_writeback(plan, worker_call=worker, dry_run=False)

    assert out["success"] is False
    assert out["written"] is False
    result = out["result"]
    assert result["elapsed_milliseconds"] == 2500
    assert result["written_block_count"] == 0
    assert result["errors"] == [
        {
            "block_name": "FB_ST10_Main",
            "network_or_line": "N3",
            "tia_description": "接口时间戳不一致",
            "block_path": "",
            "timestamp": "",
        },
        {
            "block_name": "OB1_Main",
            "network_or_line": "L7",
            "tia_description": "未知块",
            "block_path": "",
            "timestamp": "",
        },
    ]
    assert out["writebackResult"].errors[0] == CompileErrorItem(
        block_name="FB_ST10_Main",
        network_or_line="N3",
        tia_description="接口时间戳不一致",
    )
    assert out["writebackResult"].failed_block_names == ["FB_ST10_Main", "OB1_Main"]


# --------------------------------------------------------------------------- #
# from_bundle_dir
# --------------------------------------------------------------------------- #
def _make_scl(kind: str, name: str) -> str:
    return {
        "TYPE": f'TYPE "{name}"\n   STRUCT\n      xHome : Bool;\n   END_STRUCT;\nEND_TYPE\n',
        "DATA_BLOCK": f'DATA_BLOCK "{name}"\n"FB_Host"\nBEGIN\nEND_DATA_BLOCK\n',
        "FUNCTION_BLOCK": (
            f'FUNCTION_BLOCK "{name}"\nVAR\n   statX : Int;\nEND_VAR\n'
            f"BEGIN\n   #statX := 1;\nEND_FUNCTION_BLOCK\n"
        ),
        "FUNCTION": f'FUNCTION "{name}" : Int\nVAR_INPUT\n   iVal : Int;\nEND_VAR\nBEGIN\nEND_FUNCTION\n',
        "ORGANIZATION_BLOCK": f'ORGANIZATION_BLOCK "{name}"\nBEGIN\nEND_ORGANIZATION_BLOCK\n',
    }[kind]


def test_from_bundle_dir_skips_xml(tmp_path: Path) -> None:
    (tmp_path / "FB_Comment.xml").write_text("<Document />", encoding="utf-8")
    ext = tmp_path / "external_sources"
    ext.mkdir()
    (ext / "FB_ST10.scl").write_text(_make_scl("FUNCTION_BLOCK", "FB_ST10"), encoding="utf-8")

    blocks = from_bundle_dir(tmp_path)

    assert [b.name for b in blocks] == ["FB_ST10"]
    assert blocks[0].kind == "FB"
    assert not any(b.kind == "" for b in blocks), ".xml 不得混进来"


def test_from_bundle_dir_survives_broken_file(tmp_path: Path) -> None:
    ext = tmp_path / "external_sources"
    ext.mkdir()
    (ext / "broken.scl").write_bytes(b"\xff\xfe\x00\x01\x80")  # 非 UTF-8，读取必失败
    (ext / "garbage.scl").write_text("REGION 无用片段\nEND_REGION\n", encoding="utf-8")
    (ext / "UDT_OK.scl").write_text(_make_scl("TYPE", "UDT_OK"), encoding="utf-8")
    (ext / "FC_OK.scl").write_text(_make_scl("FUNCTION", "FC_OK"), encoding="utf-8")

    blocks = from_bundle_dir(tmp_path)

    assert sorted(b.name for b in blocks) == ["FC_OK", "UDT_OK"]


@pytest.mark.parametrize(
    ("keyword", "expected_kind"),
    [
        ("TYPE", "UDT"),
        ("DATA_BLOCK", "INSTANCE_DB"),
        ("FUNCTION_BLOCK", "FB"),
        ("FUNCTION", "FC"),
        ("ORGANIZATION_BLOCK", "OB"),
    ],
)
def test_kind_inference(tmp_path: Path, keyword: str, expected_kind: str) -> None:
    ext = tmp_path / "external_sources"
    ext.mkdir()
    stem = f"X_{expected_kind}"
    (ext / f"{stem}.scl").write_text(_make_scl(keyword, stem), encoding="utf-8")

    blocks = from_bundle_dir(tmp_path)

    assert [b.kind for b in blocks] == [expected_kind]
    assert blocks[0].name == stem
