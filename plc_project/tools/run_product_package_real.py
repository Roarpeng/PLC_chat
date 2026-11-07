"""Agent Y · 批次 4 收口 · 正式产品通道 ``xml_supplement/`` 的 V19 真机验证。

分工（沿用 W 的 ``tools/run_batch4_real_machine.py`` 方法学）：
- Y1 纯离线：构造冻结会话 → ``deliver_tia(session, mode="package")`` → 把 ``zip_bytes``
  落到 Temp 临时目录 → 解压 ``xml_supplement/`` → manifest 真实值 / 逐文件 sha256 /
  Python XML 解析核对 CallInfo.Name / Component.Name / DB InstanceOfName 与 FB/DB ``<Name>``；
- Y2 真机：在 ``Temp/gf_real_y4_*/case_*/proj`` 干净副本上按 ``import_order``
  （FB → DB → OB）逐项 ``--cli import-xml --kind auto`` → ``create-block-group`` →
  ``list-blocks`` → ``compile-plc``，逐项留真实 CLI 原始返回。

本脚本**只**把原始真相源写入 ``Temp/gf_real_y4_20261107/raw_all.json``（每轮 append，
不覆盖、不掩盖中间失败）；``evidence/uc04_product_package_real.json`` 与
``docs/greenfield/18-product-package-real.md`` 由 Agent Y 审读原始返回后另行落盘。

安全（契约 14-batch4-contract.md §1 / 任务书）：
- 真机操作只在 ``C:/Users/vboxuser/AppData/Local/Temp/gf_real_y4_*`` 临时副本；
  只读源 ``PLC_Openness_data/openness_e2e/CanvasE2E`` 仅 ``shutil.copytree`` 复制，
  **从不打开/写回原始 .ap19/.zap19**、不删除原始文件；
- 全程 ``--cli`` 一次性调用（不启动 serve 常驻进程，8791 从未监听）；
- 每个真机子进程 Python ``subprocess.run(timeout=180)``，复现命令附 ``timeout -k 5 180``；
- 不执行任何 git 操作 / 不改任何产品代码 / 不改冻结清单与证据台账；
- 所有数字来自真实 CLI 原始返回，失败如实记录，禁止编造。

用法：
    python tools/run_product_package_real.py                 # 全跑，run_id=Y-1
    python tools/run_product_package_real.py --case Y-2     # 干净副本重测（保留旧轮）
    python tools/run_product_package_real.py --only Y1      # 仅离线结构核对
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project")
sys.path.insert(0, str(ROOT))
REPO = ROOT.parent
SRC = REPO / "PLC_Openness_data" / "openness_e2e" / "CanvasE2E"
EXE = ROOT / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server" / "bin" / "Release" / "net481" / "TiaOpenness.Server.exe"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
TEMP = Path(r"C:/Users/vboxuser/AppData/Local/Temp/gf_real_y4_20261107")
RAW_PATH = TEMP / "raw_all.json"
CLI_TIMEOUT = 180.0


# --------------------------------------------------------------------------- 通用工具
def win(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_prefixed(b: bytes) -> str:
    return "sha256:" + sha256_bytes(b)


def _local(tag: str) -> str:
    """去 namespace：``{urn}CallInfo`` → ``CallInfo``；``Name`` → ``Name``。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_xml(data: bytes) -> ET.Element:
    return ET.fromstring(data.decode("utf-8-sig"))


def _block_name(root: ET.Element) -> str | None:
    """块根 AttributeList 下唯一 ``<Name>`` 元素文本。"""
    for el in root.iter():
        if _local(el.tag) == "Name" and el.text and el.text.strip():
            return el.text.strip()
    return None


def _callinfo_component(root: ET.Element) -> tuple[str | None, str | None]:
    """从 FlgNet Call 网络提取 ``CallInfo@Name`` / ``Component@Name``（按 localname 精确匹配）。"""
    ci = comp = None
    for el in root.iter():
        if _local(el.tag) == "CallInfo":
            ci = el.get("Name")
        elif _local(el.tag) == "Component":
            comp = el.get("Name")
    return ci, comp


def _instance_of_name(root: ET.Element) -> str | None:
    for el in root.iter():
        if _local(el.tag) == "InstanceOfName":
            return (el.text or "").strip()
    return None


