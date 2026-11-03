"""xml_guard 单测：DTD/实体拒绝守卫的正常与大小写/空白变体用例。"""

from __future__ import annotations

import pytest

from plc_engine.xml_guard import assert_no_dtd


def test_plain_xml_passes() -> None:
    # 无 DTD/实体的正常 SimaticML 片段与空串一律放行
    assert_no_dtd(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Document xmlns="http://www.siemens.com/SimaticML"><SW.Blocks.FC /></Document>'
    )
    assert_no_dtd("<Document><!-- 普通注释 --><Name>FB_Test</Name></Document>")
    assert_no_dtd("")


def test_doctype_rejected() -> None:
    with pytest.raises(ValueError):
        assert_no_dtd(
            '<?xml version="1.0"?><!DOCTYPE Document [<!ELEMENT foo EMPTY>]><Document />'
        )


def test_entity_rejected() -> None:
    with pytest.raises(ValueError):
        assert_no_dtd(
            '<!DOCTYPE Document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            "<Document>&xxe;</Document>"
        )
    with pytest.raises(ValueError):
        assert_no_dtd('<Document><!ENTITY lol "lol"></Document>')


@pytest.mark.parametrize(
    "snippet",
    [
        "<!DOCTYPE Document>",
        "<!doctype Document>",
        "<!DoCtYpE Document>",
        "<! DOCTYPE Document>",
        "<!\tDOCTYPE Document>",
        '<!ENTITY foo "bar">',
        "<!entity foo 'bar'>",
        "<!Entity\tfoo 'bar'>",
        "<!\nENTITY foo 'bar'>",
    ],
)
def test_decl_case_and_whitespace_variants_rejected(snippet: str) -> None:
    # 大小写不敏感、<! 与关键字之间允许任意空白
    with pytest.raises(ValueError):
        assert_no_dtd(f"<Document>{snippet}</Document>")
