"""SCL rewrite — importable compilation units + HITL diffs (not advisory-only).

Distinct from parse / analyze / optimize / writeback. Consumes PLC-IR or a
ready job's ``scl_sources`` + folded logic. Never decrypts Know-how, never
invents CALLS, never writes Safety/F-block bodies.

Importable SCL is Siemens External Source ASCII:
  FUNCTION_BLOCK / FUNCTION / ORGANIZATION_BLOCK … END_*
Writeback imports it via Openness
  ExternalSourceGroup.ExternalSources.CreateFromFile + GenerateBlocksFromSource.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.plc.tia.ir import Block, PlcProject
from agents.plc.tia.scl import convert_project_to_scl, translate_block_to_scl

SKIP_SAFETY = "safety"
SKIP_PROTECTED = "know_how"
SKIP_INTERFACE_ONLY = "interface_only"
SKIP_NO_BODY = "no_body"
SKIP_UNTRANSLATED = "untranslated"

_TODO_RE = re.compile(r"\(\*\s*TODO", re.IGNORECASE)
_STMT_RE = re.compile(
    r"^\s*(?:IF\b|[A-Za-z_#\"%][\w.#\"]*\s*:?=|[A-Za-z_#\"%][\w.#\"]*\s*\()",
    re.IGNORECASE,
)


@dataclass
class SclSkip:
    block_name: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"block": self.block_name, "reason": self.reason, "detail": self.detail}


@dataclass
class SclDiff:
    block_name: str
    before: str
    after: str
    unified_diff: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    new_block: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "block": self.block_name,
            "before": self.before,
            "after": self.after,
            "diff": self.unified_diff,
            "evidence": list(self.evidence),
            "new_block": self.new_block,
        }


@dataclass
class SclRewriteResult:
    files: dict[str, str] = field(default_factory=dict)
    diffs: list[SclDiff] = field(default_factory=list)
    skipped: list[SclSkip] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": dict(self.files),
            "diffs": [d.to_dict() for d in self.diffs],
            "skipped": [s.to_dict() for s in self.skipped],
            "notes": list(self.notes),
        }


def refuse_body_write_reason(block: dict[str, Any] | Block | None) -> str | None:
    """Return a skip reason if this block must never receive a body write."""
    if block is None:
        return SKIP_NO_BODY
    if isinstance(block, Block):
        if getattr(block, "is_safety", False):
            return SKIP_SAFETY
        if block.is_protected():
            return SKIP_PROTECTED
        if block.is_interface_only():
            return SKIP_INTERFACE_ONLY
        if not block.has_program_body():
            return SKIP_NO_BODY
        return None
    if block.get("is_safety") or block.get("safety"):
        return SKIP_SAFETY
    if block.get("interface_only") or block.get("protected"):
        return SKIP_PROTECTED if block.get("protected") else SKIP_INTERFACE_ONLY
    if block.get("body_available") is False:
        return SKIP_NO_BODY
    return None


def scl_has_untranslated(scl: str) -> bool:
    return bool(_TODO_RE.search(scl or ""))


def scl_is_untranslated(scl: str) -> bool:
    """True when the unit has no real statements — only TODOs / placeholders."""
    text = scl or ""
    has_todo = scl_has_untranslated(text)
    real = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("//") or s.startswith("(*"):
            continue
        if _TODO_RE.search(s):
            continue
        if _STMT_RE.match(s) and not s.upper().startswith(("FUNCTION", "VAR", "END_", "BEGIN", "TYPE", "DATA_")):
            real = True
            break
    return has_todo and not real


def unified_scl_diff(before: str, after: str, name: str) -> str:
    a = (before or "").splitlines(keepends=True)
    b = (after or "").splitlines(keepends=True)
    if a and not a[-1].endswith("\n"):
        a[-1] = a[-1] + "\n"
    if b and not b[-1].endswith("\n"):
        b[-1] = b[-1] + "\n"
    return "".join(
        difflib.unified_diff(a, b, fromfile=f"a/{name}.scl", tofile=f"b/{name}.scl", n=3)
    )


def _evidence_for_block(block: Block) -> list[dict[str, Any]]:
    ev: list[dict[str, Any]] = [
        {
            "kind": "block",
            "block": block.name,
            "type": getattr(block.block_type, "value", str(block.block_type)),
            "language": block.programming_language or "",
            "networks": len(block.networks),
        }
    ]
    for idx, net in enumerate(block.networks, start=1):
        tags: list[str] = []
        for acc in net.accesses():
            label = acc.as_scl()
            if label and label not in tags:
                tags.append(label)
        ev.append(
            {
                "kind": "network",
                "block": block.name,
                "network": net.id or str(idx),
                "title": net.title or "",
                "tags": tags[:24],
            }
        )
    return ev


def convert_project_to_importable_scl(project: PlcProject) -> SclRewriteResult:
    """Successor to ``convert_project_to_scl``: importable units + skip reasons.

    Native SCL/STL is passed through. Folded LAD/FBD keeps ``(* TODO[...] *)``
    for untranslated parts — never silently dropped.
    """
    result = SclRewriteResult(
        notes=[
            "Importable SCL for External Source + GenerateBlocksFromSource.",
            "Skipped: safety / know-how / interface-only / no body.",
            "Untranslated instructions stay as (* TODO[...] *); never dropped.",
        ]
    )
    items: list[tuple[str, Block]] = []
    for name, block in project.blocks.items():
        reason = refuse_body_write_reason(block)
        if reason:
            result.skipped.append(
                SclSkip(name, reason, f"{reason}: refuse body write")
            )
            continue
        items.append((name, block))

    def _one(item: tuple[str, Block]) -> tuple[str, str]:
        name, block = item
        return name, translate_block_to_scl(block)

    from agents.plc.tia.parallel import map_parallel

    for name, scl in map_parallel(_one, items, min_items=8):
        if scl_is_untranslated(scl):
            result.skipped.append(
                SclSkip(name, SKIP_UNTRANSLATED, "SCL is only TODO/empty; not staged for import")
            )
            continue
        result.files[name] = scl
        result.diffs.append(
            SclDiff(
                block_name=name,
                before="",
                after=scl,
                unified_diff=unified_scl_diff("", scl, name),
                evidence=_evidence_for_block(project.blocks[name]),
            )
        )
    return result


def rewrite_block_to_importable_scl(block: Block) -> str:
    """One writable non-safety block → Siemens SCL compilation unit."""
    reason = refuse_body_write_reason(block)
    if reason:
        raise ValueError(f"refuse body write ({reason}): {block.name}")
    return translate_block_to_scl(block)


def _block_map(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }


def _load_ir_blocks(job: dict[str, Any]) -> dict[str, Block]:
    """Best-effort re-parse source XML so LAD/FBD can be rewritten from IR."""
    out: dict[str, Block] = {}
    xmls = [Path(p) for p in (job.get("source_xmls") or []) if p]
    if not xmls:
        return out
    try:
        from agents.plc.tia.safety import detect_block_safety
        from agents.plc.tia.simaticml import parse_block_xml
    except ImportError:
        return out
    for xml in xmls:
        if not xml.is_file():
            continue
        try:
            block = parse_block_xml(xml)
        except Exception:  # noqa: BLE001
            continue
        if block is None:
            continue
        block.is_safety = detect_block_safety(block)
        out[block.name] = block
    return out


def rewrite_job_to_importable_scl(
    job: dict[str, Any],
    *,
    extra_files: dict[str, str] | None = None,
    extra_evidence: dict[str, list[dict[str, Any]]] | None = None,
) -> SclRewriteResult:
    """Job-level rewrite: IR when XML is present, else existing ``scl_sources``.

    ``extra_files`` overlays decouple extracts (new FC + updated callers).
    """
    result = SclRewriteResult(
        notes=[
            "SCL rewrite artifact for HITL + Openness External Source import.",
            "Linux Docker can stage .scl; GenerateBlocksFromSource needs Windows HostGateway.",
        ]
    )
    blocks = _block_map(job)
    baseline = dict(job.get("scl_sources") or {})
    ir_blocks = _load_ir_blocks(job)
    produced: dict[str, str] = {}

    if ir_blocks:
        project = PlcProject(name=str(job.get("project_name") or "job"))
        for block in ir_blocks.values():
            project.add_block(block)
        try:
            from agents.plc.tia.flgnet_fold import attach_folded

            attach_folded(project)
        except Exception:  # noqa: BLE001
            pass
        ir_result = convert_project_to_importable_scl(project)
        produced.update(ir_result.files)
        result.skipped.extend(ir_result.skipped)
        result.notes.extend(ir_result.notes)
    else:
        # No XML: reuse ingest SCL, still refuse unsafe bodies.
        for name, scl in baseline.items():
            reason = refuse_body_write_reason(blocks.get(name))
            if reason:
                result.skipped.append(SclSkip(name, reason, f"{reason}: refuse body write"))
                continue
            if scl_is_untranslated(scl):
                result.skipped.append(
                    SclSkip(name, SKIP_UNTRANSLATED, "SCL is only TODO/empty; not staged for import")
                )
                continue
            produced[name] = scl

    # Job metadata may list blocks that never made it into scl_sources
    for name, meta in blocks.items():
        if name in produced or any(s.block_name == name for s in result.skipped):
            continue
        reason = refuse_body_write_reason(meta)
        if reason:
            result.skipped.append(SclSkip(name, reason, f"{reason}: refuse body write"))

    if extra_files:
        for name, scl in extra_files.items():
            reason = refuse_body_write_reason(blocks.get(name))
            if reason and name in blocks:
                result.skipped.append(SclSkip(name, reason, f"{reason}: refuse overlay"))
                continue
            produced[name] = scl

    result.files = produced
    extra_ev = extra_evidence or {}
    for name, after in produced.items():
        before = baseline.get(name) or ""
        if before == after and name in baseline and name not in (extra_files or {}):
            # Still a reviewable artifact (LAD→SCL first import)
            diff = unified_scl_diff(before, after, name)
            if not diff.strip():
                diff = f"--- a/{name}.scl\n+++ b/{name}.scl\n@@ (unchanged importable SCL) @@\n"
        else:
            diff = unified_scl_diff(before, after, name)
        ev = list(extra_ev.get(name) or [])
        if name in ir_blocks:
            ev = ev or _evidence_for_block(ir_blocks[name])
        else:
            ev.append({"kind": "block", "block": name, "source": "job.scl_sources"})
        result.diffs.append(
            SclDiff(
                block_name=name,
                before=before,
                after=after,
                unified_diff=diff,
                evidence=ev,
                new_block=name not in baseline and name not in blocks,
            )
        )
    return result


# Keep convert_project_to_scl behavior aligned: skip safety as well as know-how.
def convert_project_to_scl_safe(project: PlcProject) -> dict[str, str]:
    """Like ``convert_project_to_scl`` but also skips ``is_safety`` blocks."""
    out = convert_project_to_scl(project)
    return {
        name: scl
        for name, scl in out.items()
        if not getattr(project.blocks.get(name), "is_safety", False)
    }
