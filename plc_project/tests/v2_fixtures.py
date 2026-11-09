"""Shared, deterministic V2 test fixtures (offline only).

Every fixture is a pure, fully-specified EngineeringIRV2: 1 driver + 6 steps +
6 transitions + exception paths. No TIA Portal and no network is involved.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from plc_engine.components.catalog import DriverCatalog
from plc_engine.engineering_ir.models import EngineeringIRV2, new_project_ir
from plc_engine.process.guard_ast import guard_not, guard_signal
from plc_engine.process.sequence_ir import (
    Action,
    ExceptionTrigger,
    SequenceException,
    SequenceIR,
    Step,
    Transition,
)
from gateway.app.services.plc.workspace_v2 import WorkspaceStore


def build_valid_demo_ir(project_id: str = "prj_demo") -> EngineeringIRV2:
    """Build a fully valid demo IR (US-2/US-3 baseline: S2 hold = 1000ms)."""
    ir = new_project_ir(project_id)
    component, spec = DriverCatalog().create_component(
        "double_acting_cylinder", component_id="CM1", overrides={"move_timeout_ms": 3000}
    )
    ir.components.append(component)
    ir.driver_specs[spec.id] = spec
    signal = guard_signal
    ir.process = SequenceIR(
        id="SEQ_1",
        mode="AUTO",
        initial_step="S0",
        steps=[
            Step(id="S0", name="IDLE", source_id="S0"),
            Step(
                id="S1", name="EXTEND", max_duration_ms=500, failure_target="FAULT",
                entry_actions=[Action(id="A1", target_component_id="CM1", command="CmdExtend", value=True, source_id="S1")],
                source_id="S1",
            ),
            Step(id="S2", name="HOLD", min_duration_ms=1000, max_duration_ms=5000, failure_target="FAULT", source_id="S2"),
            Step(
                id="S3", name="RETRACT", max_duration_ms=500, failure_target="FAULT",
                entry_actions=[Action(id="A2", target_component_id="CM1", command="CmdRetract", value=True, source_id="S3")],
                source_id="S3",
            ),
            Step(id="S4", name="DONE", source_id="S4"),
            Step(id="FAULT", name="FAULT", source_id="FAULT"),
        ],
        transitions=[
            Transition(id="T0", from_step="S0", to_step="S1", guard_ast=signal("CmdStart"), priority=0, source_id="T0"),
            Transition(id="T1", from_step="S1", to_step="S2", guard_ast=signal("SensorOut"), priority=0, source_id="T1"),
            Transition(id="T2", from_step="S2", to_step="S3", guard_ast=signal("HoldDone"), priority=0, source_id="T2"),
            Transition(id="T3", from_step="S3", to_step="S4", guard_ast=signal("SensorIn"), priority=0, source_id="T3"),
            Transition(id="T4", from_step="S4", to_step="S0", guard_ast=guard_not(signal("CmdStart")), priority=0, source_id="T4"),
            Transition(id="T5", from_step="FAULT", to_step="S0", guard_ast=signal("Reset"), priority=0, source_id="T5"),
        ],
        exceptions=[
            SequenceException(id="E1", from_step="S1", to_step="FAULT", trigger=ExceptionTrigger.TIMEOUT, source_id="E1"),
            SequenceException(id="E2", from_step="S2", to_step="FAULT", trigger=ExceptionTrigger.TIMEOUT, source_id="E2"),
            SequenceException(id="E3", from_step="S3", to_step="FAULT", trigger=ExceptionTrigger.TIMEOUT, source_id="E3"),
            SequenceException(id="E4", from_step="S0", to_step="FAULT", trigger=ExceptionTrigger.SAFETY_PERMIT_LOST, source_id="E4"),
            SequenceException(id="E5", from_step="S4", to_step="FAULT", trigger=ExceptionTrigger.SAFETY_PERMIT_LOST, source_id="E5"),
        ],
    )
    ir.refresh_hash()
    return ir


def build_store(tmp_path: Path, *, project_id: str = "prj_demo") -> WorkspaceStore:
    """Create an isolated WAL store preloaded with a valid demo project.

    Also redirects the V2 evidence ledger and artifact store into this test's
    temporary directory so contract tests never pollute repository evidence.
    """
    os.environ["PLC_V2_EVIDENCE_ROOT"] = str(tmp_path / "evidence_v2")
    os.environ["PLC_V2_ARTIFACT_ROOT"] = str(tmp_path / "artifact_store")
    store = WorkspaceStore(
        db_path=str(tmp_path / "v2.db"), ir_store_dir=str(tmp_path / "ir_store")
    )
    store.create_project(project_id, build_valid_demo_ir(project_id))
    return store


def make_fake_openness_worker(
    tmp_path: Path,
    *,
    error_count: int = 0,
    warning_count: int = 2,
    reopen_ok: bool = True,
    archive_ok: bool = True,
    create_path_ok: bool = True,
    save_ok: bool = True,
) -> tuple[Any, Path]:
    """Deterministic fake C# Openness worker (explicitly MOCKED evidence).

    Returns ``(worker_callable, exact_archive_path)``. It never touches TIA
    Portal; injected adapters declare ``real_machine`` separately.
    """
    workspace = tmp_path / "ws"
    archive_dir = workspace / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / "Demo.zap19"
    if archive_ok:
        archive_file.write_bytes(b"deterministic native archive bytes")
    project_path = str(workspace / "tia_project" / "Demo.ap19")

    def worker(command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
        if command == "create-project":
            if not create_path_ok:
                return {"ok": True, "create": {"ok": True}}  # D-1: missing projectPath
            return {"ok": True, "create": {"ok": True, "projectPath": project_path}}
        if command == "create-device":
            return {"ok": True, "device": {"typeId": args[3] if len(args) > 3 else ""}}
        if command in ("generate-from-source", "import-xml"):
            return {"ok": True, "imported": args[-1] if args else ""}
        if command == "compile-plc":
            return {"ok": True, "compile": {"state": "Success", "errorCount": error_count,
                                            "warningCount": warning_count}}
        if command == "save-project":
            return {"ok": save_ok, "save": {"ok": save_ok}}
        if command == "archive-project":
            return {"ok": archive_ok, "archive": {
                "ok": archive_ok, "archivePath": str(archive_file),
                "archiveSha256": "", "sizeBytes": archive_file.stat().st_size if archive_file.exists() else 0,
            }}
        if command == "retrieve":
            return {"ok": reopen_ok, "reopenOk": reopen_ok, "retrieve": {
                "ok": True, "reopenOk": reopen_ok,
                "projectPath": str(workspace / "reopen" / "Demo.ap19"),
            }}
        return {"ok": False, "error": f"unknown command {command}"}

    return worker, archive_file
