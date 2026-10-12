"""Unit tests — writeback stages SCL and does not archive on compile-fail."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.changeset import PlcChangeOp, PlcChangeSet
from agents.plc.tia.writeback import execute_writeback, prepare_writeback


def test_execute_writeback_stages_scl_and_skips_archive_on_compile_fail(
    tmp_path: Path, monkeypatch
):
    bundle_root = tmp_path / "export"
    cs = PlcChangeSet(
        id="wb",
        ops=[
            PlcChangeOp(
                kind="rewrite_scl",
                payload={
                    "block_name": "FB_Motor",
                    "scl_text": (
                        'FUNCTION_BLOCK "FB_Motor"\n'
                        "BEGIN\n    #Q := TRUE;\nEND_FUNCTION_BLOCK\n"
                    ),
                },
            )
        ],
        notes=["optimize_plan:# plan\n"],
    )
    bundle = prepare_writeback(bundle_root, cs, [])
    staged = list((bundle / "external_sources").glob("*.scl"))
    assert staged, "expected staged .scl in import_bundle/external_sources"

    calls: list[str] = []

    def fake_xml(*_a, **_k):
        raise AssertionError("XML import should not run when no XML staged")

    def fake_scl(project_path, scl_path, **_k):
        calls.append(f"scl:{Path(scl_path).name}")
        return {"ok": True, "generate": {"ok": True}}

    def fake_compile(project_path, **_k):
        calls.append("compile")
        return {
            "ok": False,
            "compile": {
                "ok": False,
                "apiAvailable": True,
                "state": "Error",
                "errorCount": 2,
                "inconsistentBlocks": ["FB_Motor"],
                "error": {"code": "compile_failed", "message": "Compile State=Error errors=2"},
            },
        }

    def fake_archive(*_a, **_k):
        calls.append("archive")
        raise AssertionError("must not archive when compile fails")

    monkeypatch.setattr(
        "agents.plc.tia.writeback.import_block_via_openness_cli", fake_xml
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.generate_from_source_via_openness_cli", fake_scl
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.compile_plc_via_openness_cli", fake_compile
    )

    project = tmp_path / "Line.ap19"
    project.write_bytes(b"fake")
    result = execute_writeback(project, bundle, plc_name="PLC_1")
    assert result["import_ok"] is True
    assert result["compiled_ok"] is False
    assert result["ok"] is False
    assert result["scl_imported"] == 1
    assert "compile" in calls
    assert any(c.startswith("scl:") for c in calls)
    assert "archive" not in calls
    compile = result["compile"]["compile"]
    assert compile["inconsistentBlocks"] == ["FB_Motor"]


def test_confirm_job_writeback_no_zap_on_compile_fail(tmp_path: Path, monkeypatch):
    from gateway.app.services import plc_jobs as plc

    export = tmp_path / "job_export"
    export.mkdir()
    job = {
        "id": "plc_test",
        "status": "ready",
        "project_path": str(tmp_path / "Line.ap19"),
        "export_dir": str(export),
        "knowledge_graph": {"nodes": [], "edges": []},
        "blocks": [{"name": "FB_Motor", "type": "FB", "body_available": True}],
        "source_xmls": [],
        "changeset": PlcChangeSet(
            id="cs1",
            ops=[
                PlcChangeOp(
                    kind="rewrite_scl",
                    payload={
                        "block_name": "FB_Motor",
                        "scl_text": 'FUNCTION_BLOCK "FB_Motor"\nBEGIN\nEND_FUNCTION_BLOCK\n',
                    },
                )
            ],
        ).to_dict(),
    }
    (tmp_path / "Line.ap19").write_bytes(b"fake")

    monkeypatch.setattr(
        "agents.plc.tia.writeback.generate_from_source_via_openness_cli",
        lambda *a, **k: {"ok": True},
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.compile_plc_via_openness_cli",
        lambda *a, **k: {
            "ok": False,
            "compile": {
                "ok": False,
                "apiAvailable": True,
                "errorCount": 1,
                "inconsistentBlocks": ["FB_Motor"],
            },
        },
    )
    archived = {"called": False}

    def boom(*_a, **_k):
        archived["called"] = True
        raise AssertionError("archive must not run")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.archive_project_via_openness_cli", boom
    )

    result = plc.confirm_job_writeback(
        job,
        project_path=str(tmp_path / "Line.ap19"),
        execute_openness_import=True,
        archive_zap=True,
    )
    assert result.get("zap_path") is None
    assert result.get("zap_archive", {}).get("ok") is False
    assert archived["called"] is False
    assert result["openness"]["ok"] is False


def test_filter_changeset_for_focus_keeps_helpers_drops_dead_blocks():
    from agents.plc.tia.changeset import filter_changeset_for_focus, helper_block_names_for_focus

    cs = PlcChangeSet(
        id="mix",
        ops=[
            PlcChangeOp(
                kind="rewrite_scl",
                payload={
                    "block_name": "FB_A",
                    "scl_text": 'FUNCTION_BLOCK "FB_A"\nBEGIN\nEND_FUNCTION_BLOCK\n',
                },
            ),
            PlcChangeOp(
                kind="stage_scl_source",
                payload={
                    "block_name": "FC_A_Extract",
                    "scl_text": 'FUNCTION "FC_A_Extract" : Void\nEND_FUNCTION\n',
                    "new_block": True,
                },
            ),
            PlcChangeOp(
                kind="add_edge",
                payload={
                    "source": "Block::FB_A",
                    "target": "Block::FC_A_Extract",
                    "type": "CALLS",
                    "props": {"evidence": "decouple_extract"},
                },
            ),
            PlcChangeOp(
                kind="annotate",
                payload={"block_name": "FB_orphan", "text": "[OPT] dead"},
            ),
            PlcChangeOp(
                kind="stage_xml_import",
                payload={"block_name": "FB_orphan", "xml_path": "/tmp/FB_orphan.xml"},
            ),
            PlcChangeOp(
                kind="rewrite_scl",
                payload={
                    "block_name": "FB_Motor",
                    "scl_text": 'FUNCTION_BLOCK "FB_Motor"\nEND_FUNCTION_BLOCK\n',
                },
            ),
        ],
        notes=["optimize:decouple:FB_A->FC_A_Extract", "optimize:dead_block:FB_orphan"],
    )
    assert helper_block_names_for_focus(cs, "FB_A") == {"FC_A_Extract"}
    focused = filter_changeset_for_focus(cs, "FB_A")
    names = {str(o.payload.get("block_name") or "") for o in focused.ops if o.payload.get("block_name")}
    assert "FB_A" in names
    assert "FC_A_Extract" in names
    assert "FB_orphan" not in names
    assert "FB_Motor" not in names
    assert any(o.kind == "add_edge" for o in focused.ops)
    whole = filter_changeset_for_focus(cs, None)
    assert len(whole.ops) == len(cs.ops)


def test_confirm_skip_write_does_not_execute_openness(tmp_path: Path, monkeypatch):
    from gateway.app.services import plc_jobs as plc

    export = tmp_path / "job_export"
    export.mkdir()
    job = {
        "id": "plc_skip",
        "status": "ready",
        "export_dir": str(export),
        "knowledge_graph": {"nodes": [], "edges": []},
        "blocks": [
            {
                "name": "FB_Locked",
                "type": "FB",
                "protected": True,
                "body_available": False,
                "interface_only": True,
            }
        ],
        "source_xmls": [str(tmp_path / "unrelated.xml")],
        "scl_skipped": [
            {"block": "FB_Locked", "reason": "know_how", "detail": "Know-how / protected"}
        ],
        "changeset": PlcChangeSet(
            id="cs-kh",
            ops=[
                PlcChangeOp(
                    kind="annotate",
                    payload={"block_name": "FB_Locked", "text": "[OPT] know-how, report only"},
                )
            ],
        ).to_dict(),
        "engineer_understanding": {
            "constraints": {"do_not_touch": [], "must_keep_nested": [], "may_extract": []}
        },
    }
    (tmp_path / "unrelated.xml").write_text("<SW.Blocks.FB/>", encoding="utf-8")
    opened = {"n": 0}

    def boom(*_a, **_k):
        opened["n"] += 1
        raise AssertionError("Openness must not run when there is nothing to write")

    monkeypatch.setattr("agents.plc.tia.writeback.execute_writeback", boom)
    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.archive_project_via_openness_cli", boom
    )
    result = plc.confirm_job_writeback(
        job,
        block_name="FB_Locked",
        execute_openness_import=True,
        archive_zap=True,
    )
    assert opened["n"] == 0
    assert result.get("skipped") is True
    assert result.get("zap_path") is None
    assert result.get("openness", {}).get("skipped") is True
    reason = str(result.get("skip_reason") or result.get("openness", {}).get("reason") or "")
    assert reason
    assert "Openness" in reason or "Know-how" in reason or "程序体" in reason or "无可写" in reason


def test_confirm_focus_does_not_apply_unrelated_dead_block(tmp_path: Path, monkeypatch):
    from gateway.app.services import plc_jobs as plc

    export = tmp_path / "job_export"
    export.mkdir()
    ap = tmp_path / "Line.ap19"
    ap.write_bytes(b"fake")
    job = {
        "id": "plc_focus",
        "status": "ready",
        "project_path": str(ap),
        "export_dir": str(export),
        "knowledge_graph": {"nodes": [], "edges": []},
        "blocks": [
            {"name": "FB_A", "type": "FB", "body_available": True},
            {"name": "FB_orphan", "type": "FB", "body_available": True},
        ],
        "source_xmls": [],
        "changeset": PlcChangeSet(
            id="cs-mix",
            ops=[
                PlcChangeOp(
                    kind="rewrite_scl",
                    payload={
                        "block_name": "FB_A",
                        "scl_text": 'FUNCTION_BLOCK "FB_A"\nBEGIN\n    #Q := TRUE;\nEND_FUNCTION_BLOCK\n',
                    },
                ),
                PlcChangeOp(
                    kind="stage_scl_source",
                    payload={
                        "block_name": "FC_A_Extract",
                        "scl_text": 'FUNCTION "FC_A_Extract" : Void\nBEGIN\nEND_FUNCTION\n',
                        "new_block": True,
                    },
                ),
                PlcChangeOp(
                    kind="add_edge",
                    payload={
                        "source": "Block::FB_A",
                        "target": "Block::FC_A_Extract",
                        "type": "CALLS",
                        "props": {"evidence": "decouple_extract"},
                    },
                ),
                PlcChangeOp(
                    kind="rewrite_scl",
                    payload={
                        "block_name": "FB_orphan",
                        "scl_text": 'FUNCTION_BLOCK "FB_orphan"\nEND_FUNCTION_BLOCK\n',
                    },
                ),
            ],
            notes=["optimize:decouple:FB_A->FC_A_Extract", "optimize:dead_block:FB_orphan"],
        ).to_dict(),
    }
    staged: list[str] = []

    def fake_scl(_project, scl_path, **_k):
        staged.append(Path(scl_path).stem)
        return {"ok": True}

    monkeypatch.setattr(
        "agents.plc.tia.writeback.generate_from_source_via_openness_cli", fake_scl
    )
    monkeypatch.setattr(
        "agents.plc.tia.writeback.compile_plc_via_openness_cli",
        lambda *_a, **_k: {"ok": True, "compile": {"ok": True, "apiAvailable": True}},
    )
    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.archive_project_via_openness_cli",
        lambda *_a, **_k: tmp_path / "out.zap",
    )
    monkeypatch.setattr(
        plc,
        "resolve_allowed_path",
        lambda path, settings=None: Path(path),
    )
    result = plc.confirm_job_writeback(
        job,
        project_path=str(ap),
        block_name="FB_A",
        execute_openness_import=True,
        archive_zap=True,
    )
    assert result.get("scope") == "block:FB_A"
    assert "FC_A_Extract" in (result.get("helper_blocks") or [])
    assert "FB_A" in staged
    assert "FC_A_Extract" in staged
    assert "FB_orphan" not in staged

