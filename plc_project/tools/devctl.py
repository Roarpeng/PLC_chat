#!/usr/bin/env python3
"""devctl — 工具链微服务监督器（docs/10 落地实现）。

按需起停各语言服务：`devctl up gateway` 秒级拉起（uv 免装依赖），
`devctl down --all` 一键归零，`devctl prune` 回收超过 idle_timeout 的闲置服务。

设计约束：纯标准库（tomllib 只读解析 services.toml）、零守护进程——
devctl 自身只在执行命令的瞬间存在，服务进程全部脱离控制台独立存活，
状态落在 .devctl/state.json，日志落在 .devctl/logs/<name>.log。

用法：
    python tools/devctl.py up gateway
    python tools/devctl.py up web
    python tools/devctl.py status
    python tools/devctl.py prune          # 停掉超过 idle_timeout 的服务
    python tools/devctl.py down web
    python tools/devctl.py down --all
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # py<3.11
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]  # plc_project/
SERVICES_FILE = ROOT / "services.toml"
STATE_DIR = ROOT / ".devctl"
STATE_FILE = STATE_DIR / "state.json"
LOG_DIR = STATE_DIR / "logs"

# Windows 静默后台运行：新进程组（便于整树终止）+ CREATE_NO_WINDOW
# （子进程树——cmd/uv/python/npm——全部不弹控制台窗口）
CREATE_FLAGS = 0
CREATE_NO_WINDOW = 0x08000000
if sys.platform == "win32":
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_FLAGS = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

# 健康检查/探活 URL 只允许 loopback 主机（本地服务探活，SSRF 兜底）
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# pythonw（无控制台）重定向用的空设备路径（Windows: nul，POSIX: /dev/null）
DEVNULL_PATH = Path(os.devnull)


# ---------------------------------------------------------------- 基础设施

def load_services() -> dict:
    if not SERVICES_FILE.is_file():
        sys.exit(f"未找到 {SERVICES_FILE}")
    if tomllib is None:
        sys.exit("需要 Python 3.11+（tomllib）")
    with SERVICES_FILE.open("rb") as f:
        return tomllib.load(f).get("services", {})


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        # tasklist 在中文 Windows 输出 GBK，容错解码（ASCII 的 PID 数字不受影响）
        raw = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
        out = raw.decode("utf-8", errors="replace")
        return str(pid) in out
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
    else:
        import os
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass


# ---------------------------------------------------------------- 健康检查

def _assert_loopback_http(url: str) -> str:
    """断言探活 URL 为 http(s) 且主机为 loopback；不符抛 ValueError。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in LOOPBACK_HOSTS:
        raise ValueError(f"健康检查 URL 必须指向 loopback 主机: {url!r}")
    return url


def probe_health(health: str, timeout: float = 2.0) -> tuple[bool, str]:
    """health 形如 http://127.0.0.1:8000/health 或 tcp:5173；空 = 不检查。"""
    if not health:
        return True, "无健康检查"
    if health.startswith("http"):
        try:
            url = _assert_loopback_http(health)
        except ValueError as exc:
            return False, str(exc)[:60]
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status == 200, f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:60]
    if health.startswith("tcp:"):
        host, _, port = health[4:].rpartition(":")
        try:
            with socket.create_connection((host or "127.0.0.1", int(port)), timeout=timeout):
                return True, "TCP 通"
        except OSError as exc:
            return False, str(exc)[:60]
    return False, "无法识别的健康检查配置"


# ---------------------------------------------------------------- 子命令

def _start_argv(start: str | list[str]) -> list[str]:
    """把 services.toml 的 start 命令解析成 argv 列表（不走 shell）。

    shell=True 会把配置串里的任何元字符交给 cmd 解释；改为逐参数列表传参后，
    元字符只能是普通参数。字符串按 shlex 拆分（现有配置无引号/反斜杠路径），
    列表原样采用。Windows 下 CreateProcess 不做 PATHEXT 搜索（找不到 npm.cmd），
    先用 shutil.which 把 argv[0] 解析成完整可执行路径。
    """
    argv = list(start) if isinstance(start, list) else shlex.split(start)
    if argv:
        exe = shutil.which(argv[0])
        if exe:
            argv[0] = exe
    return argv


