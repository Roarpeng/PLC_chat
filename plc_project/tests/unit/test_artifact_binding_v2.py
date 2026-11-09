"""AC-01-6 / D-2: exact 4-tuple artifact binding, no directory wildcard."""
from __future__ import annotations

import pytest

from gateway.app.services.plc.artifact_store_v2 import (
    ArtifactJobMismatchError,
    ArtifactNotFoundError,
    ArtifactStore,
)
from gateway.app.services.plc.native_artifact_v2 import (
    assert_exact_binding,
    attach_evidence,
    evidence_bundle,
)
from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine.engineering_ir.models import NativeTiaArtifact
from plc_engine.canonical import compute_file_sha256


def build_files(tmp_path):
    """Create one real archive file plus a DECOY older archive in the same dir."""
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    real = archive_dir / "job_current.zap19"
    real.write_bytes(b"CURRENT JOB NATIVE ARCHIVE")
    (archive_dir / "job_old.zap19").write_bytes(b"OLD JOB ARCHIVE - MUST NOT BE SERVED")
    return real, archive_dir


def make_artifact(real_path, project_id="prj_a", job_id="job_1", sha="") -> NativeTiaArtifact:
    return NativeTiaArtifact(
        artifact_id="a_exact_1", job_id=job_id, project_id=project_id,
        project_path="C:/work/Demo.ap19", archive_path=str(real_path),
        archive_sha256=sha or compute_file_sha256(real_path),
        size_bytes=real_path.stat().st_size, kind="zap19", reopen_ok=True,
    )


def test_exact_four_tuple_authorisation(tmp_path) -> None:
    real, _ = build_files(tmp_path)
    store = WorkspaceStore(db_path=str(tmp_path / "v2.db"), ir_store_dir=str(tmp_path / "ir"))
    artifact_store = ArtifactStore(store, root=tmp_path / "artifact_store")
    artifact = make_artifact(real)
    stored = artifact_store.store_file(real, kind="zap19")
    artifact_store.register(artifact.to_dict(), stored=stored)

    assert artifact_store.authorize("prj_a", "job_1", "a_exact_1", artifact.archive_sha256) is True
    assert artifact_store.authorize("prj_a", "job_OTHER", "a_exact_1", artifact.archive_sha256) is False
    assert artifact_store.authorize("prj_other", "job_1", "a_exact_1", artifact.archive_sha256) is False
    assert artifact_store.authorize("prj_a", "job_1", "a_exact_1", "sha256:" + "0" * 64) is False


def test_download_uses_exact_artifact_and_ignores_decoy_archive(tmp_path) -> None:
    real, archive_dir = build_files(tmp_path)
    store = WorkspaceStore(db_path=str(tmp_path / "v2.db"), ir_store_dir=str(tmp_path / "ir"))
    artifact_store = ArtifactStore(store, root=tmp_path / "artifact_store")
    artifact = make_artifact(real)
    stored = artifact_store.store_file(real, kind="zap19")
    artifact_store.register(artifact.to_dict(), stored=stored)

    data, meta = artifact_store.download("a_exact_1", project_id="prj_a", job_id="job_1",
                                          sha256=artifact.archive_sha256)
    assert data == b"CURRENT JOB NATIVE ARCHIVE"
    assert meta["job_id"] == "job_1"
    assert b"OLD JOB" not in data
    assert (archive_dir / "job_old.zap19").exists()  # decoy still present, never scanned


def test_cross_job_download_is_rejected(tmp_path) -> None:
    real, _ = build_files(tmp_path)
    store = WorkspaceStore(db_path=str(tmp_path / "v2.db"), ir_store_dir=str(tmp_path / "ir"))
    artifact_store = ArtifactStore(store, root=tmp_path / "artifact_store")
    artifact = make_artifact(real)
    stored = artifact_store.store_file(real)
    artifact_store.register(artifact.to_dict(), stored=stored)
    with pytest.raises(ArtifactJobMismatchError):
        artifact_store.download("a_exact_1", project_id="prj_a", job_id="job_2")
    with pytest.raises(ArtifactNotFoundError):
        artifact_store.download("a_missing", project_id="prj_a", job_id="job_1")


def test_sha256_mismatch_is_rejected(tmp_path) -> None:
    real, _ = build_files(tmp_path)
    store = WorkspaceStore(db_path=str(tmp_path / "v2.db"), ir_store_dir=str(tmp_path / "ir"))
    artifact_store = ArtifactStore(store, root=tmp_path / "artifact_store")
    artifact = make_artifact(real)
    stored = artifact_store.store_file(real)
    artifact_store.register(artifact.to_dict(), stored=stored)
    with pytest.raises(ArtifactJobMismatchError):
        artifact_store.download("a_exact_1", project_id="prj_a", job_id="job_1",
                                sha256="sha256:" + "f" * 64)


def test_evidence_bundle_is_bound_to_exact_artifact(tmp_path) -> None:
    real, _ = build_files(tmp_path)
    artifact = attach_evidence(make_artifact(real), real_tia_v19_tested=False,
                               raw_evidence_path="evidence/v2/T02/x.json")
    assert artifact.evidence_level.value == "pending_real_machine"
    bundle = evidence_bundle(artifact, job_events=[{"seq": 0, "state": "FAILED"}])
    assert bundle["artifact_id"] == "a_exact_1"
    assert bundle["real_tia_v19_tested"] is False
    assert bundle["archive"]["sha256"] == artifact.archive_sha256
    assert "no V19 real" in bundle["notice"]
    assert "must never be shown" in bundle["notice"]


def test_assert_exact_binding_rejects_foreign_job(tmp_path) -> None:
    real, _ = build_files(tmp_path)
    artifact = make_artifact(real)
    assert assert_exact_binding(artifact, project_id="prj_a", job_id="job_1",
                                sha256=artifact.archive_sha256) is True
    assert assert_exact_binding(artifact, project_id="prj_a", job_id="job_9",
                                sha256=artifact.archive_sha256) is False


def test_store_file_is_hash_named_and_whitelisted(tmp_path) -> None:
    real, _ = build_files(tmp_path)
    store = WorkspaceStore(db_path=str(tmp_path / "v2.db"), ir_store_dir=str(tmp_path / "ir"))
    artifact_store = ArtifactStore(store, root=tmp_path / "artifact_store")
    descriptor = artifact_store.store_file(real)
    assert descriptor["path"].startswith("artifact_store/")
    assert ".." not in descriptor["path"]
    assert descriptor["sha256"] == compute_file_sha256(real)
    with pytest.raises(ArtifactJobMismatchError):
        artifact_store._resolve("../../../etc/passwd")
