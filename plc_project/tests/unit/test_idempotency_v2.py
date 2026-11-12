"""WP-06: idempotency, path whitelist, schema migration, minimum disclosure."""
from __future__ import annotations

import io
import zipfile

from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.fault_injection_v2 import (
    PathWhitelist,
    minimal_disclosure,
    reject_bad_xml,
    reject_bad_zip,
    schema_migration_check,
)
from plc_engine.engineering_ir.patch import make_patch
from tests.v2_fixtures import build_store, build_valid_demo_ir


def test_patch_request_id_is_idempotent(tmp_path) -> None:
    store = build_store(tmp_path)
    patch = make_patch("prj_demo", 0, [{"op": "set_view_layout", "layout": {"x": 1}}], request_id="req_idem_1")
    first = store.commit_patch("prj_demo", patch)
    second = store.commit_patch("prj_demo", patch)
    assert first.revision == second.revision == 1
    assert second.idempotent_hit is True
    assert len(store.list_revisions("prj_demo")) == 2


def test_delivery_idempotency_key_returns_the_same_job(tmp_path) -> None:
    """The idempotency key is enforced at the store UNIQUE constraint.

    API-level 202 idempotency with an approved ChangeSet is already covered by
    T01/T02 contract tests; here we prove the underlying persistence guarantee.
    """
    store = build_store(tmp_path)
    first, created1 = store.insert_job(
        "job_idem_1", project_id="prj_demo", changeset_id="cs_idem",
        idempotency_key="delivery_idem_1", expected_baseline_hash="",
    )
    second, created2 = store.insert_job(
        "job_idem_2", project_id="prj_demo", changeset_id="cs_idem",
        idempotency_key="delivery_idem_1", expected_baseline_hash="",
    )
    assert created1 is True and created2 is False
    assert first["id"] == second["id"] == "job_idem_1"
    assert DeliveryCoordinator(store).get_job("job_idem_1")["state"] == "QUEUED"


def test_path_whitelist_rejects_browser_supplied_paths(tmp_path) -> None:
    whitelist = PathWhitelist(tmp_path)
    assert whitelist.is_allowed("artifact_store/ab/cde.zap19") is True
    for bad in ("../../etc/passwd", "/etc/passwd", "C:/Windows/system32", "a/../../b", "x|whoami", ""):
        assert whitelist.is_allowed(bad) is False, bad
    try:
        whitelist.assert_allowed("../escape")
    except PermissionError:
        pass
    else:
        raise AssertionError("path whitelist must fail closed")


def test_schema_migration_check_sees_all_ten_tables(tmp_path) -> None:
    store = build_store(tmp_path)
    report = schema_migration_check(store)
    assert report["ok"] is True
    assert len(report["expected_tables"]) == 10
    assert report["missing_tables"] == []


def test_minimum_disclosure_never_sends_whole_project() -> None:
    ir = build_valid_demo_ir().to_dict()
    sliced = minimal_disclosure(ir, max_blocks=1)
    assert len(sliced["block_index"]) <= 1
    assert "components" not in sliced  # full objects are not forwarded
    assert "legacy_raw" not in sliced
    assert sliced["notice"].startswith("minimum disclosure")


def test_bad_xml_dtd_is_rejected() -> None:
    ok, why = reject_bad_xml(b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>")
    assert ok is False and "BAD_XML" in why
    ok2, why2 = reject_bad_xml(b"<broken><a></broken>")
    assert ok2 is False and "BAD_XML" in why2
    ok3, _ = reject_bad_xml(b"<root><a>1</a></root>")
    assert ok3 is True


def test_bad_zip_traversal_is_rejected(tmp_path) -> None:
    target = tmp_path / "evil.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("../escape.txt", "payload")
    ok, why = reject_bad_zip(target)
    assert ok is False and "BAD_ZIP_TRAVERSAL" in why

    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("scl/FB.scl", "FUNCTION_BLOCK FB")
    ok2, _ = reject_bad_zip(good)
    assert ok2 is True

    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not-a-zip")
    ok3, why3 = reject_bad_zip(broken)
    assert ok3 is False and "BAD_ZIP" in why3
