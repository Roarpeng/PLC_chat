"""Citation Agent node: evidence → citations with stable C# ids."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from runtime.researchos_runtime.state import TaskState

# --- trust_level heuristics -------------------------------------------------

# Domains / suffixes treated as authoritative (government, education, registries).
GOV_EDU_SUFFIXES = (
    ".gov",
    ".gov.cn",
    ".gov.uk",
    ".gov.au",
    ".mil",
    ".edu",
    ".edu.cn",
    ".edu.au",
    ".ac.uk",
)

# Official vendor / primary-source domains (small curated whitelist).
OFFICIAL_DOMAINS = {
    "uspto.gov",
    "epo.org",
    "wipo.int",
    "fanuc.com",
    "kuka.com",
    "abb.com",
    "yaskawa.com",
    "universal-robots.com",
    "densorobotics.com",
    "festo.com",
    "siemens.com",
    "hikvision.com",
    "keyence.com",
    "omron.com",
    "rockwellautomation.com",
    "beckhoff.com",
}

# Low-trust host patterns (aggregators / commentary / social).
LOW_TRUST_PREFIXES = ("news.", "forum.", "blog.", "community.", "social.", "bbs.")
LOW_TRUST_DOMAINS = {
    "reddit.com",
    "quora.com",
    "wikipedia.org",
    "medium.com",
    "zhihu.com",
    "weibo.com",
    "twitter.com",
    "x.com",
    "bilibili.com",
    "youtube.com",
}
LOW_TRUST_TYPES = {"forum", "social", "blog", "aggregator", "commentary", "news"}


def _host(url: str) -> str:
    """Return lowercase bare host (no scheme/path/query), empty string if absent."""
    url = (url or "").strip().lower()
    if not url:
        return ""
    url = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url)
    host = url.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return host.strip().rstrip(".")


def _bare_host(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def _trust_level(url: str, source_type: str | None = None) -> str:
    host = _host(url)
    if not host:
        return "low"
    bare = _bare_host(host)
    if host.endswith(GOV_EDU_SUFFIXES) or bare in OFFICIAL_DOMAINS:
        return "high"
    if (
        host.startswith(LOW_TRUST_PREFIXES)
        or bare in LOW_TRUST_DOMAINS
        or (source_type or "").lower() in LOW_TRUST_TYPES
    ):
        return "low"
    return "medium"


def _publisher(item: dict[str, Any], url: str) -> str:
    meta = item.get("meta") or {}
    pub = meta.get("publisher")
    if pub:
        return str(pub)
    return _bare_host(_host(url)) or str(item.get("source_id") or "")


def run(state: TaskState) -> dict[str, Any]:
    evidence = list(state.get("evidence") or [])
    existing = list(state.get("citations") or [])
    now = datetime.now(timezone.utc).isoformat()
    seen_keys: set[str] = set()
    for cit in existing:
        key = cit.get("url") or cit.get("evidence_id") or cit.get("id")
        if key:
            seen_keys.add(str(key))

    start_idx = len(existing) + 1
    new_citations: list[dict[str, Any]] = []
    evid_to_cid: dict[str, str] = {}

    for offset, item in enumerate(evidence):
        eid = str(item.get("id") or f"ev_{offset}")
        key = str(item.get("url") or item.get("source_id") or eid)
        if key in seen_keys:
            # map to existing if same evidence id already cited
            for cit in existing:
                if cit.get("evidence_id") == eid or cit.get("url") == item.get("url"):
                    evid_to_cid[eid] = str(cit.get("id"))
                    break
            continue

        cid = f"C{start_idx + len(new_citations)}"
        quote = (item.get("content") or "")[:240]
        url = item.get("url") or ""
        source_type = (item.get("meta") or {}).get("source_type")
        new_citations.append(
            {
                "id": cid,
                "evidence_id": eid,
                "source_id": item.get("source_id") or url or eid,
                "locator": item.get("locator") or "",
                "quote": quote,
                "url": url,
                "title": item.get("title") or eid,
                "trust_level": _trust_level(url, source_type),
                "publisher": _publisher(item, url),
                "accessed_at": now,
            }
        )
        evid_to_cid[eid] = cid
        seen_keys.add(key)

    # Rewrite analysis citation_ids from TMP:ev_* → C#
    analysis = dict(state.get("analysis_results") or {})
    updated_analysis: dict[str, Any] = {}
    for specialty, block in analysis.items():
        block = dict(block or {})
        raw_ids = list(block.get("citation_ids") or [])
        mapped: list[str] = []
        for ref in raw_ids:
            if isinstance(ref, str) and ref.startswith("TMP:"):
                eid = ref[4:]
                if eid in evid_to_cid:
                    mapped.append(evid_to_cid[eid])
            elif isinstance(ref, str) and ref.startswith("C"):
                mapped.append(ref)
            elif isinstance(ref, str) and ref in evid_to_cid:
                mapped.append(evid_to_cid[ref])
        # If analysis had no ids, attach all new citations
        if not mapped and evid_to_cid:
            mapped = list(dict.fromkeys(evid_to_cid.values()))
        block["citation_ids"] = mapped
        updated_analysis[specialty] = block

    out: dict[str, Any] = {
        "citations": new_citations,
        "events": [
            {
                "type": "citation.normalized",
                "task_id": state.get("task_id", ""),
                "payload": {"added": len(new_citations), "mapping": evid_to_cid},
                "ts": now,
            }
        ],
        "route": "reviewer",
        "meta": {
            **(state.get("meta") or {}),
            "citation_style": "footnote",
            "citation_mapping": evid_to_cid,
        },
    }
    if updated_analysis:
        out["analysis_results"] = updated_analysis
    return out