def cli(*args: str) -> dict:
    """``TiaOpenness.Server.exe --cli <args>``，原样保留 stdout / stderr / exit。"""
    cmd = [str(EXE), "--cli", *args]
    rec: dict = {"command": " ".join([win(EXE), "--cli", *args]), "args": list(args),
                 "timeout_s": CLI_TIMEOUT}
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CLI_TIMEOUT, check=False, cwd=str(EXE.parent),
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
        rec["transport_error"] = f"CLI timeout after {CLI_TIMEOUT}s: {e}"
        rec["json"] = {"ok": False, "error": {"code": "cli_timeout"}}
    except Exception as e:  # noqa: BLE001
        rec["_exit_code"] = None
        rec["transport_error"] = f"{type(e).__name__}: {e}"
        rec["json"] = {"ok": False, "error": {"code": "cli_transport_error"}}
    return rec


def health_probe() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8791/health", timeout=3.0) as r:
            return {"reachable": True, "http_status": r.status}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- Y1 离线
def generate_and_check() -> dict:
    """生成正式产品包并做结构核对；不改 ZIP 内容、不改产品代码。"""
    out: dict = {"method": "deliver_tia(_frozen_session(...), mode='package') 正式产品通道"}
    TEMP.mkdir(parents=True, exist_ok=True)
    work = TEMP / "work"
    work.mkdir(parents=True, exist_ok=True)
    os.environ["PLC_WORK_DIR"] = win(work)  # 所有 staged/PCEC 写盘落到 Temp，不污染产品目录

    from gateway.app.services.plc.greenfield_session import registry
    from gateway.app.services.plc import greenfield_service as svc
    from gateway.app.services.plc import tia_delivery

    registry.reset()
    session = registry.get("y4-real")
    svc.load_reference_fixture(session, "")
    svc.revalidate(session)
    svc.engineering_summary(session)
    svc.confirm_and_freeze(session, explicit=True)
    result = tia_delivery.deliver_tia(session, mode="package")

    zb = result["zip_bytes"]
    zip_path = TEMP / "product_package.zip"
    zip_path.write_bytes(zb)
    out["zip_path"] = win(zip_path)
    out["zip_bytes"] = len(zb)
    out["zip_sha256"] = sha256_prefixed(zb)
    out["zip_filename"] = result["package"]["zip_filename"]
    out["mode"] = result["mode"]
    out["status"] = result["status"]

    # 解压 xml_supplement/（保留前缀，使 TEMP/<import_order 项> 直接可用；不修改任何内容）
    supp_root = TEMP / "xml_supplement"
    if supp_root.exists():
        shutil.rmtree(supp_root)
    zf = zipfile.ZipFile(io.BytesIO(zb))
    members = sorted(n for n in zf.namelist() if n.startswith("xml_supplement/"))
    for n in members:
        target = TEMP / n
        target.parent.mkdir(parents=True, exist_ok=True)
        if not n.endswith("/"):
            target.write_bytes(zf.read(n))
    out["xml_supplement_dir"] = win(supp_root)
    out["xml_supplement_member_count"] = len(members)

    # ---- manifest 真实值（zip 内 + 解压后磁盘两份，核对一致）----
    m_bytes = zf.read("xml_supplement/manifest.json")
    m_disk = (supp_root / "manifest.json").read_bytes()
    manifest = json.loads(m_bytes.decode("utf-8"))
    out["manifest_from_zip_equals_disk"] = m_bytes == m_disk
    out["manifest_sha256"] = sha256_prefixed(m_bytes)
    out["manifest_real_values"] = {
        "xml_package_unverified": manifest.get("xml_package_unverified"),
        "pending_real_machine": manifest.get("pending_real_machine"),
        "references_self_consistent": manifest.get("references_self_consistent"),
        "ob_count": manifest.get("ob_count"),
        "generated_blocks": manifest.get("generated_blocks"),
        "skipped_blocks": manifest.get("skipped_blocks"),
        "import_order": manifest.get("import_order"),
        "generated_obs": manifest.get("generated_obs"),
        "skipped_obs": manifest.get("skipped_obs"),
        "pending_reason": manifest.get("pending_reason"),
        "note": manifest.get("note"),
        "template_source": manifest.get("template_source"),
    }
    # 与 result 回执（另一条交付路径）同步核对
    out["result_vs_manifest_sync"] = {
        "generated_blocks_equal": result["generated_blocks"] == manifest["generated_blocks"],
        "skipped_blocks_equal": result["skipped_blocks"] == manifest["skipped_blocks"],
        "import_order_equal": result["import_order"] == manifest["import_order"],
        "references_self_consistent_equal": result["references_self_consistent"] == manifest["references_self_consistent"],
        "xml_package_unverified": result["xml_package_unverified"],
        "pending_real_machine": result["pending_real_machine"],
    }

    # ---- 逐文件 sha256（generated_blocks + generated_obs，与清单记录核对）----
    per_file = []
    for rec in manifest["generated_blocks"] + manifest["generated_obs"]:
        p = TEMP / rec["path"]
        data = p.read_bytes() if p.is_file() else None
        computed = sha256_prefixed(data) if data is not None else None
        per_file.append({
            "path": rec["path"],
            "kind": rec.get("kind") or ("blocks" if rec["path"].startswith("xml_supplement/blocks/") else "ob"),
            "name": rec.get("name"),
            "expected_sha256": rec.get("sha256"),
            "computed_sha256": computed,
            "expected_bytes_in_zip": len(zf.read(rec["path"])),
            "computed_bytes": len(data) if data is not None else None,
            "match": computed == rec.get("sha256"),
        })
    out["per_file_sha256_recompute"] = per_file
    out["per_file_sha256_all_match"] = all(x["match"] for x in per_file)

    # xml_supplement/ 全部成员 sha256 清单（含 README.md / folders.json / manifest.json）
    all_members = []
    for n in members:
        if n.endswith("/"):
            continue
        data = zf.read(n)
        all_members.append({"path": n, "bytes": len(data), "sha256": sha256_prefixed(data)})
    out["all_members_sha256"] = all_members

    # ---- Python XML 解析：逐字一致性核对 ----
    fb_paths = [b["path"] for b in manifest["generated_blocks"] if b["type"] == "FB"]
    db_paths = [b["path"] for b in manifest["generated_blocks"] if b["type"] == "InstanceDB"]
    fb_names_by_path = {p: _block_name(_parse_xml((TEMP / p).read_bytes())) for p in fb_paths}
    db_names_by_path = {p: _block_name(_parse_xml((TEMP / p).read_bytes())) for p in db_paths}
    fb_xml_names = set(fb_names_by_path.values())
    db_xml_names = set(db_names_by_path.values())
    db_by_name = {b["name"]: b for b in manifest["generated_blocks"] if b["type"] == "InstanceDB"}

    xml_checks = []
    for ob in manifest["generated_obs"]:
        data = (TEMP / ob["path"]).read_bytes()
        root = _parse_xml(data)
        ci, comp = _callinfo_component(root)
        entry = {
            "ob": ob["name"],
            "ob_number": ob["number"],
            "path": ob["path"],
            "ob_xml_name": _block_name(root),
            "call_db_from_manifest": ob["call_db"],
            "has_call_network": ci is not None or comp is not None,
            "callinfo_name": ci,
            "component_name": comp,
        }
        if ci is None and comp is None:
            entry["verdict"] = "empty_network_ob_no_call_reference"
        else:
            fb_name_ok = ci in fb_xml_names
            db_name_ok = comp in db_xml_names
            # 该 Component 指向的 DB 的 InstanceOfName == FB 的 <Name>
            iof = None
            if comp in db_by_name:
                db_root = _parse_xml((TEMP / db_by_name[comp]["path"]).read_bytes())
                iof = _instance_of_name(db_root)
            iof_ok = (iof == ci) and (ci in fb_xml_names)
            convention_ok = (ci == re.sub(r"_DB$", "", comp or ""))
            entry.update({
                "callinfo_matches_fb_xml_name": fb_name_ok,
                "component_matches_db_xml_name": db_name_ok,
                "db_instance_of_name": iof,
                "instance_of_name_matches_fb_xml_name": iof_ok,
                "product_convention_callfb_eq_strip_db_suffix": convention_ok,
                "verdict": "all_consistent" if all([fb_name_ok, db_name_ok, iof_ok, convention_ok]) else "INCONSISTENT",
            })
        xml_checks.append(entry)
    out["xml_reference_checks"] = xml_checks
    out["xml_references_all_consistent"] = all(
        x["verdict"] in ("all_consistent", "empty_network_ob_no_call_reference") for x in xml_checks
    )
    out["fb_xml_names"] = sorted(fb_xml_names)
    out["db_xml_names"] = sorted(db_xml_names)

    # folders.json（供 Y2 create-block-group 消费）
    folders_doc = json.loads(zf.read("xml_supplement/folders.json").decode("utf-8"))
    out["folders_json_original"] = folders_doc
    out["import_order"] = manifest["import_order"]
    return out


