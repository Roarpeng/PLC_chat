"""Client for resident TiaOpenness.Server ``serve`` mode + one-shot fallback.

Environment:
  RESEARCHOS_TIA_SESSION_URL   default http://127.0.0.1:8791
  RESEARCHOS_TIA_SESSION_TOKEN optional bearer token
  RESEARCHOS_TIA_SESSION=0     disable resident session (always one-shot)
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_session_proc: subprocess.Popen[str] | None = None

_DEFAULT_SESSION_URL = "http://127.0.0.1:8791"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def session_enabled() -> bool:
    return os.getenv("RESEARCHOS_TIA_SESSION", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _validated_worker_url() -> str:
    """校验后的会话/worker 基址（SSRF 收口，_post/_get 统一取用）。

    scheme 限 http/https 且必须带主机名；默认基址必须 loopback——
    非 loopback 主机仅当操作者通过 RESEARCHOS_TIA_SESSION_URL 显式配置时
    放行（本机/局域网 openness worker 是合法拓扑，不硬禁私网）。
    不符抛 ValueError（调用方按「会话不可达 → 一次性 CLI 回退」降级）。
    """
    from urllib.parse import urlparse

    explicit = os.getenv("RESEARCHOS_TIA_SESSION_URL", "").strip()
    url = (explicit or _DEFAULT_SESSION_URL).rstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError(f"会话基址非法（需 http(s)://host[:port]）: {url!r}")
    if not explicit and host not in _LOOPBACK_HOSTS:
        raise ValueError(f"会话基址必须指向 loopback 主机: {url!r}")
    return url


def session_base_url() -> str:
    return _validated_worker_url()


def session_token() -> str:
    return os.getenv("RESEARCHOS_TIA_SESSION_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    tok = session_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _post(path: str, body: dict[str, Any], timeout_s: float = 120.0) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        base = _validated_worker_url()
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "unreachable": True}
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"ok": False, "error": raw or str(exc)}
        if isinstance(payload, dict):
            payload.setdefault("ok", False)
            return payload
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "unreachable": True}
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"ok": False, "error": raw}
    return data if isinstance(data, dict) else {"ok": False, "error": "invalid json"}


def _get(path: str, timeout_s: float = 10.0) -> dict[str, Any]:
    import urllib.request

    try:
        base = _validated_worker_url()
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "unreachable": True}
    req = urllib.request.Request(
        f"{base}{path}",
        headers=_headers(),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {"ok": False}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "unreachable": True}


def health() -> dict[str, Any]:
    return _get("/health")


def _find_server_exe() -> Path | None:
    from agents.plc.tia.openness_cli import find_openness_exe, openness_server_project

    exe = find_openness_exe()
    if exe and exe.is_file():
        return exe
    csproj = openness_server_project()
    hint = csproj.parent / "bin" / "Release" / "net481" / "TiaOpenness.Server.exe"
    return hint if hint.is_file() else None


def ensure_session_running() -> bool:
    """Start resident serve process if not reachable. Returns True if healthy."""
    if not session_enabled():
        return False
    h = health()
    if h.get("ok") or h.get("status") == "ok":
        return True
    exe = _find_server_exe()
    if exe is None:
        return False
    global _session_proc
    with _lock:
        if _session_proc is not None and _session_proc.poll() is None:
            time.sleep(0.5)
            h2 = health()
            return bool(h2.get("ok") or h2.get("status") == "ok")
        port = "8791"
        try:
            from urllib.parse import urlparse

            port = str(urlparse(session_base_url()).port or 8791)
        except Exception:  # noqa: BLE001
            pass
        args = [str(exe), "serve", "--host", "127.0.0.1", "--port", port]
        tok = session_token()
        if tok:
            args.extend(["--token", tok])
        _session_proc = subprocess.Popen(
            args,
            cwd=str(exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    for _ in range(40):
        time.sleep(0.25)
        h3 = health()
        if h3.get("ok") or h3.get("status") == "ok":
            return True
    return False


def ensure_project_open(project_path: str, *, plc_name: str = "") -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True, "error": "session unavailable"}
    return _post(
        "/open",
        {"project": project_path, "plc": plc_name},
        timeout_s=300.0,
    )


def compile_plc(
    project_path: str = "",
    *,
    plc_name: str = "",
    blocks: list[str] | str | None = None,
) -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True}
    body: dict[str, Any] = {"project": project_path, "plc": plc_name}
    if blocks:
        body["blocks"] = "|".join(blocks) if isinstance(blocks, list) else str(blocks)
    return _post("/compile-plc", body, timeout_s=300.0)


def compile_hmi(project_path: str = "", *, hmi_name: str = "") -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True}
    return _post("/compile-hmi", {"project": project_path, "hmi": hmi_name}, timeout_s=600.0)


def save_project(project_path: str = "") -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True}
    return _post("/save", {"project": project_path}, timeout_s=120.0)


def generate_from_source(
    project_path: str,
    scl_path: str,
    *,
    plc_name: str = "",
    software_unit: str = "",
) -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True}
    body: dict[str, Any] = {"project": project_path, "scl": scl_path, "plc": plc_name}
    if software_unit:
        body["unit"] = software_unit
    return _post(
        "/generate-from-source",
        body,
        timeout_s=300.0,
    )


def import_xml(
    project_path: str,
    xml_path: str,
    *,
    kind: str = "auto",
    hmi_name: str = "",
    software_unit: str = "",
) -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True}
    body: dict[str, Any] = {"project": project_path, "xml": xml_path, "kind": kind, "hmi": hmi_name}
    if software_unit:
        body["unit"] = software_unit
    return _post(
        "/import-xml",
        body,
        timeout_s=300.0,
    )


def fast_writeback(body: dict[str, Any], timeout_s: float = 300.0) -> dict[str, Any]:
    """向常驻服务 POST 发送 /fast-writeback 请求。

    入参需满足 FastWritebackRequest 契约（scl_path, interfaceChanged,
    hasUdtOrGlobalDbChange, blockNames, 等）。
    """
    if not ensure_session_running():
        return {"ok": False, "fallback": True, "error": "session unavailable"}
    payload = dict(body)
    if "scl_path" in payload and "scl" not in payload:
        payload["scl"] = payload["scl_path"]
    if "project_path" in payload and "project" not in payload:
        payload["project"] = payload["project_path"]
    if "software_unit" in payload and "unit" not in payload:
        payload["unit"] = payload["software_unit"]

    resp = _post("/fast-writeback", payload, timeout_s=timeout_s)
    if isinstance(resp, dict):
        if "success" in resp and "ok" not in resp:
            resp["ok"] = bool(resp.get("success"))
        elif "ok" in resp and "success" not in resp:
            resp["success"] = bool(resp.get("ok"))
    return resp


# ---------------------------------------------------------------------------
# WP-02 / P0-G：Greenfield 会话端口底层能力（批次 2 增量回写真机地基）
#
# 本段为**纯追加**：不改动上面的 _post / _get / health / ensure_session_running /
# fast_writeback 等既有函数体，避免影响存量 canvas 回写链测试。职责：
#   1) close_project：显式结束会话（三次增量过程中不调用，保持项目未关闭）；
#   2) session_status：合并 /health 与 CLI status，作 tia_unavailable 显式失败判据；
#   3) classify_session_failure：fail-closed 错误归类，把 ExclusiveAccess / 文件锁 /
#      许可 / token / TIA 不可用信号映射为明确错误码，供 TiaSessionPort 实现方
#      在**写入前**阻止（契约 §1.5 / §3.1）。
# ---------------------------------------------------------------------------

#: fail-closed 明确错误码（ASCII，与契约 §3.1 / tia_delivery 既有常量一致）。
GF_EXCLUSIVE_ACCESS_DENIED = "GF_EXCLUSIVE_ACCESS_DENIED"
GF_TIA_UNAVAILABLE = "GF_TIA_UNAVAILABLE"
GF_TIA_TOKEN_DENIED = "GF_TIA_TOKEN_DENIED"
GF_TIA_LICENSE_DENIED = "GF_TIA_LICENSE_DENIED"
GF_TIA_UNAUTHORIZED = "GF_TIA_UNAUTHORIZED"
GF_SESSION_NOT_OPEN = "GF_SESSION_NOT_OPEN"
GF_TIA_EXEC_ERROR = "GF_TIA_EXEC_ERROR"


def close_project() -> dict[str, Any]:
    """POST /close：显式结束常驻会话。

    UC-05 要求三次增量「项目未关闭」，因此调试期增量编排**不调用**本函数；
    本函数仅作为 TiaSessionPort.close 的底层能力，由调用方在会话生命周期
    结束时显式触发。不改 C# 源码，走现有 HTTP 路由。
    """
    if not ensure_session_running():
        return {"ok": False, "fallback": True, "error": "session unavailable"}
    return _post("/close", {}, timeout_s=60.0)


def session_status() -> dict[str, Any]:
    """探测常驻会话 + TIA Openness 状态，作 ``tia_unavailable`` 显式失败判据。

    返回结构含 ``ok`` / ``available`` / ``tia_version`` / ``tia_running`` /
    ``openness_available`` / ``reason``。探测失败一律 ``available=False``，
    由上层 fail-closed，**绝不**把不可用包装成 ``ok=true``（契约 §0.4 / §1.8）。
    """
    h = health()
    healthy = bool(h.get("ok") or h.get("status") == "ok")
    if not healthy:
        return {
            "ok": False,
            "available": False,
            "tia_version": "",
            "tia_running": False,
            "openness_available": False,
            "reason": str(h.get("error") or "session /health 不可达"),
        }
    tia_version = ""
    openness_available = False
    tia_running = False
    try:
        from agents.plc.tia.openness_cli import openness_cli

        st = openness_cli("status", timeout_s=60)
        tia_version = str(st.get("tiaVersion") or st.get("TiaVersion") or "")
        openness_available = bool(
            st.get("OpennessAvailable") or st.get("opennessAvailable")
        )
        tia_running = bool(st.get("tiaRunning") or st.get("TiaRunning"))
    except Exception as exc:  # noqa: BLE001 - 探测异常一律按不可用处理
        return {
            "ok": False,
            "available": False,
            "tia_version": "",
            "tia_running": False,
            "openness_available": False,
            "reason": f"Openness status 探测异常：{exc}",
        }
    available = bool(openness_available)
    return {
        "ok": available,
        "available": available,
        "tia_version": tia_version,
        "tia_running": tia_running,
        "openness_available": openness_available,
        "reason": "" if available else "Openness 不可用（opennessAvailable=false）",
    }


def classify_session_failure(
    resp: dict[str, Any] | None, *, stage: str = ""
) -> dict[str, Any] | None:
    """fail-closed 错误归类：把 SessionServer 响应里的失败信号映射为明确错误码。

    返回 ``None`` 表示未检测到基础设施失败（调用方继续）；否则返回
    ``{"ok": False, "code", "stage", "reason", "http_status"}``。命中任一信号
    即显式失败：``tia_unavailable`` 绝不返回 200（契约 §3.1）。

    归类优先级：不可达/TIA 不可用 → token/401 → 许可 → ExclusiveAccess/文件锁。
    纯编译 ``errorCount>0`` 不在此归类（那是结构化编译结论，交给
    ``CompileDiagnostics`` 判定，warning 单列不并入成功）。
    """
    if not isinstance(resp, dict):
        resp = {}
    try:
        text = json.dumps(resp, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        text = str(resp).lower()
    err = resp.get("error")
    err_code = ""
    if isinstance(err, dict):
        err_code = str(err.get("code") or "").lower()
    elif isinstance(err, str):
        err_code = err.lower()
    combined = f"{text} {err_code}"
    reason = str(
        (err.get("message") if isinstance(err, dict) else err)
        or resp.get("message")
        or ""
    )

    def _fail(code: str, http_status: int) -> dict[str, Any]:
        return {
            "ok": False,
            "code": code,
            "stage": stage,
            "reason": reason or f"{stage or 'session'} 失败",
            "http_status": http_status,
        }

    # 1) 会话不可达 / TIA 不可用：显式失败，非 HTTP 200。
    if (
        resp.get("unreachable") is True
        or resp.get("fallback") is True
        or "tia_unavailable" in combined
    ):
        return _fail(GF_TIA_UNAVAILABLE, 503)
    # 2) token / 401（C# SessionServer 返回 {ok:false, error:"unauthorized"}）。
    if (
        "unauthorized" in combined
        or "401" in combined
        or str(err_code) == "unauthorized"
        or ("token" in combined and ("invalid" in combined or "denied" in combined))
    ):
        return _fail(GF_TIA_TOKEN_DENIED, 503)
    # 3) 许可失败。
    if "license" in combined or "almservice" in combined or "licensemanager" in combined:
        return _fail(GF_TIA_LICENSE_DENIED, 503)
    # 4) ExclusiveAccess 获取失败 / 文件锁：契约 §3.1 明确码。
    #    仅对显式 unavailable/denied/fail/error/exception 信号 fail-closed；
    #    C# 侧「无 UI 会话 noop / 版本降级」属合法降级，不在此拦截（保留 warning）。
    exclusive_signal = "exclusive_access" in combined or "exclusiveaccess" in combined
    exclusive_failed = any(
        token in combined
        for token in ("unavailable", "denied", "failed", "exception", "access_denied")
    )
    lock_signal = any(
        token in combined
        for token in ("file lock", "filelock", "already open", "another instance", "project is locked")
    )
    if (exclusive_signal and exclusive_failed) or lock_signal:
        return _fail(GF_EXCLUSIVE_ACCESS_DENIED, 409)
    return None

