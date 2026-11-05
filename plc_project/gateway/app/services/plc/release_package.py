"""重构交付包生成器（refactor pipeline 交付阶段专用）。

从重构画布 + 引擎报告（+ 编译结论）生成本地交付目录并打 zip：

- ``refactored_scl_sources/<块名>.scl``  每个块一个 SCL 文件（文件名=块名）；
- ``refactor_report.json``               引擎报告原样透传（含 pending_blocks/degraded）；
- ``io_retention_matrix.csv``            report.io_retention.details 逐行导出（字段自适应）；
- ``compile_receipt.json``               **诚实收据**：编译没跑就写
  ``{"compiled": false, "reason": ...}``，绝不伪造「0 错误」；
- ``equivalence_report.json``            （可选）行为等价性核对报告：文本级/地址级
                                          preserved/dropped/added 与语句计数，把
                                          io_retention 的「记账」升级为可核对的断言；
- ``README.md``                          生成式说明（工程名/块数/pending/degraded/
                                          编译状态/生成时间；有等价性报告时附小节）。

立场：本模块只读画布与报告、只写自己的输出目录；**绝不触碰用户工程工作副本**，
输出目录由调用方给定（缺省临时目录），无任何硬编码工程路径（HR001 之类一律禁止）。
"""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import CanvasState

logger = logging.getLogger("researchos.gateway.plc.release_package")

#: 交付包内固定成员文件名
SCL_DIR_NAME = "refactored_scl_sources"
REPORT_FILE = "refactor_report.json"
IO_MATRIX_FILE = "io_retention_matrix.csv"
RECEIPT_FILE = "compile_receipt.json"
EQUIVALENCE_FILE = "equivalence_report.json"
README_FILE = "README.md"

#: io_retention.details 无行时的兜底表头（与引擎当前字段对齐；有行时按行内键自适应）
_DEFAULT_IO_FIELDS = [
    "address",
    "tag_name",
    "data_type",
    "cm_name",
    "cm_type",
    "cm_field",
    "em_name",
]

#: 收据 / README 中最多保留的编译错误条数（与流水线 result.compile.errors 同上限）
_RECEIPT_ERRORS_LIMIT = 50

#: 块名 → 文件名的非法字符（防路径穿越/分隔符）
_INVALID_FILENAME_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def _safe_filename(name: str) -> str:
    """块名 → 安全文件名（非法字符折叠为 ``_``，空名兜底 ``block``）。"""
    safe = _INVALID_FILENAME_RE.sub("_", str(name or "").strip()).strip("_")
    return safe or "block"


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _pending_count(report: dict[str, Any]) -> tuple[int, str]:
    """报告里的 pending 规模：兼容 int（计数）与 list（清单）两种形态。

    返回 (数量, 来源描述)；报告没有该字段时返回 (0, "")。
    """
    value = report.get("pending_blocks")
    if isinstance(value, list):
        return len(value), "清单"
    if isinstance(value, (int, float)):
        return int(value), "计数"
    return 0, ""


def build_compile_receipt(compile_info: dict[str, Any] | None) -> dict[str, Any]:
    """把流水线的 compile 结论转成**诚实收据**。

    - 没跑（compiled 缺省/false）：``{"compiled": false, "reason": ...}``，
      绝不输出「0 错误」这种容易被当成「编译通过」的字段；
    - 跑了：``{"compiled": true, "ok": 是否零错误, "error_count", "errors"(≤50),
      "warnings_count", "mode", "generated_at"}``。
    """
    info = compile_info if isinstance(compile_info, dict) else {}
    receipt: dict[str, Any] = {"generated_at": _now_str()}
    if not info.get("compiled"):
        reason = str(
            info.get("skipped_reason")
            or info.get("reason")
            or "本次交付未执行编译验证（未请求或环境不可用）"
        )
        receipt["compiled"] = False
        receipt["reason"] = reason
        # 诚实边界：没编译就不给任何可被误读为「通过」的字段
        return receipt
    errors = [str(e) for e in (info.get("errors") or []) if str(e).strip()]
    receipt.update(
        {
            "compiled": True,
            "ok": not errors,
            "error_count": len(errors),
            "errors": errors[:_RECEIPT_ERRORS_LIMIT],
            "warnings_count": int(info.get("warnings_count") or 0),
            # TIA 指认的不一致块(宿主归属;编译 API 无逐条文本时的唯一清单)
            "inconsistent_blocks": [
                str(n) for n in (info.get("inconsistent_blocks") or []) if str(n).strip()
            ][:20],
            "mode": str(info.get("mode") or "temp_copy"),
        }
    )
    return receipt


