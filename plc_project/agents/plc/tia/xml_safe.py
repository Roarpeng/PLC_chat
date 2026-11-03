"""DTD/实体拒绝的 XML 文件解析包装（防 billion-laughs 实体扩展，CWE-776）。

上传/导入的 SimaticML XML 属半信任输入；Python ElementTree 会接受内部 DTD
实体扩展。与 plc_engine/xml_guard.py 同一规则的自包含实现（解析核心层
不引画布引擎层，避免跨层依赖）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

_DTD_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def parse_xml_tree_no_dtd(path: str | Path) -> ET.ElementTree:
    """ET.parse 的 DTD 拒绝版：文件含 <!DOCTYPE/<!ENTITY> 即抛 ValueError。

    语义与 ``ET.parse(path)`` 一致（返回 ElementTree，可 .getroot()/.write()），
    以字节解析以保留 XML 声明的编码语义。
    """
    data = Path(path).read_bytes()
    if _DTD_RE.search(data.decode("utf-8", errors="ignore")):
        raise ValueError(f"XML 含 DTD/实体声明，已拒绝解析: {path}")
    return ET.ElementTree(ET.fromstring(data))
