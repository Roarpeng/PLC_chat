"""Real V19 native compile probe for the ProcessOS clamp slice (WS6).

Runs the FULL generated logic (including OB_Main, no exclusion) through the real
C# Openness CLI. Writes an honest receipt JSON. Any failure stays FAILED with
diagnostics; only a real 0-error compile + archive + reopen yields V19_real.

Usage:
  .venv/Scripts/python.exe scripts/processos_real_compile.py [--cpu-type-id ID] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from processos.contract import clamp_contract
from processos.frameworks import register_hr001_af_v19
from processos.native import DEFAULT_CPU_TYPE_ID, run_native_delivery


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpu-type-id", default=DEFAULT_CPU_TYPE_ID)
    ap.add_argument("--out", default="tmp_validate/processos_real_compile.json")
    args = ap.parse_args()

    profile = register_hr001_af_v19()
    contract = clamp_contract()
    print(f"[processos] real V19 compile probe; cpu={args.cpu_type_id}; profile={profile.profile_id}")
    print(f"[processos] template_sha256={profile.template_sha256}")
    job = run_native_delivery(contract, profile, real=True, cpu_type_id=args.cpu_type_id)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[processos] status={job['status']} chain_state={job.get('chain_state')} evidence={job['evidence_level']}")
    print(f"[processos] ob_main_included={job.get('ob_main_included')}")
    for ev in job.get("events", []):
        print(f"  stage={ev['stage']} ok={ev['ok']} state={ev['state']} code={ev.get('error_code','')} msg={ev.get('message','')[:160]}")
    if job.get("diagnostics"):
        print("[processos] diagnostics:")
        for d in job["diagnostics"]:
            print(f"  {d}")
    print(f"[processos] receipt written: {out}")
    return 0 if job["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())