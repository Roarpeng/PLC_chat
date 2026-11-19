"""Export one V5 KUKA snapshot as a verified V19 offline acceptance archive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.app.services.plc.af_v5_native import archive_kuka_snapshot
from gateway.app.services.plc.station_native import CPU_IDENTIFIER


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    parser.add_argument("--cpu", required=True, help="Approved Siemens CPU order number and firmware identifier")
    args = parser.parse_args()
    if not CPU_IDENTIFIER.fullmatch(args.cpu):
        parser.error("--cpu must be a Siemens OrderNumber:…/V… identifier")
    def report(stage) -> None:
        print(f"{stage.stage} {stage.state}: {stage.message}", flush=True)

    result = archive_kuka_snapshot(args.snapshot.read_bytes(), args.out, args.cpu, on_stage=report)
    if not result.ok or result.state != "NATIVE_ARCHIVED" or result.artifact is None:
        print(f"Export failed: {result.error_message}", file=sys.stderr)
        return 1
    print(json.dumps(result.artifact.to_dict(), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
