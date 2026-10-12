"""PLC change-set model: propose heuristics, KG apply, Openness import bundle."""

from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ChangeOpKind = Literal[
    "set_node_prop",
    "add_edge",
    "remove_edge",
    "set_block_comment",
    "annotate",
    "stage_xml_import",
    "rewrite_scl",
    "stage_scl_source",
]

ChangeSetStatus = Literal["proposed", "accepted", "rejected", "applied"]

OP_KINDS: frozenset[str] = frozenset(
    {
        "set_node_prop",
        "add_edge",
        "remove_edge",
        "set_block_comment",
        "annotate",
        "stage_xml_import",
        "rewrite_scl",
        "stage_scl_source",
    }
)


@dataclass
class PlcChangeOp:
    kind: ChangeOpKind
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlcChangeSet:
    id: str
    ops: list[PlcChangeOp] = field(default_factory=list)
    status: ChangeSetStatus = "proposed"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ops": [{"kind": o.kind, "payload": dict(o.payload)} for o in self.ops],
            "status": self.status,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlcChangeSet:
        ops = [
            PlcChangeOp(kind=o["kind"], payload=dict(o.get("payload") or {}))
            for o in data.get("ops") or []
            if o.get("kind") in OP_KINDS
        ]
        status = data.get("status") or "proposed"
        if status not in {"proposed", "accepted", "rejected", "applied"}:
            status = "proposed"
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            ops=ops,
            status=status,  # type: ignore[arg-type]
            notes=list(data.get("notes") or []),
        )


def _block_id(name: str) -> str:
    return f"Block::{name}" if name and not name.startswith("Block::") else name


def apply_changeset_to_kg(kg_json: dict[str, Any], changeset: PlcChangeSet) -> dict[str, Any]:
    """Apply change-set ops to a deep copy of KG JSON ``{nodes, edges}``."""
    out = copy.deepcopy(kg_json)
    nodes_by_id: dict[str, dict[str, Any]] = {
        n["id"]: n for n in out.get("nodes") or [] if isinstance(n, dict) and "id" in n
    }
    edges: list[dict[str, Any]] = [
        e for e in (out.get("edges") or []) if isinstance(e, dict)
    ]

    for op in changeset.ops:
        p = op.payload
        if op.kind == "set_node_prop":
            nid = str(p.get("node_id") or "")
            prop = str(p.get("prop") or "")
            if nid and prop and nid in nodes_by_id:
                props = nodes_by_id[nid].setdefault("props", {})
                props[prop] = p.get("value")
        elif op.kind == "add_edge":
            src = str(p.get("source") or "")
            tgt = str(p.get("target") or "")
            etype = str(p.get("type") or p.get("edge_type") or "DEPENDS_ON")
            if src and tgt:
                edges.append(
                    {
                        "source": src,
                        "target": tgt,
                        "type": etype,
                        "props": dict(p.get("props") or {}),
                    }
                )
        elif op.kind == "remove_edge":
            src = str(p.get("source") or "")
            tgt = str(p.get("target") or "")
            etype = str(p.get("type") or p.get("edge_type") or "")
            edges = [
                e
                for e in edges
                if not (
                    e.get("source") == src
                    and e.get("target") == tgt
                    and (not etype or e.get("type") == etype)
                )
            ]
        elif op.kind == "set_block_comment":
            name = str(p.get("block_name") or "")
            nid = _block_id(name)
            if nid not in nodes_by_id and name:
                nodes_by_id[nid] = {
                    "id": nid,
                    "type": "Block",
                    "props": {"name": name},
                }
            if nid in nodes_by_id:
                nodes_by_id[nid].setdefault("props", {})["comment"] = p.get("comment", "")
        elif op.kind == "annotate":
            nid = str(p.get("node_id") or _block_id(str(p.get("block_name") or "")))
            if nid and nid in nodes_by_id:
                props = nodes_by_id[nid].setdefault("props", {})
                notes = props.setdefault("annotations", [])
                if not isinstance(notes, list):
                    notes = [notes]
                    props["annotations"] = notes
                text = p.get("text") or p.get("annotation") or ""
                if text:
                    notes.append(text)
        elif op.kind in {"stage_xml_import", "rewrite_scl", "stage_scl_source"}:
            # Bundle-only; no KG mutation (CALLS edges are explicit add_edge ops).
            pass

    out["nodes"] = list(nodes_by_id.values())
    out["edges"] = edges
    return out


