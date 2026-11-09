"""Generate deterministic V2 golden snapshots (WP-03 / G4).

Run: ``uv run python scripts/gen_golden_v2.py``.
Outputs are pure functions of the frozen demo IR + AFProfile + template hash;
timestamps never enter semantic files, so re-running produces identical bytes.
"""
from __future__ import annotations

import json
from pathlib import Path

from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.process.scan_simulator import ScanSimulator, build_standard_scenarios
from plc_engine.process.scl_lowering import CompilerService, assert_deterministic
from tests.v2_fixtures import build_valid_demo_ir

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "snapshots" / "v2"


def main() -> None:
    """Write the manifest / Trace / SCL golden snapshots."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ir = build_valid_demo_ir()
    report = ValidationEngine().validate(ir)
    if not report.passed:
        raise SystemExit(f"demo IR failed validation: {report.issues}")
    manifest, source_map = CompilerService(ir.af_profile).lower(ir)
    manifest_json = {
        "ir_sha256": ir.ir_sha256,
        "manifest_sha256": manifest.sha256,
        "af_profile_id": manifest.af_profile_id,
        "import_order": manifest.import_order,
        "file_hashes": {f.path: f.sha256 for f in sorted(manifest.files, key=lambda x: x.path)},
        "block_numbers": {f.path: f.block_number for f in sorted(manifest.files, key=lambda x: x.path)},
        "source_map_entries": len(source_map.mappings),
        "deterministic": assert_deterministic(ir)["deterministic"],
        "evidence_level": "offline",
    }
    (OUTPUT_DIR / "manifest.golden.json").write_text(
        json.dumps(manifest_json, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    simulator = ScanSimulator()
    scenarios: dict[str, dict[str, object]] = {}
    for name, scenario in sorted(build_standard_scenarios().items()):
        frames = simulator.run(ir, scenario)
        scenarios[name] = {
            "frames": len(frames),
            "last_step": frames[-1].active_step,
            "alarms": frames[-1].alarms,
            "first_step": frames[0].active_step,
            "evidence_level": frames[-1].evidence_level,
            "data_source": frames[-1].data_source,
        }
    trace_json = {
        "shortest_counterexample": simulator.shortest_counterexample(ir),
        "scenarios": scenarios,
        "notice": "offline prediction, not a real machine verification",
    }
    (OUTPUT_DIR / "trace_scenarios.golden.json").write_text(
        json.dumps(trace_json, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    for file in manifest.files:
        (OUTPUT_DIR / f"{file.tia_block}.golden.scl").write_text(file.content, encoding="utf-8")
    print(f"golden snapshots written to {OUTPUT_DIR}")
    print(f"manifest_sha256={manifest.sha256}")


if __name__ == "__main__":
    main()
