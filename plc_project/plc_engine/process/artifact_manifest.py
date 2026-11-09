"""Deterministic ArtifactManifest for AF SCL/SimaticML lowering (WP-03 / G4).

Import order is explicit and validated: UDT -> FB/FC -> instance DB -> call OB.
Block numbers are never invented and FB names are never guessed from DB names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plc_engine.canonical import canonical_dumps, sha256_prefixed

#: Allowed artifact roles and their mandated relative order.
ROLE_ORDER: tuple[str, ...] = ("UDT", "FB", "FC", "DB", "OB", "SCL", "XML")


@dataclass
class ArtifactFile:
    """One generated semantic file, addressed by content hash."""

    path: str = ""
    sha256: str = ""
    role: str = ""
    content: str = ""
    source_ids: list[str] = field(default_factory=list)
    tia_block: str = ""
    block_number: int | None = None

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "sha256": self.sha256,
            "role": self.role,
            "source_ids": sorted(self.source_ids),
            "tia_block": self.tia_block,
            "block_number": self.block_number,
        }
        if include_content:
            payload["content"] = self.content
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactFile:
        number = data.get("block_number")
        return cls(
            path=str(data.get("path") or ""),
            sha256=str(data.get("sha256") or ""),
            role=str(data.get("role") or ""),
            content=str(data.get("content") or ""),
            source_ids=[str(x) for x in (data.get("source_ids") or [])],
            tia_block=str(data.get("tia_block") or ""),
            block_number=int(number) if number not in (None, "") else None,
        )


@dataclass
class ArtifactManifest:
    """Frozen, hash-addressed manifest of generated semantic artifacts."""

    manifest_id: str = ""
    af_profile_id: str = ""
    template_sha256: str = ""
    ir_sha256: str = ""
    files: list[ArtifactFile] = field(default_factory=list)
    import_order: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    sha256: str = ""
    receipt: dict[str, Any] = field(default_factory=dict)

    def file_index(self) -> dict[str, ArtifactFile]:
        """Map path to artifact file."""
        return {item.path: item for item in self.files}

    def compute_sha256(self) -> str:
        """Deterministic manifest hash; timestamps live only in ``receipt``.

        The hash covers each file's own content hash, role, explicit source ids,
        the import order and the dependency graph — never timestamps.
        """
        payload = {
            "af_profile_id": self.af_profile_id,
            "template_sha256": self.template_sha256,
            "ir_sha256": self.ir_sha256,
            "files": [item.to_dict() for item in sorted(self.files, key=lambda f: f.path)],
            "import_order": list(self.import_order),
            "dependencies": {k: sorted(v) for k, v in sorted(self.dependencies.items())},
        }
        return sha256_prefixed(canonical_dumps(payload))

    def refresh_hash(self) -> str:
        """Recompute and store the deterministic manifest hash."""
        self.sha256 = self.compute_sha256()
        return self.sha256

    def validate_import_order(self) -> list[str]:
        """Return issues when UDT/FB/FC/DB/OB dependency order is violated."""
        issues: list[str] = []
        index = self.file_index()
        rank = {role: i for i, role in enumerate(ROLE_ORDER)}
        positions: dict[str, int] = {}
        seen: set[str] = set()
        for position, path in enumerate(self.import_order):
            if path in seen:
                issues.append(f"duplicate import_order entry: {path}")
            seen.add(path)
            item = index.get(path)
            if item is None:
                issues.append(f"import_order references unknown file: {path}")
                continue
            if item.role not in rank:
                issues.append(f"file {path} has unknown role {item.role!r}")
                continue
            positions[path] = rank[item.role]
            for required in self.dependencies.get(path) or []:
                if required not in positions:
                    issues.append(f"file {path} depends on {required} which is not imported before it")
                else:
                    dep_item = index.get(required)
                    if dep_item is not None and rank.get(dep_item.role, 99) > rank[item.role]:
                        issues.append(f"dependency order violation: {path} ({item.role}) before {required} ({dep_item.role})")
        for item in self.files:
            if item.path not in seen:
                issues.append(f"generated file missing from import_order: {item.path}")
        return issues

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "af_profile_id": self.af_profile_id,
            "template_sha256": self.template_sha256,
            "ir_sha256": self.ir_sha256,
            "files": [f.to_dict(include_content=include_content) for f in sorted(self.files, key=lambda x: x.path)],
            "import_order": list(self.import_order),
            "dependencies": {k: sorted(v) for k, v in sorted(self.dependencies.items())},
            "sha256": self.sha256,
            "receipt": dict(self.receipt),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactManifest:
        return cls(
            manifest_id=str(data.get("manifest_id") or ""),
            af_profile_id=str(data.get("af_profile_id") or ""),
            template_sha256=str(data.get("template_sha256") or ""),
            ir_sha256=str(data.get("ir_sha256") or ""),
            files=[ArtifactFile.from_dict(x) if isinstance(x, dict) else x for x in (data.get("files") or [])],
            import_order=[str(x) for x in (data.get("import_order") or [])],
            dependencies={str(k): [str(v) for v in value] for k, value in (data.get("dependencies") or {}).items()},
            sha256=str(data.get("sha256") or ""),
            receipt=dict(data.get("receipt") or {}),
        )
