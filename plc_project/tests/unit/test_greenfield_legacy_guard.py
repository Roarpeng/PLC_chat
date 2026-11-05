"""R8 / AC-6：存量重构链零 diff + import 闭包隔离 + 新端点零副作用。"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from fastapi.testclient import TestClient
from gateway.app.main import app

from plc_engine.af.greenfield_ir import sha256_prefixed

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads(
    (ROOT / "tests/fixtures/greenfield/legacy_baseline.json").read_text(encoding="utf-8")
)


def test_frozen_legacy_files_have_zero_diff() -> None:
    """逐文件 sha256 与基线比对：任何一行改动直接 FAIL。"""
    assert BASELINE["schema"] == "gf-legacy-baseline-v1"
    for rel, expected in BASELINE["files"].items():
        target = ROOT / rel
        assert target.exists(), f"禁止清单文件缺失：{rel}"
        actual = sha256_prefixed(target.read_bytes())
        assert actual == expected, f"存量链文件被改动：{rel}"


def test_greenfield_modules_do_not_import_legacy_chain() -> None:
    """AST 级 import 闭包断言；docstring 里提到 PCEC 不算依赖。"""
    targets = [
        *sorted((ROOT / "plc_engine/af").glob("greenfield_*.py")),
        *sorted((ROOT / "gateway/app/services/plc").glob("greenfield_*.py")),
        ROOT / "gateway/app/routers/greenfield.py",
    ]
    assert targets
    imports: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
    joined = "\n".join(imports)
    for forbidden in BASELINE["forbidden_modules"]:
        assert forbidden not in joined, f"新通道 import 了存量模块 {forbidden}"


def test_router_never_calls_forbidden_endpoints() -> None:
    src = (ROOT / "gateway/app/routers/greenfield.py").read_text(encoding="utf-8")
    for endpoint in BASELINE["forbidden_endpoints"]:
        assert endpoint not in src, f"新路由引用了禁止端点 {endpoint}"


def test_greenfield_endpoints_produce_no_side_effects() -> None:
    """真实 HTTP 调用新端点后，ops / disk_writes / writebacks / generations 全为 0。"""
    client = TestClient(app)
    prefix = "/api/v1/plc/canvas/greenfield"
    session_id = client.get(f"{prefix}/state").json()["data"]["session_id"]
    assert client.post(f"{prefix}/draft", json={"session_id": session_id, "prompt": ""}).status_code == 200
    assert client.post(f"{prefix}/validate", json={"session_id": session_id}).status_code == 200
    assert client.get(f"{prefix}/export/mermaid?session_id={session_id}").status_code == 200
    state = client.get(f"{prefix}/state?session_id={session_id}").json()["data"]
    assert state["stage"] != "FROZEN"
    assert all(value == 0 for value in state["counters"].values())
    assert not state["specs"]