IMPORT_WRITE_KINDS: frozenset[str] = frozenset(
    {"rewrite_scl", "stage_scl_source", "stage_xml_import"}
)


def _block_name_from_node_id(nid: str) -> str:
    s = str(nid or "").strip()
    if s.startswith("Block::"):
        return s.split("::", 1)[-1]
    return s


def payload_block_name(payload: dict[str, Any] | None) -> str:
    p = payload or {}
    name = str(p.get("block_name") or "").strip()
    if name:
        return name
    return _block_name_from_node_id(str(p.get("node_id") or ""))


def helper_block_names_for_focus(cs: PlcChangeSet, focus: str) -> set[str]:
    """Helper FCs extracted *for* ``focus`` (decouple notes / new_block CALLS)."""
    focus = (focus or "").strip()
    helpers: set[str] = set()
    if not focus:
        return helpers
    prefix = f"optimize:decouple:{focus}->"
    for note in cs.notes:
        s = str(note)
        if s.startswith(prefix):
            helpers.add(s[len(prefix) :].split(":")[0].strip())
    new_blocks = {
        str(op.payload.get("block_name") or "")
        for op in cs.ops
        if op.payload.get("new_block") and op.payload.get("block_name")
    }
    for op in cs.ops:
        if op.kind != "add_edge":
            continue
        src = _block_name_from_node_id(str(op.payload.get("source") or ""))
        tgt = _block_name_from_node_id(str(op.payload.get("target") or ""))
        props = op.payload.get("props") if isinstance(op.payload.get("props"), dict) else {}
        evidence = str(props.get("evidence") or "")
        etype = str(op.payload.get("type") or op.payload.get("edge_type") or "")
        if src != focus or not tgt:
            continue
        if evidence == "decouple_extract" or (etype == "CALLS" and tgt in new_blocks):
            helpers.add(tgt)
    return {h for h in helpers if h and h != focus}


