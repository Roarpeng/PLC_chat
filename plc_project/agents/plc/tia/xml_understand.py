"""Deep SimaticML XML understanding for call / dependency evidence.

Rules:
- Never invent CALLS from network titles or SCL comments.
- Deterministic extraction from ``CallInfo`` / FlgNet XML is authoritative.
- Optional LLM pass may propose additional links, but each claim MUST be
  validated against literal XML evidence (``CallInfo Name="…"`` or Access
  symbol text) before acceptance — writeback depends on this accuracy.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("researchos.plc.xml_understand")

_CALLINFO_RE = re.compile(
    r'<CallInfo\b[^>]*\bName="([^"]+)"[^>]*(?:\bBlockType="([^"]*)")?',
    re.IGNORECASE,
)
_CALLINFO_RE2 = re.compile(
    r"<CallInfo\b[^>]*\bBlockType=\"([^\"]*)\"[^>]*\bName=\"([^\"]+)\"",
    re.IGNORECASE,
)
_INSTANCE_DB_RE = re.compile(
    r"<Instance\b[^>]*>\s*(?:<Component\b[^>]*\bName=\"([^\"]+)\"\s*/>)",
    re.IGNORECASE | re.DOTALL,
)


def extract_callinfos_from_xml(xml_text: str) -> list[dict[str, str]]:
    """Deterministic CallInfo extraction from raw SimaticML XML text."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _CALLINFO_RE.finditer(xml_text or ""):
        name = (m.group(1) or "").strip()
        btype = (m.group(2) or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append({"callee": name, "block_type": btype, "evidence": "xml_callinfo"})
    for m in _CALLINFO_RE2.finditer(xml_text or ""):
        btype = (m.group(1) or "").strip()
        name = (m.group(2) or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append({"callee": name, "block_type": btype, "evidence": "xml_callinfo"})
    return out


def validate_llm_call_claims(
    xml_text: str,
    claims: list[dict[str, Any]],
    *,
    known_blocks: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Keep only LLM claims that appear literally in XML CallInfo (or known Access)."""
    xml = xml_text or ""
    known = known_blocks or set()
    accepted: list[dict[str, Any]] = []
    for claim in claims:
        callee = str(claim.get("callee") or claim.get("target") or "").strip()
        if not callee:
            continue
        # Hard gate: CallInfo Name must appear in XML
        needle = f'CallInfo Name="{callee}"'
        needle2 = f"CallInfo Name='{callee}'"
        if needle not in xml and needle2 not in xml:
            # Also allow Name attribute order variations already covered by regex set
            if not any(c["callee"] == callee for c in extract_callinfos_from_xml(xml)):
                logger.info("reject LLM call claim without XML CallInfo evidence: %s", callee)
                continue
        if known and callee not in known:
            # Still accept if CallInfo exists — may be library block
            pass
        accepted.append(
            {
                "callee": callee,
                "block_type": str(claim.get("block_type") or ""),
                "evidence": "llm_validated_xml_callinfo",
                "rationale": str(claim.get("rationale") or "")[:240],
            }
        )
    return accepted


def _llm_chat_json(prompt: str, *, timeout: float = 90.0) -> dict[str, Any] | None:
    """Best-effort chat via LiteLLM OpenAI-compatible endpoint. Returns None if unset."""
    base = (os.getenv("LITELLM_BASE_URL") or "").rstrip("/")
    if not base:
        return None
    model = os.getenv("LITELLM_DEFAULT_MODEL") or "default"
    key = os.getenv("LITELLM_MASTER_KEY") or os.getenv("OPENAI_API_KEY") or ""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Siemens TIA Portal SimaticML expert. "
                    "Extract ONLY block CALLS that appear as <Call>/<CallInfo> in the XML. "
                    "Never invent calls from network titles or comments. "
                    "Return JSON: {\"calls\":[{\"callee\":\"...\",\"block_type\":\"FB|FC|...\", "
                    "\"rationale\":\"quote CallInfo snippet\"}]}"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base}/v1/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM XML understand failed: %s", exc)
        return None


def llm_understand_block_xml(
    *,
    block_name: str,
    xml_text: str,
    known_blocks: set[str] | None = None,
) -> list[dict[str, Any]]:
    """LLM deep-read of one block XML; claims are XML-evidence gated."""
    # Cap prompt size — OB1 can be large; keep Call-heavy regions
    text = xml_text or ""
    if len(text) > 60000:
        # Prefer sections containing CallInfo
        chunks = re.split(r"(?=<SW\.Blocks\.CompileUnit\b)", text)
        keep = [chunks[0][:2000]] if chunks else []
        for ch in chunks[1:]:
            if "CallInfo" in ch or "Call " in ch:
                keep.append(ch[:8000])
            if sum(len(x) for x in keep) > 50000:
                break
        text = "\n".join(keep) if keep else text[:60000]

    prompt = (
        f"Block name: {block_name}\n"
        f"Known project blocks (subset): {', '.join(sorted(list(known_blocks or []))[:80])}\n\n"
        f"SimaticML XML:\n```xml\n{text}\n```\n"
    )
    parsed = _llm_chat_json(prompt)
    if not parsed:
        return []
    claims = parsed.get("calls") if isinstance(parsed, dict) else None
    if not isinstance(claims, list):
        return []
    return validate_llm_call_claims(xml_text, claims, known_blocks=known_blocks)


def enrich_kg_calls_from_xml_files(
    kg: dict[str, Any],
    *,
    xml_paths: list[str] | list[Path],
    known_blocks: set[str] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Merge XML/LLM-validated CALLS into a serialized knowledge_graph dict."""
    nodes = {n["id"]: n for n in (kg.get("nodes") or [])}
    edges = list(kg.get("edges") or [])
    existing = {
        (e.get("source"), e.get("target"), e.get("type"))
        for e in edges
    }
    known = known_blocks or {
        str((n.get("props") or {}).get("name") or n["id"].split("::")[-1])
        for n in nodes.values()
        if n.get("type") == "Block"
    }

    for path in xml_paths:
        p = Path(path)
        if not p.is_file():
            continue
        try:
            xml_text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Infer block name from XML <Name>…</Name> near block root, else stem
        m = re.search(r"<Name>([^<]+)</Name>", xml_text)
        block_name = (m.group(1).strip() if m else p.stem)
        caller_id = f"Block::{block_name}"
        if caller_id not in nodes:
            nodes[caller_id] = {
                "id": caller_id,
                "type": "Block",
                "props": {"name": block_name},
            }

        calls = extract_callinfos_from_xml(xml_text)
        if use_llm:
            llm_calls = llm_understand_block_xml(
                block_name=block_name,
                xml_text=xml_text,
                known_blocks=known,
            )
            # Prefer deterministic; LLM only adds validated extras
            have = {c["callee"] for c in calls}
            for c in llm_calls:
                if c["callee"] not in have:
                    calls.append(c)
                    have.add(c["callee"])

        for i, c in enumerate(calls, start=1):
            callee = c["callee"]
            tgt = f"Block::{callee}"
            if tgt not in nodes:
                nodes[tgt] = {
                    "id": tgt,
                    "type": "Block",
                    "props": {
                        "name": callee,
                        "block_type": c.get("block_type") or None,
                    },
                }
            key = (caller_id, tgt, "CALLS")
            if key in existing:
                continue
            existing.add(key)
            edges.append(
                {
                    "source": caller_id,
                    "target": tgt,
                    "type": "CALLS",
                    "props": {
                        "seq": i,
                        "evidence": c.get("evidence") or "xml_callinfo",
                        "block_type": c.get("block_type") or "",
                    },
                }
            )

    return {"nodes": list(nodes.values()), "edges": edges}
