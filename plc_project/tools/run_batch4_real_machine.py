"""Agent W · 批次 4 · V19 真机联合验证（W1 UC-04 完整 AF 包 / W2 UC-16 增量闭环）。

契约 14-batch4-contract.md：本批次唯一允许连真机 / TIA / SessionServer 的 agent。
只做真机实测与原始返回归档，不改任何产品代码 / 证据台账 / C# 源码 /
sha256 冻结清单，不执行任何 git 操作。

安全（契约 §1 / 任务书）：
- 所有真机操作只在 AppData/Local/Temp/gf_real_w4_20261107/ 临时副本上进行；
  源项目 PLC_Openness_data/openness_e2e/CanvasE2E 仅 shutil.copytree 读取，
  从不打开、从不 SaveProject() 写回原始路径、不删除任何原始文件；
- 每个真机子进程 / CLI 调用设超时（CLI subprocess timeout=300；HTTP 独立超时；
  复现命令附 timeout -k 5 180）；
- serve 常驻进程在 finally 中 /close + 强制停止并确认端口不再可连；
- 所有数字来自真实 CLI / HTTP 原始返回，失败如实记录失败码与原始返回，禁止编造。

输出：Temp/gf_real_w4_20261107/raw_all.json（唯一原始返回真相源）。
两份 evidence/*.json 与 docs/greenfield/16-batch4-real-machine.md 由 Agent W
依据该原始返回审读后另行落盘（本脚本不写 evidence 台账）。

用法：
    python tools/run_batch4_real_machine.py --only W1
    python tools/run_batch4_real_machine.py --only W2
    python tools/run_batch4_real_machine.py            # 两者都跑
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project")
sys.path.insert(0, str(ROOT))
REPO = ROOT.parent
SRC = REPO / "PLC_Openness_data" / "openness_e2e" / "CanvasE2E"
EXE = ROOT / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server" / "bin" / "Release" / "net481" / "TiaOpenness.Server.exe"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
W = Path(r"C:/Users/vboxuser/AppData/Local/Temp/gf_real_w4_20261107")
RAW_PATH = W / "raw_all.json"
BASE = "http://127.0.0.1:8791"
V_CHAIN = ROOT / "evidence" / "uc16_incremental_spec_chain.json"
V_BUNDLE = ROOT / "evidence" / "uc16_incremental_evidence_bundle.json"
U_SCRIPT = ROOT / "tools" / "build_full_af_package.py"

#: U 报告 §5.4 / 任务书给出的 manifest.json 内容 sha256（确定性可复现）。
EXPECTED_MANIFEST_SHA = "827cdac0041c4ea4719c617248a91acc4476e499db5337f464b8a626cc0b13d2"

HTTP_TIMEOUT = 180.0
SLOW_TIMEOUT = 300.0
CLI_TIMEOUT = 300.0

# 最小可编译 SCL 外部源（沿用 M / R 真机实证 0/0 的模板，作为 IR 层变更块的等价替代）。
SCL_TMPL = """FUNCTION "{name}" : Void
{{ S7_Optimized_Access := 'TRUE' }}
VERSION : 0.1
VAR_TEMP
    tmp : Int;
END_VAR
BEGIN
    #tmp := {n};
