"""CAD metadata connector — read-only stub with fake catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class CadMetaEntry:
    id: str
    name: str
    format: str
    revision: str
    mass_kg: float | None
    material: str | None
    summary: str
    tags: tuple[str, ...] = ()


class CadMetaConnector(Protocol):
    def list_formats(self) -> list[str]: ...

    def search(self, query: str, *, limit: int = 10) -> list[CadMetaEntry]: ...

    def get(self, part_id: str) -> CadMetaEntry | None: ...


FAKE_CATALOG: list[CadMetaEntry] = [
    CadMetaEntry(
        id="cad_ee_gripper_v3",
        name="Parallel Gripper Assembly",
        format="STEP",
        revision="C",
        mass_kg=1.24,
        material="Al6061",
        summary="End-effector gripper assembly metadata (stub catalog).",
        tags=("gripper", "eoat"),
    ),
    CadMetaEntry(
        id="cad_base_plate",
        name="Robot Base Plate",
        format="SOLIDWORKS",
        revision="A",
        mass_kg=8.5,
        material="Steel",
        summary="Mounting plate with ISO hole pattern; read-only metadata.",
        tags=("mount", "base"),
    ),
    CadMetaEntry(
        id="cad_bracket_iso",
        name="Sensor Bracket",
        format="IGES",
        revision="B",
        mass_kg=0.18,
        material="Al6061",
        summary="Vision sensor bracket; no silent overwrite of engineering vault.",
        tags=("bracket", "vision"),
    ),
]


class FakeCadMetaConnector:
    def list_formats(self) -> list[str]:
        return sorted({e.format for e in FAKE_CATALOG})

    def search(self, query: str, *, limit: int = 10) -> list[CadMetaEntry]:
        q = query.lower()
        hits = [
            e
            for e in FAKE_CATALOG
            if q in e.name.lower() or q in e.summary.lower() or q in e.format.lower()
        ]
        return hits[:limit]

    def get(self, part_id: str) -> CadMetaEntry | None:
        for e in FAKE_CATALOG:
            if e.id == part_id:
                return e
        return None

    def as_dict(self, entry: CadMetaEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "name": entry.name,
            "format": entry.format,
            "revision": entry.revision,
            "mass_kg": entry.mass_kg,
            "material": entry.material,
            "summary": entry.summary,
            "tags": list(entry.tags),
            "readonly": True,
        }
