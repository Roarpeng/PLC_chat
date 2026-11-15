"""Import Agent (L) · TIA 块导出真解析 + 保真度分级 + 工位/执行器认领 + 开工前比对。

输入契约（锁定）：前端多文件上传 TIA「块导出」产物后提交 JSON——
``POST /api/processos/import/parse {project_name, blocks: [{name, xml_text, language?}]}``。
每个块 XML 用标准库 ``xml.etree`` 防御性解析（解析失败 → 该块 OPAQUE，绝不 500），
提取 ``Name/Number/ProgrammingLanguage/SecondaryType`` 与接口 Member 清单。

保真度分级（诚实保守，写死在此、不因调用方愿望升级）：

- ``PROTECTED`` — 块名以 ``F_``/``FDB`` 开头（Fail-Safe 命名约定），或 XML 携带
  SafetyLanguage 元素/属性、命名空间 URI 含 ``Safety``。只读零修改（PLAN §11
  SAFETY_SCOPE_BLOCKED 域；认领映射一律 403 拒绝）。
- ``EXACT`` — 块名匹配 AF 生成模式（``FB_EM_*``/``FB_CM_*``/``FB_U_*``/``iFB_*``/
  ``OB_Main``/``Main``：我们自己的 codegen 产出过的结构）且接口 Member 提取 ≥1 条；
  SCL 块还要求 StructuredText/Access 正文提取出至少一个可解析信号访问——提取不完整
  则降 ``PARTIAL``。
- ``PARTIAL`` — 常规用户块：元数据 + 接口可读，语义重建不完全（默认诚实档）。
- ``OPAQUE`` — XML 解析失败或完全提取不到接口信息；认领时落
  ``ownership=MANAGED_NATIVE_OVERRIDE`` 黑盒标记（PLAN §3.2B，禁止 AI 重生成/覆盖）。

claim（认领映射）把块指派为 station/component/em/cm/ob/other 并在 ObjectRegistry
落对象（``attributes.driver_hint`` 等），按确定性规则建边：component ``part_of``
station；物理工位 ``maps_to`` AF EM（PLAN §0.2：一个工位可映射多个 EM）；同批同工位
的 cm ``part_of`` em。``ob``/``other`` 使用开放 kind（``ob``/``native_block``），
registry 的 graph_of 兜底归 EvidenceGraph——导入块是软件证据而非工艺节点，这是当前
的诚实归属，不虚构 AfGraph 成员身份。

baseline-check（开工前比对，PLAN §4）：无任何基线 → ``UNVERIFIED_ONLINE`` + 提示
「登记 B2 后可比对」；有 B2 → ``BaselineService.compare`` 结果透传，并可对上传的
逐块 sha256 与 B2 block_manifest 做块级三方差异预检。

Persistence：``db`` 给定时写 namespace ``"import_parses"``/``"import_claims"``
（每次操作一条短命连接 + RLock；``db=None`` 纯内存，no-db 应用不触碰默认 SQLite 路径）。
"""
from __future__ import annotations

import contextlib
import threading
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from processos.registry import ObjectRegistry
from processos.safety import SafetyError
from processos.store.db import JsonDao, open_db, utcnow

PARSE_NAMESPACE = "import_parses"
CLAIM_NAMESPACE = "import_claims"

FIDELITIES = ("EXACT", "PARTIAL", "OPAQUE", "PROTECTED")

#: AF 生成命名模式——我们 codegen 产出过的块结构，接口完整时可声明 EXACT。
_AF_NAME_PATTERNS = ("FB_EM_", "FB_CM_", "FB_U_", "iFB_", "OB_Main")

#: claim target_kind -> registry kind（ob/other 见模块 docstring 的归属说明）。
_CLAIM_KINDS: dict[str, str] = {
    "station": "station",
    "component": "component",
    "em": "af_em",
    "cm": "af_cm",
    "ob": "ob",
    "other": "native_block",
}


class ParseError(ValueError):
    """Block-level parse failure — becomes an OPAQUE node, never a 500."""


# ---------- namespace-insensitive XML helpers (SimaticML carries xmlns) ----------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _local(c.tag) == name]


