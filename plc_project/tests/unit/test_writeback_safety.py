"""Unit tests — write-back safety rails: dry-run / backup / rollback / idempotency.

所有真实 Openness CLI 调用都被 monkeypatch 掉，只验证编排逻辑。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.plc.tia.changeset import PlcChangeOp, PlcChangeSet
from agents.plc.tia.writeback import execute_writeback, prepare_writeback
from agents.plc.tia.writeback_safety import (
    backup_target,
    content_sha256,
    load_manifest,
    manifest_path,
    restore_from_backup,
)

SCL_BODY = 'FUNCTION_BLOCK "FB_Motor"\nBEGIN\n    #Q := TRUE;\nEND_FUNCTION_BLOCK\n'


def _changeset(scl: str = SCL_BODY) -> PlcChangeSet:
    return PlcChangeSet(
        id="wb-safety",
        ops=[
            PlcChangeOp(
                kind="rewrite_scl",
                payload={"block_name": "FB_Motor", "scl_text": scl},
            )
        ],
        notes=["optimize_plan:# plan\n"],
    )


def _patch_clis(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    """把四种 Openness 写/编译入口换成记录型假实现。"""

    def fake_block(project_path, xml_path, **_k):
        calls.append(f"block:{Path(xml_path).name}")
        return {"ok": True, "import": {"ok": True}}

    def fake_xml(project_path, xml_path, **kwargs):
        calls.append(f"xml:{Path(xml_path).name}")
        return {"ok": True, "import": {"ok": True, "kind": kwargs.get("kind")}}

    def fake_scl(project_path, scl_path, **_k):
        calls.append(f"scl:{Path(scl_path).name}")
        return {"ok": True, "generate": {"ok": True}}

    def fake_compile(project_path, **_k):
        calls.append("compile")
        return {"ok": True, "compile": {"ok": True, "apiAvailable": True, "errorCount": 0}}

    monkeypatch.setattr(
        "agents.plc.tia.writeback.import_block_via_openness_cli", fake_block
    )
    monkeypatch.setattr("agents.plc.tia.writeback.import_xml_via_openness_cli", fake_xml)
    monkeypatch.setattr(
        "agents.plc.tia.writeback.generate_from_source_via_openness_cli", fake_scl
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.compile_plc_via_openness_cli", fake_compile
    )


def test_dry_run_never_calls_write_clis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"fake")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)

    result = execute_writeback(project, bundle, plc_name="PLC_1", dry_run=True)

    assert calls == [], f"dry-run 不得触发任何 Openness 写操作，实际: {calls}"
    assert result["dry_run"] is True
    assert result["ok"] is True
    assert result["written"] is False
    assert result["backup_path"] is None
    actions = [p["action"] for p in result["planned"]]
    assert "generate_from_source" in actions
    assert actions[-1] == "compile"
    for entry in result["planned"]:
        assert {"action", "block", "target", "reason"} <= set(entry)
    scl_entry = next(p for p in result["planned"] if p["action"] == "generate_from_source")
    assert scl_entry["block"] == "FB_Motor"
    assert Path(scl_entry["target"]).is_file()
    # bundle 仍然被完整生成
    assert list((bundle / "external_sources").glob("*.scl"))


def test_dry_run_can_prepare_bundle_from_changeset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """一次调用走完 prepare→plan：传入 changeset 即可，无需先 prepare_writeback。"""
    export = tmp_path / "export"
    bundle = export / "import_bundle"
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"fake")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    result = execute_writeback(
        project, bundle, plc_name="PLC_1", dry_run=True, changeset=_changeset()
    )
    assert calls == []
    assert result["dry_run"] is True
    assert (bundle / "external_sources" / "FB_Motor.scl").is_file()
    assert any(p["action"] == "generate_from_source" for p in result["planned"])


def test_backup_too_large_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"x" * 4096)

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    # 上限压到 ~1KB，4KB 工程必然超限
    monkeypatch.setenv("RESEARCHOS_WRITEBACK_BACKUP_MAX_MB", "0.001")

    result = execute_writeback(project, bundle, plc_name="PLC_1")

    assert calls == [], f"备份超限不得写任何东西，实际: {calls}"
    assert result["ok"] is False
    assert result["skippedReason"] == "backup_too_large"
    assert result["written"] is False
    assert result["backup_path"] is None
    assert not (export / "backup").exists()


def test_backup_created_before_writes_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    result = execute_writeback(project, bundle, plc_name="PLC_1")

    assert result["ok"] is True
    assert result["backup_path"]
    backup_dir = Path(result["backup_path"])
    assert (backup_dir / "Line.ap19").read_bytes() == b"original"
    assert result["rollback"]["backup_path"] == result["backup_path"]
    assert "restore_from_backup" in result["rollback"]["restore_hint"]
    # 写操作确实发生（备份在前）
    assert "scl:FB_Motor.scl" in calls and "compile" in calls


def test_backup_handles_project_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TIA 工程目录（非单文件）也要能备份。"""
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "LineProj"
    (project / "Line").mkdir(parents=True)
    (project / "Line.ap19").write_bytes(b"ap")
    (project / "Line" / "project.bin").write_bytes(b"bin")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    result = execute_writeback(project, bundle, plc_name="PLC_1")

    assert result["ok"] is True
    backup_dir = Path(result["backup_path"])
    assert (backup_dir / "LineProj" / "Line" / "project.bin").read_bytes() == b"bin"


