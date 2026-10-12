"""Stream XML parse while Openness is still exporting (journal + thread pool).

Siemens Export stays serial on one Portal. Python watches ``_exported.jsonl``
and parses each finished XML on a worker thread so extract overlaps export.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from agents.plc.tia.ir import PlcProject
from agents.plc.tia.parallel import ingest_workers
from agents.plc.tia.simaticml import XmlParseResult, merge_parse_results, parse_export_xml


def drain_export_journal(
    path: Path,
    offset: int,
    on_obj,
) -> int:
    """Read complete JSONL lines from ``offset``; leave a partial last line unread."""
    if offset < 0:
        offset = 0
    if not path.is_file():
        return offset
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        while True:
            pos = handle.tell()
            line = handle.readline()
            if not line:
                return pos
            if not line.endswith("\n"):
                return pos
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                on_obj(obj)
        return handle.tell()


class ExportJournalExtractor:
    """Submit XML parses as journal lines arrive; glob leftovers on finalize."""

    def __init__(self, export_dir: str | Path, *, project_name: str = "") -> None:
        self.export_path = Path(export_dir)
        self.project = PlcProject(
            name=project_name or self.export_path.name,
            source_path=str(self.export_path),
        )
        self._seen: set[str] = set()
        self._results: list[XmlParseResult] = []
        self._lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=ingest_workers(32, min_items=1)
        )
        self._futures: list[Future[XmlParseResult]] = []

    def reset(self) -> None:
        """Drop in-flight work (Openness skip-compile retry rewrites the journal)."""
        with self._lock:
            for fut in self._futures:
                fut.cancel()
            self._futures.clear()
            self._results.clear()
            self._seen.clear()
            self.project = PlcProject(
                name=self.project.name,
                source_path=str(self.export_path),
            )

    def submit_journal(self, obj: dict) -> None:
        if obj.get("reset"):
            self.reset()
            return
        if not obj.get("ok"):
            with self._lock:
                self.project.export_journal.append(obj)
                name = str(obj.get("name") or "").strip()
                err = str(obj.get("error") or "export failed")
                if name:
                    self.project.extraction_notes.append(
                        f"openness export failed: {name}: {err}"
                    )
                    self.project.parse_gaps.append(
                        {
                            "name": name,
                            "kind": "block",
                            "type": str(obj.get("type") or ""),
                            "status": "failed",
                            "reason": "openness_error",
                            "detail": err,
                        }
                    )
            return
        raw = obj.get("path")
        if not raw:
            return
        path = Path(str(raw))
        if path.is_file():
            self.submit_xml(path)

    def submit_xml(self, xml_file: Path) -> None:
        try:
            key = str(xml_file.resolve())
        except OSError:
            key = str(xml_file)
        with self._lock:
            if key in self._seen or self._pool is None:
                return
            self._seen.add(key)
            fut = self._pool.submit(parse_export_xml, xml_file, self.export_path)
            self._futures.append(fut)

    def finalize(self) -> PlcProject:
        if self.export_path.is_dir():
            for xml_file in sorted(self.export_path.rglob("*.xml")):
                if xml_file.is_file():
                    self.submit_xml(xml_file)
        pending = list(self._futures)
        extra: list[XmlParseResult] = []
        for fut in pending:
            try:
                extra.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                extra.append(
                    XmlParseResult(
                        kind="error",
                        rel="?",
                        note=f"parallel parse failed: {exc}",
                    )
                )
        pool = self._pool
        self._pool = None
        if pool is not None:
            pool.shutdown(wait=True)
        with self._lock:
            self._results.extend(extra)
            results = list(self._results)
        merge_parse_results(self.project, results)
        from agents.plc.tia.simaticml import _attach_export_manifest, _has_parsed_surface

        _attach_export_manifest(self.project, self.export_path)
        if not _has_parsed_surface(self.project):
            self.project.extraction_notes.append(
                "no PLC blocks or tag tables recognized — check Openness export layout"
            )
        from agents.plc.tia.enrich import enrich_project_interfaces
        from agents.plc.tia.safety import apply_safety_flags

        enrich_project_interfaces(self.project)
        apply_safety_flags(self.project)
        return self.project

    def close(self) -> None:
        """Best-effort shutdown if Openness CLI fails before finalize."""
        pool = self._pool
        self._pool = None
        if pool is not None:
            pool.shutdown(wait=False)