def _first_child(elem: ET.Element, name: str) -> ET.Element | None:
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _text_of(attr: ET.Element, name: str) -> str:
    child = _first_child(attr, name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _root_of(xml_text: str) -> ET.Element:
    text = xml_text.strip().lstrip("﻿")  # TIA 导出带 UTF-8 BOM
    if not text:
        raise ParseError("empty xml")
    return ET.fromstring(text)


def _has_safety_markers(root: ET.Element) -> bool:
    """保守判定 F/Safety 域：SafetyLanguage 元素/属性名，或 Safety 命名空间 URI。"""
    for elem in root.iter():
        if _local(elem.tag) == "SafetyLanguage":
            return True
        for key, value in elem.attrib.items():
            if "Safety" in _local(key) or ("http" in value and "Safety" in value):
                return True
    return False


def _interface_members(block: ET.Element) -> list[dict[str, str]] | None:
    """Extract interface Members from AttributeList/Interface.

    Returns ``None`` when no interface information is extractable (→ OPAQUE).
    Handles both shapes seen in the wild: nested ``<Sections>`` elements, and
    escaped-XML ``Interface.text`` (re-parsed defensively).
    """
    attr = _first_child(block, "AttributeList")
    if attr is None:
        return None
    iface = _first_child(attr, "Interface")
    if iface is None:
        return None
    sections = _first_child(iface, "Sections")
    if sections is None and iface.text and iface.text.strip().startswith("<"):
        try:
            inner = ET.fromstring(iface.text.strip())
        except ET.ParseError:
            return None
        sections = inner if _local(inner.tag) == "Sections" else _first_child(inner, "Sections")
    if sections is None:
        return None
    members: list[dict[str, str]] = []
    for section in sections:
        if _local(section.tag) != "Section":
            continue
        section_name = section.get("Name", "")
        for member in section:
            if _local(member.tag) != "Member":
                continue
            members.append({
                "name": member.get("Name", ""),
                "datatype": member.get("Datatype", ""),
                "section": section_name,
            })
    return members


def _scl_accessed_signals(block: ET.Element) -> list[str]:
    """Signal names referenced from StructuredText/Access/Symbol/Component bodies."""
    seen: list[str] = []
    for elem in block.iter():
        if _local(elem.tag) != "Access":
            continue
        symbol = _first_child(elem, "Symbol")
        if symbol is None:
            continue
        for comp in symbol:
            if _local(comp.tag) == "Component":
                name = comp.get("Name", "")
                if name and name not in seen:
                    seen.append(name)
    return seen


def _grade(block_name: str, root: ET.Element, block: ET.Element,
           members: list[dict[str, str]] | None) -> tuple[str, str]:
    """Fidelity grading (see module docstring; conservative, never upgraded on wish)."""
    upper = block_name.upper()
    if upper.startswith(("F_", "FDB")) or _has_safety_markers(root):
        return "PROTECTED", "F/Safety 域（F_ 前缀或 Safety 标记）：只读零修改"
    if members is None:
        return "OPAQUE", "未提取到接口信息：仅块名可见，按黑盒处理"
    if not members:
        return "OPAQUE", "接口 Sections 为空：无信号清单"
    af_named = upper.startswith(_AF_NAME_PATTERNS) or block_name == "Main"
    attr = _first_child(block, "AttributeList")
    language = (_text_of(attr, "ProgrammingLanguage") if attr is not None else "").upper()
    if af_named:
        if language == "SCL" and not _scl_accessed_signals(block):
            return "PARTIAL", "AF 命名匹配，但 SCL 正文 Access 提取不完整：不声称行为等价"
        return "EXACT", "AF 生成模式命名 + 接口结构完整：模式/接口可重建"
    return "PARTIAL", "常规用户块：元数据 + 接口可读，语义重建不完全"


def _parse_one(name: str, xml_text: str, language_hint: str) -> dict[str, Any]:
    """Parse one block XML defensively; any failure degrades to an OPAQUE node."""
    node: dict[str, Any] = {
        "node_id": "", "block_name": name, "block_type": "", "number": "",
        "language": language_hint, "fidelity": "OPAQUE", "signals": "UNKNOWN",
        "note": "",
    }
    try:
        root = _root_of(xml_text)
        block = next((c for c in root if _local(c.tag).startswith("SW.Blocks.")), None)
        if block is None:
            raise ParseError("no SW.Blocks.* element")
        attr = _first_child(block, "AttributeList")
        block_name = _text_of(attr, "Name") if attr is not None else ""
        if block_name:
            node["block_name"] = block_name
        node["block_type"] = _local(block.tag).rsplit(".", 1)[-1]
        node["number"] = _text_of(attr, "Number") if attr is not None else ""
        lang = _text_of(attr, "ProgrammingLanguage") if attr is not None else ""
        node["language"] = (language_hint or lang).upper()
        secondary = _text_of(attr, "SecondaryType") if attr is not None else ""
        if secondary:
            node["secondary_type"] = secondary
        members = _interface_members(block)
        fidelity, note = _grade(node["block_name"], root, block, members)
        node["fidelity"] = fidelity
        node["note"] = note
        if fidelity != "OPAQUE" and members:
            node["signals"] = members
    except (ET.ParseError, ParseError, ValueError, TypeError, AttributeError) as exc:
        node["fidelity"] = "OPAQUE"
        node["signals"] = "UNKNOWN"
        node["note"] = f"XML 解析失败（{type(exc).__name__}）：按黑盒保留，不猜测结构"
    return node


class ImportParseService:
    """Parse TIA block exports, grade fidelity, claim-map into the registry.

    ``trace`` is a TraceabilityService (or the app's thread-affinity adapter over
    one); ``None`` falls back to a standalone in-memory registry so the routes
    stay mountable on a bare app. ``baselines`` drives baseline-check; ``None``
    keeps that endpoint honest about no baseline service being configured.
    """

    def __init__(self, trace: Any = None, baselines: Any = None,
                 db: str | None = None) -> None:
        self._registry: ObjectRegistry = getattr(trace, "registry", None) or ObjectRegistry()
        self._trace = trace
        self._baselines = baselines
        self._db = None if db is None else str(db)
        self._lock = threading.RLock()
        self._parses: dict[str, dict[str, Any]] = {}   # memory fallback (db=None)
        self._claims: dict[str, dict[str, Any]] = {}

    # ---------- persistence (short-lived connection per operation) ----------

    @contextmanager
    def _dao(self, namespace: str) -> Iterator[JsonDao | None]:
        if self._db is None:
            yield None
            return
        with contextlib.closing(open_db(self._db)) as conn:
            yield JsonDao(conn, namespace)

    # ---------- parse ----------

    def parse(self, project_name: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        """Parse uploaded block XMLs; per-block failures stay OPAQUE nodes."""
        nodes = [_parse_one(str(b.get("name", f"block_{i + 1}")),
                            str(b.get("xml_text", "")),
                            str(b.get("language", "")))
                 for i, b in enumerate(blocks)]
        for i, node in enumerate(nodes):
            node["node_id"] = f"node_{i + 1:03d}"
        stats = {f: sum(1 for n in nodes if n["fidelity"] == f) for f in FIDELITIES}
        doc = {
            "parse_id": "PARSE_" + uuid.uuid4().hex[:10].upper(),
            "project_name": project_name,
            "parsed_at": utcnow(),
            "nodes": nodes,
            "stats": stats,
        }
        with self._lock, self._dao(PARSE_NAMESPACE) as dao:
            if dao is not None:
                dao.put(doc["parse_id"], "parse", doc)
            else:
                self._parses[doc["parse_id"]] = doc
        return doc

    def get_parse(self, parse_id: str) -> dict[str, Any] | None:
        with self._dao(PARSE_NAMESPACE) as dao:
            if dao is not None:
                return dao.get(parse_id)
        return self._parses.get(parse_id)

    # ---------- claim ----------

    def _station_for(self, claim_local: dict[str, str], station_name: str):
        """Find-or-create a station object; claim-local first, then registry names."""
        if not station_name:
            return None
        oid = claim_local.get("station:" + station_name)
        if oid:
            return self._registry.get(oid)
        existing = self._registry.find_by_name(station_name)
        if existing is not None:
            claim_local["station:" + station_name] = existing.object_id
            return existing
        obj = self._registry.register("station", station_name, {"name": station_name})
        claim_local["station:" + station_name] = obj.object_id
        return obj

    def claim(self, parse_id: str, mappings: list[dict[str, Any]],
              project_id: str = "") -> dict[str, Any]:
        """Register claimed blocks as registry objects with deterministic edges.

        PROTECTED blocks refuse every editable mapping (403 SAFETY_SCOPE_BLOCKED);
        OPAQUE blocks land with ``ownership=MANAGED_NATIVE_OVERRIDE``. Unknown
        project ids are the caller's (route) concern; here an empty ``project_id``
        means a standalone structure tree (attached later).
        """
        parse = self.get_parse(parse_id)
        if parse is None:
            raise KeyError(f"unknown parse {parse_id}")
        nodes = {n["block_name"]: n for n in parse["nodes"]}

        objects: list[dict[str, Any]] = []
        unmapped: list[dict[str, str]] = []
        claimed: set[str] = set()
        claim_local: dict[str, str] = {}   # station name / em object ids within this claim
        registry = self._registry

        for m in mappings:
            block_name = str(m.get("block_name", ""))
            target = str(m.get("target_kind", ""))
            node = nodes.get(block_name)
            if node is None:
                unmapped.append({"block_name": block_name, "reason": "not in parse"})
                continue
            if block_name in claimed:
                unmapped.append({"block_name": block_name, "reason": "duplicate mapping"})
                continue
            if target not in _CLAIM_KINDS:
                raise ValueError(f"unknown target_kind {target!r}")
            if node["fidelity"] == "PROTECTED":
                # fail-closed：安全块不允许任何可编辑结构映射（§11 独立流程）
                raise SafetyError(
                    "SAFETY_SCOPE_BLOCKED",
                    f"块 {block_name} 属 F/Safety 保护域，禁止映射为可编辑对象；"
                    "安全块保持只读，需走独立安全流程",
                    details={"block_name": block_name, "target_kind": target,
                             "fidelity": "PROTECTED"},
                    http_status=403,
                )
            claimed.add(block_name)
            kind = _CLAIM_KINDS[target]  # route-level Literal validated
            display_name = str(m.get("display_name") or block_name)
            attributes: dict[str, Any] = {
                "block_name": block_name,
                "language": node.get("language", ""),
                "fidelity": node["fidelity"],
                "parse_id": parse_id,
                "block_number": node.get("number", ""),
            }
            if m.get("driver_hint"):
                attributes["driver_hint"] = str(m["driver_hint"])
            if node["fidelity"] == "OPAQUE":
                attributes["ownership"] = "MANAGED_NATIVE_OVERRIDE"
                attributes["override_note"] = "结构不可解析：受控黑盒，禁止 AI 重生成/自动覆盖"
            if project_id:
                attributes["project_id"] = project_id
            obj = registry.register(kind, display_name, attributes)
            objects.append({"object_id": obj.object_id, "block_name": block_name,
                            "kind": kind})

            station_name = str(m.get("station_name") or "")
            station = self._station_for(claim_local, station_name) if station_name else None
            if target == "component" and station is not None:
                registry.relate(obj.object_id, "part_of", station.object_id)
            elif target == "em":
                if station is not None:
                    registry.relate(station.object_id, "maps_to", obj.object_id)  # §0.2
                if station_name:
                    claim_local["em:" + station_name] = obj.object_id
            elif target == "cm":
                em_oid = claim_local.get("em:" + station_name) if station_name else None
                if em_oid:
                    registry.relate(obj.object_id, "part_of", em_oid)

        for node in parse["nodes"]:
            if node["block_name"] not in claimed:
                unmapped.append({"block_name": node["block_name"], "reason": "not claimed"})

        doc = {
            "claim_id": "CLAIM_" + uuid.uuid4().hex[:10].upper(),
            "parse_id": parse_id,
            "project_id": project_id or None,
            "objects": objects,
            "unmapped": unmapped,
            "created_at": utcnow(),
        }
        with self._lock, self._dao(CLAIM_NAMESPACE) as dao:
            if dao is not None:
                dao.put(doc["claim_id"], "claim", doc)
            else:
                self._claims[doc["claim_id"]] = doc
        return doc

    # ---------- baseline-check (开工前比对，PLAN §4) ----------

    def baseline_check(self, project_id: str,
                       block_hashes: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Three-state pre-work comparison over the BaselineService ledger.

        - no baseline records at all → ``UNVERIFIED_ONLINE`` + first-B2 note;
        - otherwise → ``BaselineService.compare`` passed through verbatim, plus a
          block-level diff when both an uploaded per-block hash list and a B2
          ``block_manifest`` exist (honest: missing either side → ``None``).
        """
        if self._baselines is None:
            return {"project_id": project_id, "verdict": "UNVERIFIED_ONLINE",
                    "note": "未配置基线服务（无持久化存储）：现场 PLC 状态未知",
                    "compare": None, "block_diff": None}
        records = self._baselines.baselines(project_id)
        if not records:
            return {"project_id": project_id, "verdict": "UNVERIFIED_ONLINE",
                    "note": "新导入，无历史基线，登记 B2 后可比对",
                    "compare": None, "block_diff": None}
        compare = self._baselines.compare(project_id)
        b2 = compare.get("latest_b2") or {}
        manifest = b2.get("block_manifest") or {}
        block_diff: dict[str, list[str]] | None = None
        if block_hashes and manifest:
            uploaded = {str(h.get("block_name", "")): str(h.get("sha256", ""))
                        for h in block_hashes}
            block_diff = {
                "matched": sorted(n for n in uploaded if n in manifest and uploaded[n] == manifest[n]),
                "changed": sorted(n for n in uploaded if n in manifest and uploaded[n] != manifest[n]),
                "added_in_upload": sorted(n for n in uploaded if n not in manifest),
                "missing_from_upload": sorted(n for n in manifest if n not in uploaded),
            }
        return {"project_id": project_id, "verdict": compare["verdict"],
                "note": "", "compare": compare, "block_diff": block_diff}