def test_second_run_with_same_content_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    first = execute_writeback(project, bundle, plc_name="PLC_1")
    assert first["ok"] is True
    assert calls and "scl:FB_Motor.scl" in calls

    manifest = load_manifest(export)
    assert manifest, "首次执行后应写入幂等清单"
    key = next(iter(manifest))
    assert manifest[key]["status"] == "ok"
    assert manifest[key]["sha256"] == content_sha256(
        bundle / "external_sources" / "FB_Motor.scl"
    )
    assert manifest_path(export).is_file()

    calls.clear()
    second = execute_writeback(project, bundle, plc_name="PLC_1")
    assert calls == [], f"内容未变化不应重复导入，实际: {calls}"
    assert second["skipped"] == "unchanged"
    assert second["written"] is False
    assert second["ok"] is True
    assert second["skipped_items"]
    assert second["skipped_items"][0]["skipped"] == "unchanged"


def test_changed_content_is_reimported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    assert execute_writeback(project, bundle, plc_name="PLC_1")["ok"] is True

    prepare_writeback(export, _changeset(SCL_BODY + "    #Extra := 1;\n"), [])
    calls.clear()
    again = execute_writeback(project, bundle, plc_name="PLC_1")
    assert "scl:FB_Motor.scl" in calls, "内容变了必须重新导入"
    assert again["ok"] is True
    assert again.get("skipped") is None


def test_failed_entry_is_retried_next_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    calls: list[str] = []

    def failing_scl(project_path, scl_path, **_k):
        calls.append("scl")
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr(
        "agents.plc.tia.writeback.import_block_via_openness_cli",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.import_xml_via_openness_cli",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.generate_from_source_via_openness_cli", failing_scl
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.compile_plc_via_openness_cli",
        lambda *_a, **_k: {"ok": True, "compile": {"ok": True}},
    )
    failed = execute_writeback(project, bundle, plc_name="PLC_1")
    assert failed["ok"] is False
    manifest = load_manifest(export)
    assert next(iter(manifest.values()))["status"] == "failed"

    calls.clear()
    _patch_clis(monkeypatch, calls)
    retried = execute_writeback(project, bundle, plc_name="PLC_1")
    assert "scl:FB_Motor.scl" in calls, "上次失败必须重跑而不是跳过"
    assert retried["ok"] is True


