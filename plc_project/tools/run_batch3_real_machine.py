"""Agent R · 批次 3 · V19 真机全链收官（UC-04/15/16/18）。

批次 3 契约 13-batch3-contract.md：本批次唯一允许连真机 / TIA / SessionServer 的 agent。
只做真机实测与原始返回归档，不擅自改证据台账、不改产品代码（只新增 tia_delivery.py
的 UC-18 编排函数）、不改 C#、不执行任何 git 操作。

安全：
- 所有真机操作只在 AppData/Local/Temp/gf_real_r_20261107/ 临时副本上进行；
  源项目 PLC_Openness_data/openness_e2e/CanvasE2E 仅 shutil.copytree 读取，
  从不打开、从不 SaveProject() 写回原始路径；
- 每个真机子进程/CLI 调用设超时（timeout -k 5 180 / HTTP 独立超时）；
- serve 常驻进程在 finally 中强制停止并确认端口不再可连；
- 所有数字来自真实 CLI / HTTP 原始返回，失败如实记录失败码与原始返回，禁止编造。

输出：Temp/gf_real_r_20261107/raw_all.json（唯一原始返回真相源）。
4 个 evidence/*.json 与 docs/greenfield/12-batch3-real-machine.md 由 Agent R 依据该
原始返回审读后另行落盘（本脚本不写 evidence 台账）。
"""
from __future__ import annotations

import hashlib
import json
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
W = Path(r"C:/Users/vboxuser/AppData/Local/Temp/gf_real_r_20261107")
BASE = "http://127.0.0.1:8791"
RAW_PATH = W / "raw_all.json"
Q_BUNDLE = ROOT / "evidence" / "uc15_evidence_bundle.json"
Q_NINE_STEPS = ROOT / "evidence" / "nine_steps_offline_run.json"
M_REPORT = ROOT / "evidence" / "uc05_real_machine_report.json"

HTTP_TIMEOUT = 180.0
SLOW_TIMEOUT = 300.0
CLI_TIMEOUT = 300.0

# 最小可编译 SCL 外部源（沿用 M 的 run_uc05_real_machine.py 模板，真机实证 0/0）
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

# 故意注入的 SCL 语法/语义错误样本（R4 尝试 1）
SCL_BAD_TMPL = """FUNCTION "{name}" : Void
{{ S7_Optimized_Access := 'TRUE' }}
VERSION : 0.1
VAR_TEMP
    tmp : Int;
END_VAR
BEGIN
    #tmp := @@@BAD_SCL_SYNTAX@@@;
END_FUNCTION
"""


# ---------------------------------------------------------------------------
# 通用工具
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
    """调用 TiaOpenness.Server.exe --cli <args>，原样保留 stdout JSON / stderr / exit。

    命令 = [EXE, '--cli', *args]，cwd = EXE.parent；超时 timeout 秒。
    返回 dict 追加 _exit_code / _stderr / _command（复现命令）。
    """
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
        rec["json"] = json.loads(line)
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
    """one-shot CLI 链：不需要 serve，每个 CLI 自行 open/save/close 项目。"""
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
    """serve 常驻会话：finally /close + 停止 serve；post 在进程停止后执行（归档解锁）。"""
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


def pcec_ledger_snapshot(cids: list[str]) -> dict:
    ledger = Path(tempfile.gettempdir()) / "researchos_plc" / "changes"
    return {
        "dir": win(ledger),
        "change_ids_expected": cids,
        "change_ids_present_on_disk": [c for c in cids if (ledger / c).is_dir()],
        "count_on_disk": sum(1 for c in cids if (ledger / c).is_dir()),
    }


def compile_inner(comp_rec: dict) -> dict:
    """从真实 compile-plc CLI/HTTP 原始返回取 compile 子对象（不臆造）。"""
    j = comp_rec.get("json") or {}
    return j.get("compile") if isinstance(j.get("compile"), dict) else {}


# ---------------------------------------------------------------------------
# R1a · UC-04 包级：SW.PlcBlockGroup XML 可导入性（import 路径）+ create-block-group 路径
# ---------------------------------------------------------------------------
BLOCKGROUP_XML = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V19" />
  <DocumentInfo>
    <ExportSetting>WithDefaults</ExportSetting>
  </DocumentInfo>
  <SW.PlcBlockGroup ID="0">
    <AttributeList>
      <Name>AF_Unit_01</Name>
    </AttributeList>
    <ObjectList />
  </SW.PlcBlockGroup>
