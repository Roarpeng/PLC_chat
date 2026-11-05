"""生成 any2scl 语义等价 golden 回归基线（真实运行，可重跑）。

用法（项目根）：
    .venv/Scripts/python.exe tests/fixtures/build_any2scl_baseline.py

对只读真实导出 ``PLC_Openness_data/hr001/export`` 跑一次
``agents.plc.tia.pipeline.analyze_tia_exports``，把真实数字写入
``tests/fixtures/any2scl_baseline.json``：

- 块数 / 网络数 / converted / parsed / interface_only / unknown；
- TODO 总数、todo_rate、instruction_count、translated_rate、TODO 直方图；
- 含 5 类缺陷模式（S1~S5）的 SCL 文件数（逐块扫描，数字来自真实运行）；
- fail-closed 门禁对真实 result 的判定结果；
- 仍未等价项（如实说明，不修饰数字、不放宽期望值）。

全量耗时约 1~2 s，故不裁剪子集；若真实导出不可达会明确报错而不是编造。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_EXPORT = Path(
    "C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/PLC_Openness_data/hr001/export"
)
_OUT = Path(__file__).resolve().parent / "any2scl_baseline.json"


def _ensure_root_on_path() -> None:
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def build_baseline(export_dir: Path = _EXPORT) -> dict[str, Any]:
    """跑一次真实全量转换，返回基线 dict（所有数字来自本次运行）。"""
    _ensure_root_on_path()
    from agents.plc.tia import analyze_tia_exports
    from agents.plc.tia.coverage import (
        SCL_DEFECT_PATTERNS,
        SclWritebackUnsafeError,
        assert_scl_safe_for_writeback,
        scan_scl_defects,
    )

    export_dir = Path(export_dir)
    if not export_dir.is_dir():
        raise FileNotFoundError(f"真实 HR001 导出目录不可达：{export_dir}")

    started = time.time()
    result = analyze_tia_exports(str(export_dir), project_name="hr001")
    elapsed_ms = round((time.time() - started) * 1000, 1)

    cov = result["coverage"]
    conv = result["conversion_report"]
    scl_sources: dict[str, str] = result["scl_sources"]
    project = result["project"]

    # 覆盖范围：全量 rglob("*.xml")，未裁剪子集
    blocks_dir = export_dir / "plc" / "CPU_1200" / "blocks"
    block_xml_count = len(list(blocks_dir.glob("*.xml"))) if blocks_dir.is_dir() else 0
    networks = sum(len(b.networks) for b in project.blocks.values())

    # 五类缺陷模式：逐块扫描，记录命中文件数 + 文件名清单
    defect_pattern_files: dict[str, Any] = {}
    for code in SCL_DEFECT_PATTERNS:
        names = sorted(n for n, text in scl_sources.items() if code in scan_scl_defects(text))
        defect_pattern_files[code] = {"file_count": len(names), "files": names}
    any_names = sorted(n for n, text in scl_sources.items() if scan_scl_defects(text))
    defect_pattern_files["any"] = {"file_count": len(any_names), "files": any_names}

    # S4 取反守恒（真实 IR → SCL）：含 negated 部件的块是否都保留了 NOT (
    negated_blocks: list[str] = []
    for name, block in project.blocks.items():
        found = False
        for network in block.networks:
            for part in network.parts.values():
                if part.negated or "operand" in (part.negated_pins or set()):
                    found = True
                    break
            if found:
                break
        if found:
            negated_blocks.append(name)
    missing_not = [
        n for n in negated_blocks if n in scl_sources and "NOT (" not in scl_sources[n]
    ]

    # fail-closed 门禁对真实 result 的判定（如实记录，不吞异常）
    gate: dict[str, Any] = {"safe": None, "issues": [], "affected_blocks": []}
    try:
        assert_scl_safe_for_writeback(result)
        gate["safe"] = True
    except SclWritebackUnsafeError as exc:
        gate["safe"] = False
        gate["issues"] = [str(i.get("code")) for i in exc.issues]
        gate["affected_blocks"] = list(exc.blocks)

    return {
        "schema": "any2scl-golden-baseline/1",
        "generated_by": "tests/fixtures/build_any2scl_baseline.py",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "entrypoint": "agents.plc.tia.pipeline.analyze_tia_exports",
        "source": {
            "path": str(export_dir),
            "readonly": True,
            "coverage_scope": "full",
            "scope_note": (
                "对 export 全目录跑一次 analyze_tia_exports：rglob('*.xml') 覆盖"
                "块 XML / PLC 标签表 / HMI / manifest（跳过 _source_artifacts）；"
                "全量耗时约 1~2 s，未做子集裁剪。"
            ),
            "block_xml_count": block_xml_count,
            "tag_table_count": len(project.tag_tables),
        },
        "timings_ms": {
            "analyze_tia_exports_wall_ms": elapsed_ms,
            "pipeline_internal": dict(result.get("timings") or {}),
        },
        "counts": {
            "total_blocks": cov.get("total_blocks"),
            "project_blocks": len(project.blocks),
            "networks": networks,
            "scl_files": len(scl_sources),
            "converted": cov.get("converted"),
            "parsed": cov.get("parsed"),
            "protected": cov.get("protected"),
            "interface_only": cov.get("interface_only"),
            "unknown": cov.get("unknown"),
            "conversion_report_failed": conv.get("failed"),
            "warning_count": cov.get("warning_count"),
            "warning_codes": [str(w.get("code")) for w in (cov.get("warnings") or [])],
        },
        "todos": {
            "total": cov.get("todo_count"),
            "instruction_count": cov.get("instruction_count"),
            "todo_rate": cov.get("todo_rate"),
            "translated_rate": cov.get("translated_rate"),
            "histogram": cov.get("todo_histogram"),
            "blocks_with_any_todo": sorted(
                n for n, text in scl_sources.items() if "TODO[" in text
            ),
        },
        "defect_pattern_files": defect_pattern_files,
        "negation_conservation": {
            "blocks_with_negated_parts": len(negated_blocks),
            "blocks_missing_NOT": sorted(missing_not),
            "note": "S4 极性守恒：含 <Negated> 部件的块其 SCL 必须保留 NOT (；缺失即不等价",
        },
        "gate": gate,
        "golden_tests": {
            "file": "tests/unit/test_any2scl_golden.py",
            "positive_cases": 6,
            "negative_cases": 5,
            "xfail_known_gaps": 1,
            "defect_classes": list(SCL_DEFECT_PATTERNS),
            "note": "声明自测试文件（每类 >=1 正例 + 1 反例）；不是本次运行推算值",
        },
        "still_not_equivalent": [
            {
                "item": "FC2300 网络 5 含空格成员名未加引号",
                "detail": (
                    '生成 "DB2500 Visual Chiseling".PLC Time.MINUTE / "DB2100 Modbus Value".'
                    "PLC Para.Time Word 2，含空格成员未渲染成引号标识符，TIA External Source "
                    "编译会失败；数学语义已恢复但 SCL 文本仍非合法等价。"
                ),
                "evidence": (
                    "docs/16 §7.4 残留；test_any2scl_golden.py::"
                    "test_known_gap_fc2300_spaced_identifiers_not_quoted 标 xfail(strict=False)"
                ),
            },
            {
                "item": "S11 合理 TODO（真正未支持部件）",
                "detail": (
                    "MOVE_BLK_VARIANT / InRange / Shr / Or(Word) / S_Move / OutRange / "
                    "JmpList / MB_SERVER 仍以 TODO[...] 保留，fold 与 translate 均未支持；"
                    "对应 8 个 parsed 块，回写前必须人工补齐，门禁按 fail-closed 拦下。"
                ),
                "evidence": "docs/16 §4 S11 / §7.1；本基线 todos.histogram 与 gate",
            },
            {
                "item": "Word 字逻辑 Or 门（SrcType=Word）",
                "detail": "1 处，fold/translate 均未支持，建议归一到 *Word 算子族（docs/16 §7.4-2）。",
                "evidence": "todos.histogram['Or'] == 1",
            },
            {
                "item": "Move.eno → Move.en 链（ENO≈EN 近似）未折",
                "detail": "维持无条件（docs/16 §7.4-4）。",
                "evidence": "docs/16 §7.4",
            },
            {
                "item": "S12 可读性噪声 (TRUE AND X) 未做布尔化简",
                "detail": "语义正确，仅影响可读性（docs/16 §7.4-1）。",
                "evidence": "docs/16 §7.4",
            },
            {
                "item": "真实 TIA 回灌编译验证未执行",
                "detail": (
                    "本基线为离线 analyze_tia_exports 静态输出；未启动 TIA Portal / Openness / "
                    "devctl 做 External Source 导入 + GenerateBlocksFromSource + Compile。"
                ),
                "evidence": "docs/16 §5-1 / §7.4-3",
            },
        ],
    }


def main() -> int:
    baseline = build_baseline()
    _OUT.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = baseline["counts"]
    todos = baseline["todos"]
    print(f"written: {_OUT}")
    print(
        "blocks={total_blocks} networks={networks} scl_files={scl_files} "
        "converted={converted} parsed={parsed} interface_only={interface_only} "
        "unknown={unknown}".format(**counts)
    )
    print(
        f"todos={todos['total']} todo_rate={todos['todo_rate']} "
        f"instruction_count={todos['instruction_count']}"
    )
    print(
        "defect_files="
        + ", ".join(
            f"{k}={v['file_count']}"
            for k, v in baseline["defect_pattern_files"].items()
        )
    )
    print(f"gate_safe={baseline['gate']['safe']} gate_issues={baseline['gate']['issues']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
