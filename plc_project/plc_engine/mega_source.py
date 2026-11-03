"""Mega-Source 合并回写：真拓扑排序 + SHA-256 脏块过滤 + 单文件拼接落盘。

设计依据：docs/plc_chat_v3_0.html Tab1「Mega-Source 单文件回写」。
西门子外部源（External Source File）要求被依赖者先于依赖者出现，
因此合并前必须做真正的拓扑排序，而不能按名字或类型粗略排序。

本模块只依赖 plc_engine.writeback_contract，不引入任何第三方库。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from plc_engine.writeback_contract import BlockArtifact, scl_block_name

# 文件末尾行尾与块间分隔：博途外部源对空行数量敏感，统一为一空行。
_BLOCK_SEPARATOR = "\n\n"

__all__ = [
    "BundleResult",
    "CycleError",
    "DuplicateBlockError",
    "bundle",
    "filter_dirty",
    "topological_sort",
    "write_bundle",
]


class CycleError(ValueError):
    """依赖成环。属性 cycle 为参与环的块名（按环序）。"""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = list(cycle)
        super().__init__("检测到循环依赖：" + " -> ".join(self.cycle + self.cycle[:1]))


class DuplicateBlockError(ValueError):
    """同名块重复出现（不区分大小写）。"""


@dataclass
class BundleResult:
    """一次合并回写的结果。"""

    text: str
    # 实际写出的顺序（已剔除 skipped_unchanged 中的块）
    block_names: list[str] = field(default_factory=list)
    # 依赖了但不在本次集合里的块名（如博世标准库 LAF_xxx），去重后按字母序
    external_dependencies: list[str] = field(default_factory=list)
    # 因 sha256 命中 cache 而未重复写出的块名
    skipped_unchanged: list[str] = field(default_factory=list)


def _normalize(name: str) -> str:
    """去掉首尾空白与外部源里的双引号，统一成可比较的块名。"""
    return name.strip().strip('"').strip()


def _index_blocks(blocks: Sequence[BlockArtifact]) -> dict[str, BlockArtifact]:
    """按小写块名建立索引，顺带做大小写不敏感的重复检测。"""
    index: dict[str, BlockArtifact] = {}
    for block in blocks:
        key = _normalize(block.name).lower()
        if key in index:
            raise DuplicateBlockError(
                f"块名重复：{index[key].name!r} 与 {block.name!r}（块名不区分大小写）"
            )
        index[key] = block
    return index


def _sorted_key(block: BlockArtifact) -> tuple[int, str]:
    """同层稳定排序键：先按类型顺序（UDT → DB → FC/FB → IDB/OB），再按名字。"""
    return (block.type_order, block.name)


def topological_sort(blocks: Sequence[BlockArtifact]) -> list[BlockArtifact]:
    """Kahn 算法拓扑排序：被依赖者先出队。

    入度表 + 队列（按层分批，层内按 (type_order, name) 稳定排序），
    同一输入两次调用结果完全一致。成环时抛 CycleError，绝不静默切断。
    """
    index = _index_blocks(blocks)
    if not index:
        return []

    indegree: dict[str, int] = {key: 0 for key in index}
    children: dict[str, list[str]] = {key: [] for key in index}
    deps_internal: dict[str, list[str]] = {key: [] for key in index}

    for key, block in index.items():
        seen: set[str] = set()
        for raw_dep in block.dependencies:
            dep = _normalize(raw_dep).lower()
            # 外部依赖（标准库块、系统块）不参与排序；重复书写只计一次
            if not dep or dep not in index or dep in seen:
                continue
            seen.add(dep)
            indegree[key] += 1
            deps_internal[key].append(dep)
            children[dep].append(key)

    ready: list[str] = [key for key, degree in indegree.items() if degree == 0]
    ordered: list[BlockArtifact] = []

    while ready:
        # 层内排序保证确定性；heapq 只是一次性挑出本层全部节点
        layer = sorted(ready, key=lambda key: _sorted_key(index[key]))
        ready = []
        for key in layer:
            ordered.append(index[key])
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)

    if len(ordered) != len(index):
        residual = [key for key, degree in indegree.items() if degree > 0]
        raise CycleError(_find_cycle(residual, deps_internal, index))

    return ordered


def _find_cycle(
    residual: list[str],
    deps_internal: dict[str, list[str]],
    index: dict[str, BlockArtifact],
) -> list[str]:
    """在残余子图上沿"依赖"方向走出一个实际环，返回环上的块名序列。

    残余节点在子图内的入度均 > 0，即至少有一个仍在残余集合内的依赖，
    因此沿依赖方向必能走到重复节点。
    """
    residual_set = set(residual)
    visited: set[str] = set()
    for start in residual:
        if start in visited:
            continue
        path: list[str] = []
        position: dict[str, int] = {}
        node: str | None = start
        while node is not None:
            if node in position:
                return [index[key].name for key in path[position[node] :]]
            position[node] = len(path)
            path.append(node)
            node = next((dep for dep in deps_internal[node] if dep in residual_set), None)
        visited.update(path)
    # 理论上不可达：残余节点必有残余依赖，必然能走出环
    return [index[key].name for key in residual]


def _cache_lookup(cache: Mapping[str, str], name: str) -> str | None:
    """块名大小写不敏感地查 cache。"""
    if name in cache:
        return cache[name]
    lowered = _normalize(name).lower()
    for key, value in cache.items():
        if _normalize(key).lower() == lowered:
            return value
    return None


def filter_dirty(
    blocks: Sequence[BlockArtifact],
    cache: Mapping[str, str],
) -> tuple[list[BlockArtifact], dict[str, str]]:
    """按 SHA-256 过滤未变化块。

    返回（脏块列表, 完整的新 cache）。新 cache 覆盖全部块 —— 只回填脏块会让
    未变块在下一轮重新变成"缺失"，从而每次全量回写。
    """
    dirty: list[BlockArtifact] = []
    new_cache: dict[str, str] = {}
    for block in blocks:
        digest = block.sha256()
        new_cache[block.name] = digest
        if _cache_lookup(cache, block.name) != digest:
            dirty.append(block)
    return dirty, new_cache


def _validate_source(block: BlockArtifact) -> str:
    """校验 source 非空且块名与 artifact.name 一致，返回 strip 后的源码。"""
    source = block.source.strip()
    if not source:
        raise ValueError(f"块 {block.name!r} 的 source 为空，无法合并回写")

    actual = scl_block_name(source)
    if actual is None:
        raise ValueError(
            f"无法从 source 中解析出块名：artifact.name={block.name!r}，"
            f"source 首行={source.splitlines()[0]!r}"
        )
    if _normalize(actual).lower() != _normalize(block.name).lower():
        raise ValueError(
            f"块名与源码不一致：artifact.name={block.name!r}，source 中声明的是 {actual!r}"
        )
    return source


def bundle(
    blocks: Sequence[BlockArtifact],
    *,
    keep_unchanged: bool = False,
    cache: Mapping[str, str] | None = None,
) -> BundleResult:
    """把多个块合并成一个外部源文件文本。

    keep_unchanged=False 且传入 cache 时，sha256 命中 cache 的块不重复写出，
    记入 skipped_unchanged；这些块仍参与依赖图，因此不会误判成外部依赖。
    """
    _index_blocks(blocks)  # 先报重复，避免后续排序/解析给出误导性错误

    sources: dict[str, str] = {}
    for block in blocks:
        sources[_normalize(block.name).lower()] = _validate_source(block)

    ordered = topological_sort(blocks)

    internal_names = {_normalize(block.name).lower() for block in blocks}
    externals: dict[str, str] = {}
    for block in ordered:
        for raw_dep in block.dependencies:
            dep = _normalize(raw_dep)
            if not dep or dep.lower() in internal_names:
                continue
            externals.setdefault(dep.lower(), dep)

    skipped: list[str] = []
    written: list[str] = []
    if cache is not None and not keep_unchanged:
        for block in ordered:
            if _cache_lookup(cache, block.name) == block.sha256():
                skipped.append(block.name)

    skipped_set = set(skipped)
    chunks: list[str] = []
    for block in ordered:
        if block.name in skipped_set:
            continue
        written.append(block.name)
        chunks.append(sources[_normalize(block.name).lower()])

    text = _BLOCK_SEPARATOR.join(chunks) + "\n" if chunks else ""

    return BundleResult(
        text=text,
        block_names=written,
        external_dependencies=sorted(externals.values()),
        skipped_unchanged=skipped,
    )


def write_bundle(
    blocks: Sequence[BlockArtifact],
    path: str | Path,
    *,
    keep_unchanged: bool = False,
    cache: Mapping[str, str] | None = None,
) -> Path:
    """合并并落盘为带 UTF-8 BOM 的外部源文件，返回写入路径。

    博途外部源对中文注释要求 BOM，因此显式用 utf-8-sig 写出；
    同时锁死换行为 LF，避免 Windows 文本模式把空行翻译成 CRLF。
    """
    result = bundle(blocks, keep_unchanged=keep_unchanged, cache=cache)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="\n") as handle:
        handle.write(result.text)

    if target.read_bytes()[:3] != b"\xef\xbb\xbf":
        raise RuntimeError(f"写出失败：{target} 缺少 UTF-8 BOM")  # 防御性自检
    return target