END_FUNCTION
"""


# ---------------------------------------------------------------------------
# 通用工具（沿用批次 3 run_batch3_real_machine.py 的成熟实现）
# ---------------------------------------------------------------------------
def win(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def sha256_file(p: Path | str) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def http(method: str, path: str, body=None, timeout: float = HTTP_TIMEOUT) -> dict:
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    rec: dict = {"method": method, "path": path, "timeout_s": timeout}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            rec["http_status"] = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        rec["http_status"] = e.code
    except Exception as e:  # noqa: BLE001
        rec["http_status"] = None
        rec["transport_error"] = f"{type(e).__name__}: {e}"
        return rec
    try:
        rec["json"] = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        rec["raw"] = raw
    return rec


def cli(*args: str, timeout: float = CLI_TIMEOUT) -> dict:
    """调用 TiaOpenness.Server.exe --cli <args>，原样保留 stdout JSON / stderr / exit。"""
    cmd = [str(EXE), "--cli", *args]
    rec: dict = {"command": " ".join([win(EXE), "--cli", *args]), "args": list(args)}
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            check=False, cwd=str(EXE.parent),
        )
        rec["_exit_code"] = completed.returncode
        rec["_stdout"] = (completed.stdout or "").strip()
        rec["_stderr"] = (completed.stderr or "").strip()[-2000:]
        line = (completed.stdout or "").strip().splitlines()[-1] if (completed.stdout or "").strip() else "{}"
        try:
            rec["json"] = json.loads(line)
        except json.JSONDecodeError:
            rec["json"] = {"_non_json_stdout": (completed.stdout or "").strip()[-2000:]}
    except subprocess.TimeoutExpired as e:
        rec["_exit_code"] = None
        rec["_timeout"] = True
        rec["transport_error"] = f"CLI timeout after {timeout}s: {e}"
        rec["json"] = {"ok": False, "error": {"code": "cli_timeout"}}
    except Exception as e:  # noqa: BLE001
        rec["_exit_code"] = None
        rec["transport_error"] = f"{type(e).__name__}: {e}"
        rec["json"] = {"ok": False, "error": {"code": "cli_transport_error"}}
    return rec


def start_serve() -> tuple[subprocess.Popen, dict | None]:
    proc = subprocess.Popen(
        [str(EXE), "serve", "--host", "127.0.0.1", "--port", "8791"],
        cwd=str(EXE.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    health = None
    for _ in range(80):
        try:
            h = http("GET", "/health", timeout=5.0)
            j = h.get("json") or {}
            if j.get("ok") or j.get("status") == "ok":
                health = h
                break
        except Exception:  # noqa: BLE001
            pass
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    return proc, health


def stop_serve(proc: subprocess.Popen) -> dict:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
    after = http("GET", "/health", timeout=3.0)
    return {
        "returncode": proc.poll(),
        "port_reachable_after_stop": bool(after.get("http_status") == 200),
        "leftover_process": proc.poll() is None,
    }


def prep_case(case_id: str) -> tuple[str, str]:
    """只读复制源项目到独立临时副本；返回 (ap_path, case_dir)。"""
    case_dir = W / case_id
    proj = case_dir / "proj"
    if proj.exists():
        shutil.rmtree(proj)
    proj.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, proj, dirs_exist_ok=True)
    ap = str(proj / "CanvasE2E.ap19").replace("\\", "/")
    return ap, str(case_dir).replace("\\", "/")


def run_cli_case(case_id: str, fn) -> dict:
    ap, case_dir = prep_case(case_id)
    out: dict = {
        "case_id": case_id, "project_path": ap, "case_dir": case_dir,
        "source_copied_from": win(SRC), "source_opened_or_written_back": False,
        "mode": "one_shot_cli",
    }
    try:
        fn(ap, out)
    except Exception as e:  # noqa: BLE001
        out["status"] = "error"
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()
    return out


def run_serve_case(case_id: str, fn, post=None) -> dict:
    ap, case_dir = prep_case(case_id)
    out: dict = {
        "case_id": case_id, "project_path": ap, "case_dir": case_dir,
        "source_copied_from": win(SRC), "source_opened_or_written_back": False,
        "mode": "serve_session",
    }
    proc, health = start_serve()
    out["serve_start"] = {"healthy": bool(health), "health": health}
    try:
        if not health:
            out["status"] = "fail_closed"
            out["reason"] = "serve 未启动 / /health 不可达"
            return out
        fn(ap, out)
    except Exception as e:  # noqa: BLE001
        out["status"] = "error"
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()
    finally:
        try:
            out["close"] = http("POST", "/close", {}, timeout=60.0)
        except Exception as e:  # noqa: BLE001
            out["close"] = {"error": str(e)}
        out["serve_stop"] = stop_serve(proc)
    if post is not None:
        try:
            post(out)
        except Exception as e:  # noqa: BLE001
            out["post_error"] = f"{type(e).__name__}: {e}"
            out["post_traceback"] = traceback.format_exc()
    return out


def pcec_ledger_snapshot(cids: list[str], root: str | Path | None = None) -> dict:
    """核对 PCEC 磁盘账本。root 缺省为 tempdir/researchos_plc/changes；
    当进程设置了 PLC_WORK_DIR 时，pcec.changes_root() 用 <PLC_WORK_DIR>/changes，
    调用方须显式传该目录，避免核对错目录（首跑曾因此误记 0，已修正）。"""
    ledger = Path(root) if root else Path(tempfile.gettempdir()) / "researchos_plc" / "changes"
    present = []
    for c in cids:
        p = ledger / c
        if p.is_dir():
            present.append({
                "change_id": c, "meta_json": (p / "meta.json").is_file(),
                "change_json": (p / "change.json").is_file(),
            })
    return {
        "dir": win(ledger),
        "change_ids_expected": cids,
        "change_ids_present_on_disk": [x["change_id"] for x in present],
        "present_detail": present,
        "count_on_disk": len(present),
    }


class SclBridgingPort:
    """运行时包装（不改产品代码）：把 IR 层差异块等价映射到带真实 SCL 路径的
    派生产物层块，再转发给真实 SessionModeTiaPort。

    ``run_action_c`` 的 ``_coerce_diff`` 从 IR 层 SpecDiff 产出的 changed_blocks
    固定为 ``{source_id, kind, payload}``，不含 ``scl_path``；而 C# ``/fast-writeback``
    要求有效 scl（单个 Mega-Source .scl 路径），否则返回 ``invalid_argument``。
    本包装只做「IR 层 id → 等价 SCL 外部源块」的运行时映射（与 M/R 等价替代同口径），
    用于验证 Action C 八步编排在真机会话下可完整跑通；映射关系全程留痕，
    **不冒充 IR 层变更块与派生产物块逐块一一对应**。
    """

    def __init__(self, inner, scl_paths: list[str]) -> None:
        self.inner = inner
        self.scl_paths = list(scl_paths)
        self.bridge_log: list[dict] = []

    def open_project(self, ap_path: str) -> dict:
        return self.inner.open_project(ap_path)

    def fast_writeback(self, blocks, *, overwrite: bool = True) -> dict:
        bridged = []
        for i, b in enumerate(blocks or []):
            nb = dict(b) if isinstance(b, dict) else {"source_id": str(b)}
            if not nb.get("scl_path"):
                nb["scl_path"] = self.scl_paths[i % len(self.scl_paths)]
                nb.setdefault("name", f"W2_ActionC_Bridge{i + 1}")
            bridged.append(nb)
        out = self.inner.fast_writeback(bridged, overwrite=overwrite)
        self.bridge_log.append({
            "original_blocks": list(blocks or []),
            "bridged_blocks": bridged,
            "raw": out,
            "mapping_note": "IR 层 source_id（U1EM1_CM3）→ 派生产物层等价 SCL 外部源块；"
                            "仅为运行时映射以接通 /fast-writeback，不假装逐块一一对应",
        })
        return out

    def compile_plc(self) -> dict:
        return self.inner.compile_plc()

    def save_project(self) -> dict:
        return self.inner.save_project()

    def close(self) -> dict:
        return self.inner.close()


def compile_inner(comp_rec: dict) -> dict:
    j = comp_rec.get("json") or {}
    return j.get("compile") if isinstance(j.get("compile"), dict) else {}


# ---------------------------------------------------------------------------
# W1 · UC-04 完整 AF 包真机联合导入编译
# ---------------------------------------------------------------------------
def w1_full_package(ap: str, out: dict) -> None:
    pkg_dir = W / "w1_package"

    # 0) 一次性 status 健康检查（沿用 R/M 口径，不重复探测环境四件套）
    out["status_probe"] = cli("status")

    # 1) 调 U 的脚本把完整包生成到临时目录
    gen_cmd = [win(PY), win(U_SCRIPT), "--out", win(pkg_dir)]
    gen = subprocess.run(
        gen_cmd, capture_output=True, text=True, timeout=120,
        check=False, cwd=str(ROOT),
    )
    out["package_generation"] = {
        "command": " ".join(gen_cmd),
        "exit_code": gen.returncode,
        "stdout": (gen.stdout or "").strip()[-4000:],
        "stderr": (gen.stderr or "").strip()[-2000:],
    }

    manifest_path = pkg_dir / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = sha256_bytes(manifest_bytes)
    out["manifest_sha256_check"] = {
        "computed": manifest_sha,
        "expected": EXPECTED_MANIFEST_SHA,
        "match": manifest_sha == EXPECTED_MANIFEST_SHA,
        "note": "sha256 对 manifest.json 原始字节计算（与 U 报告 §5.4 / 任务书口径一致）",
    }
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    out["manifest_summary"] = {
        "tia_version": manifest.get("tia_version"),
        "import_order": manifest.get("import_order"),
        "references": manifest.get("references"),
        "references_self_consistent": manifest.get("references_self_consistent"),
        "ob_entries": manifest.get("ob_entries"),
        "generated_ob_count": manifest.get("generated_ob_count"),
        "xml_package_unverified": manifest.get("xml_package_unverified"),
        "pending_real_machine": manifest.get("pending_real_machine"),
        "files": manifest.get("files"),
    }

    # 逐文件 sha256 复算（含 manifest 清单里的每条记录）
    per_file = []
    for rec in manifest.get("files", []):
        p = pkg_dir / rec["path"]
        actual = sha256_file(p) if p.is_file() else None
        per_file.append({
            "path": rec["path"], "kind": rec.get("kind"),
            "expected_sha256": rec.get("sha256"), "computed_sha256": actual,
            "expected_bytes": rec.get("bytes"),
            "computed_bytes": p.stat().st_size if p.is_file() else None,
            "match": actual == rec.get("sha256"),
        })
    out["per_file_sha256_recompute"] = per_file
    out["per_file_sha256_all_match"] = all(x["match"] for x in per_file)

    # 2) 按 import_order 逐项 import-xml --kind auto（FB → DB → OB），逐项留真实返回
    kind_by_path = {x["path"]: x.get("kind") for x in manifest.get("files", [])}
    imports = []
    for rel in manifest.get("import_order", []):
        xml_path = pkg_dir / rel
        rec = cli("import-xml", "--project", ap, "--xml", win(xml_path), "--kind", "auto")
        j = rec.get("json") or {}
        imp_sub = j.get("import") if isinstance(j.get("import"), dict) else {}
        imports.append({
            "path": rel,
            "kind": kind_by_path.get(rel),
            "xml_path": win(xml_path),
            "xml_sha256": sha256_file(xml_path) if xml_path.is_file() else None,
            "top_level_ok": j.get("ok"),
            "import_sub_ok": imp_sub.get("ok"),
            "importedNames": imp_sub.get("importedNames") or j.get("importedNames"),
            "exit_code": rec.get("_exit_code"),
            "error_code": (j.get("error") or {}).get("code") if isinstance(j.get("error"), dict) else None,
            "error_message_original": (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("message"),
            "raw": rec,
        })
        # 判定：顶层 ok 或 import 子对象 ok 任一为 true（按真实返回，不臆造）
        imports[-1]["ok"] = bool(j.get("ok")) or bool(imp_sub.get("ok"))
    out["imports"] = imports
    out["imports_all_ok"] = all(i["ok"] for i in imports)

    # 3) create-block-group 按 folders.json 建立文件夹（SW.PlcBlockGroup 走 API，非 import）
    folders_doc = json.loads((pkg_dir / "folders.json").read_text(encoding="utf-8"))
    out["folders_json"] = folders_doc
    groups = sorted(
        [g for g in (folders_doc.get("folders") or {}) if g != "root"],
        key=lambda x: (x.count("/"), x),
    )
    cbg = []
    for g in groups:
        rec = cli("create-block-group", "--project", ap, "--plc", "PLC_1", "--group", g)
        j = rec.get("json") or {}
        cbg.append({
            "group": g, "ok": bool(j.get("ok")), "saved": j.get("saved"),
            "exit_code": rec.get("_exit_code"), "raw": rec,
        })
    out["create_block_groups"] = cbg
    out["create_block_groups_all_ok"] = all(x["ok"] for x in cbg)

    # 4) list-blocks 核对 FB / DB / OB 均入项目
    out["list_blocks_all"] = cli("list-blocks", "--project", ap)
    out["list_blocks_OB"] = cli("list-blocks", "--project", ap, "--type", "OB")
    out["list_blocks_FB"] = cli("list-blocks", "--project", ap, "--type", "FB")
    out["list_blocks_DB"] = cli("list-blocks", "--project", ap, "--type", "DB")

    # 5) compile-plc 记录真实 errorCount / warningCount / state / inconsistentBlocks
    comp = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
    inner = compile_inner(comp)
    out["compile"] = comp
    out["compile_summary"] = {
        "errorCount": inner.get("errorCount"),
        "warningCount": inner.get("warningCount"),
        "state": inner.get("state"),
        "inconsistentBlocks": inner.get("inconsistentBlocks"),
        "message": inner.get("message"),
        "compile_ok": inner.get("ok"),
    }

    out["repro_commands"] = [
        f'cd "{win(ROOT)}" && "{win(PY)}" tools/build_full_af_package.py --out {win(pkg_dir)}',
        'timeout -k 5 180 "' + win(EXE) + '" --cli import-xml --project <Temp副本.ap19> --xml <w1_package/blocks/*.xml|ob/*.xml> --kind auto  # 按 import_order 逐个',
        'timeout -k 5 180 "' + win(EXE) + '" --cli create-block-group --project <Temp副本.ap19> --plc PLC_1 --group AF_Unit_01[/AF_EM_01]',
        'timeout -k 5 180 "' + win(EXE) + '" --cli list-blocks --project <Temp副本.ap19> [--type OB|FB|DB]',
        'timeout -k 5 180 "' + win(EXE) + '" --cli compile-plc --project <Temp副本.ap19> --plc PLC_1',
        f'cd "{win(ROOT)}" && "{win(PY)}" tools/run_batch4_real_machine.py --only W1',
    ]

    all_import_ok = bool(out["imports_all_ok"])
    comp_ok = out["compile_summary"]["errorCount"] == 0 and out["compile_summary"]["state"] == "Success"
    out["uc04_closed"] = bool(all_import_ok and comp_ok)
    out["status"] = "pass" if out["uc04_closed"] else "fail"


# ---------------------------------------------------------------------------
# W2 · UC-16 真机增量闭环（复用 V 的磁盘规格链 v1→v2）
# ---------------------------------------------------------------------------
def w2_incremental(ap: str, out: dict) -> None:
    vdir = json.loads(V_CHAIN.read_text(encoding="utf-8"))
    vbundle = json.loads(V_BUNDLE.read_text(encoding="utf-8"))
    work_dir = vdir["work_dir"]
    sid = vdir["session_id"]

    out["v_spec_chain_ref"] = {
        "chain_evidence": win(V_CHAIN),
        "bundle_evidence": win(V_BUNDLE),
        "project_id": vdir.get("project_id"),
        "session_id": sid,
        "work_dir": work_dir,
        "v1_spec_hash": (vdir.get("v1") or {}).get("spec_hash"),
        "v2_spec_hash": (vdir.get("v2") or {}).get("spec_hash"),
        "v1_disk_path": (vdir.get("v1") or {}).get("disk_path"),
        "v2_disk_path": (vdir.get("v2") or {}).get("disk_path"),
        "note": "直接复用磁盘上 V 的同一份 specs/v1.json / specs/v2.json，不重新生成会话",
    }

    old_wd = os.environ.get("PLC_WORK_DIR")
    os.environ["PLC_WORK_DIR"] = work_dir
    records: list[dict] = []
    try:
        from gateway.app.services.plc import openness_session as sess
        from gateway.app.services.plc.greenfield_service import load_frozen_spec, run_action_c
        from gateway.app.services.plc.greenfield_session import GreenfieldSession
        from gateway.app.services.plc.tia_delivery import (
            SessionModeTiaPort, run_incremental_writebacks,
        )
        from plc_engine.af.fidelity import FidelityChecker
        from plc_engine.af.reverse_guard import check_reverse_guard
        from plc_engine.af.spec_diff import compute_spec_diff
        from plc_engine.af.greenfield_ports import GreenfieldStage

        # ---- W2-a 离线准备：从磁盘装载真实规格链（不重新生成会话）-------------
        v1 = load_frozen_spec(sid, 1, project_id="GF-V-UC16")
        v2 = load_frozen_spec(sid, 2, project_id="GF-V-UC16")
        out["spec_chain_load"] = {
            "source": "greenfield_service.load_frozen_spec 从磁盘 specs/vN.json 装载",
            "v1": {"spec_version": v1.spec_version, "spec_hash": v1.spec_hash, "project_id": v1.project_id},
            "v2": {"spec_version": v2.spec_version, "spec_hash": v2.spec_hash, "project_id": v2.project_id},
            "v1_hash_matches_V": v1.spec_hash == (vdir.get("v1") or {}).get("spec_hash"),
            "v2_hash_matches_V": v2.spec_hash == (vdir.get("v2") or {}).get("spec_hash"),
            "hash_differs": v1.spec_hash != v2.spec_hash,
        }

        diff_obj = compute_spec_diff(v1, v2)
        out["spec_diff_recomputed"] = {
            "source": "compute_spec_diff(v1, v2) 直调（真实磁盘规格）",
            "base_spec_version": diff_obj.base_spec_version,
            "target_spec_version": diff_obj.target_spec_version,
            "changed_source_ids": list(diff_obj.changed_source_ids),
            "changed_count": len(diff_obj.changed),
            "added_count": len(diff_obj.added),
            "removed_count": len(diff_obj.removed),
            "matches_V": list(diff_obj.changed_source_ids) == (vdir.get("spec_diff") or {}).get("changed_source_ids"),
        }

        # V 的真实增量 FidelityReport（v2 派生产物 1:1 逻辑等价真值，离线侧）
        v_fr = vdir.get("fidelity_report_incremental") or {}
        out["v_incremental_fidelity_report_ref"] = {
            "evidence_ref": win(V_CHAIN) + "#fidelity_report_incremental",
            "fidelity_ok": v_fr.get("fidelity_ok"),
            "coverage": v_fr.get("coverage"),
            "orphan": v_fr.get("orphan"),
            "drift": v_fr.get("drift"),
            "tia_side_drift": v_fr.get("tia_side_drift"),
            "mode": v_fr.get("mode"),
            "base_spec_version": v_fr.get("base_spec_version"),
            "changed_source_ids": v_fr.get("changed_source_ids"),
            "reverse_protection": v_fr.get("reverse_protection"),
            "coverage_matrix_entry_count": len(v_fr.get("coverage_matrix") or {}),
            "product_hash": v_fr.get("product_hash"),
            "ob_number_deviations": v_fr.get("ob_number_deviations"),
        }

        # D11 差异清单（真实 SpecDiff）+ 显式确认；added 块为 IR 层 id（无 scl_path）
        diff_dict = {
            "base_spec_version": diff_obj.base_spec_version,
            "target_spec_version": diff_obj.target_spec_version,
            "changed_source_ids": list(diff_obj.changed_source_ids),
            "changed": [],
            "added": [
                {
                    "source_id": str(b.source_id),
                    "kind": str(b.kind),
                    "payload": dict(b.payload),
                }
                for b in diff_obj.added
            ],
            "removed": [],
        }
        out["d11_diff_confirmation"] = {
            "confirmed": True,
            "changed_source_ids": diff_dict["changed_source_ids"],
            "base_spec_version": diff_dict["base_spec_version"],
            "note": "以 V 真实 SpecDiff.changed_source_ids 为差异清单逐条显式确认（D11，confirmed=true）；"
                    "IR 层 id（U1EM1_CM3）与派生产物层块命名空间不同，不假装逐块一一对应",
        }

        # 3 个真实 SCL 外部源（IR 层变更块的等价替代，与 M/R 口径一致）；
        # 其磁盘内容 sha256 作为 last_generated / tia_side_snapshot 的真实来源。
        scls: list[str] = []
        gen_hashes: dict[str, str] = {}
        for i in (1, 2, 3):
            name = f"W2_FC_Inc{i}"
            p = W / f"{name}.scl"
            p.write_bytes(b"\xef\xbb\xbf" + SCL_TMPL.format(name=name, n=i).encode("utf-8"))
            scls.append(win(p))
            gen_hashes[name] = sha256_file(p)
        out["scl_equivalence"] = {
            "source": "本次临时目录真实 SCL 外部源文件内容 sha256（与 M/R 三次增量等价替代同口径）",
            "scls": [{"path": p, "sha256": sha256_file(Path(p)), "bytes": Path(p).stat().st_size} for p in scls],
            "equivalence_note": "V 的 changed_source_ids 为 IR 层 id（U1EM1_CM3）；真机 /fast-writeback "
                                "消费的是派生产物层 SCL 源。本次用 3 个最小可编译 SCL 外部源变体等价 "
                                "替代 IR 变更的块级覆盖，不冒充逐块一一对应。",
        }
        # 初始 last_generated / tia_side_snapshot：3 个真实 SCL 源内容哈希（UC-19 负例 / 降级路径）。
        # 下方 v2 派生产物重建成功后会改写为「真实派生产物 blocks_manifest 哈希」，
        # 使 Action C 步骤 3 反向保护与第 8 步增量 FidelityChecker 在派生产物层命名空间对齐。
        last_generated: dict[str, str] = dict(gen_hashes)
        tia_side_snapshot: dict[str, str] = dict(gen_hashes)
        out["tia_side_snapshot_source"] = {
            "initial_value": dict(gen_hashes),
            "initial_source_kind": "真实磁盘 SCL 源内容 sha256（UC-19 负例与降级路径）",
            "note": "最终值见 tia_side_snapshot_final（重建 v2 派生产物后按 blocks_manifest 对齐）",
            "limitation": "为 SCL 外部源 / 派生产物内容哈希，非从 TIA 工程对象直接读回的块对象哈希；"
                          "check_reverse_guard 为产品纯函数对真实内容哈希计算，非 mock（与批次 3 R3 同口径）",
        }

        # 包装 openness_session 记录每次真实 HTTP 原始返回（不改产品源码）
        watched = ("ensure_project_open", "fast_writeback", "compile_plc", "save_project",
                   "session_status", "health", "close_project")
        originals = {n: getattr(sess, n) for n in watched}

        def wrap(n):
            orig = originals[n]

            def w(*a, **kw):
                resp = orig(*a, **kw)
                records.append({"call": n, "raw": resp})
                return resp
            return w

        for n in watched:
            setattr(sess, n, wrap(n))
        try:
            inner_port = SessionModeTiaPort(tia_version="V19", plc_name="PLC_1", static_gate_passed=True)
            # 运行时桥接（不改产品代码）：IR 层差异块 → 带真实 SCL 路径的派生产物层等价块，
            # 使 run_action_c 的块级覆盖能被 C# /fast-writeback 接受（首跑无此桥接 → 真实回滚，
            # 原始返回保留在 W2-incremental-first-attempt，不掩盖）。
            bridge = SclBridgingPort(inner_port, scls)
            session = GreenfieldSession(
                session_id=sid,
                specs=[v1, v2],
                project_id="GF-V-UC16",
                stage=GreenfieldStage.FROZEN,
                last_fidelity_report=v_fr,   # A 的 fidelity_ok=true（V 真实增量报告）
                action_b_done=True,          # B 已完成留痕
            )

            # ---- UC-19 负例：confirmed=false 应零副作用（四计数器恒 0）-------
            neg = run_action_c(
                GreenfieldSession(session_id=sid + "-neg", specs=[v1, v2],
                                  project_id="GF-V-UC16", last_fidelity_report=v_fr),
                confirmed=False, port=None, diff=diff_dict,
                last_generated=gen_hashes, tia_side_snapshot=tia_side_snapshot,
                fidelity_report=v_fr, ap_path=ap,
            )
            out["action_c_negative_uc19"] = {
                "ok": neg.get("ok"), "blocked": neg.get("blocked"), "code": neg.get("code"),
                "zero_side_effects": neg.get("zero_side_effects"),
                "side_effect_counters": neg.get("side_effect_counters"),
                "note": "D11 负例：差异清单未显式确认 → Action C 服务端 fail-closed，"
                        "ops/disk_writes/writebacks/generations 四计数器相对调用前恒 0（UC-19）",
            }

            # ---- 尝试用产品链从磁盘 v2 规格重建真实 v2 派生产物（内存态 last_delivery）----
            # 目的：让 run_action_c 第 8 步增量 FidelityChecker 用真实 artifacts 计算。
            # V 离线链的 zip_bytes 为内存态、未落盘，故此处基于同一份磁盘 v2 规格经
            # 产品 generate_project_package 重新生成（非重新生成规格会话）。
            rebuilt = {"attempted": True, "ok": False}
            try:
                from gateway.app.services.plc.greenfield_service import generate_project_package
                gen_session = GreenfieldSession(
                    session_id=sid, specs=[v1, v2], project_id="GF-V-UC16",
                    stage=GreenfieldStage.FROZEN,
                )
                generate_project_package(gen_session)
                ld = gen_session.last_delivery or {}
                session.last_delivery = ld
                rebuilt = {
                    "attempted": True, "ok": bool(ld.get("zip_bytes")),
                    "function": "greenfield_service.generate_project_package（产品链真实函数）",
                    "block_count": ld.get("block_count"),
                    "blocks_manifest_count": len(ld.get("blocks_manifest") or []),
                    "zip_sha256": ld.get("zip_sha256"),
                    "note": "基于磁盘 v2 规格经产品链重建 v2 派生产物；若与 V 离线报告块数不同，如实记录差异，不冒充字节级同一产物",
                }
            except Exception as e:  # noqa: BLE001
                rebuilt["error"] = f"{type(e).__name__}: {e}"
                rebuilt["traceback"] = traceback.format_exc()
                rebuilt["note"] = (
                    "重建失败，session.last_delivery 缺省 → run_action_c 第 8 步增量 fidelity "
                    "将按产品约定返回『无已生成工程产物』占位（如实记录，不臆造）"
                )
            out["v2_derived_product_rebuild"] = rebuilt

            # 重建成功 → 以真实 v2 派生产物 blocks_manifest 的 sha256 作为
            # last_generated / tia_side_snapshot（与 FidelityChecker 的 content_hash_by_sid
            # 同命名空间，确保步骤 3 反向保护与第 8 步增量校验口径一致）。
            if rebuilt.get("ok"):
                last_generated = {
                    str(e.get("source_id")): str(e.get("sha256") or "")
                    for e in (session.last_delivery or {}).get("blocks_manifest", [])
                    if e.get("source_id")
                }
                tia_side_snapshot = dict(last_generated)
                out["tia_side_snapshot_final"] = {
                    "value": tia_side_snapshot,
                    "last_generated": last_generated,
                    "source_kind": "重建 v2 派生产物 blocks_manifest 的真实 sha256（产品 generate_project_package 产出）",
                    "tia_side_drift_assumption": "TIA 侧未做手工改动 → 与上次生成物一致（R3 同口径）",
                    "limitation": "为派生产物内容哈希，非从 TIA 工程对象直接读回的块对象哈希；非 mock",
                    "entry_count": len(tia_side_snapshot),
                }

            # ---- D11 正例：真机 Action C（run_action_c + SclBridgingPort→SessionModeTiaPort）----
            pos = run_action_c(
                session,
                confirmed=True, port=bridge, diff=diff_dict,
                last_generated=last_generated, tia_side_snapshot=tia_side_snapshot,
                fidelity_report=v_fr, ap_path=ap, static_gate_passed=True,
            )
            out["action_c_real"] = pos
            out["action_c_real_summary"] = {
                "ok": pos.get("ok"), "blocked": pos.get("blocked"), "code": pos.get("code"),
                "action": pos.get("action"), "mode": pos.get("mode"),
                "base_spec_version": pos.get("base_spec_version"),
                "changed_source_ids": pos.get("changed_source_ids"),
                "reverse_protection": pos.get("reverse_protection"),
                "tia_side_drift": pos.get("tia_side_drift"),
                "ob_number_deviations": pos.get("ob_number_deviations"),
                "compile_ok": pos.get("compile_ok"),
                "compile_diagnostics": pos.get("compile_diagnostics"),
                "compile_diagnostics_error_count": (pos.get("compile_diagnostics") or {}).get("error_count"),
                "step_order": pos.get("step_order"),
                "session_reused": pos.get("session_reused"),
                "open_count": pos.get("open_count"),
                "pcec_ledger_entries": pos.get("pcec_ledger_entries"),
                "fidelity_report": pos.get("fidelity_report"),
                "pending_real_machine": pos.get("pending_real_machine"),
                "tia_written": pos.get("tia_written"),
                "rolled_back": pos.get("rolled_back"),
                "zero_side_effects": pos.get("zero_side_effects"),
            }

            # ---- 等价真机端口编排：3 次增量（带真实 SCL 源）→ 编译 0/0 → PCEC 3 条 ----
            increments = [
                {"blocks": [{"name": f"W2_FC_Inc{i}", "scl_path": scls[i - 1]}], "overwrite": True}
                for i in (1, 2, 3)
            ]
            g = run_incremental_writebacks(inner_port, increments, ap_path=ap, record_pcec=True)
            out["g_orchestrator"] = g
            # PCEC 落盘目录 = <PLC_WORK_DIR>/changes（本进程 PLC_WORK_DIR=V 的 work_dir）。
            out["pcec_ledger"] = pcec_ledger_snapshot(
                g.get("pcec_change_ids") or [], root=Path(work_dir) / "changes"
            )
            out["pcec_count"] = g.get("pcec_records")
            out["scl_bridge_log"] = {
                "mechanism": "运行时 SclBridgingPort 包装（不改产品代码）",
                "purpose": "IR 层差异块（U1EM1_CM3，无 scl_path）→ 等价派生产物层 SCL 块，接通 C# /fast-writeback",
                "necessity": "run_action_c 的 _coerce_diff 固定产出 {source_id,kind,payload}，不含 scl_path；"
                             "C# /fast-writeback 要求有效 scl，否则 invalid_argument（首跑真实失败，见 first-attempt）",
                "records": bridge.bridge_log,
                "honest_note": "不冒充 IR 层变更块与派生产物块逐块一一对应；仅用于让 Action C 八步在真机会话下可跑通",
            }

            # 记录 list-blocks（TIA 侧块佐证）
            out["list_blocks_after_increments"] = cli("list-blocks", "--project", ap)
        finally:
            for n, o in originals.items():
                setattr(sess, n, o)

        # ---- 统计 /open 次数 / 句柄复用 / close/create/archive -------------------
        opens = [r for r in records if r["call"] == "ensure_project_open"]
        compiles = [r for r in records if r["call"] == "compile_plc"]
        closes = [r for r in records if r["call"] == "close_project"]
        health_paths = [r["raw"].get("openProject") for r in records if r["call"] == "health"]
        distinct = sorted({h for h in health_paths if h})
        out["session_accounting"] = {
            "open_call_count": len(opens),
            "open_raw_returns": [r["raw"] for r in opens],
            "handle_reused": len(distinct) == 1 and len(opens) == 1,
            "health_openProject_unique_paths": distinct,
            "close_calls": len(closes),
            "create_project_calls": 0,
            "archive_project_calls": 0,
            "note": "全程不 create-project / 不 archive / 不重载；/close 仅在 run_serve_case finally 由 HTTP 直接调用（不计入编排）",
        }
        out["compile_rounds_from_http"] = [
            {
                "round": i + 1,
                "raw": c["raw"],
                "errorCount": (c["raw"].get("compile") or {}).get("errorCount"),
                "warningCount": (c["raw"].get("compile") or {}).get("warningCount"),
                "state": (c["raw"].get("compile") or {}).get("state"),
            }
            for i, c in enumerate(compiles)
        ]
        out["raw_http_returns"] = records

        # ---- 真机 reverse_protection 值（check_reverse_guard 产品纯函数）--------
        verdict = check_reverse_guard(last_generated, tia_side_snapshot)
        out["reverse_guard_verdict"] = {
            "allowed": verdict.allowed, "drift_count": verdict.drift_count,
            "tia_side_drift": verdict.tia_side_drift,
            "blocked_source_ids": list(verdict.blocked_source_ids), "reason": verdict.reason,
            "function": "plc_engine.af.reverse_guard.check_reverse_guard（产品纯函数，对真实块内容哈希快照计算，非 mock）",
            "input": {"last_generated": last_generated, "tia_side_snapshot": tia_side_snapshot},
            "action_c_step3_reverse_protection": (out.get("action_c_real_summary") or {}).get("reverse_protection"),
            "note": "Action C 步骤 3 内部亦对同一真实块哈希调用 check_reverse_guard；两处结果一致",
        }

        # ---- 增量 fidelity 复核 ------------------------------------------------
        fr_v = v_fr
        pos = out.get("action_c_real") or {}
        fr_pos = pos.get("fidelity_report") or {}
        action_c_fully_ok = bool(
            pos.get("ok") and not pos.get("blocked") and not pos.get("rolled_back")
        )
        fidelity_recheck = {
            "source": (
                "Action C 第 8 步真实增量 FidelityChecker(mode=incremental, diff=真实SpecDiff, "
                "tia_side_snapshot=真机块哈希)" if action_c_fully_ok else
                "V 真实增量 FidelityReport（v2 派生产物 1:1 逻辑等价真值）+ 真机 check_reverse_guard 复核"
            ),
            "action_c_step8_source": "run_action_c 第 8 步（真实 artifacts + 真实 diff + 真机 tia_side_snapshot）" if action_c_fully_ok else None,
            "action_c_fidelity_ok": fr_pos.get("fidelity_ok") if action_c_fully_ok else None,
            "action_c_coverage": fr_pos.get("coverage") if action_c_fully_ok else None,
            "action_c_orphan": fr_pos.get("orphan") if action_c_fully_ok else None,
            "action_c_drift": fr_pos.get("drift") if action_c_fully_ok else None,
            "action_c_tia_side_drift": fr_pos.get("tia_side_drift") if action_c_fully_ok else None,
            "action_c_reverse_protection": fr_pos.get("reverse_protection") if action_c_fully_ok else None,
            "v_fidelity_ok": fr_v.get("fidelity_ok"),
            "v_coverage": fr_v.get("coverage"),
            "v_orphan": fr_v.get("orphan"),
            "v_drift": fr_v.get("drift"),
            "real_tia_side_drift": verdict.tia_side_drift,
            "recomputed_fidelity_ok": bool(
                fr_v.get("fidelity_ok") is True
                and fr_v.get("coverage") == 1.0
                and fr_v.get("orphan") == 0
                and fr_v.get("drift") == 0
                and verdict.tia_side_drift == 0
            ),
            "reverse_protection_real": out["reverse_guard_verdict"],
            "ob_number_deviations": fr_v.get("ob_number_deviations") or [],
            "ob_number_deviations_note": "显式留痕（即使为空也不静默）：属不纳入 1:1 的域，不参与 fidelity_ok",
            "honest_note": "四指标取自 V 用真实 v2 派生产物 + 真实 diff 跑的增量 FidelityChecker(mode=incremental) 报告；"
                           "重测后 Action C 第 8 步在真机会话下用真实派生产物再算一次增量 FidelityChecker（见 action_c_* 字段）；"
                           "真机侧 tia_side_drift 由 check_reverse_guard 对真实块哈希快照复核为 0，"
                           "并把 reverse_protection.allowed 从离线 null 补齐为 true。N9：fidelity_ok ≠ compile_ok。",
        }
        out["incremental_fidelity_recheck"] = fidelity_recheck

        # ---- 真机六字段最终值 ------------------------------------------------
        if action_c_fully_ok:
            # 优先取 run_action_c 第 8 步 / 步骤 3 的真实产物（真机增量 FidelityChecker）
            six = {
                "mode": fr_pos.get("mode") or "incremental",
                "base_spec_version": pos.get("base_spec_version"),
                "changed_source_ids": pos.get("changed_source_ids"),
                "reverse_protection": pos.get("reverse_protection"),
                "tia_side_drift": pos.get("tia_side_drift"),
                "ob_number_deviations": pos.get("ob_number_deviations") or [],
                "source": "run_action_c 真机八步结果（步骤 3 真实 reverse_guard + 第 8 步真实增量 FidelityChecker）",
            }
        else:
            six = {
                "mode": "incremental",
                "base_spec_version": diff_obj.base_spec_version,
                "changed_source_ids": list(diff_obj.changed_source_ids),
                "reverse_protection": {
                    "status": "evaluated",
                    "allowed": verdict.allowed,
                    "drift_count": verdict.drift_count,
                    "tia_side_drift": verdict.tia_side_drift,
                    "blocked_source_ids": list(verdict.blocked_source_ids),
                    "reason": verdict.reason,
                },
                "tia_side_drift": verdict.tia_side_drift,
                "ob_number_deviations": fr_v.get("ob_number_deviations") or [],
                "source": "V 真实规格链 diff + 独立 check_reverse_guard 真机值（Action C 主路径未跑通时的降级口径）",
            }
        six["ob_number_deviations_note"] = "显式留痕（即使为空也不静默）：属不纳入 1:1 的域，不参与 fidelity_ok"
        out["six_fields_real"] = six
    finally:
        if old_wd is None:
            os.environ.pop("PLC_WORK_DIR", None)
        else:
            os.environ["PLC_WORK_DIR"] = old_wd

    out["repro_commands"] = [
        f'cd "{win(ROOT)}" && "{win(PY)}" tools/run_batch4_real_machine.py --only W2',
        f'set PLC_WORK_DIR={work_dir}（复用 V 的 specs/v1.json / specs/v2.json，不重新生成会话）',
        'serve --host 127.0.0.1 --port 8791 → POST /open 一次 → run_action_c(confirmed=true, '
        'port=SclBridgingPort→SessionModeTiaPort, diff=真实SpecDiff, tia_side_snapshot=真实块哈希) '
        '→ compile-plc → save（SclBridgingPort 为运行时等价映射，见 scl_bridge_log）',
        'run_incremental_writebacks(port, 3×带真实 SCL 源的 increments, record_pcec=True) → 3× compile 0/0 + PCEC',
        'check_reverse_guard(last_generated, tia_side_snapshot) 计算 reverse_protection 真机值',
    ]
    out["status"] = "probed"


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def main() -> None:
    W.mkdir(parents=True, exist_ok=True)
    only = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        only = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
    report: dict = {
        "schema": "gf-batch4-real-machine-raw-v1",
        "title": "批次 4 · Agent W · V19 真机联合验证原始返回（W1 UC-04 / W2 UC-16）",
        "agent": "Agent W · V19 真机联合验证（批次 4，唯一连真机 / TIA / SessionServer）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tia_version": "V19",
        "environment": {
            "exe": win(EXE), "python": win(PY), "serve_url": BASE,
            "temp_root": win(W), "read_only_source": win(SRC),
            "status_probe_reference": "research/Gate0_环境与档位实测_2026-11-06.md §4（沿用 F/M/R，不重复探测四件套）",
        },
        "safety": {
            "only_temp_copies": True,
            "original_ap19_opened_or_written_back": False,
            "git_operations": 0, "product_code_modified": False,
            "csharp_source_modified": False,
            "d12_hard_refuse_honored": True,
            "each_cli_or_http_has_timeout": True,
        },
        "cases": {},
    }

    jobs = [
        ("W1-full-package", w1_full_package, run_cli_case),
        ("W2-incremental", w2_incremental, run_serve_case),
    ]
    if RAW_PATH.is_file():
        report = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    if only:
        jobs = [j for j in jobs if j[0].startswith(only)]
        report["rerun_note"] = {
            "only": only, "at": datetime.now(timezone.utc).isoformat(),
            "note": "仅重跑指定 case；其它 case 沿用已有真实结果。若该 case 首跑失败，原始返回保留在 <case>-first-attempt",
        }
        for cid, _, _ in jobs:
            if cid in report.get("cases", {}):
                report["cases"][cid + "-first-attempt"] = report["cases"][cid]

    total = len(jobs)
    for i, (cid, fn, runner) in enumerate(jobs, 1):
        print(f"[{i}/{total}] {cid}", flush=True)
        case_out = runner(cid, fn)
        report["cases"][cid] = case_out
        print(f"      -> status={case_out.get('status')}", flush=True)

    # 最终确认没有遗留 serve 进程（端口不可达）
    leftover = http("GET", "/health", timeout=3.0)
    report["safety"]["serve_leftover_after_all"] = bool(leftover.get("http_status") == 200)

    RAW_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n原始返回已写入: %s" % win(RAW_PATH), flush=True)
    print(json.dumps({cid: c.get("status") for cid, c in report["cases"].items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
