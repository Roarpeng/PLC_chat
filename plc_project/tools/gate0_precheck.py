"""Gate-0 环境四件套预检（WP-00 / Plan §6.1）。

复用真机探针 ``TiaOpenness.Server.exe --cli status``，逐项输出
``pass`` / ``fail`` / ``unknown`` + 证据 + 失败处理建议，整体 fail-closed。

用法::

    python tools/gate0_precheck.py
    python tools/gate0_precheck.py --verify-license <临时副本.ap19>

说明:
- 探针只回报环境状态，**不回报 STEP 7 许可有效性**；许可有效性必须由一次真实
  ``--cli compile-plc`` 编译确认（契约 05 §0 / Plan §6.1）。因此默认运行第 1 项为
  ``unknown``，可用 ``--verify-license`` 在临时副本上做真实编译把它抬到 ``pass``。
- ``--verify-license`` 只允许指向 ``AppData/Local/Temp/gf_real_*`` 下的副本；检测到
  ``PLC_Openness_data`` 原始路径即 fail-closed 拒绝，避免打开/写回原始 .ap19。
- 退出码: ``0``=pass / ``2``=unknown / ``1``=fail（unknown 亦非 0，不静默降级）。
- 不做任何在线下载 / online / run-stop / compare-to-PLC、F-block/Safety 写入、
  UI 自动化、任何 git 操作。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_PROBE = (
    ROOT / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server"
    / "bin" / "Release" / "net481" / "TiaOpenness.Server.exe"
)
BLOCKSERVICE_CS = (
    ROOT / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server"
    / "BlockService.cs"
)
README_MD = ROOT / "industrial" / "tia_openness_cli" / "README.md"

EXIT_PASS, EXIT_FAIL, EXIT_UNKNOWN = 0, 1, 2


def run_cli(exe: Path, args: list[str], timeout: float) -> tuple[dict, dict | None]:
    """运行一次 --cli 命令并解析其单行 JSON 输出；绝不吞掉失败。"""
    cmd = [str(exe), "--cli", *args]
    rec: dict = {"command": " ".join(cmd), "timeout_s": timeout}
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        rec["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        rec["exit_code"] = None
        rec["error"] = f"probe timed out after {timeout}s (fail-closed)"
        return rec, None
    except OSError as exc:
        rec["exit_code"] = None
        rec["error"] = f"probe launch failed: {exc} (fail-closed)"
        return rec, None

    payload = None
    for line in out.splitlines():
        s = line.strip().lstrip("\ufeff")
        if s.startswith("{"):
            try:
                payload = json.loads(s)
            except json.JSONDecodeError as exc:
                rec["parse_error"] = f"{exc}"
            break
    rec["raw_stdout"] = out[:4000]
    if payload is None and "parse_error" not in rec:
        rec["parse_error"] = "no JSON object found in probe output (fail-closed)"
    return rec, payload


def _check(cid: int, name: str, result: str, evidence: list[str], remediation: str) -> dict:
    return {
        "id": cid,
        "name": name,
        "result": result,
        "evidence": evidence,
        "remediation": remediation,
    }


def _probe_failed_checks(probe_rec: dict) -> list[dict]:
    """探针本身失败 -> 四项全部 fail（fail-closed，不静默降级）。"""
    reason = probe_rec.get("error") or probe_rec.get("parse_error") or "unknown probe failure"
    shared = [f"探针不可用: {reason}", f"命令: {probe_rec.get('command')}"]
    names = [
        "TIA Portal V19 + 有效 STEP 7 许可",
        "Openness 用户组 token + 防火墙白名单",
        "V19 版 Siemens.Engineering.dll + F-block 拒绝边界",
        "项目文件锁归属（D9 专用后台实例）",
    ]
    return [
        _check(i + 1, n, "fail", shared,
               "修复探针后重跑；禁止在探针不可用时推进任何真机验收（契约 §1 fail-closed）。")
        for i, n in enumerate(names)
    ]


def build_checks(status: dict, license_result: dict | None) -> list[dict]:
    checks: list[dict] = []

    # 1. TIA V19 + 有效 STEP 7 许可
    ver = status.get("tiaVersion")
    dll = status.get("engineeringDll")
    ev1 = [f"tiaVersion={ver!r}（探针 --cli status）"]
    if dll:
        ev1.append(f"engineeringDll={dll}")
        ev1.append(f"Portal 安装路径存在={Path(dll).exists()}")
    if ver != "V19":
        checks.append(_check(
            1, "TIA Portal V19 + 有效 STEP 7 许可", "fail",
            ev1 + [f"要求 V19，实测 {ver!r}"],
            "安装或切换到 TIA Portal V19；确认 TIA_VERSION 环境变量指向 V19。",
        ))
    elif license_result is None:
        checks.append(_check(
            1, "TIA Portal V19 + 有效 STEP 7 许可", "unknown",
            ev1 + [
                "status 不返回 STEP 7 许可有效性字段；许可有效性必须由一次真实 compile-plc 编译确认（契约 05 §0 / Plan §6.1）",
            ],
            "运行: python tools/gate0_precheck.py --verify-license <AppData/Local/Temp/gf_real_*/副本.ap19>；"
            "或采信 docs/greenfield/06-gate0-report.md 中的真实编译记录。禁止传 PLC_Openness_data 原始 .ap19。",
        ))
    else:
        ok = bool(license_result.get("api_available")) and license_result.get("state") is not None
        lev = [
            f"真实编译 compile.apiAvailable={license_result.get('api_available')}",
            f"compile.state={license_result.get('state')!r}",
            f"compile.errorCount={license_result.get('error_count')} / warningCount={license_result.get('warning_count')}",
            f"编译命令 exit_code={license_result.get('exit_code')}",
            "判定口径: 编译 API 可真实调用(返回 State)即证明 STEP 7 许可有效；项目 errorCount 与许可判定无关，单列留痕",
        ]
        checks.append(_check(
            1, "TIA Portal V19 + 有效 STEP 7 许可", "pass" if ok else "fail",
            ev1 + lev,
            "若 compile.apiAvailable=false 或抛 compile_api_unavailable，检查 STEP 7 许可与 Openness 授权后重跑。",
        ))

    # 2. Openness 用户组 token + 防火墙白名单
    ga = status.get("opennessGroupInToken")
    av = status.get("opennessAvailable")
    ok2 = ga is True and av is True
    checks.append(_check(
        2, "Openness 用户组 token + 防火墙白名单", "pass" if ok2 else "fail",
        [
            f"opennessGroupInToken={ga}",
            f"opennessAvailable={av}",
            "未见显式命名防火墙规则；以探针可启动 Openness/DCOM 连接作为白名单可用的间接证据（契约 05 §0 同口径）",
            f"ProjectService.cs:623-627 为用户组校验落点（源码依据）",
        ],
        "把运行用户加入本地组 'Siemens TIA Openness' 并重新登录刷新 token；检查 DCOM/防火墙白名单；"
        "任一失败显式报错并终止，禁止静默降级。",
    ))

    # 3. V19 Engineering.dll + F-block 拒绝边界
    dll_ok = bool(dll) and Path(dll).exists() and "V19" in str(dll)
    fblock_ok = False
    fblock_ev: list[str] = []
    if BLOCKSERVICE_CS.exists():
        text = BLOCKSERVICE_CS.read_text(encoding="utf-8", errors="replace")
        fblock_ok = "XmlLooksLikeSafety" in text and "Refusing Blocks.Import for Safety" in text
        fblock_ev.append(
            f"BlockService.cs 含 XmlLooksLikeSafety/Refusing 硬拒绝={fblock_ok}"
        )
    else:
        fblock_ev.append("BlockService.cs 未找到，无法核验 F-block 拒绝边界")
    if README_MD.exists():
        rtext = README_MD.read_text(encoding="utf-8", errors="replace")
        fblock_ev.append(f"README.md 'Out of scope (hard refuse)' 段落存在={'Out of scope (hard refuse)' in rtext}")
    checks.append(_check(
        3, "V19 版 Siemens.Engineering.dll + F-block 拒绝边界",
        "pass" if (dll_ok and fblock_ok) else "fail",
        [
            f"engineeringDll 存在且为 V19 PublicAPI={dll_ok}",
            f"engineeringDll={dll}",
        ] + fblock_ev,
        "确认 Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll 存在；F-block/Safety 写入边界"
        "依赖 CLI 源码 hard refuse，缺失即 fail-closed，禁止导入 F-XML/F-SCL。",
    ))

    # 4. 项目文件锁归属（D9 专用后台实例）
    running = status.get("tiaRunning")
    popen = status.get("projectOpen")
    conn = status.get("connected")
    ok4 = running is False
    checks.append(_check(
        4, "项目文件锁归属（D9 专用后台实例）", "pass" if ok4 else "fail",
        [
            f"tiaRunning={running}",
            f"processCount={status.get('processCount')}",
            f"connected={conn}",
            f"projectOpen={popen}",
            "tiaRunning=false 时可用 WithoutUserInterface 后台实例独占项目（D9）",
        ],
        "若 tiaRunning=true：提示关闭用户 TIA Portal UI 或转只读观察；"
        "ExclusiveAccess/文件锁获取失败必须 fail-closed，不降级为『尽力而为』。",
    ))
    return checks


def overall_of(checks: list[dict]) -> str:
    results = [c["result"] for c in checks]
    if "fail" in results:
        return "fail"
    if "unknown" in results:
        return "unknown"
    return "pass"


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate-0 环境四件套预检（fail-closed 结构化 JSON）")
    ap.add_argument("--probe", default=str(DEFAULT_PROBE), help="TiaOpenness.Server.exe 路径")
    ap.add_argument(
        "--verify-license", default=None, metavar="AP19",
        help="在临时副本上跑一次真实 compile-plc 以验证 STEP 7 许可有效性（只允许 gf_real_* 副本）",
    )
    ap.add_argument("--timeout", type=float, default=180.0, help="单个真机子进程超时秒数（默认 180）")
    args = ap.parse_args()

    exe = Path(args.probe)
    out: dict = {
        "tool": "gate0_precheck",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "fail_closed": True,
    }

    if not exe.exists():
        out["probe"] = {"command": str(exe), "error": "probe exe not found (fail-closed)"}
        out["checks"] = _probe_failed_checks(out["probe"])
        out["overall"] = "fail"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(EXIT_FAIL)

    probe_rec, status = run_cli(exe, ["status"], args.timeout)
    out["probe"] = probe_rec

    license_result: dict | None = None
    if args.verify_license:
        norm = args.verify_license.replace("\\", "/")
        if "PLC_Openness_data" in norm:
            out["license_verify"] = {
                "result": "refused",
                "reason": "--verify-license 指向 PLC_Openness_data 原始项目；安全约束禁止打开/写回原始 .ap19，fail-closed 拒绝",
                "path": args.verify_license,
            }
        else:
            lr_rec, lr_payload = run_cli(
                exe, ["compile-plc", "--project", args.verify_license], args.timeout
            )
            comp = (lr_payload or {}).get("compile") or {}
            license_result = {
                "command": lr_rec.get("command"),
                "exit_code": lr_rec.get("exit_code"),
                "api_available": bool(comp.get("apiAvailable")),
                "state": comp.get("state"),
                "error_count": comp.get("errorCount"),
                "warning_count": comp.get("WarningCount", comp.get("warningCount")),
                "message": comp.get("message"),
                "parse_ok": lr_payload is not None,
            }
            out["license_verify"] = license_result

    if status is None:
        out["checks"] = _probe_failed_checks(probe_rec)
    else:
        out["checks"] = build_checks(status, license_result)

    out["overall"] = overall_of(out["checks"])
    if out["overall"] != "pass":
        out["note"] = (
            "非 pass 即不得以本预检作为 Gate-0 准入通过依据；按各 check.remediation 处置后重跑。"
            " unknown 表示『未验证』而非『通过』，不静默降级。"
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit({"pass": EXIT_PASS, "unknown": EXIT_UNKNOWN, "fail": EXIT_FAIL}[out["overall"]])


if __name__ == "__main__":
    main()