def filter_scl_diffs_for_focus(
    diffs: list[dict[str, Any]],
    cs: PlcChangeSet | dict[str, Any] | None,
    focus: str | None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """HITL SCL preview: focused block plus helper FCs extracted for it."""
    items = [d for d in diffs if isinstance(d, dict)]
    name = (focus or "").strip()
    if not name:
        return items[:limit]
    parsed: PlcChangeSet | None
    if isinstance(cs, PlcChangeSet):
        parsed = cs
    elif isinstance(cs, dict) and (cs.get("ops") or cs.get("id")):
        parsed = PlcChangeSet.from_dict(cs)
    else:
        parsed = None
    helpers = helper_block_names_for_focus(parsed, name) if parsed else set()
    allowed = {name} | helpers
    kept = [d for d in items if str(d.get("block") or "") in allowed]
    if not kept:
        kept = [d for d in items if str(d.get("block") or "") == name]
    return kept[:limit]


def filter_changeset_for_focus(cs: PlcChangeSet, focus: str | None) -> PlcChangeSet:
    """Keep ops for the focused block and helper FCs created for that block.

    Drops unrelated whole-project dead-block XML/comment/annotate ops.
    Empty ``focus`` returns the original set (whole-project confirm).
    """
    name = (focus or "").strip()
    if not name:
        return cs
    allowed = {name} | helper_block_names_for_focus(cs, name)
    kept: list[PlcChangeOp] = []
    for op in cs.ops:
        bname = payload_block_name(op.payload)
        if bname and bname in allowed:
            kept.append(op)
            continue
        if op.kind in {"add_edge", "remove_edge"}:
            src = _block_name_from_node_id(str(op.payload.get("source") or ""))
            tgt = _block_name_from_node_id(str(op.payload.get("target") or ""))
            if src in allowed and tgt in allowed:
                kept.append(op)
    return PlcChangeSet(id=cs.id, ops=kept, status=cs.status, notes=list(cs.notes))


def changeset_has_importable_writes(cs: PlcChangeSet) -> bool:
    """True when Openness would have XML/SCL to import (not annotate-only)."""
    for op in cs.ops:
        if op.kind in IMPORT_WRITE_KINDS:
            if op.kind == "stage_xml_import":
                if op.payload.get("xml_path"):
                    return True
            else:
                scl = str(op.payload.get("scl_text") or op.payload.get("scl") or "")
                if scl.strip():
                    return True
    return False


_XML_PATH_RE = re.compile(
    r"""(?P<path>(?:[A-Za-z]:)?[^\s"'<>]+\.xml)""",
    re.IGNORECASE,
)
_DEPENDS_TARGET_RE = re.compile(
    r"(?:依赖|depends(?:\s+on)?)\s*[:：]?\s*[`\"']?(?P<name>[A-Za-z_][\w.]*)",
    re.IGNORECASE,
)
_COMMENT_TEXT_RE = re.compile(
    r"(?:注释|comment)\s*[:：]\s*(?P<text>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def propose_changeset_from_message(
    message: str,
    block_name: str = "",
    job_context: dict[str, Any] | None = None,
) -> PlcChangeSet:
    """Deterministic heuristics → proposed change-set (no LLM)."""
    _ = job_context  # reserved for future path / block resolution
    text = (message or "").strip()
    ops: list[PlcChangeOp] = []
    notes: list[str] = []
    lower = text.lower()

    if "注释" in text or "comment" in lower:
        m = _COMMENT_TEXT_RE.search(text)
        comment = (m.group("text").strip() if m else text)
        # Strip leading keyword-only noise when no explicit colon form
        if not m:
            comment = re.sub(
                r"^(?:请|帮我)?(?:添加|设置|修改)?\s*(?:注释|comment)\s*[:：]?\s*",
                "",
                comment,
                flags=re.IGNORECASE,
            ).strip() or comment
        ops.append(
            PlcChangeOp(
                kind="set_block_comment",
                payload={"block_name": block_name, "comment": comment},
            )
        )
        notes.append("heuristic:set_block_comment")

    if "依赖" in text or "depends" in lower:
        tm = _DEPENDS_TARGET_RE.search(text)
        target_name = tm.group("name") if tm else ""
        if not target_name:
            # fallback: last identifier that is not the source block
            ids = re.findall(r"\b([A-Za-z_][\w.]*)\b", text)
            for cand in reversed(ids):
                if cand.lower() in {"depends", "on", "depend", "block"}:
                    continue
                if cand != block_name:
                    target_name = cand
                    break
        if block_name and target_name:
            ops.append(
                PlcChangeOp(
                    kind="add_edge",
                    payload={
                        "source": _block_id(block_name),
                        "target": _block_id(target_name),
                        "type": "DEPENDS_ON",
                    },
                )
            )
            notes.append("heuristic:add_edge:DEPENDS_ON")

    if "导入" in text or "import" in lower:
        xm = _XML_PATH_RE.search(text)
        if xm:
            ops.append(
                PlcChangeOp(
                    kind="stage_xml_import",
                    payload={
                        "xml_path": xm.group("path"),
                        "block_name": block_name,
                    },
                )
            )
            notes.append("heuristic:stage_xml_import")

    if not ops:
        notes.append("heuristic:no_match")

    return PlcChangeSet(
        id=uuid.uuid4().hex[:12],
        ops=ops,
        status="proposed",
        notes=notes,
    )


def write_import_bundle(
    dir: str | Path,
    changeset: PlcChangeSet,
    source_xml_paths: list[str | Path] | None = None,
) -> list[Path]:
    """Stage XML + metadata for Openness import.

    ``source_xml_paths`` is a **lookup pool** to resolve block→XML for comments.
    Only matched / explicitly ``stage_xml_import`` files are copied (not the whole pool),
    unless the changeset has no comment/stage ops (legacy: stage the pool as-is).
    Applies header Comment patches into SimaticML when possible.
    """
    from agents.plc.tia.optimize import write_optimize_plan
    from agents.plc.tia.xml_patch import (
        match_xml_for_block,
        patch_block_header_comment,
        read_block_name_from_xml,
    )

    bundle = Path(dir).expanduser().resolve()
    bundle.mkdir(parents=True, exist_ok=True)

    comments: dict[str, str] = {}
    patch_by_xml: dict[str, str] = {}
    staged: list[Path] = []
    wanted: list[Path] = []
    scl_files: dict[str, str] = {}
    lookup = [Path(p).expanduser() for p in (source_xml_paths or [])]

    for op in changeset.ops:
        if op.kind == "set_block_comment":
            name = str(op.payload.get("block_name") or "")
            if name:
                comments[name] = str(op.payload.get("comment") or "")
        elif op.kind == "stage_xml_import":
            xp = op.payload.get("xml_path")
            if xp:
                wanted.append(Path(str(xp)).expanduser())
            patch = op.payload.get("patch_comment")
            name = str(op.payload.get("block_name") or "")
            if patch and xp:
                patch_by_xml[str(Path(str(xp)).expanduser().resolve())] = str(patch)
            if patch and name:
                comments.setdefault(name, str(patch))
        elif op.kind in {"rewrite_scl", "stage_scl_source"}:
            name = str(op.payload.get("block_name") or "")
            scl = str(op.payload.get("scl_text") or op.payload.get("scl") or "")
            if name and scl.strip():
                scl_files[name] = scl

    pool = list(wanted) + lookup
    for name, comment in comments.items():
        matched = match_xml_for_block(name, pool)
        if matched is None:
            continue
        key = str(matched.resolve())
        patch_by_xml.setdefault(key, comment)
        if not any(
            Path(w).is_file() and Path(w).resolve() == matched.resolve() for w in wanted
        ):
            wanted.append(matched)

    # Legacy: no comment/stage ops → stage entire provided pool
    has_xml_ops = any(o.kind in {"set_block_comment", "stage_xml_import"} for o in changeset.ops)
    if not wanted and not has_xml_ops and lookup:
        wanted = list(lookup)

    seen: set[str] = set()
    for src in wanted:
        if not src.is_file():
            continue
        key = str(src.resolve())
        if key in seen:
            continue
        seen.add(key)
        dest = bundle / src.name
        comment = patch_by_xml.get(key)
        if not comment:
            # try by parsed block name
            try:
                bname = read_block_name_from_xml(src)
            except Exception:  # noqa: BLE001
                bname = src.stem
            comment = comments.get(bname) or comments.get(src.stem)
        if comment:
            patch_block_header_comment(src, comment, dest=dest)
        else:
            shutil.copy2(src, dest)
        staged.append(dest)

    (bundle / "changeset.json").write_text(
        json.dumps(changeset.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if comments:
        (bundle / "comments.json").write_text(
            json.dumps(comments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (bundle / "staged_xmls.json").write_text(
        json.dumps([str(p) for p in staged], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    scl_dir = bundle / "external_sources"
    staged_scls: list[str] = []
    if scl_files:
        scl_dir.mkdir(parents=True, exist_ok=True)
        for name, text in scl_files.items():
            safe = re.sub(r'[\\/:*?"<>|]', "_", name) + ".scl"
            dest = scl_dir / safe
            dest.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            staged_scls.append(str(dest))
    (bundle / "staged_scls.json").write_text(
        json.dumps(staged_scls, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_optimize_plan(bundle, changeset)
    return staged
