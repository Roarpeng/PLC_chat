"""架构治理测试：锁定权威实现路径，防止文档与代码再度漂移。

权威路径（见 docs/PLC_chat_突破性架构理解与演进方案.html §05/§09、docs/19-pcec-contract.md）：

- 解析核心 = ``agents/plc/tia``（SimaticML 解析、PLC-IR、SCL 转换、知识图谱、Review 规则）
- 画布引擎 = ``plc_engine``（canvas_model / canvas_tia_transpiler / standalone_api）
- 唯一网关 = ``gateway/app``（入口 ``gateway/app/main.py``；``plc_gateway`` 为弃用历史副本）
- Openness CLI = ``industrial/tia_openness_cli``（文档旧笔误 ``tia_openness_mcp``、
  旧路径 ``tools/industrial-mcp/tia-openness`` 均不再使用）

扫描范围：plc_project 根下 ``README*.md`` 与 ``docs/*.md``；排除
16/17/18/19 号历史报告（允许保留原叙述）与 HTML 演进方案（*.md 通配天然排除）。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = PROJECT_ROOT / "docs"

# 历史报告：允许保留旧叙述，不参与漂移扫描。
EXCLUDED_DOCS = {
    "16-lad2scl-offline-validation.md",
    "17-automation-framework-research.md",
    "18-af-integration-action-plan.md",
    "19-pcec-contract.md",
}

AUTHORITATIVE_FILES = [
    # 解析核心：agents/plc/tia
    "agents/plc/tia/simaticml.py",
    "agents/plc/tia/flgnet_fold.py",
    "agents/plc/tia/scl.py",
    # 画布引擎：plc_engine
    "plc_engine/canvas_model.py",
    # 唯一网关：gateway/app
    "gateway/app/main.py",
]

AUTHORITATIVE_DIRS = [
    # Openness CLI
    "industrial/tia_openness_cli",
]

# 「plc_engine/tia 作为解析核心」类表述的关键词：命中任一即视为漂移。
STALE_CORE_HINTS = (
    "解析核心",
    "SimaticML 解析",
    "SCL 转换器",
    "IR 模型",
    "知识图谱",
    "Review 规则",
)
# plc_engine/tia 的各种书写形式（正/反斜杠、模块点号）。
PLC_ENGINE_TIA_TOKENS = ("plc_engine/tia", "plc_engine\\tia", "plc_engine.tia")
# 弃用/迁移说明中允许出现旧路径与旧职责描述。
DEPRECATION_ALLOWANCES = ("弃用", "占位", "已迁移", "历史", "agents/plc/tia", "agents.plc.tia")


def _scanned_doc_files() -> list[Path]:
    files = sorted(PROJECT_ROOT.glob("README*.md")) + sorted(
        p for p in DOCS_DIR.glob("*.md") if p.name not in EXCLUDED_DOCS
    )
    assert files, "应至少扫描到 README 与 docs 下的文档"
    return files


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _is_deprecation_notice(line: str) -> bool:
    return any(allow in line for allow in DEPRECATION_ALLOWANCES)


def test_governance_authoritative_paths_exist() -> None:
    missing = [rel for rel in AUTHORITATIVE_FILES if not (PROJECT_ROOT / rel).is_file()]
    assert not missing, f"权威实现文件缺失: {missing}"


def test_governance_openness_cli_dir_exists() -> None:
    missing = [rel for rel in AUTHORITATIVE_DIRS if not (PROJECT_ROOT / rel).is_dir()]
    assert not missing, f"权威目录缺失: {missing}"


def test_governance_docs_have_no_tia_openness_mcp() -> None:
    stale: list[str] = []
    for path in _scanned_doc_files():
        for lineno, line in enumerate(_read_lines(path), start=1):
            if "tia_openness_mcp" in line and not _is_deprecation_notice(line):
                stale.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not stale, "文档仍引用已弃用名 tia_openness_mcp（实际为 industrial/tia_openness_cli）:\n" + "\n".join(stale)


def test_governance_docs_do_not_call_plc_engine_tia_parsing_core() -> None:
    stale: list[str] = []
    for path in _scanned_doc_files():
        for lineno, line in enumerate(_read_lines(path), start=1):
            has_tia_token = any(tok in line for tok in PLC_ENGINE_TIA_TOKENS)
            has_core_claim = any(hint in line for hint in STALE_CORE_HINTS)
            if has_tia_token and has_core_claim and not _is_deprecation_notice(line):
                stale.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not stale, (
        "文档仍把 plc_engine/tia 描述为解析核心（权威解析核心为 agents/plc/tia）:\n" + "\n".join(stale)
    )


def test_governance_plc_engine_tia_is_placeholder_only() -> None:
    tia_dir = PROJECT_ROOT / "plc_engine" / "tia"
    assert tia_dir.is_dir(), "plc_engine/tia 目录应存在（兼容占位包）"
    py_files = [
        p for p in tia_dir.rglob("*.py") if "__pycache__" not in p.parts
    ]
    offenders = [str(p.relative_to(PROJECT_ROOT)) for p in py_files if p.name != "__init__.py"]
    assert not offenders, f"plc_engine/tia 应为纯占位包（仅允许 __init__.py），发现实现文件: {offenders}"


def test_governance_deprecation_docstrings_present() -> None:
    shim = (PROJECT_ROOT / "plc_engine" / "tia" / "__init__.py").read_text(encoding="utf-8")
    assert "已弃用" in shim, "plc_engine/tia/__init__.py 顶部应含弃用说明 docstring"
    assert "agents/plc/tia" in shim or "agents.plc.tia" in shim, "弃用说明应指明权威实现 agents/plc/tia"

    legacy = (PROJECT_ROOT / "plc_gateway" / "__init__.py").read_text(encoding="utf-8")
    assert "已弃用" in legacy, "plc_gateway/__init__.py 顶部应含弃用说明 docstring"
    assert "gateway/app" in legacy or "gateway.app" in legacy, "弃用说明应指明唯一权威网关 gateway/app"
