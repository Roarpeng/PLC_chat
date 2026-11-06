"""R8 / AC-6：存量重构链零 diff + import 闭包隔离 + 新端点零副作用。

§9.2 Phase 2 sanctioned 边界（本文件维护）：``gateway/app/services/plc/tia_delivery.py``
是**唯一**允许 import 回写链静态门禁与 PCEC 账存的 sanctioned 模块（P2-5/P2-6，
docs/greenfield/02-architecture.md §9.2）。它刻意不叫 ``greenfield_*``，因此不在
下方 glob 闭包的扫描范围内；其允许 import 的模块在 ``SANCTIONED_PHASE2_IMPORTS``
白名单里显式枚举，越界 import 其他存量链模块仍然 FAIL。冻结文件 sha256 基线不动。
"""
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

#: §9.2 Phase 2 sanctioned 模块 → 允许触碰的存量链 import（子串口径同 forbidden_modules）。
#: tia_delivery.py 调用（不改）这些模块实现 P2-5 四层静态门禁与 P2-6 PCEC 账本；
#: writeback_contract 是 BlockArtifact DTO（lint/mega_source 的入参类型，随门禁一并放行）。
SANCTIONED_PHASE2_IMPORTS: dict[str, set[str]] = {
    "gateway/app/services/plc/tia_delivery.py": {
        "pcec",
        "writeback_pipeline",
        "writeback_linter",
        "writeback_contract",
        "mega_source",
        "scl_precheck",
    },
}


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def test_frozen_legacy_files_have_zero_diff() -> None:
    """逐文件 sha256 与基线比对：任何一行改动直接 FAIL。"""
    assert BASELINE["schema"] == "gf-legacy-baseline-v1"
    for rel, expected in BASELINE["files"].items():
        target = ROOT / rel
        assert target.exists(), f"禁止清单文件缺失：{rel}"
        actual = sha256_prefixed(target.read_bytes())
        assert actual == expected, f"存量链文件被改动：{rel}"


def test_greenfield_modules_do_not_import_legacy_chain() -> None:
    """AST 级 import 闭包断言；docstring 里提到 PCEC 不算依赖。

    sanctioned 模块（SANCTIONED_PHASE2_IMPORTS，§9.2）不匹配 greenfield_* glob，
    天然不在扫描范围；它们由下方 test_sanctioned_phase2_module_whitelist 单独约束。
    """
    targets = [
        *sorted((ROOT / "plc_engine/af").glob("greenfield_*.py")),
        *sorted((ROOT / "gateway/app/services/plc").glob("greenfield_*.py")),
        ROOT / "gateway/app/routers/greenfield.py",
    ]
    assert targets
    imports: list[str] = []
    for path in targets:
        imports += _module_imports(path)
    joined = "\n".join(imports)
    for forbidden in BASELINE["forbidden_modules"]:
        assert forbidden not in joined, f"新通道 import 了存量模块 {forbidden}"


def test_sanctioned_phase2_module_whitelist() -> None:
    """§9.2 Phase 2 sanctioned 边界：tia_delivery.py 只允许白名单内的存量链 import。

    白名单外的 forbidden_modules（compile_jobs / changesets / refactor_pipeline /
    af_import / tia.importer / writeback_batch / FastWriteback 等）在 sanctioned
    模块里出现仍然 FAIL——P2-7/P2-8 的并线与 compile_jobs 收敛不在本轮 sanctioned 范围。
    """
    for rel, allowed in SANCTIONED_PHASE2_IMPORTS.items():
        path = ROOT / rel
        assert path.exists(), f"sanctioned 模块缺失：{rel}"
        imports = _module_imports(path)
        for forbidden in BASELINE["forbidden_modules"]:
            offenders = [imp for imp in imports if forbidden in imp]
            if offenders:
                assert forbidden in allowed, (
                    f"sanctioned 模块 {rel} 越界 import 存量链 {forbidden}：{offenders}"
                )
        # 白名单本身必须落在 forbidden 清单内（不允许夹带未审计的"白名单"）
        for entry in allowed:
            assert entry in BASELINE["forbidden_modules"], (
                f"白名单条目 {entry} 不在 forbidden 清单，疑似越界扩权"
            )


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
