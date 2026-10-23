"""LAD→SCL backend-silent contract tests — raw-source artifacts + fetch API.

Contract: docs/15-lad2scl-silent-contract.md — raw LAD (FlgNet XML / literal
SCL / ast_trace) lives in server-side files only; the Web client fetches it
on demand via GET /jobs/{id}/blocks/{name}/source?kind=….
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENV", "dev")

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
FIXTURE_OB = FIXTURE_DIR / "Blocks" / "Main_OB1.xml"
FIXTURE_FB = FIXTURE_DIR / "Blocks" / "FB_Motor.xml"
API_KEY = "ros_ak_test_key"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", API_KEY)
    monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(FIXTURE_DIR.parent.resolve()))
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app
    from gateway.app.services import store as mem

    mem.store.plc_jobs.clear()

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
    mem.store.plc_jobs.clear()


def test_fold_trace_param_keeps_default_behavior() -> None:
    """trace collection is opt-in: default (None) output is byte-identical."""
    from agents.plc.tia.flgnet_fold import attach_folded, fold_project
    from agents.plc.tia.simaticml import extract_project

    plain = fold_project(attach_folded(extract_project(FIXTURE_DIR, project_name="Demo")))
    traced: dict[str, list[str]] = {}
    payload = fold_project(
        attach_folded(extract_project(FIXTURE_DIR, project_name="Demo"), trace_out=traced)
    )

    assert payload == plain
    assert traced.get("FB_Motor")
    assert any(line.startswith("[net ") for line in traced["FB_Motor"])
    assert any("step:" in line for line in traced["FB_Motor"])


def test_run_ingest_job_persists_source_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Artifacts land in <export_dir>/_source_artifacts/<block>/; job keeps paths only."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.services import store as mem
    from gateway.app.services.plc.ingest import run_ingest_job
    from gateway.app.services.plc.job_store import create_job_record, get_job

    mem.store.plc_jobs.clear()
    export = tmp_path / "exports"
    shutil.copytree(FIXTURE_DIR, export)

    job = create_job_record(
        source_type="path",
        source_path=str(export),
        project_name="artifacts",
        created_by="test",
    )
    run_ingest_job(job["id"], publish_graph=False, result_root=str(tmp_path / "results"))
    try:
        stored = get_job(job["id"])
        assert stored is not None
        assert stored["status"] == "ready", stored.get("error")

        entry = (stored.get("source_artifacts") or {}).get("FB_Motor")
        assert entry, f"FB_Motor artifacts missing: {stored.get('source_artifacts')}"
        assert set(entry) == {"flgnet_xml", "literal_scl", "ast_trace"}

        # Paths only — raw LAD never inlines into the job record.
        for kind, path_str in entry.items():
            assert isinstance(path_str, str), kind
            assert Path(path_str).is_file(), (kind, path_str)

        # Anchored under the export dir's _source_artifacts/, not the package dir.
        flgnet = Path(entry["flgnet_xml"])
        assert flgnet.parent.parent.name == "_source_artifacts"
        assert flgnet.parent.name == "FB_Motor"
        assert str(export) in str(flgnet)
        assert str(stored["export_dir"]) not in str(flgnet)

        assert (
            flgnet.read_text(encoding="utf-8")
            == (export / "Blocks" / "FB_Motor.xml").read_text(encoding="utf-8")
        )
        literal = Path(entry["literal_scl"]).read_text(encoding="utf-8")
        assert literal == (stored.get("scl_sources") or {}).get("FB_Motor")
        trace = Path(entry["ast_trace"]).read_text(encoding="utf-8")
        assert trace.startswith("[block] FB_Motor\n")
        assert "[net " in trace
    finally:
        get_settings.cache_clear()
        mem.store.plc_jobs.clear()


def test_collect_source_xmls_skips_artifact_copies(tmp_path: Path) -> None:
    """Enrichment must see original exports only, not the copied flgnet.xml."""
    from gateway.app.services.plc.ingest import _collect_source_xmls

    blocks = tmp_path / "Blocks"
    blocks.mkdir()
    original = blocks / "Main_OB1.xml"
    original.write_text("<Document />", encoding="utf-8")
    arts = tmp_path / "_source_artifacts" / "Main"
    arts.mkdir(parents=True)
    (arts / "flgnet.xml").write_text("<Document />", encoding="utf-8")

    assert _collect_source_xmls(str(tmp_path)) == [str(original)]


def test_block_source_endpoint_contract(client: TestClient) -> None:
    create = client.post(
        "/api/v1/plc/jobs",
        json={"path": str(FIXTURE_OB), "project_name": "src", "publish_graph": False},
        headers=HEADERS,
    )
    assert create.status_code == 202, create.text
    job_id = create.json()["data"]["id"]

    detail = client.get(f"/api/v1/plc/jobs/{job_id}", headers=HEADERS).json()["data"]
    assert detail["status"] == "ready", detail.get("error")
    block = detail["blocks"][0]["name"]

    # Job detail exposes artifact *paths* only — no inline raw LAD.
    entry = (detail.get("source_artifacts") or {}).get(block) or {}
    assert set(entry) == {"flgnet_xml", "literal_scl", "ast_trace"}
    assert all(isinstance(v, str) for v in entry.values())

    base = f"/api/v1/plc/jobs/{job_id}/blocks/{block}/source"

    ok = client.get(base, params={"kind": "flgnet_xml"}, headers=HEADERS)
    assert ok.status_code == 200, ok.text
    body = ok.json()["data"]
    assert body["job_id"] == job_id
    assert body["block_name"] == block
    assert body["kind"] == "flgnet_xml"
    assert "<" in body["content"] and "SW.Blocks" in body["content"]

    scl = client.get(base, params={"kind": "literal_scl"}, headers=HEADERS)
    assert scl.status_code == 200
    assert scl.json()["data"]["content"] == detail["scl_sources"][block]

    trace = client.get(base, params={"kind": "ast_trace"}, headers=HEADERS)
    assert trace.status_code == 200
    assert f"[block] {block}" in trace.json()["data"]["content"]

    bad = client.get(base, params={"kind": "nope"}, headers=HEADERS)
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "PLC_BLOCK_SOURCE_KIND_INVALID"

    missing_block = client.get(
        f"/api/v1/plc/jobs/{job_id}/blocks/NOPE/source",
        params={"kind": "flgnet_xml"},
        headers=HEADERS,
    )
    assert missing_block.status_code == 404
    assert missing_block.json()["detail"]["code"] == "PLC_BLOCK_SOURCE_NOT_FOUND"

    missing_job = client.get(
        "/api/v1/plc/jobs/plc_doesnotexist/blocks/Main/source",
        params={"kind": "flgnet_xml"},
        headers=HEADERS,
    )
    assert missing_job.status_code == 404
    assert missing_job.json()["detail"]["code"] == "PLC_JOB_NOT_FOUND"


def test_block_source_fixture_xml_roundtrip(client: TestClient) -> None:
    """flgnet.xml artifact equals the source export file byte-for-byte (single block)."""
    create = client.post(
        "/api/v1/plc/jobs",
        json={"path": str(FIXTURE_FB), "project_name": "fb", "publish_graph": False},
        headers=HEADERS,
    )
    job_id = create.json()["data"]["id"]
    detail = client.get(f"/api/v1/plc/jobs/{job_id}", headers=HEADERS).json()["data"]
    assert detail["status"] == "ready", detail.get("error")

    resp = client.get(
        f"/api/v1/plc/jobs/{job_id}/blocks/FB_Motor/source",
        params={"kind": "flgnet_xml"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["content"] == FIXTURE_FB.read_text(encoding="utf-8")