def cmd_up(name: str) -> int:
    services = load_services()
    if name not in services:
        sys.exit(f"未知服务 {name}；可用：{', '.join(services)}")
    spec = services[name]
    state = load_state()
    pid = state.get(name, {}).get("pid")
    if alive(pid):
        _ok, detail = probe_health(spec.get("health", ""))
        print(f"[{name}] 已在运行 pid={pid} 健康={detail}")
        return 0

    cwd = (ROOT / spec.get("cwd", ".")).resolve()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"{name}.log"
    env = None
    if spec.get("env"):
        import os

        env = {**os.environ, **spec["env"]}
    with log.open("ab") as lf:
        proc = subprocess.Popen(
            _start_argv(spec["start"]),
            cwd=str(cwd),
            stdout=lf,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_FLAGS,
            env=env,
        )
    state[name] = {"pid": proc.pid, "started_at": time.time()}
    save_state(state)

    health = spec.get("health", "")
    if health:
        deadline = time.time() + spec.get("health_timeout", 90)
        while time.time() < deadline:
            time.sleep(2)
            if alive(proc.pid) and probe_health(health)[0]:
                print(f"[{name}] 已启动 pid={proc.pid} 健康=OK 日志={log}")
                return 0
            if not alive(proc.pid):
                print(f"[{name}] 启动即退出，查看日志：{log}")
                return 1
        print(f"[{name}] 健康检查超时（进程仍在跑 pid={proc.pid}），日志：{log}")
        return 1
    print(f"[{name}] 已启动 pid={proc.pid} 日志={log}")
    return 0


def cmd_down(name: str) -> int:
    state = load_state()
    entry = state.get(name) or state.get(str(name))
    if not entry or not alive(entry.get("pid")):
        print(f"[{name}] 未在运行")
        if name in state:
            del state[name]
            save_state(state)
        return 0
    kill_tree(entry["pid"])
    state.pop(name, None)
    save_state(state)
    print(f"[{name}] 已停止")
    return 0


def cmd_status() -> int:
    services = load_services()
    state = load_state()
    now = time.time()
    for name, spec in services.items():
        entry = state.get(name)
        pid = entry and entry.get("pid")
        run = alive(pid)
        _ok, detail = probe_health(spec.get("health", "")) if run else (False, "—")
        up = f"{int(now - entry['started_at']) // 60} 分钟" if run and entry else "—"
        ttl = spec.get("idle_timeout")
        flag = ""
        if run and ttl and (now - entry.get("started_at", 0)) > ttl:
            flag = "（已超时，可 prune）"
        print(f"{name:<12} {'●运行' if run else '○停止'}  pid={pid or '-':<7} 运行={up:<8} 健康={detail}{flag}")
    return 0


def cmd_prune() -> int:
    services = load_services()
    state = load_state()
    now = time.time()
    stopped = 0
    for name, entry in list(state.items()):
        spec = services.get(name, {})
        ttl = spec.get("idle_timeout")
        if not ttl or not alive(entry.get("pid")):
            continue
        if now - entry.get("started_at", 0) > ttl:
            print(f"[{name}] 超过 idle_timeout={ttl}s，回收")
            cmd_down(name)
            stopped += 1
    if not stopped:
        print("无超时服务")
    return 0


def main(argv: list[str]) -> int:
    # pythonw（无控制台）运行时 stdout/stderr 为 None，print 会抛异常 → 引到空设备
    if sys.stdout is None:
        sys.stdout = DEVNULL_PATH.open("w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = DEVNULL_PATH.open("w", encoding="utf-8")
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, arg = argv[1], argv[2] if len(argv) > 2 else ""
    if cmd == "up" and arg:
        return cmd_up(arg)
    if cmd == "down":
        if arg == "--all":
            return sum(cmd_down(n) for n in list(load_state())) and 0
        if arg:
            return cmd_down(arg)
        sys.exit("down 需要 <name> 或 --all")
    if cmd == "status":
        return cmd_status()
    if cmd == "prune":
        return cmd_prune()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
