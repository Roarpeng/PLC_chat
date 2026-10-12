"""Run PLC ingest timing bench on offline fixtures; write JSON report."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agents.plc.tia.timings import timings_summary
from gateway.app.services import plc_jobs as plc
from gateway.app.services import store as mem

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = [
    ("tia_exports", ROOT / "tests" / "fixtures" / "tia_exports"),
    ("tia_ce", ROOT / "tests" / "fixtures" / "tia_ce"),
]


def main() -> None:
    mem.store.plc_jobs.clear()
    rows: list[dict] = []
    for name, path in FIXTURES:
        if not path.is_dir():
            continue
        job = plc.create_job_record(
            source_type="path",
            source_path=str(path),
            project_name=name,
            created_by="bench",
        )
        with tempfile.TemporaryDirectory() as td:
            out = plc.run_ingest_job(job["id"], publish_graph=False, result_root=td)
        timings = out.get("timings") or {}
        progress = [
            {
                "step": p.get("step"),
                "duration_ms": p.get("duration_ms"),
                "detail": (p.get("detail") or "")[:200],
            }
            for p in (out.get("progress") or [])
        ]
        rows.append(
            {
                "fixture": name,
                "status": out.get("status"),
                "blocks": len(out.get("blocks") or []),
                "xmls": len(out.get("source_xmls") or []),
                "timings": timings,
                "progress": progress,
                "summary": timings_summary(timings),
            }
        )
        print(f"=== {name} ===")
        print(timings_summary(timings))
        for p in progress:
            print(f"  {p['step']}: {p['duration_ms']}ms")
        print()

    out_path = ROOT / ".researchos" / "ingest_timing_fixture.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out_path)
    mem.store.plc_jobs.clear()


if __name__ == "__main__":
    main()
