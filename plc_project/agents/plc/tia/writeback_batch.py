"""Mega-Source 单文件批次回写适配器（旁路通道，不修改 writeback.py）。

为什么要有这一层
----------------
``agents/plc/tia/writeback.py`` 的执行通道是**逐块导入**：
``_staged_scls(bundle)`` 返回 N 个 .scl，``execute_writeback`` 对每个文件各调一次
``generate_from_source_via_openness_cli``（C# 侧即
``ExternalSourceGroup.CreateFromFile`` + ``GenerateBlocksFromSource`` 各一次），
也就是 N 次 IPC + N 次生成。V3.0 文档 Tab1 要求把它换成**单次 Mega-Source 导入**：
N 个块拼成一个外部源文件，一次 CreateFromFile、一次 GenerateBlocksFromSource。

由于既有执行通道不能被破坏，本模块提供**旁路适配器**：

    BlockArtifact[]  ->  writeback_pipeline.build_plan()  ->  单文件 .scl
                     ->  contracts.AfBatchSource          ->  Openness worker（一次 IPC）

产出的是与 ``writeback.py`` 同形状的 dry-run / 结果字典（``success`` / ``dryRun`` /
``bundlePath`` / ``result`` / ``backupHint``），上层替换调用点即可，无需改契约。


如何把 execute_writeback 的 staged_scls 换成单个 batch（接线说明，不真改文件）
--------------------------------------------------------------------------
现状（``agents/plc/tia/writeback.py``）：

    1. ``prepare_writeback()`` -> ``changeset.write_import_bundle()``
       把每个块单独写成 ``{bundle}/external_sources/{name}.scl``，
       文件名清单落在 ``{bundle}/staged_scls.json``。
    2. ``plan_writeback()`` 对每个 .scl 生成一条
       ``{"action": "generate_from_source", "target": "<单个 .scl>"}``。
    3. ``execute_writeback()`` 在 ``for entry in pending:`` 循环里对
       ``action == "generate_from_source"`` 的条目逐个调用
       ``generate_from_source_via_openness_cli(project_path, target, ...)``
       —— N 个块就是 N 次 IPC。

换法（三步，第 1、2 步本模块已经做完，第 3 步是接线者要动的那一行）：

    第 1 步：拿批次文件与契约（本模块）
        blocks = from_bundle_dir(bundle)                 # .xml 自动跳过
        plan   = prepare_batch_writeback(blocks, output_dir=export_dir)
        # plan.bundle_path  -> 唯一的 .scl（Mega-Source 单文件）
        # plan.af_batch     -> contracts.AfBatchSource（path/sha256/block_names/...）

    第 2 步：让 stage 阶段只 stage 这一个文件
        把 ``write_import_bundle`` 写出的 ``external_sources/*.scl`` 换掉：
        清空 ``{bundle}/external_sources`` 并把 ``plan.bundle_path`` 复制进去，
        或直接把 ``{bundle}/staged_scls.json`` 写成
        ``[{"path": "<plan.bundle_path>", "software_unit": ""}]``。
        这样 ``_staged_scls(bundle)`` 返回长度为 1 的列表，
        ``plan_writeback()`` 自然只产出一条 ``generate_from_source`` 计划。

    第 3 步：execute_writeback 的 SCL 分支从"循环"降成"一次调用"
        把 ``for entry in pending:`` 里的
            payload = generate_from_source_via_openness_cli(project_path, target, ...)
        换成对单个批次文件的一次调用（等价 C# 侧）：
            payload = generate_from_source_via_openness_cli(
                project_path, Path(plan.bundle_path), plc_name=plc_name,
                software_unit="", overwrite=True,
            )
        # ExternalSourceGroup.CreateFromFile(plan.bundle_path) 一次
        # + GenerateBlocksFromSource 一次；编译门禁与备份/回滚逻辑保持原样。

**不改 writeback.py 也能跑通的默认姿势**（本模块现在就是这样）：
用 ``execute_batch_writeback`` 顶替 ``execute_writeback`` 的 SCL 分支，
XML 导入、备份、编译门禁仍交给 ``writeback.py``：

        out = execute_batch_writeback(plan, worker_call=worker)   # dry_run 默认 True
        out["result"]       # contracts.WritebackResult 经 to_dict() 的字典
        out["writebackResult"]  # 同一份结果的 dataclass 本体

安全底线
--------
* ``execute_batch_writeback`` 的 ``dry_run`` **默认 True**：不注入 worker 且显式
  ``dry_run=False`` 时直接拒绝，绝不静默触发真实回写。
* fail-closed 穿透：``build_plan`` 有 lint error 时 ``prepare_batch_writeback``
  返回 ``blocked=True`` 且**不创建任何文件**；``execute_batch_writeback`` 遇到
  blocked 计划直接返回拒绝结果，不调 worker。
* 依赖成环等结构性错误原样抛出（``mega_source.CycleError``），不吞异常。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.plc.tia.writeback import staged_files
from plc_engine.contracts import (
    AfBatchSource,
    CompileErrorItem,
    WritebackResult,
    to_dict,
)
from plc_engine.writeback_contract import BlockArtifact, scl_block_name, sha256_text
from plc_engine.writeback_linter import Finding
from plc_engine.writeback_pipeline import build_plan, materialize

__all__ = [
    "BATCH_FILE_NAME",
    "BatchWritebackPlan",
    "execute_batch_writeback",
    "from_bundle_dir",
    "infer_kind",
    "prepare_batch_writeback",
    "to_fast_writeback_request",
]

logger = logging.getLogger(__name__)

#: 单个 Mega-Source 批次的文件名（一个批次 = 一个文件 = 一次 IPC）。
BATCH_FILE_NAME = "AF_Batch.scl"

#: UTF-8 BOM 字节头，用于按"实际字节"断言 has_utf8_bom（绝不硬编码 True）。
BOM_BYTES = b"\xef\xbb\xbf"

_NOTE = (
    "Mega-Source 单文件批次：N 个块合并为一个外部源 .scl，"
    "一次 ExternalSourceGroup.CreateFromFile + GenerateBlocksFromSource。"
    "门禁失败即整批拒绝且不写盘；dry_run 默认 True；"
    "依赖成环以 mega_source.CycleError 原样抛出。"
)


@dataclass
class BatchWritebackPlan:
    """一次单文件批次回写的计划。

    bundle_path 为空串表示被门禁拦截（blocked=True）或无可写内容，
    此时 af_batch 的 path/sha256 也为空，切勿拿去喂 Openness。
    """

    bundle_path: str
    af_batch: AfBatchSource
    block_count: int
    skipped_count: int
    blocked: bool = False
    blocking_findings: list[Finding] = field(default_factory=list)
    dry_run: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #
def _planned_entry(batch: AfBatchSource) -> list[dict[str, Any]]:
    """一条计划 = 一次 IPC（与 writeback.plan_writeback 的条目形状对齐）。"""
    if not batch.block_names or not batch.path:
        return []
    return [
        {
            "action": "generate_from_source",
            "block": Path(batch.path).stem,
            "target": batch.path,
            "kind": "scl",
            "reason": "mega-source-batch",
            "blocks": list(batch.block_names),
        }
    ]


def _dry_payload(
    batch: AfBatchSource,
    *,
    blocked: bool,
    blocking: Sequence[Finding] = (),
) -> dict[str, Any]:
    return {
        "dryRun": True,
        "blocked": blocked,
        "bundlePath": batch.path,
        "blockCount": len(batch.block_names),
        "skippedCount": len(batch.skipped_unchanged),
        "blockNames": list(batch.block_names),
        "skippedUnchanged": list(batch.skipped_unchanged),
        "externalDependencies": list(batch.external_dependencies),
        "blockingFindings": [to_dict(f) for f in blocking],
        "planned": _planned_entry(batch),
        "note": _NOTE,
    }


def prepare_batch_writeback(
    blocks: Sequence[BlockArtifact],
    *,
    output_dir: str | Path,
    seeds: Iterable[str] | None = None,
    cache: Mapping[str, str] | None = None,
    bom_enabled: bool = True,
) -> BatchWritebackPlan:
    """计算计划并写盘出单文件 .scl。门禁失败时 blocked=True 且不写盘。

    seeds 为 None 视为全量重建；传入 cache 时未变化块不进批次（记入
    skipped_unchanged）。**全部命中缓存时不落盘任何文件**：bundle_path 为空串、
    block_count == 0，execute_batch_writeback 据此跳过 worker。
    绝不产出"仅含 BOM 的空 .scl"——那种文件会被 staged_files 捡到，
    触发一次毫无意义的 Openness IPC。
    """
    plan = build_plan(blocks, seeds=seeds, cache=cache, bom_enabled=bom_enabled)

    if plan.has_errors:
        errors = [f for f in plan.findings if f.severity == "error"]
        logger.error("静态门禁拦截 %d 条 error，未生成批次文件", len(errors))
        return BatchWritebackPlan(
            bundle_path="",
            af_batch=AfBatchSource(),
            block_count=0,
            skipped_count=0,
            blocked=True,
            blocking_findings=errors,
            dry_run={
                **_dry_payload(AfBatchSource(), blocked=True, blocking=errors),
                "message": "静态门禁拦截，未生成批次文件。",
            },
        )

    if not plan.planned_text or not plan.block_names:
        logger.info("全部块命中脏块缓存，无需生成批次文件")
        return BatchWritebackPlan(
            bundle_path="",
            af_batch=AfBatchSource(skipped_unchanged=list(plan.skipped_unchanged)),
            block_count=0,
            skipped_count=len(plan.skipped_unchanged),
            dry_run={
                **_dry_payload(
                    AfBatchSource(skipped_unchanged=list(plan.skipped_unchanged)),
                    blocked=False,
                ),
                "message": "全部命中脏块缓存，未生成批次文件，无需导入。",
            },
        )

    written = materialize(plan, Path(output_dir) / BATCH_FILE_NAME)
    raw = written.read_bytes()
    text = raw.decode("utf-8-sig")
    batch = AfBatchSource(
        path=str(written),
        sha256=sha256_text(text),
        block_names=list(plan.block_names),
        external_dependencies=list(plan.external_dependencies),
        skipped_unchanged=list(plan.skipped_unchanged),
        has_utf8_bom=raw[:3] == BOM_BYTES,
    )
    return BatchWritebackPlan(
        bundle_path=str(written),
        af_batch=batch,
        block_count=len(batch.block_names),
        skipped_count=len(batch.skipped_unchanged),
        dry_run=_dry_payload(batch, blocked=False),
    )


# --------------------------------------------------------------------------- #
# execute
# --------------------------------------------------------------------------- #
def _compile_error_item(raw: Any) -> CompileErrorItem:
    """worker 的一条 error -> contracts.CompileErrorItem（camelCase 优先）。"""
    if not isinstance(raw, Mapping):
        return CompileErrorItem(tia_description=str(raw))

    def pick(*keys: str) -> str:
        for key in keys:
            value = raw.get(key)
            if value:
                return str(value)
        return ""

    return CompileErrorItem(
        block_name=pick("blockName", "block_name"),
        network_or_line=pick("networkOrLine", "network_or_line", "line"),
        tia_description=pick("tiaDescription", "tia_description", "message", "error"),
        block_path=pick("blockPath", "block_path"),
        timestamp=pick("timestamp"),
    )


def _backup_hint(payload: Mapping[str, Any]) -> str:
    """与 writeback._restore_hint 同形状的回滚提示；无备份则空串。"""
    raw = payload.get("backupPath") or payload.get("backup_path")
    if not raw:
        return ""
    return f"restore_from_backup({str(raw)!r}, '<project_path>')"


def _base_payload(plan: BatchWritebackPlan, *, dry_run: bool) -> dict[str, Any]:
    return {
        "success": False,
        "dryRun": bool(dry_run),
        "written": False,
        "bundlePath": plan.bundle_path,
        "blockCount": plan.block_count,
        "skippedCount": plan.skipped_count,
        "planned": list(plan.dry_run.get("planned", [])),
        "skippedItems": list(plan.af_batch.skipped_unchanged),
        "backupHint": "",
        "note": _NOTE,
    }


def _with_result(base: dict[str, Any], result: WritebackResult, **extra: Any) -> dict[str, Any]:
    return {**base, "result": to_dict(result), "writebackResult": result, **extra}


def execute_batch_writeback(
    plan: BatchWritebackPlan,
    *,
    worker_call: Callable[[str], dict] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """执行（或预演）一次单文件批次回写。默认 dry_run=True，绝不真的碰博途。

    ``worker_call`` 注入后由它把 ``bundle_path`` 交给 Openness worker，返回形如
    ``{"success": bool, "errors": [...], "elapsedMilliseconds": int}`` 的字典；
    本函数把结果映射成 ``contracts.WritebackResult`` 并一并返回 ``to_dict()``。
    计划为 blocked、块数为 0、处于 dry-run 或缺少 ``worker_call`` 时，
    一律不调用 worker。worker 自身抛出的异常原样上抛，不做静默降级。
    """
    base = _base_payload(plan, dry_run=dry_run)

    if plan.blocked:
        return _with_result(
            base,
            WritebackResult(success=False),
            blocked=True,
            refused="gate_blocked",
            blockingFindings=[to_dict(f) for f in plan.blocking_findings],
            message="静态门禁未通过，已拒绝回写（未调用 Openness）。",
        )

    if plan.block_count == 0:
        return _with_result(
            base,
            WritebackResult(success=True, skipped_unchanged_blocks=plan.skipped_count),
            success=True,
            skipped="unchanged",
            message="全部块命中脏块缓存，无需回写（未调用 Openness）。",
        )

    if dry_run:
        return _with_result(
            base,
            WritebackResult(
                success=True,
                written_block_count=plan.block_count,
                skipped_unchanged_blocks=plan.skipped_count,
            ),
            success=True,
            message="dry-run：只回传计划，未执行任何 Openness 写操作。",
        )

    if worker_call is None:
        return _with_result(
            base,
            WritebackResult(success=False),
            refused="no_worker_call",
            message="dry_run=False 但未注入 worker_call，拒绝触发真实回写。",
        )

    payload = worker_call(plan.bundle_path)
    if not isinstance(payload, Mapping):
        raise TypeError(f"worker_call 必须返回 Mapping，实际返回 {type(payload).__name__}")
    ok = bool(payload.get("success"))
    result = WritebackResult(
        success=ok,
        elapsed_milliseconds=int(payload.get("elapsedMilliseconds") or 0),
        written_block_count=plan.block_count if ok else 0,
        skipped_unchanged_blocks=plan.skipped_count,
        errors=[_compile_error_item(item) for item in (payload.get("errors") or [])],
    )
    return _with_result(
        base,
        result,
        success=ok,
        written=ok,
        backupHint=_backup_hint(payload),
        worker=dict(payload),
    )


# --------------------------------------------------------------------------- #
# 从既有 staged bundle 反解 BlockArtifact
# --------------------------------------------------------------------------- #
#: 顺序敏感：FUNCTION_BLOCK 必须先于 FUNCTION 匹配。
_KIND_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("FUNCTION_BLOCK", "FB"),
    ("ORGANIZATION_BLOCK", "OB"),
    ("DATA_BLOCK", "INSTANCE_DB"),
    ("FUNCTION", "FC"),
    ("TYPE", "UDT"),
)


def infer_kind(source: str) -> str | None:
    """按 SCL 内容推断 BlockArtifact.kind；认不出返回 None。"""
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        upper = line.upper()
        for keyword, kind in _KIND_KEYWORDS:
            if upper.startswith(keyword):
                return kind
    return None


def from_bundle_dir(bundle_dir: str | Path) -> list[BlockArtifact]:
    """从 ``staged_files()`` 产出的 .scl / .xml 列表构造 BlockArtifact。

    .xml 一律跳过（外部源只吃 SCL）；单个 .scl 读不出来或认不出块类型/块名时
    跳过并记 warning，不让整批崩掉。
    """
    xmls, scls = staged_files(bundle_dir)
    if xmls:
        logger.info("跳过 %d 个 .xml（外部源只吃 SCL）", len(xmls))

    blocks: list[BlockArtifact] = []
    for path in scls:
        try:
            source = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning("跳过无法读取的 .scl：%s（%s）", path, exc)
            continue
        kind = infer_kind(source)
        name = scl_block_name(source)
        if kind is None or not name:
            logger.warning("跳过无法识别的 .scl：%s（kind=%s, name=%s）", path, kind, name)
            continue
        blocks.append(BlockArtifact(name=name, kind=kind, source=source))
    return blocks


def to_fast_writeback_request(
    plan: BatchWritebackPlan,
    blocks: Sequence[BlockArtifact],
    *,
    force_full_compile: bool = False,
    exclusive_access_reason: str = "Mega-Source 单文件批次回写",
) -> dict[str, Any]:
    """把批次计划映射成 C# ``/fast-writeback`` 的请求 JSON。

    C# 侧 ``FastWriteback`` 用 ``InterfaceChanged || HasUdtOrGlobalDbChange``
    判定编译范围：二者皆 false 时走 ``incremental_blocks`` 增量编译，而
    ``GenerateBlocksFromSource`` 只重建 FB 本体、**不会刷新已存在的 Instance DB**。

    真机依据（TIA Portal V19 / HR001，2026-11-02）：
      未标记接口变更 -> incremental_blocks -> 1008 条结构化错误，其中 928 条
      为 ``The data block is not up-to-date, because the interface has been
      changed in the meantime.``
      标记接口变更 -> full_software_interface_changed -> 27.52s、9 条错误，
      全量编译后仅剩 3 条 know-how protected 块的真实错误。

    因此本函数从 ``BlockArtifact.interface_changed`` 与块类型**自动推断**，
    不允许调用方漏填；``force_full_compile=True`` 可显式强制全量编译。
    """
    if plan.blocked:
        raise ValueError("静态门禁拦截，禁止生成 /fast-writeback 请求")
    if not plan.bundle_path:
        raise ValueError("全量命中脏块缓存或计划为空，无需回写")

    by_name = {b.name.lower(): b for b in blocks}
    selected = [
        by_name[name.lower()]
        for name in plan.af_batch.block_names
        if name.lower() in by_name
    ]
    interface_changed = any(b.interface_changed for b in selected)
    type_changed = any(b.kind in ("UDT", "GLOBAL_DB") for b in selected)
    full_compile = force_full_compile or interface_changed or type_changed

    return {
        "scl": plan.bundle_path,
        "interfaceChanged": interface_changed,
        "hasUdtOrGlobalDbChange": full_compile,
        "blockNames": list(plan.af_batch.block_names),
        "skippedUnchangedBlocks": len(plan.af_batch.skipped_unchanged),
        "writtenBlockCount": plan.block_count,
        "exclusiveAccessReason": exclusive_access_reason,
    }