# --------------------------------------------------------------------------- Y2 真机
def prep_case(run_id: str) -> tuple[str, str]:
    """只读复制源项目到独立干净临时副本；返回 (ap 路径, case 目录)。"""
    case_dir = TEMP / f"case_{run_id}"
    proj = case_dir / "proj"
    if proj.exists():
        shutil.rmtree(proj)
    proj.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, proj, dirs_exist_ok=True)
    ap = proj / "CanvasE2E.ap19"
    return win(ap), win(case_dir)


def real_machine(ap: str, case_dir: str, import_order: list[str], folders_doc: dict) -> dict:
    out: dict = {
        "ap_path": ap,
        "case_dir": case_dir,
        "source_copied_from": win(SRC),
        "source_opened_or_written_back": False,
        "mode": "one_shot_cli_no_serve",
        "cli_timeout_s": CLI_TIMEOUT,
    }
    try:
        # 0) status 预检
        out["status_probe"] = cli("status")

        # 1) 导入前基线 list-blocks（证明干净副本、无 W 独立包遗留同号块）
        out["list_blocks_before"] = cli("list-blocks", "--project", ap)

        # 2) 按 import_order 逐项 import-xml --kind auto（FB → DB → OB）
        imports = []
        for rel in import_order:
            xml_path = win(TEMP / rel)
            rec = cli("import-xml", "--project", ap, "--xml", xml_path, "--kind", "auto")
            j = rec.get("json") or {}
            imp = j.get("import") if isinstance(j.get("import"), dict) else {}
            err = j.get("error") if isinstance(j.get("error"), dict) else None
            item = {
                "path": rel,
                "xml_path": xml_path,
                "xml_sha256": sha256_prefixed((TEMP / rel).read_bytes()),
                "top_level_ok": j.get("ok"),
                "import_sub_ok": imp.get("ok"),
                "importedNames": imp.get("importedNames") or j.get("importedNames"),
                "kind_resolved": imp.get("kind"),
                "api": imp.get("api"),
                "exit_code": rec.get("_exit_code"),
                "error_code": (err or {}).get("code"),
                "error_message_original": (err or {}).get("message") if err else j.get("message"),
                "raw": rec,
            }
            item["ok"] = bool(j.get("ok")) or bool(imp.get("ok"))
            imports.append(item)
        out["imports_itemized"] = imports
        out["imports_all_ok"] = all(i["ok"] for i in imports)

        # 3) create-block-group（folders.json 文档化清单，SW.PlcBlockGroup XML 不可 import，不尝试）
        groups = sorted(
            [g for g in (folders_doc.get("folders") or {}) if g != "root"],
            key=lambda x: (x.count("/"), x),
        )
        cbg = []
        for g in groups:
            rec = cli("create-block-group", "--project", ap, "--plc", "PLC_1", "--group", g)
            j = rec.get("json") or {}
            cbg.append({"group": g, "ok": bool(j.get("ok")), "saved": j.get("saved"),
                        "exit_code": rec.get("_exit_code"), "raw": rec})
        out["create_block_groups"] = cbg
        out["create_block_groups_all_ok"] = all(x["ok"] for x in cbg)

        # 4) list-blocks 核对入项目
        out["list_blocks_all"] = cli("list-blocks", "--project", ap)
        out["list_blocks_OB"] = cli("list-blocks", "--project", ap, "--type", "OB")
        out["list_blocks_FB"] = cli("list-blocks", "--project", ap, "--type", "FB")
        out["list_blocks_DB"] = cli("list-blocks", "--project", ap, "--type", "DB")

        # 5) compile-plc 真实返回
        comp = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
        inner = (comp.get("json") or {}).get("compile")
        inner = inner if isinstance(inner, dict) else {}
        out["compile_raw"] = comp
        out["compile_exit_code"] = comp.get("_exit_code")
        out["compile_summary"] = {
            "ok": inner.get("ok"),
            "errorCount": inner.get("errorCount"),
            "warningCount": inner.get("warningCount"),
            "state": inner.get("state"),
            "inconsistentBlocks": inner.get("inconsistentBlocks"),
            "message": inner.get("message"),
            "error": inner.get("error"),
        }
        out["repro_commands"] = [
            f'cd "{win(ROOT)}" && "{win(PY)}" tools/run_product_package_real.py --case {case_dir.rsplit("/", 1)[-1].replace("case_", "")}',
            'timeout -k 5 180 "' + win(EXE) + '" --cli status',
            'timeout -k 5 180 "' + win(EXE) + '" --cli list-blocks --project <Temp干净副本.ap19>  # 导入前基线',
            'timeout -k 5 180 "' + win(EXE) + f'" --cli import-xml --project {ap} --xml <TEMP/xml_supplement/按 import_order> --kind auto  # 逐项 FB→DB→OB',
            'timeout -k 5 180 "' + win(EXE) + f'" --cli create-block-group --project {ap} --plc PLC_1 --group <folders.json 各组>',
            'timeout -k 5 180 "' + win(EXE) + f'" --cli list-blocks --project {ap} [--type OB|FB|DB]',
            'timeout -k 5 180 "' + win(EXE) + f'" --cli compile-plc --project {ap} --plc PLC_1',
        ]
    except Exception as e:  # noqa: BLE001
        out["status"] = "error"
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()
    return out


