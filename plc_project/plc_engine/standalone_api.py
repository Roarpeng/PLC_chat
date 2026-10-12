"""Standalone Decoupled PLC Engine & API.

This module provides a 100% independent, cross-platform PLC analysis, translation,
and inspection API completely decoupled from Siemens TIA Portal. It runs on Linux,
macOS, Windows, Docker, and Web services without requiring TIA Portal installation
or licenses.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents.plc.tia.flgnet_fold import attach_folded, fold_project
from agents.plc.tia.ir import Block, BlockType, PlcProject, TagTable
from agents.plc.tia.kg import PlcKnowledgeGraph, build_knowledge_graph
from agents.plc.tia.review import run_review
from agents.plc.tia.scl import convert_project_to_scl, translate_block_to_scl
from agents.plc.tia.simaticml import extract_project, parse_block_xml, parse_tag_table_xml


def translate_simaticml_to_scl(xml_content_or_path: str | Path) -> str:
    """Translate a SimaticML XML block directly to structured SCL text.

    Accepts either an XML file path or raw XML content string.
    Zero TIA Portal dependency.
    """
    if isinstance(xml_content_or_path, (str, Path)) and Path(str(xml_content_or_path)).is_file():
        block = parse_block_xml(Path(str(xml_content_or_path)))
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as tf:
            tf.write(str(xml_content_or_path))
            temp_path = Path(tf.name)
        try:
            block = parse_block_xml(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    if block is None:
        raise ValueError("Provided XML is not a recognized SimaticML block export")

    return translate_block_to_scl(block)


def parse_simaticml_block_content(xml_content_or_path: str | Path) -> dict[str, Any]:
    """Parse block metadata, parameters, interfaces, and networks into structured JSON."""
    if isinstance(xml_content_or_path, (str, Path)) and Path(str(xml_content_or_path)).is_file():
        block = parse_block_xml(Path(str(xml_content_or_path)))
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as tf:
            tf.write(str(xml_content_or_path))
            temp_path = Path(tf.name)
        try:
            block = parse_block_xml(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    if block is None:
        raise ValueError("Provided XML is not a recognized SimaticML block export")

    return {
        "name": block.name,
        "number": block.number,
        "type": block.block_type.value if hasattr(block.block_type, "value") else str(block.block_type),
        "language": block.programming_language,
        "headerComment": block.header_comment,
        "isSafety": getattr(block, "is_safety", False),
        "networkCount": len(block.networks),
        "interfaceVariables": [
            {
                "name": v.name,
                "section": v.section.value if hasattr(v.section, "value") else str(v.section),
                "dataType": v.data_type,
                "comment": v.comment,
            }
            for v in block.interface
        ],
    }


def extract_tag_table_content(xml_content_or_path: str | Path) -> list[dict[str, Any]]:
    """Parse a PLC Tag Table XML into structured tag objects."""
    if isinstance(xml_content_or_path, (str, Path)) and Path(str(xml_content_or_path)).is_file():
        table = parse_tag_table_xml(Path(str(xml_content_or_path)))
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as tf:
            tf.write(str(xml_content_or_path))
            temp_path = Path(tf.name)
        try:
            table = parse_tag_table_xml(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    if table is None:
        return []

    return [
        {
            "name": t.name,
            "dataType": t.data_type,
            "logicalAddress": t.logical_address,
            "comment": t.comment,
        }
        for t in table.tags
    ]


def audit_block_content(xml_content_or_path: str | Path) -> list[dict[str, Any]]:
    """Perform offline code review, rule checks, and safety audits on a block."""
    if isinstance(xml_content_or_path, (str, Path)) and Path(str(xml_content_or_path)).is_file():
        block = parse_block_xml(Path(str(xml_content_or_path)))
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as tf:
            tf.write(str(xml_content_or_path))
            temp_path = Path(tf.name)
        try:
            block = parse_block_xml(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    if block is None:
        return []

    project = PlcProject(name="AuditProject", blocks={block.name: block})
    try:
        project = attach_folded(project)
    except Exception:
        pass
    kg = build_knowledge_graph(project)
    folded = fold_project(project)
    job = {
        "blocks": [
            {
                "name": block.name,
                "type": block.block_type.value if hasattr(block.block_type, "value") else str(block.block_type),
                "members": [f"{v.name} : {v.data_type}" for v in block.interface],
                "body_available": block.has_program_body(),
                "protected": block.is_protected(),
                "interface_only": block.is_interface_only(),
            }
        ],
        "folded_logic": folded,
        "knowledge_graph": kg.to_json(),
    }
    review_res = run_review(job)
    findings = review_res.get("findings") or []
    return [
        {
            "ruleId": f.get("rule", "rule"),
            "severity": f.get("severity", "info"),
            "message": f.get("title", ""),
            "detail": f.get("detail", ""),
            "evidence": f.get("evidence", []),
        }
        for f in findings
    ]


class StandalonePlcEngine:
    """High-level client class for offline standalone PLC intelligence."""

    def __init__(self, export_dir: str | Path | None = None) -> None:
        self.export_dir = Path(export_dir) if export_dir else None
        self._project: PlcProject | None = None
        if self.export_dir and self.export_dir.is_dir():
            self._project = extract_project(self.export_dir)

    @property
    def project(self) -> PlcProject | None:
        return self._project

    def load_project(self, export_dir: str | Path, project_name: str = "") -> PlcProject:
        """Load and parse an entire export directory offline."""
        self.export_dir = Path(export_dir)
        self._project = extract_project(self.export_dir, project_name=project_name)
        return self._project

    def get_blocks(self) -> list[dict[str, Any]]:
        """List all parsed blocks with summary information."""
        if self._project is None:
            return []
        return [
            {
                "name": b.name,
                "number": b.number,
                "type": b.block_type.value if hasattr(b.block_type, "value") else str(b.block_type),
                "language": b.programming_language,
                "networks": len(b.networks),
                "isSafety": getattr(b, "is_safety", False),
            }
            for b in self._project.blocks.values()
        ]

    def translate_to_scl(self, block_name: str | None = None) -> dict[str, str]:
        """Convert one or all blocks into structured SCL."""
        if self._project is None:
            return {}
        all_scl = convert_project_to_scl(self._project)
        if block_name:
            match = all_scl.get(block_name)
            return {block_name: match} if match else {}
        return all_scl

    def get_knowledge_graph(self) -> dict[str, Any]:
        """Build deterministic knowledge graph of function calls and variable usages."""
        if self._project is None:
            return {"nodes": [], "edges": []}
        return build_knowledge_graph(self._project).to_json()

    def export_scl_package(self, output_dir: str | Path) -> list[Path]:
        """Write all translated SCL files to a directory."""
        if self._project is None:
            return []
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        scl_map = convert_project_to_scl(self._project)
        emitted: list[Path] = []
        for name, text in scl_map.items():
            file_path = out / f"{name}.scl"
            file_path.write_text(text, encoding="utf-8")
            emitted.append(file_path)
        return emitted
