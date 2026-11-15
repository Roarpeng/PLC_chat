"""Fast diagnostic: create-project + create-device via the real Openness CLI.

Characterises the WS6 real-compile blocker (CPU type identifier / TIA interaction)
without running the full slow chain. Unbuffered; bounded timeout per call.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from agents.plc.tia.openness_cli import openness_cli

CPU = sys.argv[1] if len(sys.argv) > 1 else "6ES7511-1AK02-0AB0/V2.9"


def main() -> int:
    ws = Path(tempfile.mkdtemp(prefix="processos_cpu_probe_"))
    print(f"[probe] workspace={ws} cpu={CPU}", flush=True)
    print("[probe] create-project ...", flush=True)
    created = openness_cli("create-project", "--dir", str(ws / "proj"), "--name", "Probe", timeout_s=180)
    print(f"[probe] create-project ok={created.get('ok')} keys={list(created)}", flush=True)
    project_path = (created.get("create") or {}).get("projectPath", "")
    print(f"[probe] projectPath={project_path}", flush=True)
    if not project_path:
        print(f"[probe] CREATE FAILED: {created}", flush=True)
        return 1
    print("[probe] create-device ...", flush=True)
    device = openness_cli("create-device", "--project", project_path, "--type-id", CPU, "--name", "PLC_1", timeout_s=180)
    print(f"[probe] create-device ok={device.get('ok')}", flush=True)
    print(f"[probe] device receipt: {str(device)[:600]}", flush=True)
    return 0 if device.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())