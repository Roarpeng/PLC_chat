"""Route user chat turns to research vs PLC by content (not by UI mode)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Explicit engineering / TIA / Simatic cues (zh + en)
_PLC_KEYWORDS = re.compile(
    r"("
    r"\bplc\b|tia\s*portal|simatic|openness|scl|ladder|"
    r"\bob\d+\b|\bfc\d+\b|\bfb\d+\b|\bdb\d+\b|"
    r"西门子|功能块|组织块|梯形图|西门子plc|"
    r"\.ap1[5-9]\b|\.ap\d{2}\b|\.zap\d*\b|simaticml"
    r")",
    re.IGNORECASE,
)

# Paths that look like project / export artifacts
_PATH_RE = re.compile(
    r"(?:"
    r"[A-Za-z]:\\[^\s\"']+"  # Windows
    r"|/(?:plc_projects|tmp|data|export|tia)[^\s\"']*"
    r"|/(?:[^\s\"']+\.(?:xml|zip|zap\d*|ap1[5-9]|ap\d{2}))"
    r"|(?:[^\s\"']+\.(?:xml|zip|zap\d*|ap1[5-9]|ap\d{2}))"
    r")"
)


@dataclass(frozen=True)
class RouteDecision:
    route: str  # research | plc | plc_need_source
    path: str | None = None
    reason: str = ""


def extract_plc_path(text: str, explicit: str | None = None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    if not text:
        return None
    matches = _PATH_RE.findall(text)
    if not matches:
        return None
    # Prefer longest / most specific match
    candidate = max((m.strip().strip("\"'") for m in matches), key=len)
    return candidate or None


def detect_route(
    query: str,
    *,
    tia_export_dir: str | None = None,
    mode: str | None = None,
    has_upload: bool = False,
) -> RouteDecision:
    """Decide whether this turn is PLC work or general research."""
    q = (query or "").strip()
    if has_upload:
        return RouteDecision(route="plc", reason="upload")

    path = extract_plc_path(q, tia_export_dir)
    if path:
        suffix = Path(path).suffix.lower()
        if suffix in {".xml", ".zip", ".zap", ".ap15", ".ap16", ".ap17", ".ap18", ".ap19", ".ap20"} or (
            suffix.startswith(".zap") and len(suffix) > 4 and suffix[4:].isdigit()
        ) or _PLC_KEYWORDS.search(
            q
        ) or mode == "industrial":
            return RouteDecision(route="plc", path=path, reason="path")
        # Bare path under allowlist-style roots still treated as PLC ingest
        if "plc" in path.lower() or "tia" in path.lower() or "export" in path.lower():
            return RouteDecision(route="plc", path=path, reason="path_hint")

    if mode == "industrial":
        if path:
            return RouteDecision(route="plc", path=path, reason="industrial_mode")
        return RouteDecision(route="plc_need_source", reason="industrial_no_path")

    if _PLC_KEYWORDS.search(q):
        if path:
            return RouteDecision(route="plc", path=path, reason="keyword+path")
        return RouteDecision(route="plc_need_source", reason="keyword_no_path")

    return RouteDecision(route="research", reason="default")
