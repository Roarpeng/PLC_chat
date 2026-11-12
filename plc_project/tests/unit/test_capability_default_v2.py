"""P-07: fail-closed capability_manifest default + real legacy-DB migration."""
from __future__ import annotations

import sqlite3

from gateway.app.services.plc.workspace_v2 import SCHEMA_USER_VERSION, WorkspaceStore

LEGACY_SCHEMA = """
CREATE TABLE capability_manifest (
  probe_receipt_id TEXT PRIMARY KEY, tia_version TEXT NOT NULL,
  cpu_templates_json TEXT NOT NULL, probed_at TEXT NOT NULL,
  raw_probe_receipt TEXT NOT NULL, evidence_level TEXT NOT NULL DEFAULT 'V19_real'
);
"""

INSERT_MINIMAL = (
    "INSERT INTO capability_manifest "
    "(probe_receipt_id, tia_version, cpu_templates_json, probed_at, raw_probe_receipt) "
    "VALUES (?,?,?,?,?)"
)


def _insert_minimal(store: WorkspaceStore, receipt_id: str) -> None:
    with store._lock:  # noqa: SLF001 - contract test of the schema default
        store._conn.execute(  # noqa: SLF001
            INSERT_MINIMAL, (receipt_id, "V19", "[]", "2026-11-09T00:00:00+00:00", "{}")
        )


def _level(store: WorkspaceStore, receipt_id: str) -> str:
    with store._lock:  # noqa: SLF001
        row = store._conn.execute(  # noqa: SLF001
            "SELECT evidence_level FROM capability_manifest WHERE probe_receipt_id=?", (receipt_id,)
        ).fetchone()
    return str(row["evidence_level"])


def test_new_db_omitted_evidence_level_fails_closed(tmp_path) -> None:
    store = WorkspaceStore(db_path=str(tmp_path / "new.db"), ir_store_dir=str(tmp_path / "ir"))
    _insert_minimal(store, "g0_omitted")
    assert _level(store, "g0_omitted") == "pending_real_machine"
    store.close()


def test_legacy_db_is_really_migrated(tmp_path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.executescript(LEGACY_SCHEMA)
    # Pre-existing row written by the OLD default must be preserved verbatim.
    conn.execute(INSERT_MINIMAL, ("g0_legacy", "V19", "[]", "2026-11-09T00:00:00+00:00", "{}"))
    assert conn.execute(
        "SELECT evidence_level FROM capability_manifest WHERE probe_receipt_id='g0_legacy'"
    ).fetchone()[0] == "V19_real"
    conn.close()

    store = WorkspaceStore(db_path=str(db), ir_store_dir=str(tmp_path / "ir"))
    with store._lock:  # noqa: SLF001
        version = int(store._conn.execute("PRAGMA user_version").fetchone()[0])  # noqa: SLF001
        ddl = str(store._conn.execute(  # noqa: SLF001
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='capability_manifest'"
        ).fetchone()["sql"])
    assert version == SCHEMA_USER_VERSION == 2
    assert "pending_real_machine" in ddl and "V19_real" not in ddl
    assert _level(store, "g0_legacy") == "V19_real"  # history preserved, not erased

    _insert_minimal(store, "g0_after_migration")
    assert _level(store, "g0_after_migration") == "pending_real_machine"
    store.close()


def test_migration_is_idempotent_and_keeps_rows(tmp_path) -> None:
    db = tmp_path / "legacy2.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(INSERT_MINIMAL, ("g0_a", "V19", "[]", "2026-11-09T00:00:00+00:00", "{}"))
    conn.close()

    first = WorkspaceStore(db_path=str(db), ir_store_dir=str(tmp_path / "ir"))
    assert _level(first, "g0_a") == "V19_real"
    first.close()
    second = WorkspaceStore(db_path=str(db), ir_store_dir=str(tmp_path / "ir"))
    assert _level(second, "g0_a") == "V19_real"
    with second._lock:  # noqa: SLF001
        assert int(second._conn.execute("PRAGMA user_version").fetchone()[0]) == 2  # noqa: SLF001
    second.close()
