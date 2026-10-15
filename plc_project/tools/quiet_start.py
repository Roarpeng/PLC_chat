#!/usr/bin/env python3
"""quiet_start — 静默启动器（由 pythonw 运行，全程无窗口）。

顺序：up gateway（等健康）→ up web → 打开浏览器界面。
供 启动项目.vbs 单次调用；也可直接命令行：
    pythonw tools\\quiet_start.py
"""

from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
URL = "http://127.0.0.1:5173"


def devctl(*args: str, timeout: float = 240) -> int:
    """以同一解释器静默运行 devctl 子命令。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "devctl.py"), *args],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    return proc.returncode


def main() -> None:
    try:
        devctl("up", "gateway")
        devctl("up", "web")
    except Exception:
        # 静默启动：失败也绝不弹窗，日志在 .devctl/logs/*.log
        pass
    # 等前端可访问后打开界面（最多 30s）
    import urllib.request

    for _ in range(15):
        try:
            with urllib.request.urlopen(URL, timeout=1):
                break
        except OSError:
            time.sleep(2)
    try:
        webbrowser.open(URL)
    except Exception:
        pass


if __name__ == "__main__":
    main()
