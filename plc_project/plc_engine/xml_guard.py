"""XML 解析安全守卫：解析半信任 XML 前拒绝 DTD / 实体声明。

导入链（.zip/.xml/.txt 上传 → SimaticML / HMI XML 解析）属半信任输入，
而 Python ElementTree 会展开内部 DTD 实体（billion-laughs 实体膨胀、
CWE-776 资源耗尽）。gateway 与 plc_engine 共用本守卫；plc_engine 不得
依赖 gateway，故纯函数守卫落在本层。
"""

from __future__ import annotations

import re

#: DTD / 内部实体声明特征（大小写不敏感、容忍 ``<!`` 与关键字之间的空白）
_DTD_DECL_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def assert_no_dtd(text: str) -> None:
    """防 billion-laughs 实体扩展：文本含 DTD/ENTITY 声明即抛 ValueError。"""
    if text and _DTD_DECL_RE.search(text):
        raise ValueError("XML 含 DTD/ENTITY 声明，已拒绝解析（防实体扩展攻击）")
