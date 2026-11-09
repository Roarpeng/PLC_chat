"""G0 read-only capability probe (executable, serial real-machine schedule).

Usage:
    uv run python scripts/probe_capability_v2.py
    uv run python scripts/probe_capability_v2.py --output evidence/v2/T01/g0_probe.json

This script ONLY calls the C# ``status`` probe: no TIA project is created and
no engineering write is performed. If the worker is unavailable the manifest
is stamped ``pending_real_machine`` with the raw failure receipt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gateway.app.services.plc.capability_v2 import probe_capability, probe_cli_payload
from gateway.app.services.plc.workspace_v2 import get_store


def main() -> None:
    parser = argparse.ArgumentParser(description="PLC Agent V2 G0 read-only capability probe")
    parser.add_argument("--output", default="", help="optional JSON output path")
    parser.add_argument("--no-db", action="store_true", help="do not persist to the workspace store")
    args = parser.parse_args()

    store = None if args.no_db else get_store()
    manifest = probe_capability(store=store, write_evidence=True)
    payload = probe_cli_payload(manifest)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    print(text)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {target}")
    print("\n[NEXT] Report candidate_cpu_templates to the team lead; the lead must appoint "
          "one approved CPU skeleton (U-02). No skeleton is auto-selected here.")


if __name__ == "__main__":
    main()
