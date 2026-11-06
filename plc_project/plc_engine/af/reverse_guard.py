"""Greenfield 反向保护哈希比对（WP-04 / F18 / D10 / 契约 §2.4）。

纯哈希比对逻辑：输入为 mock 块快照（``source_id -> sha256``），
**不调用** TIA / CLI / Openness、不写盘、不侵入生成链。

语义是「阻止并提示」，不是「先覆盖再提示」：任一 TIA 侧块与上次生成物
哈希不一致即 ``allowed=False`` 且列出 ``blocked_source_ids`` 与 ``reason``；
``tia_side_drift > 0`` 一律 fail-closed（契约 §0.7 / §6.4）。

说明：调用方在 TIA 侧不可用 / 读取失败时必须自行 fail-closed；本函数只负责
对**已取得**的快照做确定性比对。空 ``tia_side`` 配非空 ``last_generated`` 会被
判为全部缺失，从而自然触发 ``allowed=False``。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ReverseGuardVerdict:
    allowed: bool
    drift_count: int
    tia_side_drift: int
    blocked_source_ids: tuple[str, ...]
    reason: str


def check_reverse_guard(
    last_generated: Mapping[str, str],
    tia_side: Mapping[str, str],
) -> ReverseGuardVerdict:
    """比对「上次生成物哈希」与「TIA 侧现有块哈希」，不一致即阻止覆盖。

    参数
    ----
    last_generated : ``source_id -> sha256``
        上一次成功生成 / 写入的产物哈希（本次覆盖的基准）。
    tia_side : ``source_id -> sha256``
        本次覆盖前从 TIA 侧读到的现有块哈希快照（可为 mock）。

    口径
    ----
    ``drift_count``：上次生成物范围内哈希不一致（或被 TIA 侧删除）的块数。
    ``tia_side_drift``：TIA 侧相对生成物的全部漂移（不一致 + 缺失 + TIA 侧多出块），
    即 fail-closed 的直接依据，要求 ``== 0``。
    """
    gen = {str(k): str(v) for k, v in last_generated.items()}
    tia = {str(k): str(v) for k, v in tia_side.items()}

    mismatched: list[str] = []
    for sid, gen_hash in gen.items():
        tia_hash = tia.get(sid)
        if tia_hash is None or tia_hash != gen_hash:
            mismatched.append(sid)

    tia_only = [sid for sid in tia if sid not in gen]

    blocked = tuple(sorted(set(mismatched) | set(tia_only)))
    drift_count = len(mismatched)
    tia_side_drift = len(mismatched) + len(tia_only)
    allowed = tia_side_drift == 0

    if allowed:
        reason = "TIA 侧块哈希与上次生成物一致,允许增量覆盖(D10 反向保护通过)"
    else:
        reason = (
            "阻止并提示:TIA 侧存在与上次生成物不一致的块,"
            f"tia_side_drift={tia_side_drift},禁止覆盖(D10 / fail-closed,"
            "不是先覆盖再提示).被阻止的 source_id="
            + ", ".join(blocked)
            + ".请先在 TIA 侧核对该差异并显式确认后再写入."
        )

    return ReverseGuardVerdict(
        allowed=allowed,
        drift_count=drift_count,
        tia_side_drift=tia_side_drift,
        blocked_source_ids=blocked,
        reason=reason,
    )
