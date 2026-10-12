"""Safe SimaticML XML patches for Openness re-import (no LAD rewrite)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def read_block_name_from_xml(xml_path: str | Path) -> str:
    """Best-effort block Name from SimaticML AttributeList."""
    path = Path(xml_path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return path.stem
    for node in root.iter():
        if _local_name(node.tag) != "Name":
            continue
        text = (node.text or "").strip()
        if text:
            return text
    return path.stem


def _find_header_comment_text_els(root: ET.Element) -> list[ET.Element]:
    """Block-level MultilingualText Comment → Text (exclude CompileUnit network comments)."""
    parent_map = {c: p for p in root.iter() for c in p}
    texts: list[ET.Element] = []
    for node in root.iter():
        if _local_name(node.tag) != "MultilingualText":
            continue
        if node.attrib.get("CompositionName") != "Comment":
            continue
        cur: ET.Element | None = node
        under_compile = False
        while cur is not None:
            if _local_name(cur.tag) in {"SW.Blocks.CompileUnit", "CompileUnit"}:
                under_compile = True
                break
            cur = parent_map.get(cur)
        if under_compile:
            continue
        for text_el in node.iter():
            if _local_name(text_el.tag) == "Text":
                texts.append(text_el)
    return texts


def patch_block_header_comment(
    xml_path: str | Path,
    comment: str,
    *,
    dest: str | Path | None = None,
) -> Path:
    """Set block header MultilingualText Comment Text; write to dest (or overwrite).

    If no Comment MultilingualText exists, copies XML unchanged to dest.
    Returns destination path.
    """
    src = Path(xml_path).expanduser().resolve()
    out = Path(dest).expanduser().resolve() if dest else src
    out.parent.mkdir(parents=True, exist_ok=True)

    tree = ET.parse(src)
    root = tree.getroot()
    text_els = _find_header_comment_text_els(root)
    new_comment = (comment or "").strip()
    if text_els and new_comment:
        for el in text_els:
            el.text = new_comment
        tree.write(out, encoding="utf-8", xml_declaration=True)
    elif out != src:
        out.write_bytes(src.read_bytes())
    return out


def match_xml_for_block(block_name: str, xml_paths: list[str | Path]) -> Path | None:
    """Resolve a source XML path for ``block_name`` from job source_xmls."""
    name = (block_name or "").strip()
    if not name:
        return None
    exact: list[Path] = []
    soft: list[Path] = []
    for raw in xml_paths:
        p = Path(raw)
        if not p.is_file():
            continue
        stem = p.stem
        if stem == name or stem.endswith(f"_{name}") or stem.endswith(name):
            exact.append(p)
            continue
        try:
            xml_name = read_block_name_from_xml(p)
        except Exception:  # noqa: BLE001
            xml_name = ""
        if xml_name == name:
            exact.append(p)
        elif name.lower() in stem.lower():
            soft.append(p)
    if exact:
        return sorted(exact, key=lambda x: len(x.stem))[0]
    if soft:
        return sorted(soft, key=lambda x: abs(len(x.stem) - len(name)))[0]
    return None
