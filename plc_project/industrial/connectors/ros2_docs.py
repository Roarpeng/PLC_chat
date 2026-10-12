"""ROS2 documentation connector — read-only stub with fake catalog.

Also provides :class:`Ros2WorkspaceConnector`, a read-only scanner over a
ROS2 workspace on disk (package.xml + msg/srv/action interfaces) that does
not require a ROS installation or a running DDS domain.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class DocEntry:
    id: str
    title: str
    package: str
    url: str
    summary: str
    tags: tuple[str, ...] = ()


class Ros2DocsConnector(Protocol):
    """Read-only interface for ROS2 package / interface docs."""

    def list_packages(self) -> list[str]: ...

    def search(self, query: str, *, limit: int = 10) -> list[DocEntry]: ...

    def get(self, doc_id: str) -> DocEntry | None: ...


FAKE_CATALOG: list[DocEntry] = [
    DocEntry(
        id="ros2_nav2",
        title="Nav2 Navigation Stack",
        package="nav2_bringup",
        url="https://docs.ros.org/en/humble/Tutorials/Navigation.html",
        summary="Lifecycle-managed navigation stack for differential and omnidirectional robots.",
        tags=("navigation", "humble"),
    ),
    DocEntry(
        id="ros2_moveit",
        title="MoveIt 2 Motion Planning",
        package="moveit2",
        url="https://moveit.picknik.ai/",
        summary="Motion planning, kinematics, and manipulation framework for ROS 2.",
        tags=("manipulation", "planning"),
    ),
    DocEntry(
        id="ros2_control",
        title="ros2_control Framework",
        package="ros2_control",
        url="https://control.ros.org/",
        summary="Hardware interfaces, controllers, and real-time robot control abstractions.",
        tags=("control", "hardware"),
    ),
]


class FakeRos2DocsConnector:
    """In-memory fake catalog implementing Ros2DocsConnector."""

    def list_packages(self) -> list[str]:
        return sorted({e.package for e in FAKE_CATALOG})

    def search(self, query: str, *, limit: int = 10) -> list[DocEntry]:
        q = query.lower()
        hits = [
            e
            for e in FAKE_CATALOG
            if q in e.title.lower()
            or q in e.summary.lower()
            or q in e.package.lower()
            or any(q in t for t in e.tags)
        ]
        return hits[:limit]

    def get(self, doc_id: str) -> DocEntry | None:
        for e in FAKE_CATALOG:
            if e.id == doc_id:
                return e
        return None

    def as_dict(self, entry: DocEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "title": entry.title,
            "package": entry.package,
            "url": entry.url,
            "summary": entry.summary,
            "tags": list(entry.tags),
            "readonly": True,
        }


# ---------------------------------------------------------------------------
# Ros2WorkspaceConnector — real on-disk workspace scanning (read-only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ros2Package:
    """A ROS2 package discovered in a workspace."""

    name: str
    version: str = ""
    description: str = ""
    path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "path": self.path,
        }


def _local_name(tag: str) -> str:
    """Strip an XML namespace so ``{uri}name`` -> ``name``."""
    return tag.rsplit("}", 1)[-1]


def _child_text(elem: Any, tag: str) -> str:
    for child in elem:
        if _local_name(child.tag) == tag:
            return " ".join(child.itertext()).strip()
    return ""


def _parse_package_xml(xml_path: Path) -> Ros2Package | None:
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError):
        return None
    name = _child_text(root, "name")
    if not name:
        return None
    return Ros2Package(
        name=name,
        version=_child_text(root, "version"),
        description=_child_text(root, "description"),
        path=str(xml_path.parent),
    )


_CONST_RE = re.compile(r"^(?P<type>\S+)\s+(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*(?P<value>.*)$")
_FIELD_RE = re.compile(r"^(?P<type>.+?)\s+(?P<name>[A-Za-z_]\w*)(?:\s*=\s*(?P<default>.+))?$")


def _split_comment(line: str) -> tuple[str, str]:
    if "#" in line:
        code, comment = line.split("#", 1)
        return code.rstrip(), comment.strip()
    return line.rstrip(), ""


def _parse_interface_line(line: str) -> dict[str, Any]:
    """Parse one ROS2 interface definition line into a small owned dict."""
    code, comment = _split_comment(line)
    code = code.strip()
    if not code:
        return {"kind": "blank", "comment": comment}
    if code == "---":
        return {"kind": "separator", "comment": comment}
    const = _CONST_RE.match(code)
    if const:
        return {
            "kind": "constant",
            "type": const.group("type"),
            "name": const.group("name"),
            "value": const.group("value").strip(),
            "comment": comment,
        }
    field = _FIELD_RE.match(code)
    if field:
        return {
            "kind": "field",
            "type": field.group("type").strip(),
            "name": field.group("name"),
            "default": (field.group("default") or "").strip(),
            "comment": comment,
        }
    return {"kind": "raw", "line": code, "comment": comment}


class Ros2WorkspaceConnector:
    """Read-only scanner over a ROS2 workspace on disk (no ROS runtime)."""

    _INTERFACE_KINDS = ("msg", "srv", "action")
    _SECTION_NAMES = {
        "srv": ("request", "response"),
        "action": ("goal", "result", "feedback"),
    }

    def list_packages(self, workspace_root: str) -> list[dict[str, Any]]:
        """Recursively find package.xml files and return parsed packages."""
        root = Path(workspace_root)
        seen: dict[str, Ros2Package] = {}
        for xml_path in sorted(root.rglob("package.xml")):
            pkg = _parse_package_xml(xml_path)
            if pkg is not None:
                seen.setdefault(pkg.name, pkg)
        return [pkg.as_dict() for pkg in sorted(seen.values(), key=lambda p: p.name)]

    def _find_package_dir(self, workspace_root: str, package_name: str) -> Path | None:
        root = Path(workspace_root)
        for xml_path in sorted(root.rglob("package.xml")):
            pkg = _parse_package_xml(xml_path)
            if pkg is not None and pkg.name == package_name:
                return xml_path.parent
        return None

    @staticmethod
    def _rel_files(package_dir: Path, subdir: str) -> list[str]:
        d = package_dir / subdir
        if not d.is_dir():
            return []
        return sorted(
            str(p.relative_to(package_dir)).replace("\\", "/")
            for p in d.rglob("*")
            if p.is_file()
        )

    def inspect_package(self, workspace_root: str, package_name: str) -> dict[str, Any] | None:
        """Return include/msg/srv/action contents and the launch file list."""
        package_dir = self._find_package_dir(workspace_root, package_name)
        if package_dir is None:
            return None
        pkg = _parse_package_xml(package_dir / "package.xml")
        launch = [
            str(p.relative_to(package_dir)).replace("\\", "/")
            for p in sorted(package_dir.rglob("*"))
            if p.is_file() and p.name.endswith((".launch.py", ".launch.xml", ".launch.yaml", ".launch"))
        ]
        return {
            "name": pkg.name,
            "version": pkg.version,
            "description": pkg.description,
            "path": str(package_dir),
            "include": self._rel_files(package_dir, "include"),
            "msg": self._rel_files(package_dir, "msg"),
            "srv": self._rel_files(package_dir, "srv"),
            "action": self._rel_files(package_dir, "action"),
            "launch": launch,
        }

    def _resolve_interface(self, package_dir: Path, interface_name: str) -> tuple[str, Path] | None:
        base = (interface_name or "").strip()
        for kind in self._INTERFACE_KINDS:
            if base.endswith("." + kind):
                base = base[: -(len(kind) + 1)]
                break
        base = Path(base).name  # strip any "msg/" / "srv/" prefix
        for kind in self._INTERFACE_KINDS:
            candidate = package_dir / kind / f"{base}.{kind}"
            if candidate.is_file():
                return kind, candidate
        return None

    def show_interface(
        self, workspace_root: str, package_name: str, interface_name: str
    ) -> dict[str, Any] | None:
        """Parse a msg/srv/action file into field lines (with comments)."""
        package_dir = self._find_package_dir(workspace_root, package_name)
        if package_dir is None:
            return None
        resolved = self._resolve_interface(package_dir, interface_name)
        if resolved is None:
            return None
        kind, path = resolved
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        lines: list[dict[str, Any]] = []
        sections: dict[str, list[dict[str, Any]]] = {}
        section_names = self._SECTION_NAMES.get(kind)
        current_section = section_names[0] if section_names else None
        section_idx = 0
        for raw in text.splitlines():
            parsed = _parse_interface_line(raw)
            lines.append(parsed)
            if section_names is None:
                continue
            if parsed["kind"] == "separator":
                section_idx += 1
                current_section = section_names[section_idx] if section_idx < len(section_names) else None
                continue
            if current_section is not None:
                sections.setdefault(current_section, []).append(parsed)

        result: dict[str, Any] = {
            "package": package_name,
            "name": path.stem,
            "kind": kind,
            "file": str(path.relative_to(package_dir)).replace("\\", "/"),
            "fields": [p for p in lines if p["kind"] in {"field", "constant"}],
            "lines": lines,
        }
        if section_names is not None:
            for name in section_names:
                sections.setdefault(name, [])
            result["sections"] = sections
        return result
