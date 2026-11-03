"""agents/plc/tia/xml_safe.py 的 DTD/实体拒绝单测（CWE-776 加固）。"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from agents.plc.tia.xml_safe import parse_xml_tree_no_dtd

NORMAL_XML = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<Document><SW.Blocks.ObjectSW><Attribute Name="X">1</Attribute></SW.Blocks.ObjectSW></Document>'
)


def _write(tmp_path, data: bytes, name: str = "block.xml"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_normal_xml_parses_with_declaration(tmp_path):
    tree = parse_xml_tree_no_dtd(_write(tmp_path, NORMAL_XML))
    assert tree.getroot().tag == "Document"


def test_doctype_rejected(tmp_path):
    p = _write(tmp_path, b"<!DOCTYPE foo [<!ENTITY x \"y\">]>\n" + NORMAL_XML)
    with pytest.raises(ValueError):
        parse_xml_tree_no_dtd(p)


@pytest.mark.parametrize("decl", [b"<!DOCTYPE doc>", b"<! doctype doc>", b"<!entity x \"y\">"])
def test_decl_variants_rejected(tmp_path, decl):
    p = _write(tmp_path, decl + b"\n" + NORMAL_XML)
    with pytest.raises(ValueError):
        parse_xml_tree_no_dtd(p)


def test_tree_write_still_works(tmp_path):
    """drop-in 语义：返回的 ElementTree 可 .write()（xml_patch 依赖此行为）。"""
    tree = parse_xml_tree_no_dtd(_write(tmp_path, NORMAL_XML))
    out = tmp_path / "out.xml"
    tree.write(out, encoding="utf-8", xml_declaration=True)
    assert ET.parse(out).getroot().tag == "Document"
