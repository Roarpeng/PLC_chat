"""Project Brief contract — Q1 owns the device/sensor summary section.

M2 (and later Q2/Q3) consume ``sections.device_sensor_summary``. This module
does not invent run-logic or HITL write-back sections.
"""

from __future__ import annotations

from typing import Any

from gateway.app.services.plc.device_cards import (
    BRIEF_SCHEMA,
    BRIEF_SECTION_SCHEMA,
    list_device_cards,
)


def _card_brief_row(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "kind": card.get("kind"),
        "symbol_name": card.get("symbol_name"),
        "address": card.get("address") or "",
        "io_type": card.get("io_type"),
        "meaning_status": card.get("meaning_status"),
        "meaning_text": card.get("meaning_text") or "",
        "meaning_source": card.get("meaning_source"),
        "used_by_count": len(card.get("used_by") or []),
        "tag_table": card.get("tag_table") or "",
    }


def device_sensor_summary_section(job: dict[str, Any]) -> dict[str, Any]:
    listing = list_device_cards(job, limit=500)
    cards = listing.get("cards") or []
    counts = listing.get("counts") or {}
    unconfirmed = [c for c in cards if c.get("meaning_status") == "meaning_unconfirmed"]
    io_counts: dict[str, int] = {}
    for card in cards:
        key = str(card.get("io_type") or "UNKNOWN")
        io_counts[key] = io_counts.get(key, 0) + 1
    gaps: list[str] = []
    n_unc = int(counts.get("meaning_unconfirmed") or 0)
    if n_unc:
        gaps.append(
            f"meaning_unconfirmed: {n_unc} cards have no cited comment, HMI text, "
            "or engineer annotation — do not invent process meaning"
        )
    unused = [
        c
        for c in cards
        if c.get("kind") == "tag" and not (c.get("used_by") or [])
    ]
    if unused:
        gaps.append(f"unused_io: {len(unused)} tag cards have no READS/WRITES edges")
    return {
        "schema": BRIEF_SECTION_SCHEMA,
        "owned_by": "Q1",
        "total_cards": int(counts.get("total") or len(cards)),
        "cited": int(counts.get("cited") or 0),
        "annotated": int(counts.get("annotated") or 0),
        "meaning_unconfirmed": n_unc,
        "io_type_counts": io_counts,
        "cards": [_card_brief_row(c) for c in cards],
        "unconfirmed_ids": [c["id"] for c in unconfirmed],
        "gaps": gaps,
    }


def build_project_brief(job: dict[str, Any]) -> dict[str, Any]:
    """Stubby Brief document with a required device/sensor section for M2."""
    section = device_sensor_summary_section(job)
    ready = job.get("status") == "ready"
    return {
        "schema": BRIEF_SCHEMA,
        "job_id": job.get("id"),
        "project_name": job.get("project_name") or "",
        "status": "ready" if ready else str(job.get("status") or "unknown"),
        "sections": {
            "device_sensor_summary": section,
        },
        "notes": [
            "Q1: device/sensor cards are cited-field only; meaning_unconfirmed is explicit.",
            "Q2 run-logic and Q3 impact/SCL write-back are out of scope for this Brief.",
            "Engineer annotations on /device-cards take priority over tag comments.",
        ],
        "card_count": section["total_cards"],
    }


def brief_includes_device_sensor_section(brief: dict[str, Any]) -> bool:
    section = (brief.get("sections") or {}).get("device_sensor_summary")
    return isinstance(section, dict) and section.get("schema") == BRIEF_SECTION_SCHEMA