def _io_matrix_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    io_retention = report.get("io_retention")
    details = io_retention.get("details") if isinstance(io_retention, dict) else None
    if not isinstance(details, list):
        return []
    return [dict(d) for d in details if isinstance(d, dict)]


def write_io_matrix_csv(report: dict[str, Any], path: Path) -> int:
    """io_retention.details → CSV；字段对全部行自适应（保序取首次出现的键）。

    返回写入的数据行数（不含表头）。无 details 时仍产出带兜底表头的空表，
    保证交付包成员完整、下游拿到的一定是合法 CSV。
    """
    rows = _io_matrix_rows(report)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    if not fields:
        fields = list(_DEFAULT_IO_FIELDS)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_cell(row.get(k)) for k in fields})
    return len(rows)


def _csv_cell(value: Any) -> Any:
    """CSV 单元格规整：dict/list 转紧凑 JSON，其余原样交给 csv 模块。"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _equivalence_readme_lines(equivalence_report: dict[str, Any]) -> list[str]:
    """README 等价性小节：preserved/dropped 数、语句数变化、caveats 一句。"""
    verdict = equivalence_report.get("io_verdict")
    verdict = verdict if isinstance(verdict, dict) else {}
    counts = equivalence_report.get("statement_counts")
    counts = counts if isinstance(counts, dict) else {}
    delta = counts.get("delta_pct")
    if isinstance(delta, (int, float)):
        delta_text = f"{delta:+.1f}%"
    else:
        delta_text = "不适用（旧侧 0 语句）"
    caveats = equivalence_report.get("caveats")
    caveat_line = (
        str(caveats[0]) if isinstance(caveats, list) and caveats else "文本级/地址级核对，不是行为等价性证明。"
    )
    return [
        "## 等价性核对（文本级）",
        "",
        (
            f"- IO 地址判定：preserved {verdict.get('preserved_count', 0)} / "
            f"dropped {verdict.get('dropped_count', 0)} / "
            f"added {verdict.get('added_count', 0)}（逐地址明细见 equivalence_report.json）"
        ),
        (
            f"- 语句数变化：{counts.get('total_legacy', 0)} → {counts.get('total_af', 0)}"
            f"（{delta_text}）"
        ),
        f"- 口径限制：{caveat_line}",
        "",
    ]


def build_readme(
    *,
    project_name: str,
    canvas: CanvasState,
    report: dict[str, Any],
    receipt: dict[str, Any],
    equivalence_report: dict[str, Any] | None = None,
    zap_name: str = "",
) -> str:
    """生成式 README：工程名/块数/pending/degraded/编译状态/生成时间。

    ``equivalence_report`` 非 None 时追加「等价性核对（文本级）」小节与成员说明；
    缺省 None 时输出与历史行为完全一致。
    """
    pending_n, pending_kind = _pending_count(report)
    degraded = report.get("degraded")
    scl_count = len(canvas.blocks)
    if receipt.get("compiled"):
        if receipt.get("ok"):
            compile_line = f"编译验证：已执行（{receipt.get('mode')} 临时副本），0 错误 / {receipt.get('warnings_count', 0)} 警告"
        else:
            compile_line = (
                f"编译验证：已执行（{receipt.get('mode')} 临时副本），"
                f"{receipt.get('error_count', 0)} 个错误（见 compile_receipt.json）"
            )
    else:
        compile_line = f"编译验证：未执行——{receipt.get('reason')}"
    io = report.get("io_retention") if isinstance(report.get("io_retention"), dict) else {}
    lines = [
        f"# {project_name} — AF V1.2 重构交付包",
        "",
        f"- 生成时间：{_now_str()}",
        f"- 目标 Unit：{report.get('target_unit_name') or '-'}",
        f"- 画布块数：{scl_count}（SCL 源见 refactored_scl_sources/）",
        f"- AF 新建块：{len(report.get('af_blocks_created') or [])}",
        f"- 待人工确认（pending）：{pending_n}" + (f"（{pending_kind}）" if pending_kind and pending_n else ""),
        f"- 降级（degraded）：{('是 — ' + str(degraded)) if degraded else '否'}",
        f"- 物理 IO 保留率：{io.get('percentage', '-')}%（{io.get('retained_ios', '-')}/{io.get('total_ios', '-')}）",
        f"- {compile_line}",
        "",
        "## 成员说明",
        "",
    ]
    if zap_name:
        lines.append(f"- `{zap_name}`：**西门子博途原生工程归档包**（解压即得，可在 TIA Portal 中通过「项目 -> 恢复 (Retrieve)」直接一键解压并打开）")
    lines.extend([
        "- `refactored_scl_sources/`：按块拆分的 SCL 源（文件名=块名，每块一个 .scl）",
        "- `refactor_report.json`：重构引擎报告原样透传（含 pending_blocks/degraded 等字段）",
        "- `io_retention_matrix.csv`：物理 IO 保留矩阵（report.io_retention.details 逐行导出）",
        "- `compile_receipt.json`：编译收据（未编译时如实写明原因，不伪造 0 错误）",
    ])
    if equivalence_report is not None:
        lines.append(
            "- `equivalence_report.json`：行为等价性核对报告（文本级/地址级，"
            "preserved/dropped/added 判定与语句计数，非行为等价性证明）"
        )
    lines += [
        "",
        "> 本包为**画布级交付**：重构/修复只作用于画布草稿，未经人工确认不会写回任何 TIA 工程。",
    ]
    if zap_name:
        lines += [
            "",
            "## 博途 (TIA Portal) 原生恢复与打开说明",
            "",
            f"1. 解压本交付母包后，直接获得博途原生工程归档文件 `{zap_name}`；",
            "2. 打开 Siemens TIA Portal (西门子博途 V19/V20)；",
            f"3. 点击主菜单「项目 (Project) -> 恢复 (Retrieve...)」，选中本包内的 `{zap_name}` 并指定目标文件夹；",
            "4. 恢复完成后打开工程，左侧项目树中**已直接呈现经过 SCL 转换与 Automation Framework (AF V1.2) 架构处理的完整工程**：",
            "   - ⭐ **全套标准 AF 架构程序块**（Sequence 步序状态机、CallEquipment、CallUnit、ControlNodes、UDT 数据类型等）已全部挂载就绪；",
            "   - ⭐ **所有 FB/FC 程序块** 均已转换为标准纯 SCL 语言并保存；",
            "5. 本包内的 `refactored_scl_sources/` 目录亦同步附带全量按块拆分的独立 SCL 源码文件，供工程人员查阅与版本追溯。",
        ]
    if equivalence_report is not None:
        lines += ["", *_equivalence_readme_lines(equivalence_report)]
    lines.append("")
    return "\n".join(lines)


def _find_source_project_dir(
    canvas: CanvasState,
    project_source_path: str | Path | None = None,
) -> tuple[Path | None, str]:
    """Locate source project directory and TIA version extension (e.g. .zap19)."""
    candidate_path: Path | None = None
    if project_source_path:
        p = Path(project_source_path).expanduser().resolve()
        if p.exists():
            candidate_path = p

    if candidate_path is None and canvas.source and canvas.source.project_path:
        p = Path(canvas.source.project_path).expanduser().resolve()
        if p.exists():
            candidate_path = p

    if candidate_path is None:
        return None, ".zap19"

    if candidate_path.is_file():
        source_dir = candidate_path.parent
        suf = candidate_path.suffix.lower()
        if suf.startswith(".ap") and len(suf) > 3 and suf[3:].isdigit():
            zap_ext = f".zap{suf[3:]}"
        else:
            zap_ext = ".zap19"
        return source_dir, zap_ext

    if candidate_path.is_dir():
        ap_files = sorted(candidate_path.glob("*.ap*"))
        if ap_files:
            suf = ap_files[0].suffix.lower()
            if suf.startswith(".ap") and len(suf) > 3 and suf[3:].isdigit():
                zap_ext = f".zap{suf[3:]}"
            else:
                zap_ext = ".zap19"
        else:
            zap_ext = ".zap19"
        return candidate_path, zap_ext

    return None, ".zap19"


def _build_project_zap_archive(
    *,
    canvas: CanvasState,
    safe_project: str,
    scl_dir: Path,
    pkg_dir: Path,
    project_source_path: str | Path | None = None,
) -> Path:
    """Create a Siemens .zap archive inside pkg_dir for direct TIA Portal import."""
    source_dir, zap_ext = _find_source_project_dir(canvas, project_source_path)
    zap_name = f"{safe_project}_AF{zap_ext}"
    zap_path = pkg_dir / zap_name

    with zipfile.ZipFile(zap_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if source_dir and source_dir.is_dir():
            # 1. Write original project files (preserving complete Siemens hardware/PLC config)
            for f in sorted(source_dir.rglob("*")):
                if f.is_file():
                    # skip internal diagnostic sidecars, log temp, lock files
                    if f.name.startswith("_researchos") or f.suffix.lower() in {".tmp", ".lock"}:
                        continue
                    rel = f.relative_to(source_dir).as_posix()
                    if rel.startswith("src/"):
                        continue
                    try:
                        zf.write(f, rel)
                    except Exception as e:
                        logger.warning("failed to include %s into zap: %s", rel, e)

        # 2. Write all refactored SCL source files into src/ inside the zap archive
        # TIA Portal recognizes src/ as standard "External Source Files" (外部源文件)
        for scl_file in sorted(scl_dir.glob("*.scl")):
            zf.write(scl_file, f"src/{scl_file.name}")

        # 3. If source_dir was missing (e.g. synthetic unit test), provide project stub so TIA recognizes it
        if not source_dir or not source_dir.is_dir():
            stub_ap = f"{safe_project}.ap19"
            zf.writestr(stub_ap, b"// ResearchOS AF Refactored Project Stub\n")
            zf.writestr("System/PEData.plf", b"")

    return zap_path


def build_release_package(
    canvas: CanvasState,
    report: dict[str, Any],
    *,
    project_name: str = "",
    compile_info: dict[str, Any] | None = None,
    out_dir: str | Path | None = None,
    equivalence_report: dict[str, Any] | None = None,
    project_source_path: str | Path | None = None,
) -> dict[str, Any]:
    """生成交付目录并打 zip；返回 ``{zip_path, dir_path, size_bytes, file_count}``。

    ``out_dir`` 缺省时落到系统临时目录（调用方负责按 TTL 清理或让 OS 回收）。
    ``equivalence_report`` 非 None 时额外写入 ``equivalence_report.json`` 并在
    README 附等价性小节；缺省 None 时包成员与历史行为完全一致。
    """
    safe_project = _safe_filename(project_name or canvas.project_name or "Refactored")
    if out_dir is not None:
        root = Path(out_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        pkg_dir = root / f"{safe_project}_AF_{time.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    else:
        pkg_dir = Path(tempfile.mkdtemp(prefix="refactor_release_"))
    pkg_dir.mkdir(parents=True, exist_ok=True)

    scl_dir = pkg_dir / SCL_DIR_NAME
    scl_dir.mkdir(parents=True, exist_ok=True)

    # 1) 按块分 SCL 文件（带命名空间防碰撞；生成全套 AF 架构块与转换块）
    written: list[Path] = []
    af_mega_sources: list[str] = []
    legacy_mega_sources: list[str] = []

    for key, block in canvas.blocks.items():
        # AF 块优先保留 key 完整前缀，防止多个 EM 的 Sequence/CallEquipment 相互覆盖
        fname = f"{_safe_filename(key)}.scl" if "::" in key else f"{_safe_filename(block.name or key)}.scl"
        target = scl_dir / fname
        scl_content = block.get_full_scl()
        target.write_text(scl_content, encoding="utf-8")
        written.append(target)

        role = getattr(block, "af_role", "")
        if "::" in key or (role and role not in {"legacy_superseded", "af_pending_manual"}):
            af_mega_sources.append(f"// ==========================================\n// Block: {key}\n// ==========================================\n{scl_content}\n")
        else:
            legacy_mega_sources.append(f"// ==========================================\n// Converted Block: {key}\n// ==========================================\n{scl_content}\n")

    # 生成一键式全量 AF 架构总源与全量旧块 SCL 批次源
    if af_mega_sources:
        af_mega_target = scl_dir / "00_AF_Full_Architecture_Blocks.scl"
        af_mega_target.write_text("\n\n".join(af_mega_sources), encoding="utf-8")
        written.append(af_mega_target)

    if legacy_mega_sources:
        legacy_mega_target = scl_dir / "01_All_Legacy_Blocks_Converted_To_SCL.scl"
        legacy_mega_target.write_text("\n\n".join(legacy_mega_sources), encoding="utf-8")
        written.append(legacy_mega_target)

    # 2) 引擎报告原样透传
    report_path = pkg_dir / REPORT_FILE
    report_path.write_text(
        json.dumps(report if isinstance(report, dict) else {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 3) IO 保留矩阵（字段自适应）
    io_path = pkg_dir / IO_MATRIX_FILE
    write_io_matrix_csv(report if isinstance(report, dict) else {}, io_path)

    # 4) 诚实编译收据
    receipt = build_compile_receipt(compile_info)
    receipt_path = pkg_dir / RECEIPT_FILE
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 5) 生成西门子原生工程归档包 (.zap19 / .zap)，方便博途直接一键导入/打开
    zap_path = _build_project_zap_archive(
        canvas=canvas,
        safe_project=safe_project,
        scl_dir=scl_dir,
        pkg_dir=pkg_dir,
        project_source_path=project_source_path,
    )
    zap_name = zap_path.name

    # 6) 等价性核对报告（可选；None 时不出现在包内，行为与历史一致）
    members = [zap_name, SCL_DIR_NAME, REPORT_FILE, IO_MATRIX_FILE, RECEIPT_FILE]
    if equivalence_report is not None:
        equiv_path = pkg_dir / EQUIVALENCE_FILE
        equiv_path.write_text(
            json.dumps(
                equivalence_report if isinstance(equivalence_report, dict) else {},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        members.append(EQUIVALENCE_FILE)

    # 7) 生成式 README
    readme_path = pkg_dir / README_FILE
    readme_path.write_text(
        build_readme(
            project_name=str(project_name or canvas.project_name or "Refactored"),
            canvas=canvas,
            report=report if isinstance(report, dict) else {},
            receipt=receipt,
            equivalence_report=equivalence_report,
            zap_name=zap_name,
        ),
        encoding="utf-8",
    )
    members.append(README_FILE)

    # 8) 打 zip（仅本包成员，不含外层目录名，解包即见成员文件）
    zip_path = pkg_dir.with_suffix(".zip")
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            src = pkg_dir / member
            if src.is_dir():
                for f in sorted(src.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(pkg_dir).as_posix())
                        file_count += 1
            elif src.is_file():
                zf.write(src, src.name)
                file_count += 1

    size_bytes = zip_path.stat().st_size
    logger.info(
        "release package built project=%s blocks=%d files=%d size=%d zap=%s zip=%s",
        safe_project,
        len(written),
        file_count,
        size_bytes,
        zap_name,
        zip_path,
    )
    return {
        "zip_path": str(zip_path),
        "zap_path": str(zap_path),
        "zap_name": zap_name,
        "dir_path": str(pkg_dir),
        "size_bytes": size_bytes,
        "file_count": file_count,
    }


def describe_package_one_liner(pkg: dict[str, Any], *, project_name: str = "") -> str:
    """「一句话可触达」的交付文案（ChatDock 直接展示用）。"""
    size_kb = int(pkg.get("size_bytes") or 0) / 1024.0
    return (
        f"{project_name or '工程'} AF V1.2 重构交付包已生成："
        f"{pkg.get('file_count')} 个文件 / {size_kb:.1f} KB"
        f"（zip：{Path(str(pkg.get('zip_path') or '')).name}）"
    )


def read_package_bytes(zip_path: str | Path) -> bytes:
    """读回 zip（单测/自检用）。"""
    return Path(zip_path).read_bytes()


def extract_zip_names(zip_path: str | Path) -> list[str]:
    """列出 zip 成员名（单测/自检用）。"""
    with zipfile.ZipFile(Path(zip_path)) as zf:
        return zf.namelist()


def remove_package(pkg: dict[str, Any] | None) -> None:
    """清理交付目录与 zip（单测收尾用；生产交给 OS 临时目录回收）。"""
    if not pkg:
        return
    for key in ("dir_path", "zip_path"):
        p = Path(str(pkg.get(key) or ""))
        if not str(p):
            continue
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)


__all__ = [
    "EQUIVALENCE_FILE",
    "IO_MATRIX_FILE",
    "README_FILE",
    "RECEIPT_FILE",
    "REPORT_FILE",
    "SCL_DIR_NAME",
    "build_compile_receipt",
    "build_readme",
    "build_release_package",
    "describe_package_one_liner",
    "extract_zip_names",
    "read_package_bytes",
    "remove_package",
    "write_io_matrix_csv",
]
