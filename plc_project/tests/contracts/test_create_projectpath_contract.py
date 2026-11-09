"""D-1 / D-2 / Q-06 receipt contracts (C# CamelCase, exact paths, reopen)."""
from __future__ import annotations

from pathlib import Path

import pytest

from gateway.app.services.plc.tia_delivery_v2 import (
    ArchiveMissingError,
    CreatePathMissingError,
    ReopenFailedError,
    unpack_archive_path,
    unpack_create_project_path,
    unpack_retrieve_reopen,
)

REPO = Path(__file__).resolve().parents[2]


def test_create_project_reply_uses_create_project_path() -> None:
    receipt = {"ok": True, "create": {"ok": True, "projectPath": "C:/work/Demo.ap19",
                                      "projectName": "Demo", "api": "Projects.Create"}}
    assert unpack_create_project_path(receipt) == "C:/work/Demo.ap19"


def test_missing_create_object_is_explicit_failure() -> None:
    with pytest.raises(CreatePathMissingError) as exc:
        unpack_create_project_path({"ok": True, "path": "C:/guessed.ap19"})
    assert "missing the 'create' object" in str(exc.value)


def test_missing_project_path_is_explicit_failure_never_guessed() -> None:
    with pytest.raises(CreatePathMissingError) as exc:
        unpack_create_project_path({"ok": True, "create": {"ok": True, "project": "Demo"}})
    assert "create.projectPath" in str(exc.value)
    assert "guess" in str(exc.value).lower()


def test_ok_false_is_explicit_failure() -> None:
    with pytest.raises(CreatePathMissingError):
        unpack_create_project_path({"ok": False, "create": {"projectPath": "C:/work/Demo.ap19"}})


def test_legacy_wrong_keys_are_not_accepted_as_fallback() -> None:
    """The old D-1 guess keys (path / project / dir+name) must never satisfy the contract."""
    for receipt in (
        {"ok": True, "path": "C:/old/path.ap19"},
        {"ok": True, "project": "C:/old/project.ap19"},
        {"ok": True, "create": {"path": "C:/old/create_path.ap19"}},
    ):
        with pytest.raises(CreatePathMissingError):
            unpack_create_project_path(receipt)


def test_legacy_tia_delivery_source_no_longer_guesses_path() -> None:
    source = (REPO / "gateway/app/services/plc/tia_delivery.py").read_text(encoding="utf-8")
    assert 'created.get("path") or created.get("project")' not in source
    assert "unpack_create_project_path(created)" in source
    assert "禁止猜路径" in source


def test_csharp_source_has_no_directory_wildcard_fallback() -> None:
    source = (REPO / "industrial/tia_openness_cli/src/TiaOpenness.Server/ProjectService.cs").read_text(encoding="utf-8")
    assert "candidates[0]" not in source
    assert "Directory.GetFiles(dir" not in source
    assert "ExactArchivePolicy.Verify" in source
    assert "archive_missing" in source


def test_csharp_create_project_reply_is_camel_case() -> None:
    program = (REPO / "industrial/tia_openness_cli/src/TiaOpenness.Server/Program.cs").read_text(encoding="utf-8")
    models = (REPO / "industrial/tia_openness_cli/src/TiaOpenness.Models/Models.cs").read_text(encoding="utf-8")
    assert 'new { ok = created.Ok, create = created }' in program
    assert "JsonNamingPolicy.CamelCase" in models
    assert '[JsonPropertyName("projectPath")]' in models


def test_archive_reply_requires_exact_path_and_hash() -> None:
    receipt = {
        "ok": True,
        "archive": {"ok": True, "archivePath": "C:/work/out/Demo.zap19",
                    "archiveSha256": "sha256:" + "a" * 64, "sizeBytes": 1234},
    }
    unpacked = unpack_archive_path(receipt)
    assert unpacked["archive_path"] == "C:/work/out/Demo.zap19"
    assert unpacked["size_bytes"] == 1234


def test_archive_missing_is_explicit_failure() -> None:
    with pytest.raises(ArchiveMissingError):
        unpack_archive_path({"ok": True, "archive": {"ok": False, "error": {"code": "archive_missing"}}})
    with pytest.raises(ArchiveMissingError):
        unpack_archive_path({"ok": True, "archive": {"ok": True}})


def test_retrieve_reopen_is_mandatory() -> None:
    receipt = {"ok": True, "retrieve": {"ok": True, "reopenOk": True,
                                        "projectPath": "C:/work/reopen/Demo.ap19"}}
    assert unpack_retrieve_reopen(receipt)["reopen_ok"] is True


@pytest.mark.parametrize("receipt", [
    {"ok": True, "retrieve": {"ok": True, "reopenOk": False, "projectPath": "x.ap19"}},
    {"ok": True, "retrieve": {"ok": True, "projectPath": "x.ap19"}},
    {"ok": False, "retrieve": {"ok": True, "reopenOk": True}},
    {"ok": True, "retrieve": {"ok": True, "reopenOk": True}},
])
def test_reopen_failure_variants_are_rejected(receipt) -> None:
    with pytest.raises(ReopenFailedError):
        unpack_retrieve_reopen(receipt)


def test_net481_target_framework_is_frozen() -> None:
    csproj = (REPO / "industrial/tia_openness_cli/src/TiaOpenness.Server/TiaOpenness.Server.csproj").read_text(encoding="utf-8")
    assert "<TargetFramework>net481</TargetFramework>" in csproj
    assert "net8" not in csproj.lower().replace("must not run on net8+", "")
