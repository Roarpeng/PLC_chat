"""JSON Schema contracts: 5 schemas parse in Python AND TS, reject unknown fields."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from plc_engine.engineering_ir.models import EngineeringIRV2
from tests.v2_fixtures import build_valid_demo_ir

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "v2" / "contracts"
SCHEMA_FILES = (
    "engineering_ir_v2.schema.json",
    "patch_v2.schema.json",
    "changeset_v2.schema.json",
    "delivery_v2.schema.json",
    "capability_v2.schema.json",
)


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    assert ref.startswith("#/$defs/"), f"unsupported $ref: {ref}"
    return root["$defs"][ref.split("/")[-1]]


def _matches_type(value: Any, declared: str | list[str]) -> bool:
    types = [declared] if isinstance(declared, str) else list(declared)
    mapping = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    return any(mapping.get(t, lambda v: True)(value) for t in types)


def validate(instance: Any, schema: dict[str, Any], root: dict[str, Any] | None = None) -> list[str]:
    """Minimal Draft-2020-12 validator (no third-party dependency).

    Supports: $ref, oneOf/anyOf, const, enum, type, pattern, required,
    additionalProperties=false, properties, items, minItems, minimum.
    """
    root = root or schema
    issues: list[str] = []
    if "$ref" in schema:
        return validate(instance, _resolve_ref(schema["$ref"], root), root)
    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not validate(instance, sub, root))
        if matches != 1:
            issues.append(f"oneOf matched {matches} schemas, expected exactly 1")
        return issues
    if "anyOf" in schema:
        if not any(not validate(instance, sub, root) for sub in schema["anyOf"]):
            issues.append("anyOf matched no schema")
        return issues
    if "const" in schema and instance != schema["const"]:
        issues.append(f"expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        issues.append(f"value {instance!r} not in enum {schema['enum']!r}")
    if "type" in schema and not _matches_type(instance, schema["type"]):
        issues.append(f"expected type {schema['type']!r}, got {type(instance).__name__}")
        return issues
    if isinstance(instance, str) and "pattern" in schema and not re.search(schema["pattern"], instance):
        issues.append(f"string {instance!r} does not match {schema['pattern']!r}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                issues.append(f"missing required field {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    issues.append(f"unknown field {key!r} (additionalProperties=false)")
        for key, sub in properties.items():
            if key in instance:
                issues.extend(validate(instance[key], sub, root))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            issues.append(f"array has {len(instance)} items, minItems={schema['minItems']}")
        if "items" in schema:
            for item in instance:
                issues.extend(validate(item, schema["items"], root))
    if isinstance(instance, (int, float)) and not isinstance(instance, bool) and "minimum" in schema:
        if instance < schema["minimum"]:
            issues.append(f"{instance} below minimum {schema['minimum']}")
    return issues


@pytest.fixture(scope="module")
def schemas() -> dict[str, dict[str, Any]]:
    return {
        name: json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
        for name in SCHEMA_FILES
    }


def test_all_five_schemas_are_valid_json_with_draft_id(schemas) -> None:
    assert len(schemas) == 5
    for name, schema in schemas.items():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(name)
        assert "type" in schema or "oneOf" in schema


def test_real_ir_instance_validates(schemas) -> None:
    ir = build_valid_demo_ir()
    assert validate(ir.to_dict(), schemas["engineering_ir_v2.schema.json"]) == []


def test_ir_roundtrip_instance_validates(schemas) -> None:
    ir = build_valid_demo_ir()
    restored = EngineeringIRV2.from_dict(ir.to_dict())
    assert validate(restored.to_dict(), schemas["engineering_ir_v2.schema.json"]) == []


def test_ir_schema_rejects_unknown_top_level_field(schemas) -> None:
    payload = build_valid_demo_ir().to_dict()
    payload["second_writable_truth"] = {"ir": "not allowed"}
    issues = validate(payload, schemas["engineering_ir_v2.schema.json"])
    assert any("unknown field" in i for i in issues)


def test_ir_schema_rejects_wrong_af_profile(schemas) -> None:
    payload = build_valid_demo_ir().to_dict()
    payload["af_profile"]["profile_id"] = "AF_V3_LATEST"
    assert any("const" in i for i in validate(payload, schemas["engineering_ir_v2.schema.json"]))


def test_patch_schema_requires_envelope_fields(schemas) -> None:
    schema = schemas["patch_v2.schema.json"]
    assert validate({"project_id": "p", "ops": [{"op": "set_view_layout"}]}, schema)
    assert validate({"project_id": "p", "base_revision": 0, "request_id": "r",
                     "ops": [{"op": "set_view_layout", "layout": {}}]}, schema) == []


def test_patch_schema_rejects_unknown_op(schemas) -> None:
    payload = {"project_id": "p", "base_revision": 0, "request_id": "r",
               "ops": [{"op": "eval_free_scl"}]}
    assert any("enum" in i for i in validate(payload, schemas["patch_v2.schema.json"]))


def test_changeset_schema_requires_zero_deletes(schemas) -> None:
    payload = {
        "id": "cs_1", "project_id": "p", "base_revision": 0,
        "before_hash": "sha256:x", "after_hash": "sha256:y", "spec_hash": "sha256:z",
        "status": "APPROVED", "ops": [],
        "impacts": {"delete_count": 1, "safety_block_changes": 0},
        "validation": {"passed": True, "issues": [], "unchanged_ir_hash": "sha256:x"},
        "review_approved": True, "explicit": True,
    }
    assert any("const" in i for i in validate(payload, schemas["changeset_v2.schema.json"]))


def test_delivery_schema_pins_v19_and_exact_artifact(schemas) -> None:
    schema = schemas["delivery_v2.schema.json"]
    request = {
        "project_id": "p", "base_revision": 0, "request_id": "r",
        "approved_changeset_id": "cs_1", "expected_baseline_hash": "sha256:x",
        "idempotency_key": "k", "artifact_type": "native_tia_archive", "tia_version": "V19",
    }
    assert validate(request, schema) == []
    request["tia_version"] = "V20"
    assert validate(request, schema)
    fake_artifact = {
        "artifact_id": "a_1", "job_id": "j_1", "project_id": "p",
        "archive_path": "C:/x/a.zap19", "archive_sha256": "sha256:" + "0" * 64,
        "size_bytes": 10, "kind": "zap19", "evidence_level": "mocked", "reopen_ok": True,
    }
    assert validate(fake_artifact, schema)  # mocked evidence can never be a native artifact


def test_capability_schema_requires_real_or_pending_level(schemas) -> None:
    payload = {
        "probe_receipt_id": "g0_1", "tia_version": "V19", "cpu_templates": [],
        "selected_cpu_template": "", "probed_at": "2026-11-09T00:00:00+00:00",
        "raw_probe_receipt": {}, "evidence_level": "pending_real_machine",
    }
    assert validate(payload, schemas["capability_v2.schema.json"]) == []
    payload["evidence_level"] = "faked_real"
    assert any("enum" in i for i in validate(payload, schemas["capability_v2.schema.json"]))


def test_schemas_are_typescript_parseable_plain_json(schemas) -> None:
    """TS reads these as plain JSON: no comments, NaN, trailing commas or BOM."""
    for name in SCHEMA_FILES:
        raw = (CONTRACTS / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"NaN" not in raw and b"undefined" not in raw
        json.loads(raw.decode("utf-8"))
