"""回写批次的依赖闭包（反向边 + 接口传播）。

背景缺陷：V3.0 蓝图回写引擎只按"本块被改"筛脏块，没有反向依赖闭包。
改 UDT_ST10_AutoCmd 的字段时，FB_ST10 的背景 DB 接口时间戳随之失效，
但 FB_ST10 / FB_Line / OB1 都不进批次，编译期报
``The interface of the block has changed``（接口时间戳不一致）。

本模块只做三件事：
1. ``build_reverse_index``：正向依赖翻转成"被依赖者 -> 直接依赖者"；
2. ``dependents_closure``：从种子出发沿反向边取**传递**闭包（不是一层）；
3. ``interface_closure`` / ``mark_interface_change``：把 UDT / GlobalDB
   的字段变化沿正向依赖向下游传播标注。

边界约定（与上层提示文案对齐）：
- 环：真实老项目里 FB 互调存在。用 visited 集合 + ``max_depth`` 双保险，
  环本身不死循环；只有**真实深度**超过 ``max_depth`` 才抛 ``RecursionError``，
  消息里带完整链路块名。
- 集合外的依赖（``LAF_ControlSclSequence`` 这类标准库 / 系统块）：
  不进 ``selected``，但以 ``external:<name>`` 记进 ``reasons``，
  供上层提示"依赖了未提供的标准库"。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from plc_engine.writeback_contract import BlockArtifact

__all__ = [
    "ClosureResult",
    "build_reverse_index",
    "dependents_closure",
    "interface_closure",
    "mark_interface_change",
]

#: ``max_depth`` 的默认上限。UDT -> FB -> FB -> FB -> OB 这类链路通常 3~6 层，
#: 32 层足够覆盖 LAF 老项目的手工嵌套，又能挡住脏依赖数据造成的爆炸。
DEFAULT_MAX_DEPTH = 32

#: 原因前缀。前端据此渲染"为什么这个块也要回写"。
REASON_SEED = "seed"
REASON_DEPENDS_ON = "depends-on"
REASON_INTERFACE = "interface-propagation"
REASON_EXTERNAL = "external"


@dataclass
class ClosureResult:
    """一次闭包计算的结果。

    selected:
        需要回写的块名（含种子），已去重，排序规则 = type_order 升序，
        同序内按块名（大小写不敏感）升序。
    reasons:
        块名 -> 入选原因。三种取值：``seed`` /
        ``depends-on:<上游块>`` / ``interface-propagation:<接口变化源头>``；
        另外集合外的依赖以 ``external:<name>`` 记账（该键**不在** selected 内）。
    max_depth:
        本次闭包**实际到达**的最大层数（种子层 = 0）。空结果为 0。
    """

    selected: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    max_depth: int = 0


# --------------------------------------------------------------------------- #
# 名字归一化
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    """大小写不敏感索引键；顺带容忍 SCL 里常见的双引号包裹。"""
    return name.strip().strip('"').strip().lower()


def _display(name: str) -> str:
    """对外展示名：去掉首尾空白与 SCL 引号，保留原始大小写。"""
    return name.strip().strip('"')


def _sort_key(block: BlockArtifact) -> tuple[int, str, str]:
    """先按 type_order，再按名字（大小写不敏感，名字兜底保证确定性）。"""
    return (block.type_order, block.name.lower(), block.name)


def _index_blocks(blocks: Sequence[BlockArtifact]) -> dict[str, BlockArtifact]:
    """归一化名 -> 块。重名（大小写不同的同名块）以先出现者为准。"""
    index: dict[str, BlockArtifact] = {}
    for block in blocks:
        index.setdefault(_norm(block.name), block)
    return index


def _reverse_by_norm(blocks: Sequence[BlockArtifact]) -> dict[str, set[str]]:
    """内部用：归一化被依赖者名 -> 直接依赖它的块名集合（名字保留原始写法）。"""
    reverse: dict[str, set[str]] = {}
    for block in blocks:
        for dep in block.dependencies:
            reverse.setdefault(_norm(dep), set()).add(block.name)
    return reverse


def _chain(via: Mapping[str, str | None], node: str) -> list[str]:
    """沿 via（子 -> 父）回溯出种子到 node 的完整链路。"""
    out = [node]
    seen = {node}
    cur = via.get(node)
    while cur is not None and cur not in seen:
        out.append(cur)
        seen.add(cur)
        cur = via.get(cur)
    out.reverse()
    return out


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def build_reverse_index(blocks: Sequence[BlockArtifact]) -> dict[str, set[str]]:
    """被依赖者 -> 直接依赖它的块集合（只翻一层）。

    匹配大小写不敏感（``fb_x`` 与 ``FB_X`` 视为同一个块），但**键保留原始名**：
    块在 ``blocks`` 里存在时用块自身的 ``name``；不存在（标准库等外部块）
    时用依赖串本身的写法（去引号）。

    只翻一层；传递闭包见 :func:`dependents_closure`。
    """
    index = _index_blocks(blocks)
    reverse: dict[str, set[str]] = {}
    for block in blocks:
        for dep in block.dependencies:
            target = index.get(_norm(dep))
            key = target.name if target is not None else _display(dep)
            reverse.setdefault(key, set()).add(block.name)
    return reverse


def dependents_closure(
    blocks: Sequence[BlockArtifact],
    seeds: Iterable[str],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ClosureResult:
    """从 seeds 出发沿反向边收集全部下游（传递闭包）。

    - seeds 大小写不敏感匹配；任一 seed 不在 ``blocks`` 内 -> ``KeyError``；
    - 空 seeds -> 空结果（不报错）；
    - 菱形 / 多入口：同一块只入选一次，reason 取**首次发现**的那条路径
      （遍历顺序固定，故结果可复现）；
    - 环（A 依赖 B 且 B 依赖 A）：visited 挡住回溯，正常返回；
    - 真实深度超过 ``max_depth`` -> ``RecursionError``，消息含链路块名。
    """
    if max_depth < 0:
        raise ValueError(f"max_depth 不能为负：{max_depth}")

    block_list = list(blocks)
    index = _index_blocks(block_list)
    reverse = _reverse_by_norm(block_list)

    # 种子解析：先全部校验，避免"解析到一半才发现未知 seed"的半成品状态。
    seed_blocks: list[BlockArtifact] = []
    seen_seed: set[str] = set()
    for raw in seeds:
        block = index.get(_norm(raw))
        if block is None:
            raise KeyError(f"种子块不存在于 blocks 中：{raw!r}")
        if block.name not in seen_seed:
            seen_seed.add(block.name)
            seed_blocks.append(block)
    seed_blocks.sort(key=_sort_key)

    if not seed_blocks:
        return ClosureResult()

    depth: dict[str, int] = {}
    via: dict[str, str | None] = {}
    reasons: dict[str, str] = {}
    # origin[x] = 从哪个 interface_changed 源头传播过来的；None 表示普通依赖路径。
    origin: dict[str, str | None] = {}

    queue: deque[str] = deque()
    for block in seed_blocks:
        depth[block.name] = 0
        via[block.name] = None
        reasons[block.name] = REASON_SEED
        origin[block.name] = block.name if block.interface_changed else None
        queue.append(block.name)

    while queue:
        current = queue.popleft()
        current_depth = depth[current]
        current_origin = origin[current]
        for child_name in sorted(
            reverse.get(_norm(current), ()), key=lambda n: index[_norm(n)].name.lower()
        ):
            child = index[_norm(child_name)]
            if child.name in depth:
                # 已访问（菱形汇合 / 环回到上游 / 多入口）——不重复入选。
                continue
            child_depth = current_depth + 1
            if child_depth > max_depth:
                chain = [*_chain(via, current), child.name]
                raise RecursionError(
                    f"依赖闭包深度超过 max_depth={max_depth}，链路：{' -> '.join(chain)}"
                )
            depth[child.name] = child_depth
            via[child.name] = current
            if current_origin is not None:
                # 接口变化沿着正向依赖下沉：reason 指回源头，而非中间层。
                origin[child.name] = current_origin
                reasons[child.name] = f"{REASON_INTERFACE}:{current_origin}"
            else:
                origin[child.name] = child.name if child.interface_changed else None
                reasons[child.name] = f"{REASON_DEPENDS_ON}:{current}"
            queue.append(child.name)

    selected_blocks = sorted((index[_norm(name)] for name in depth), key=_sort_key)
    selected = [block.name for block in selected_blocks]

    # 集合外的依赖：记账但不入选（上层据此提示"依赖了未提供的标准库"）。
    for block in selected_blocks:
        for dep in block.dependencies:
            if _norm(dep) in index:
                continue
            external = _display(dep)
            reasons.setdefault(external, f"{REASON_EXTERNAL}:{external}")

    return ClosureResult(
        selected=selected,
        reasons=reasons,
        max_depth=max(depth.values(), default=0),
    )


def interface_closure(
    blocks: Sequence[BlockArtifact],
    changed: Iterable[str] | None = None,
) -> ClosureResult:
    """接口变化闭包。

    ``changed`` 为 None 时以 ``blocks`` 中 ``interface_changed=True`` 的块为种子，
    否则用显式给定的 changed 列表（同样走大小写不敏感匹配，未知名字 -> KeyError）。

    语义：UDT / GlobalDB 的字段增删改会让所有下游块的背景 DB 失效，
    必须与接口变化源头一起回写，否则编译期接口时间戳对不上。
    """
    if changed is None:
        seeds = [b.name for b in blocks if b.interface_changed]
    else:
        seeds = list(changed)
    if not seeds:
        return ClosureResult()
    return dependents_closure(blocks, seeds)


def mark_interface_change(blocks: Sequence[BlockArtifact]) -> list[BlockArtifact]:
    """把接口变化沿正向依赖向下游传递标注，返回**新列表**。

    规则：若 A 依赖 B 且 B.interface_changed，则 A 也标为 interface_changed，
    并继续往下游传递（UDT -> FB -> FB -> OB 全链）。

    入参对象绝不修改：即使某个块无需标注，返回的也是 ``dataclasses.replace``
    出来的新实例（``dependencies`` 也复制一份，避免共享可变列表）。
    返回顺序与入参一致。
    """
    block_list = list(blocks)
    index = _index_blocks(block_list)
    reverse = _reverse_by_norm(block_list)

    propagated: set[str] = set()
    queue: deque[str] = deque()
    for block in block_list:
        if block.interface_changed:
            propagated.add(block.name)
            queue.append(block.name)

    while queue:
        current = queue.popleft()
        for child_name in sorted(
            reverse.get(_norm(current), ()), key=lambda n: index[_norm(n)].name.lower()
        ):
            child = index[_norm(child_name)]
            if child.name in propagated:
                continue
            propagated.add(child.name)
            queue.append(child.name)

    return [
        replace(
            block,
            interface_changed=block.interface_changed or block.name in propagated,
            dependencies=list(block.dependencies),
        )
        for block in block_list
    ]