# --------------------------------------------------------------------------- 编排
def main() -> None:
    TEMP.mkdir(parents=True, exist_ok=True)
    argv = sys.argv[1:]
    run_id = "Y-1"
    only = None
    if "--case" in argv:
        i = argv.index("--case")
        run_id = argv[i + 1] if i + 1 < len(argv) else "Y-1"
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1] if i + 1 < len(argv) else None

    report: dict
    if RAW_PATH.is_file():
        report = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    else:
        report = {
            "schema": "gf-y4-product-package-real-raw-v1",
            "title": "批次 4 · Agent Y · 正式产品通道 xml_supplement V19 真机验证原始返回",
            "agent": "Agent Y · 正式产品通道 XML 补充包 V19 真机验证（本阶段唯一连真机）",
            "tia_version": "V19",
            "environment": {
                "exe": win(EXE), "python": win(PY),
                "temp_root": win(TEMP), "read_only_source": win(SRC),
                "cli_timeout_s": CLI_TIMEOUT,
                "repro_timeout_wrapper": "timeout -k 5 180",
            },
            "safety": {
                "only_temp_copies": True,
                "original_ap19_opened_or_written_back": False,
                "git_operations": 0,
                "product_code_modified": False,
                "serve_started": False,
                "d12_hard_refuse_honored": True,
                "each_cli_has_timeout": True,
            },
            "runs": [],
        }

    print(f"[Y1] 生成正式产品包 + 结构核对 ...", flush=True)
    y1 = generate_and_check()
    print(f"      import_order={len(y1['import_order'])} 项, "
          f"sha256_all_match={y1['per_file_sha256_all_match']}, "
          f"xml_refs_consistent={y1['xml_references_all_consistent']}", flush=True)

    run: dict = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "y1_structure": y1,
    }

    if only != "Y1":
        print(f"[Y2] V19 真机按序导入 + 编译（case_{run_id}）...", flush=True)
        ap, case_dir = prep_case(run_id)
        y2 = real_machine(ap, case_dir, y1["import_order"], y1["folders_json_original"])
        run["y2_real_machine"] = y2
        imports = y2.get("imports_itemized") or []
        print(f"      imports={len(imports)} all_ok={y2.get('imports_all_ok')}, "
              f"compile={y2.get('compile_summary')}", flush=True)

    report["runs"].append(run)
    report["safety"]["serve_leftover_after_all"] = health_probe()
    RAW_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n原始返回已写入: {win(RAW_PATH)}", flush=True)
    print(json.dumps({"run_id": run_id,
                      "per_file_sha256_all_match": y1["per_file_sha256_all_match"],
                      "xml_references_all_consistent": y1["xml_references_all_consistent"],
                      "imports_all_ok": (run.get("y2_real_machine") or {}).get("imports_all_ok"),
                      "compile_summary": (run.get("y2_real_machine") or {}).get("compile_summary")},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