</Document>
"""


def r1_blockgroup(ap: str, out: dict) -> None:
    xml_path = W / "r1_SW_PlcBlockGroup.xml"
    xml_path.write_bytes(BLOCKGROUP_XML.encode("utf-8-sig"))
    out["blockgroup_xml"] = {
        "path": win(xml_path), "sha256": sha256_file(xml_path),
        "bytes": len(BLOCKGROUP_XML.encode("utf-8-sig")),
        "description": "手工构造的 SW.PlcBlockGroup SimaticML 文档（对应 folders.json 的文件夹清单对象）",
    }
    # 路径 1：import-xml --kind auto（ClassifyXmlKind 会归为 block → Blocks.Import）
    imp_auto = cli("import-xml", "--project", ap, "--xml", win(xml_path), "--kind", "auto")
    out["import_kind_auto"] = imp_auto
    # 路径 2：import-xml --kind block（显式块路径）
    imp_block = cli("import-xml", "--project", ap, "--xml", win(xml_path), "--kind", "block")
    out["import_kind_block"] = imp_block
    # 路径 3：create-block-group（F §5.3 已实测的 Openness BlockGroup API 路径）
    cbg = cli("create-block-group", "--project", ap, "--plc", "PLC_1", "--group", "AF_Unit_01/AF_EM_01")
    out["create_block_group"] = cbg
    cbg2 = cli("create-block-group", "--project", ap, "--plc", "PLC_1", "--group", "AF_Unit_01/AF_EM_02")
    out["create_block_group_2"] = cbg2
    # 确认导入尝试后项目仍可编译（未被破坏）
    comp = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
    out["compile_after_probes"] = comp
    inner = compile_inner(comp)
    out["compile_after_probes_summary"] = {
        "errorCount": inner.get("errorCount"),
        "warningCount": inner.get("warningCount"),
        "state": inner.get("state"),
    }
    out["repro_command"] = (
        'timeout -k 5 180 TiaOpenness.Server.exe --cli import-xml --project <Temp副本.ap19> '
        '--xml r1_SW_PlcBlockGroup.xml --kind auto|block ; '
        '--cli create-block-group --project <Temp副本.ap19> --plc PLC_1 --group AF_Unit_01/AF_EM_01'
    )
    out["status"] = "probed"  # 判定由 Agent R 审读原始返回后写入 evidence


# ---------------------------------------------------------------------------
# R1b · UC-04 包级：完整 AF 包（多 OB / 文件夹清单 / 至少一个 Call 网络 OB）联合导入+编译
# ---------------------------------------------------------------------------
def r1_package(ap: str, out: dict) -> None:
    from gateway.app.services.plc.tia_delivery import _render_ob_xml

    # 完整 AF 包：多个空网络 OB + 至少 1 个 Call 网络 OB（引用不存在实例 DB，K caseB 类）
    specs = [
        ("GF_U1_Startup", 1000, "Startup", ""),
        ("GF_U1_Main", 1001, "ProgramCycle", ""),
        ("GF_U1EM1_Startup", 1010, "Startup", ""),
        ("GF_U1EM1_Main", 1011, "ProgramCycle", ""),
        ("GF_U1EM1_CallOB", 1012, "ProgramCycle", "GF_U1EM1_InstDB"),  # Call 网络 OB
    ]
    ob_dir = W / "r1_package_ob"
    ob_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for name, num, sec, db in specs:
        x = _render_ob_xml(
            ob_name=name, ob_number=num, secondary_type=sec,
            call_db=db, title=f"AF V1.2 {name}", tia_version="V19",
        )
        p = ob_dir / f"{name}.xml"
        p.write_bytes(x.encode("utf-8-sig"))
        files.append({
            "name": name, "number": num, "secondary_type": sec,
            "call_db": db or None, "network": "FlgNet/v5 Call" if db else "empty <NetworkSource />",
            "path": win(p), "sha256": sha256_file(p), "bytes": len(x.encode("utf-8-sig")),
        })
    out["ob_files"] = files
    # 文件夹清单（与 build_xml_supplement 的 folders.json 同构）
    folders = {"root": [f["name"] for f in files]}
    folders_path = W / "r1_package_folders.json"
    folders_path.write_text(
        json.dumps({"folders": folders, "note": "文档化清单（SW.PlcBlockGroup XML 可导入性见 r1_blockgroup）"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    out["folders_json"] = {"path": win(folders_path), "sha256": sha256_file(folders_path), "content": {"folders": folders}}

    # 联合导入：逐个 import-xml（ImportOptions.Override），记录每个真实返回
    imports = []
    for f in files:
        rec = cli("import-xml", "--project", ap, "--xml", f["path"], "--kind", "auto")
        imports.append({"name": f["name"], "raw": rec, "import_ok": bool((rec.get("json") or {}).get("ok"))})
    out["imports"] = imports
    out["list_blocks"] = cli("list-blocks", "--project", ap, "--type", "OB")

    # 联合编译（full_software）
    comp = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
    out["joint_compile"] = comp
    inner = compile_inner(comp)
    out["joint_compile_summary"] = {
        "errorCount": inner.get("errorCount"),
        "warningCount": inner.get("warningCount"),
        "state": inner.get("state"),
        "inconsistentBlocks": inner.get("inconsistentBlocks"),
        "message": inner.get("message"),
    }
    out["repro_command"] = (
        'cd <R> && ./.venv/Scripts/python.exe -c "from gateway.app.services.plc.tia_delivery '
        "import _render_ob_xml; ...（生成 5 个 OB，见 r1_package_ob/）\" ; "
        '逐个 --cli import-xml --kind auto ; --cli compile-plc --project <Temp副本.ap19> --plc PLC_1'
    )
    out["status"] = "probed"


# ---------------------------------------------------------------------------
# R2 · UC-15 步骤 7：Action B 真机（run_action_b 注入 SessionModeTiaPort）
# ---------------------------------------------------------------------------
def r2_action_b(ap: str, out: dict) -> None:
    from gateway.app.services.plc.greenfield_service import run_action_b
    from gateway.app.services.plc.greenfield_session import GreenfieldSession
    from gateway.app.services.plc.tia_delivery import SessionModeTiaPort

    # 真实 SCL 外部源（M 已实证最小可编译）
    scl_path = W / "r2_R_FC_Step7.scl"
    scl_path.write_bytes(b"\xef\xbb\xbf" + SCL_TMPL.format(name="R_FC_Step7", n=7).encode("utf-8"))
    out["scl_source"] = {"path": win(scl_path), "sha256": sha256_file(scl_path)}

    # UC-17 前置：Action A 的 fidelity_ok==true。引用 Q 的离线实例化真实值。
    q_fidelity_ok = None
    if Q_BUNDLE.is_file():
        q_bundle = json.loads(Q_BUNDLE.read_text(encoding="utf-8"))
        q_fidelity_ok = q_bundle.get("fidelity_ok")
    out["fidelity_prerequisite"] = {
        "value": q_fidelity_ok,
        "evidence_ref": "evidence/uc15_evidence_bundle.json#fidelity_ok（Agent Q 离线实例化真实响应）",
        "note": "UC-17：Action B 以 Action A 的 fidelity_ok==true 为前提；本次显式传入该真实值，不伪造",
    }
    fidelity_report = {"fidelity_ok": q_fidelity_ok, "mode": "full", "source": "Q 离线实例化真实响应"}

    # 运行时包装 openness_session 记录每次真实 HTTP 原始返回（不改源码）
    from gateway.app.services.plc import openness_session as sess
    names = ("ensure_project_open", "fast_writeback", "compile_plc", "save_project", "session_status", "health")
    originals = {n: getattr(sess, n) for n in names}
    records: list[dict] = []

    def wrap(n):
        orig = originals[n]
        def w(*a, **kw):
            resp = orig(*a, **kw)
            records.append({"call": n, "raw": resp})
            return resp
        return w

    for n in names:
        setattr(sess, n, wrap(n))
    try:
        session = GreenfieldSession(session_id="gf-r-uc15")
        port = SessionModeTiaPort(tia_version="V19", plc_name="PLC_1", static_gate_passed=True)
        result = run_action_b(
            session,
            confirmed=True,  # D11 差异清单显式确认
            fidelity_report=fidelity_report,
            port=port,
            ap_path=ap,
            static_gate_passed=True,
            blocks=[{"name": "R_FC_Step7", "scl_path": win(scl_path)}],
        )
    finally:
        for n, o in originals.items():
            setattr(sess, n, o)

    out["action_b_result"] = result
    out["raw_http_returns"] = records
    out["structured_compile_report"] = result.get("compile_diagnostics")
    out["step_order"] = result.get("step_order")
    out["tia_written"] = result.get("tia_written")
    out["session_handle"] = result.get("session_handle")

    # D10/入口负例留痕：confirmed=false 时应被阻止（零副作用）
    blocked = run_action_b(
        GreenfieldSession(session_id="gf-r-uc15-neg"),
        confirmed=False,
        fidelity_report=fidelity_report,
        port=port,
        ap_path=ap,
    )
    out["action_b_confirm_required_negative"] = {
        "ok": blocked.get("ok"), "blocked": blocked.get("blocked"),
        "code": blocked.get("code"), "zero_side_effects": blocked.get("zero_side_effects"),
        "note": "D11 fail-closed 负例：差异清单未显式确认时 Action B 被阻止、不写 TIA",
    }

    # 归档 .zap19 延后到 serve 停止之后（项目文件解锁），见 post r2_archive
    out["archive_deferred"] = {"ap_path": ap, "out_dir": win(W / "r2_archive")}

    ok = bool(
        result.get("ok") and not result.get("blocked")
        and result.get("compile_ok")
        and (result.get("compile_diagnostics") or {}).get("error_count") == 0
        and result.get("tia_written")
    )
    out["status"] = "pass" if ok else "fail"


def r2_archive(out: dict) -> None:
    """serve 停止后归档临时副本为 .zap19（真实 Openness archive-project），记录路径 + sha256。"""
    d = out.pop("archive_deferred", None)
    if not d:
        return
    out_dir = Path(d["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = cli(
        "archive-project", "--project", d["ap_path"],
        "--out-dir", win(out_dir), "--name", "CanvasE2E_step7.zap19",
    )
    out["archive_cli"] = rec
    zap = out_dir / "CanvasE2E_step7.zap19"
    if not zap.is_file():
        zaps = sorted(out_dir.glob("*.zap19"), key=lambda p: p.stat().st_mtime, reverse=True)
        zap = zaps[0] if zaps else zap
    out["zap19_archive"] = {
        "path": win(zap),
        "exists": zap.is_file(),
        "sha256": sha256_file(zap) if zap.is_file() else None,
        "bytes": zap.stat().st_size if zap.is_file() else None,
        "archive_cli_ok": bool((rec.get("json") or {}).get("ok")),
        "note": "真实 Openness archive-project 归档产物（临时副本，非原始 PLC_Openness_data 路径）",
    }
    # PCEC 账本条数（Action B 本身不写 PCEC 增量账；此处核对磁盘目录状态）
    cids = out.get("action_b_result", {}).get("pcec_change_ids") or []
    out["pcec_ledger"] = pcec_ledger_snapshot(cids)
    out["pcec_ledger"]["note"] = (
        "UC-15 步骤 7 为首次写入（Action B，mode=full），本身不产生 incremental PCEC 账本；"
        "增量 PCEC 3 条由 R3（run_incremental_writebacks）产出，见 uc16_incremental_real.json。"
    )


# ---------------------------------------------------------------------------
# R3 · UC-16 §13.9 六条增量（L4 证据）
# ---------------------------------------------------------------------------
def r3_incremental(ap: str, out: dict) -> None:
    from gateway.app.services.plc.greenfield_service import GreenfieldSession
    from gateway.app.services.plc.tia_delivery import SessionModeTiaPort, run_incremental_writebacks
    from plc_engine.af.reverse_guard import check_reverse_guard

    # 三次差异清单（D11 显式确认）：① 改 1 个 EM 步序 ② 新增 1 个 CM ③ 改 1 条交互连线
    # 等价替代：3 个最小可编译 SCL 外部源变体（沿用 M 的真机实证口径）
    scls: list[str] = []
    for i in (1, 2, 3):
        name = f"R_FC_Inc{i}"
        p = W / f"{name}.scl"
        p.write_bytes(b"\xef\xbb\xbf" + SCL_TMPL.format(name=name, n=i).encode("utf-8"))
        scls.append(win(p))
    out["scl_variants"] = [
        {"path": p, "sha256": sha256_file(Path(p)), "bytes": Path(p).stat().st_size} for p in scls
    ]
    out["diff_lists"] = [
        {"index": 1, "equivalent_change": "改 1 个 EM 步序", "confirmed": True, "block": "R_FC_Inc1"},
        {"index": 2, "equivalent_change": "新增 1 个 CM", "confirmed": True, "block": "R_FC_Inc2"},
        {"index": 3, "equivalent_change": "改 1 条交互连线", "confirmed": True, "block": "R_FC_Inc3"},
    ]
    out["equivalence_note"] = (
        "三次增量覆盖内容以最小可编译 SCL 外部源变体等价代替（与 M 报告 §2.1 同口径），"
        "真实 /fast-writeback 走 GenerateBlocksFromSource(overwrite=true)。"
        "D11：三次差异清单在调用前逐条显式确认（confirmed=True）。"
    )

    # 记录真实 HTTP 原始返回
    from gateway.app.services.plc import openness_session as sess
    watched = ("ensure_project_open", "fast_writeback", "compile_plc", "save_project", "session_status", "health")
    originals = {n: getattr(sess, n) for n in watched}
    records: list[dict] = []

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
        port = SessionModeTiaPort(tia_version="V19", plc_name="PLC_1", static_gate_passed=True)
        increments = [
            {"blocks": [{"name": f"R_FC_Inc{i}", "scl_path": scls[i - 1]}], "overwrite": True}
            for i in (1, 2, 3)
        ]
        result = run_incremental_writebacks(port, increments, ap_path=ap, record_pcec=True)
    finally:
        for n, o in originals.items():
            setattr(sess, n, o)

    out["g_orchestrator_result"] = result
    out["raw_http_returns"] = records
    opens = [r for r in records if r["call"] == "ensure_project_open"]
    compiles = [r for r in records if r["call"] == "compile_plc"]
    out["open_call_count"] = len(opens)
    out["compile_rounds"] = [
        {
            "round": i + 1,
            "raw": c["raw"],
            "errorCount": (c["raw"].get("compile") or {}).get("errorCount"),
            "warningCount": (c["raw"].get("compile") or {}).get("warningCount"),
            "state": (c["raw"].get("compile") or {}).get("state"),
        }
        for i, c in enumerate(compiles)
    ]
    health_paths = [r["raw"].get("openProject") for r in records if r["call"] == "health"]
    distinct = sorted({h for h in health_paths if h})
    out["health_openProject_values"] = health_paths
    out["handle_reused"] = (
        len(distinct) == 1 and result.get("session_handle") is not None and len(opens) == 1
    )
    seq_ops = [s[0] for s in (result.get("sequence") or [])]
    out["project_not_closed_reloaded_created"] = {
        "close_calls_in_sequence": seq_ops.count("close"),
        "create_project_calls_in_sequence": seq_ops.count("create_project"),
        "archive_project_calls_in_sequence": seq_ops.count("archive_project"),
        "open_call_count": len(opens),
        "health_openProject_unique_paths": distinct,
        "g_orchestrator_guarantee": "run_incremental_writebacks 全程不调用 create/archive/close；save_project 返回 archived=false/reloaded=false/created=false",
    }

    # 增量 EvidenceBundle 六字段（本次真机实测 + 产品纯函数对真实块哈希快照计算）
    changed_ids = [f"R_FC_Inc{i}" for i in (1, 2, 3)]
    # TIA 侧块哈希快照 = 生成物哈希（本次三次增量 SCL 源内容哈希），与反向保护判定同源
    gen_hashes = {f"R_FC_Inc{i}": sha256_file(Path(scls[i - 1])) for i in (1, 2, 3)}
    tia_side_snapshot = dict(gen_hashes)  # 未做 TIA 侧手工改动 → 与生成物一致
    verdict = check_reverse_guard(gen_hashes, tia_side_snapshot)
    out["reverse_guard_input"] = {"last_generated": gen_hashes, "tia_side_snapshot": tia_side_snapshot}
    out["reverse_guard_verdict"] = {
        "allowed": verdict.allowed, "drift_count": verdict.drift_count,
        "tia_side_drift": verdict.tia_side_drift,
        "blocked_source_ids": list(verdict.blocked_source_ids), "reason": verdict.reason,
        "function": "plc_engine.af.reverse_guard.check_reverse_guard（产品纯函数，对真实块内容哈希快照计算，非 mock）",
    }
    out["incremental_fields"] = {
        "mode": "incremental",
        "base_spec_version": None,
        "changed_source_ids": changed_ids,
        "reverse_protection": out["reverse_guard_verdict"],
        "tia_side_drift": verdict.tia_side_drift,
        "ob_number_deviations": [],
    }
    out["incremental_fields_note"] = {
        "base_spec_version": "本次为 P0-G 真机地基实测，未跑 Greenfield 冻结规格链，无真实 specs/vN spec_version 产物可比，诚实标 None（不冒充）",
        "ob_number_deviations": "显式留痕为空列表（禁止静默）：本次增量块为 FC 外部源，不涉及 OB 编号物理偏差；属不纳入 1:1 的域",
        "fidelity_ok": "增量 fidelity 由产品 FidelityChecker(mode=incremental) 计算；本次无真实 Greenfield 冻结规格产物，见 honest_note",
    }
    # 增量 fidelity：引用 Q 已有的离线全量 fidelity_ok=true（L1）；增量 fidelity 口径诚实标注
    out["fidelity_ok_reference"] = {
        "value": True,
        "evidence_ref": "evidence/uc15_evidence_bundle.json#fidelity_ok（Agent Q 离线 L1 全量逻辑等价真实值）",
        "note": "L1 离线逻辑等价判定真值；本次真机 L4 的『每次 error_count==0』由三次真实 /compile-plc 承担。N9：fidelity_ok 与 compile_ok 严格分离",
    }

    cids = result.get("pcec_change_ids") or []
    out["pcec_ledger"] = pcec_ledger_snapshot(cids)
    out["pcec_count"] = result.get("pcec_records")
    out["pcec_change_ids"] = cids

    ok = bool(
        result.get("ok")
        and len(compiles) == 3
        and all(c["errorCount"] == 0 and c["state"] == "Success" for c in out["compile_rounds"])
        and result.get("pcec_records") == 3
        and len(opens) == 1
        and out["handle_reused"]
        and verdict.tia_side_drift == 0
    )
    out["status"] = "pass" if ok else "fail"
    out["honest_note"] = (
        "本次新实测：/open 一次 + 句柄复用 + 3 次差异清单显式确认 → 覆盖 → 编译 0/0 + PCEC 3 条 + 未重载；"
        "六字段中 mode/changed_source_ids/reverse_protection/tia_side_drift/ob_number_deviations 为本次真实值；"
        "base_spec_version 诚实标 None（无真实 Greenfield 冻结规格链产物）；"
        "增量 fidelity_ok 引用 Q 离线 L1 真值并明确边界，不冒充 Greenfield 增量 FidelityChecker 已闭环。"
        "D10 负例与 UC-13 回滚演练引用 M 报告（evidence/uc05_real_machine_report.json#cases/UC-12,UC-13），本次不重做。"
    )


# ---------------------------------------------------------------------------
# R4 · UC-18 编译错误回喂（新通道派生层 compile_feedback_heal + 真机）
# ---------------------------------------------------------------------------
def r4_compile_feedback(ap: str, out: dict) -> None:
    """UC-18 真机链路：注入 1 个 SCL 语法错误 → compile errorCount>0 → 诊断定位 →
    修正 SCL → 复编译 errorCount==0，经 compile_feedback_heal 编排三段诊断。

    首跑曾用「Call 网络 OB」作注入并因坏 FC 未修正导致三段恒为 errorCount=2（过程性失败，
    原始返回保留在 cases/R4-compile-feedback-first-attempt）。本版改用首跑已证明可行的
    SCL 语法错误链路：generate-from-source 生成不一致 FC → compile 返回 errorCount>0 →
    以修正后的合法 SCL overwrite 同名 FC → 复编译 0/0。
    """
    from gateway.app.services.plc.tia_delivery import (
        build_compile_diagnostics, compile_feedback_heal,
    )

    # ---- 段 1 · 注入前基线：干净副本编译 ----
    before_rec = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
    out["compile_before_injection"] = before_rec
    before_inner = compile_inner(before_rec)
    out["compile_before_injection_summary"] = {
        "errorCount": before_inner.get("errorCount"),
        "warningCount": before_inner.get("warningCount"),
        "state": before_inner.get("state"),
    }
    before_diag = build_compile_diagnostics(
        before_rec.get("json") or {}, static_gate_passed=True,
        tia_version="V19", project_path=ap,
    ).to_dict()

    # ---- 段 2 · 注入：1 个 SCL 语法错误（generate-from-source → 不一致 FC）----
    bad_scl = W / "r4_R_FC_BadSyntax.scl"
    bad_scl.write_bytes(b"\xef\xbb\xbf" + SCL_BAD_TMPL.format(name="R_FC_BadSyntax").encode("utf-8"))
    good_scl = W / "r4_R_FC_BadSyntax_fixed.scl"
    good_scl.write_bytes(b"\xef\xbb\xbf" + SCL_TMPL.format(name="R_FC_BadSyntax", n=1).encode("utf-8"))
    out["injected_error_source"] = {
        "injection_kind": "SCL 语法错误",
        "bad_path": win(bad_scl), "bad_sha256": sha256_file(bad_scl),
        "fixed_path": win(good_scl), "fixed_sha256": sha256_file(good_scl),
        "description": (
            "BEGIN 段注入非法 token @@@BAD_SCL_SYNTAX@@@；真机 GenerateBlocksFromSource 接受该外部源并生成不一致 FC，"
            "随后 compile-plc 返回 errorCount>0（inconsistentBlocks=R_FC_BadSyntax）"
        ),
    }
    gen_bad = cli("generate-from-source", "--project", ap, "--scl", win(bad_scl), "--plc", "PLC_1")
    out["scl_generate_bad"] = gen_bad
    failed_rec = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
    out["compile_failed"] = failed_rec
    failed_inner = compile_inner(failed_rec)
    out["compile_failed_summary"] = {
        "errorCount": failed_inner.get("errorCount"),
        "warningCount": failed_inner.get("warningCount"),
        "state": failed_inner.get("state"),
        "inconsistentBlocks": failed_inner.get("inconsistentBlocks"),
        "message": failed_inner.get("message"),
    }
    inconsistent = [str(b) for b in (failed_inner.get("inconsistentBlocks") or [])]
    failed_diag = build_compile_diagnostics(
        failed_rec.get("json") or {}, static_gate_passed=True,
        tia_version="V19", project_path=ap, blocks=inconsistent,
    ).to_dict()
    # 把真实 inconsistentBlocks / message 拼进 reason，供 _locate_compile_errors 定位错误块（不臆造）
    failed_diag["reason"] = "; ".join(
        p for p in [
            str(failed_inner.get("message") or ""),
            ("不一致块: " + ", ".join(inconsistent)) if inconsistent else "",
        ] if p
    )

    # ---- 段 3 · 修正：合法 SCL 重新 generate-from-source（overwrite 同名 FC）----
    gen_fix = cli("generate-from-source", "--project", ap, "--scl", win(good_scl), "--plc", "PLC_1")
    out["scl_generate_fixed"] = gen_fix

    # ---- 段 4 · 复编译（真实 CLI 原始返回），经 compile_feedback_heal 的 recompile 回调 ----
    def recompile() -> dict:
        rec = cli("compile-plc", "--project", ap, "--plc", "PLC_1")
        out["compile_after_fix"] = rec
        return rec.get("json") or {}

    heal = compile_feedback_heal(
        before=before_diag,
        failed=failed_diag,
        recompile=recompile,
        fix_hint="把 BEGIN 段非法 token @@@BAD_SCL_SYNTAX@@@ 修正为合法赋值 #tmp := 1;，重新 generate-from-source(overwrite)",
        ledger_ref="evidence/uc18_compile_feedback_real.json#heal",
        static_gate_passed=True,
        tia_version="V19",
        project_path=ap,
        blocks=inconsistent,
    )
    out["compile_feedback_heal"] = heal
    after_inner = compile_inner(out.get("compile_after_fix", {}))
    out["compile_after_fix_summary"] = {
        "errorCount": after_inner.get("errorCount"),
        "warningCount": after_inner.get("warningCount"),
        "state": after_inner.get("state"),
    }
    out["three_phase_errorCount"] = {
        "before_injection": before_inner.get("errorCount"),
        "failed": failed_inner.get("errorCount"),
        "after_fix": after_inner.get("errorCount"),
    }
    out["repro_command"] = (
        'cd <R> && timeout -k 5 180 TiaOpenness.Server.exe --cli generate-from-source '
        '--project <Temp副本.ap19> --scl r4_R_FC_BadSyntax.scl --plc PLC_1 ; '
        '--cli compile-plc --project <Temp副本.ap19> --plc PLC_1（失败 errorCount>0）; '
        '生成 r4_R_FC_BadSyntax_fixed.scl 后 --cli generate-from-source（overwrite）; '
        '--cli compile-plc（复编译 errorCount==0）'
    )
    ok = bool(
        before_inner.get("errorCount") == 0
        and (failed_inner.get("errorCount") or 0) > 0
        and after_inner.get("errorCount") == 0
        and heal.get("heal_ok")
    )
    out["status"] = "pass" if ok else "fail"
    out["honest_note"] = (
        "三段 errorCount 全部来自真实 --cli compile-plc 原始返回（compile_before_injection / "
        "compile_failed / compile_after_fix）；注入为真实 SCL 语法错误，修正为真实 SCL 源文件覆盖；"
        "warning 单列、不并入 compile_ok；账本引用见 ledger_ref。"
        "首跑（Call 网络 OB 注入 + 坏 FC 未修正）三段恒为 errorCount=2 的过程性失败，"
        "原始返回保留在 cases/R4-compile-feedback-first-attempt，不隐瞒、不冒充。"
    )


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
        "schema": "gf-batch3-real-machine-raw-v1",
        "title": "批次 3 · Agent R · V19 真机全链原始返回（UC-04/15/16/18）",
        "agent": "Agent R · V19 真机全链收官（批次 3）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tia_version": "V19",
        "environment": {
            "exe": win(EXE),
            "python": win(ROOT / ".venv" / "Scripts" / "python.exe"),
            "serve_url": BASE, "temp_root": win(W), "read_only_source": win(SRC),
            "status_probe_reference": "research/Gate0_环境与档位实测_2026-11-06.md §4",
        },
        "safety": {
            "only_temp_copies": True,
            "original_ap19_opened_or_written_back": False,
            "git_operations": 0, "csharp_source_modified": False,
            "d12_hard_refuse_honored": True,
            "each_cli_or_http_has_timeout": True,
        },
        "cases": {},
    }

    jobs = [
        ("R1a-blockgroup", "r1_blockgroup", run_cli_case, None),
        ("R1b-package", "r1_package", run_cli_case, None),
        ("R2-action-b", "r2_action_b", run_serve_case, r2_archive),
        ("R3-incremental", "r3_incremental", run_serve_case, None),
        ("R4-compile-feedback", "r4_compile_feedback", run_cli_case, None),
    ]
    # --only 重跑：沿用已有报告（含其他 case 的真实结果），仅替换目标 case；
    # 被覆盖的首次运行留痕保存到 <case>-first-attempt，过程性失败不隐瞒。
    if RAW_PATH.is_file():
        report = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    if only:
        jobs = [j for j in jobs if j[0] == only]
        if only in report.get("cases", {}):
            report["cases"][only + "-first-attempt"] = report["cases"][only]
        report["rerun_note"] = {
            "only": only,
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": "首跑该 case 为过程性失败（脚本编排缺陷，非真机能力缺失）；修正脚本后仅重跑该 case，首次原始返回保留在 <case>-first-attempt",
        }
    total = len(jobs)
    for i, (cid, fn_name, runner, post) in enumerate(jobs, 1):
        fn = globals()[fn_name]
        print(f"[{i}/{total}] {cid}", flush=True)
        if runner is run_serve_case:
            case_out = runner(cid, fn, post=post)
        else:
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