def test_compile_failure_still_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """既有 fail-closed 行为：编译失败 → ok=False，调用方不归档。"""
    export = tmp_path / "export"
    bundle = prepare_writeback(export, _changeset(), [])
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    calls: list[str] = []
    _patch_clis(monkeypatch, calls)
    monkeypatch.setattr(
        "agents.plc.tia.writeback.compile_plc_via_openness_cli",
        lambda *_a, **_k: {
            "ok": False,
            "compile": {
                "ok": False,
                "apiAvailable": True,
                "errorCount": 2,
                "inconsistentBlocks": ["FB_Motor"],
            },
        },
    )

    def boom_archive(*_a, **_k):
        calls.append("archive")
        raise AssertionError("编译失败不得归档")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.archive_project_via_openness_cli", boom_archive
    )

    result = execute_writeback(project, bundle, plc_name="PLC_1")
    assert result["import_ok"] is True
    assert result["compiled_ok"] is False
    assert result["ok"] is False
    assert result["compile"]["compile"]["inconsistentBlocks"] == ["FB_Motor"]
    assert "archive" not in calls
    # 编译失败也需要留下可回滚的备份
    assert result["backup_path"]
    # 编译门禁没过 → 不能记成成功，否则幂等跳过会掩盖失败
    manifest = load_manifest(export)
    assert manifest, "编译失败也要留痕"
    assert next(iter(manifest.values()))["status"] == "failed"


def test_restore_from_backup_roundtrip(tmp_path: Path):
    export = tmp_path / "export"
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    backup = backup_target(project, export)
    assert backup["ok"] is True
    backup_path = Path(str(backup["path"]))

    project.write_bytes(b"corrupted-by-writeback")
    restored = restore_from_backup(
        backup_path, project, allowed_roots=[export / "backup"]
    )
    assert restored["ok"] is True
    assert restored["target"] == str(project.resolve())
    assert restored["restored_from"] == str(backup_path)
    assert project.read_bytes() == b"original"
    assert restored["pre_rollback_path"]
    assert Path(str(restored["pre_rollback_path"])).name.startswith(
        "Line.ap19.pre-rollback-"
    )


def test_restore_from_backup_directory(tmp_path: Path):
    export = tmp_path / "export"
    project = tmp_path / "LineProj"
    (project / "sub").mkdir(parents=True)
    (project / "sub" / "a.bin").write_bytes(b"a")

    backup = backup_target(project, export)
    assert backup["ok"] is True
    (project / "sub" / "a.bin").write_bytes(b"broken")
    (project / "sub" / "b.bin").write_bytes(b"extra")

    restored = restore_from_backup(
        str(backup["path"]), project, allowed_roots=[export / "backup"]
    )
    assert restored["ok"] is True
    assert (project / "sub" / "a.bin").read_bytes() == b"a"
    assert not (project / "sub" / "b.bin").exists()


def test_restore_rejects_backup_outside_allowed_roots(tmp_path: Path):
    outside = tmp_path / "somewhere"
    outside.mkdir()
    (outside / "backup_manifest.json").write_text("{}", encoding="utf-8")
    (outside / "Line.ap19").write_bytes(b"evil")
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    result = restore_from_backup(outside, project, allowed_roots=[tmp_path / "export"])
    assert result["ok"] is False
    assert result["reason"] == "backup_path_outside_allowed_roots"
    assert project.read_bytes() == b"original"


def test_restore_requires_marker_without_allowed_roots(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "Line.ap19").write_bytes(b"whatever")
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")

    result = restore_from_backup(plain, project)
    assert result["ok"] is False
    assert result["reason"] == "backup_marker_missing"
    assert project.read_bytes() == b"original"


def test_restore_failure_restores_pre_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export = tmp_path / "export"
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"original")
    backup = backup_target(project, export)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("agents.plc.tia.writeback_safety.shutil.copytree", boom)
    monkeypatch.setattr("agents.plc.tia.writeback_safety.shutil.copy2", boom)

    result = restore_from_backup(
        str(backup["path"]), project, allowed_roots=[export / "backup"]
    )
    assert result["ok"] is False
    assert result["reason"] == "restore_failed"
    assert project.read_bytes() == b"original", "还原失败必须把原始文件放回去"
    leftovers = [
        p
        for p in tmp_path.iterdir()
        if p.is_dir() and p.name.startswith("Line.ap19.pre-rollback-")
    ]
    assert not leftovers
