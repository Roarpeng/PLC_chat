"""回写链路共享数据契约。

本文件是 mega_source / dependency_closure / writeback_linter 三个模块的
唯一共同依赖。任何一方都不得再定义自己的 BlockArtifact，也不得修改本文件
的字段语义 —— 只在需要时追加字段并提供默认值。

设计依据：docs/plc_chat_v3_0.html Tab1 的 AfBlockArtifact DTO。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# 西门子外部源要求：被依赖者必须先于依赖者出现。
# 同 type_order 内部再按 dependencies 做拓扑排序。
TYPE_ORDER: dict[str, int] = {
    "UDT": 1,
    "GLOBAL_DB": 2,
    "FC": 3,
    "FB": 3,
    "INSTANCE_DB": 4,
    "OB": 4,
}


class UnknownBlockKind(ValueError):
    """kind 不在 TYPE_ORDER 内。"""


@dataclass
class BlockArtifact:
    """一个待回写的外部源程序块。

    name 必须与 SCL 源里的块名严格一致（不含引号），用作图节点键。
    source 是完整的、可直接拼进外部源文件的 SCL 文本
    （例如 TYPE..END_TYPE 或 FUNCTION_BLOCK..END_FUNCTION_BLOCK）。
    """

    name: str
    kind: str
    source: str
    # 正向依赖：本块引用了哪些块（被引用者必须排在前面）
    dependencies: list[str] = field(default_factory=list)
    # 接口是否变化（VAR_INPUT / VAR / STRUCT 字段增删改）
    interface_changed: bool = False
    # 目标分组路径，形如 "U1Em1_AutoStep"；None 表示项目根
    group_path: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in TYPE_ORDER:
            raise UnknownBlockKind(
                f"未知块类型 {self.kind!r}，可选：{', '.join(TYPE_ORDER)}"
            )

    @property
    def type_order(self) -> int:
        return TYPE_ORDER[self.kind]

    @property
    def is_interface_bearing(self) -> bool:
        """UDT 与 GlobalDB 的字段变化会波及全部下游。"""
        return self.kind in ("UDT", "GLOBAL_DB")

    def sha256(self) -> str:
        return sha256_text(self.source)


def sha256_text(text: str) -> str:
    """与 v3.0 文档 ComputeSha256 对齐：UTF-8 编码后取 SHA-256 十六进制。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scl_block_name(source: str) -> str | None:
    """从 SCL 文本中提取块/类型名。

    支持：
      TYPE "UDT_X" / TYPE UDT_X
      FUNCTION_BLOCK "FB_X" / FUNCTION "FC_X"
      DATA_BLOCK "DB_X"
      ORGANIZATION_BLOCK "OB_X"
    提取不到返回 None。
    """
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        upper = line.upper()
        for kw in (
            "FUNCTION_BLOCK",
            "FUNCTION",
            "ORGANIZATION_BLOCK",
            "DATA_BLOCK",
            "TYPE",
        ):
            if upper.startswith(kw):
                rest = line[len(kw):].strip()
                # DATA_BLOCK "IDB" "FB" 这种形式只取第一个名字
                token = rest.split()[0] if rest.split() else ""
                return token.strip('"') or None
    return None
