"""WS4 Evidence Passport unit tests — immutable, bound audit chain."""
from __future__ import annotations

from processos.evidence import EvidencePassport


def test_record_and_query_by_revision():
    p = EvidencePassport()
    p.record("validation", revision_hash="sha256:aaa", evidence_level="offline_verified", payload={"ok": True})
    p.record("simulation", revision_hash="sha256:aaa", evidence_level="simulated")
    p.record("validation", revision_hash="sha256:bbb", evidence_level="offline_verified")
    assert len(p.for_revision("sha256:aaa")) == 2
    assert len(p.for_revision("sha256:bbb")) == 1
    assert len(p.all()) == 3


def test_chain_for_job_binds_artifact():
    p = EvidencePassport()
    p.record("delivery_queued", revision_hash="sha256:x", evidence_level="designed", job_id="JOB-1")
    p.record("native_compile", revision_hash="sha256:x", evidence_level="V19_compiled",
             job_id="JOB-1", artifact_sha256="sha256:art")
    chain = p.chain_for_job("JOB-1")
    assert len(chain) == 2
    assert chain[-1].artifact_sha256 == "sha256:art"
    assert chain[-1].evidence_level == "V19_compiled"


def test_entries_immutable():
    p = EvidencePassport()
    e = p.record("approval", revision_hash="sha256:x", evidence_level="offline_verified")
    try:
        e.kind = "tampered"  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_to_dict_serializable():
    p = EvidencePassport()
    p.record("validation", revision_hash="sha256:x", evidence_level="offline_verified", payload={"n": 1})
    d = p.to_dict()
    assert d["entries"][0]["payload"]["n"] == 1