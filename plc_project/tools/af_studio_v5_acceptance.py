"""End-to-end acceptance script for AF-Studio v5 orthogonal hypergraph pipeline."""
from __future__ import annotations

import copy
import json
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

BASE = "http://127.0.0.1:8000/api/v2/af-studio"


def request(path: str, payload: dict | None = None, method: str = "POST") -> tuple[dict, str]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    target = Request(BASE + path, data=body, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urlopen(target, timeout=30) as response:
            envelope = json.load(response)
        if not envelope.get("ok"):
            raise RuntimeError(f"API request failed on {path}: {envelope}")
        return envelope["data"], envelope.get("evidence_level", "offline")
    except Exception as ex:
        print(f"FAILED on URL: {BASE + path} method: {method} error: {ex}", file=sys.stderr)
        raise


def run_acceptance() -> dict:
    report: dict[str, object] = {"tests": []}

    # 1. Fetch seed workspace & mother classes
    classes_data, level = request("/mother-classes", method="GET")
    assert classes_data["source"] in ("builtin", "tia_openness_sta")
    report["tests"].append({
        "name": "Reflect Mother Classes",
        "passed": True,
        "classes": len(classes_data["motherClasses"]),
        "evidence": level,
    })

    seed_data, _ = request("/seed-workspace", method="GET")
    assert "projectGraph" in seed_data
    assert "stationHyperGraphs" in seed_data
    assert "ST20" in seed_data["stationHyperGraphs"]
    st20 = seed_data["stationHyperGraphs"]["ST20"]
    report["tests"].append({
        "name": "Load Seed HyperGraph Workspace",
        "passed": True,
        "stations": list(seed_data["stationHyperGraphs"].keys()),
    })

    # 2. Compile Deterministic SCL
    compiled, _ = request("/compile", {"station": st20})
    blocks = {b["name"]: b for b in compiled["blocks"]}
    expected_blocks = {"FB_ST20_AutoSeq", "FB_ST20_HomeSeq", "FC_ST20_GuardDiag", "DB_ST20_Instances"}
    assert expected_blocks.issubset(set(blocks.keys()))
    for name in expected_blocks:
        assert len(blocks[name]["merkleHash"]) == 8
        assert blocks[name]["sclCode"].strip()
    report["tests"].append({
        "name": "Deterministic 4-Block SCL Compilation",
        "passed": True,
        "blocks": list(blocks.keys()),
    })

    # 3. Merkle Incremental Sync
    prj_id = "prj_acc_" + uuid4().hex[:8]
    sync1, level1 = request("/merkle-sync", {"project_id": prj_id, "station": st20})
    assert sync1["dirtyCount"] == 4
    assert sync1["unchangedCount"] == 0

    # Repeat sync with zero edits -> 0 dirty
    sync2, _ = request("/merkle-sync", {"project_id": prj_id, "station": st20})
    assert sync2["dirtyCount"] == 0
    assert sync2["unchangedCount"] == 4
    report["tests"].append({
        "name": "Block-Level Merkle Incremental Sync",
        "passed": True,
        "first_sync_dirty": sync1["dirtyCount"],
        "second_sync_dirty": sync2["dirtyCount"],
        "evidence": level1,
    })

    # 4. Symbolic Formal Verification & Kahn Homing
    verify_res, _ = request("/verify", {"station": st20})
    assert verify_res["passed"] is True
    assert verify_res["issues"] == []
    homing = verify_res["homingResult"]
    assert homing["hasCycleDeadlock"] is False
    assert len(homing["concurrentLayers"]) >= 2
    report["tests"].append({
        "name": "Symbolic Verification & Kahn Homing Synthesis",
        "passed": True,
        "layers": len(homing["concurrentLayers"]),
    })

    # 5. One-Click Repair on Missing Guardrail
    st20_missing = copy.deepcopy(st20)
    st20_missing["guardEdges"] = [g for g in st20_missing["guardEdges"] if g["id"] != "G_ST20_Z_TO_X"]
    res_missing, _ = request("/verify", {"station": st20_missing})
    assert res_missing["passed"] is False
    assert any(i["code"] == "MISSING_GUARDRAIL" for i in res_missing["issues"])
    assert res_missing["suggestedPatches"]
    # Patch and re-verify
    st20_missing["guardEdges"].append(res_missing["suggestedPatches"][0])
    res_fixed, _ = request("/verify", {"station": st20_missing})
    assert res_fixed["passed"] is True
    report["tests"].append({
        "name": "Guardrail Defect Detection & One-Click Repair",
        "passed": True,
        "repaired": True,
    })

    # 6. Neuro-Symbolic Intent Synthesizer (Ghost Diff)
    ghost_tx, _ = request("/copilot/ghost-patch", {
        "station": st20,
        "prompt": "增加视觉 NG 去抛料位虚影分支",
    })
    assert ghost_tx["txId"].startswith("tx_")
    assert ghost_tx["verificationPassed"] is True
    step_nos = [s["stepNo"] for s in ghost_tx["addedTemporalSteps"]]
    assert step_nos == [35, 36]
    report["tests"].append({
        "name": "Neuro-Symbolic Ghost Diff Synthesizer",
        "passed": True,
        "tx_id": ghost_tx["txId"],
        "added_steps": step_nos,
    })

    # 7. Minimal Falsifying Cut-Set & 3-Stage Cruise
    project_graph = seed_data["projectGraph"]
    cutset_data, _ = request("/diagnostics/cutset-snapshot", {
        "project_graph": project_graph,
        "station_graphs": seed_data["stationHyperGraphs"],
        "fault_station_id": "ST20",
        "fault_step_no": 30,
    })
    assert cutset_data["faultResolved"] is False
    assert any(p["terminal"] == "%I10.0" and p["signalValue"] is True for p in cutset_data["prunedHealthyEdges"])
    assert any(f["diagCode"] == "#0203" and f["signalValue"] is False for f in cutset_data["falsifiedEdges"])
    assert len(cutset_data["rootCauses"]) == 1
    rc = cutset_data["rootCauses"][0]
    assert rc["stationId"] == "ST10"
    assert rc["physicalTerminal"] == "%I0.4"
    assert rc["cabinetWireTag"] == "X12:04"
    fly = cutset_data["cameraFlySteps"]
    assert len(fly) == 3
    assert [step["layer"] for step in fly] == ["STATION", "PROJECT", "STATION"]
    report["tests"].append({
        "name": "Minimal Cut-Set Pruning & 3-Stage Fault Cruise",
        "passed": True,
        "culprit_terminal": rc["physicalTerminal"],
        "wire_no": rc["cabinetWireTag"],
        "fly_stages": len(fly),
    })

    return report


def main() -> None:
    try:
        results = run_acceptance()
        print(json.dumps(results, indent=2, ensure_ascii=False))
        sys.exit(0)
    except URLError as ex:
        print(f"Gateway connection error: {ex}. Ensure backend gateway is running.", file=sys.stderr)
        sys.exit(1)
    except Exception as ex:
        print(f"Acceptance test assertion failed: {ex}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
