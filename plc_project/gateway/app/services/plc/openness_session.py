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


def compile_plc(project_path: str = "", *, plc_name: str = "") -> dict[str, Any]:
    if not ensure_session_running():
        return {"ok": False, "fallback": True}
    return _post("/compile-plc", {"project": project_path, "plc": plc_name}, timeout_s=300.0)


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
