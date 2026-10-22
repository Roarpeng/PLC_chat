"""Knowledge Graph builder — PLC-IR -> typed graph for agent queries.

Node types: Project, Block, Variable, Network, TagTable, Tag,
            Device, TechnologyObject, Alarm
Edge types:
  CONTAINS, HAS_INTERFACE,
  CALLS       — OB/FC/FB calls another block (CallInfo)
  USES        — block uses a DB / instance DB (global DB root or Instance)
  INSTANCE_OF — instance DB typed from an FB
  TYPED_AS    — Variable (or owning Block) member data_type is another FB/FC/UDT/DB
                (Siemens multi-instance nesting; not CALLS, not instance-DB INSTANCE_OF)
  READS / WRITES — signal-level access
  NEXT        — successive callees in one caller
  HAS_DEVICE  — Project owns a hardware Device (HardwareDevice)
  RUNS_TO     — Device runs a TechnologyObject (axis/cam/...; best-effort path ownership)
  HAS_ALARM   — Device owns an Alarm (text list / ProDiag)

Association model (engineer view):
  Main --CALLS--> ce (FC)
  Main --USES-->  ceD (GlobalDB parameter store)
  ce   --USES-->  IEC_Counter_0_DB (CTU instance)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.plc.tia.ir import (
    Access,
    AccessScope,
    Block,
    BlockType,
    HardwareDevice,
    InterfaceSection,
    Network,
    PlcProject,
    Variable,
)
from agents.plc.tia.parts import canon_part
from agents.plc.tia.typed_as import (
    NEST_SECTIONS,
    TYPED_AS,
    is_primitive_type,
    strip_type_name,
)

#: Parts whose primary Access pin writes state (coils, assignments, resets)
WRITE_PARTS = {
    "Coil",
    "NegCoil",
    "NotCoil",
    "Move",
    "Assign",
    "Reset",
    "Set",
    "Save",
}

MOVE_PARTS = {"Move", "Assign", "Move_Bool", "Move_Word", "Move_DWord", "Move_Real"}
CALL_PARTS = {"Call", "CallPart"}
INSTANCE_BOX_PARTS = {
    "CTU",
    "CTD",
    "CTUD",
    "TON",
    "TOF",
    "TP",
    "TONR",
    "SR",
    "RS",
    "R_TRIG",
    "F_TRIG",
    "P_TRIG",
}
#: Move / Call / timer-counter pins that write an IdentCon target
WRITE_PINS = {
    "out",
    "out1",
    "out2",
    "out3",
    "OUT",
    "OUT1",
    "CV",
    "Q",
    "QU",
    "QD",
    "ET",
}


@dataclass
class GraphNode:
    id: str
    type: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlcKnowledgeGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    _edge_keys: set[tuple[str, str, str]] = field(default_factory=set, repr=False)

    def add_node(self, node_id: str, node_type: str, **props: Any) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].props.update({k: v for k, v in props.items() if v is not None})
        else:
            self.nodes[node_id] = GraphNode(id=node_id, type=node_type, props=props)

    def add_edge(self, source: str, target: str, edge_type: str, **props: Any) -> None:
        key = (source, target, edge_type)
        if key in self._edge_keys:
            # Merge props onto existing edge of same triple
            for edge in self.edges:
                if edge.source == source and edge.target == target and edge.type == edge_type:
                    edge.props.update({k: v for k, v in props.items() if v})
                    return
            return
        self._edge_keys.add(key)
        self.edges.append(GraphEdge(source=source, target=target, type=edge_type, props=props))

    # -- queries -----------------------------------------------------------
    def blocks(self) -> list[GraphNode]:
        return [n for n in self.nodes.values() if n.type == "Block"]

    def out_edges(self, node_id: str, edge_type: str | None = None) -> list[GraphEdge]:
        return [
            e for e in self.edges if e.source == node_id and (edge_type is None or e.type == edge_type)
        ]

    def in_edges(self, node_id: str, edge_type: str | None = None) -> list[GraphEdge]:
        return [
            e for e in self.edges if e.target == node_id and (edge_type is None or e.type == edge_type)
        ]

    def callers_of(self, block_name: str) -> list[str]:
        return sorted(
            {
                e.source.split("::", 1)[1]
                for e in self.in_edges(f"Block::{block_name}", "CALLS")
                if "::" in e.source
            }
        )

    def callees_of(self, block_name: str) -> list[str]:
        return sorted(
            {
                e.target.split("::", 1)[1]
                for e in self.out_edges(f"Block::{block_name}", "CALLS")
                if "::" in e.target
            }
        )

    def users_of(self, block_name: str) -> list[str]:
        return sorted(
            {
                e.source.split("::", 1)[1]
                for e in self.in_edges(f"Block::{block_name}", "USES")
                if "::" in e.source
            }
        )

    def uses_of(self, block_name: str) -> list[str]:
        return sorted(
            {
                e.target.split("::", 1)[1]
                for e in self.out_edges(f"Block::{block_name}", "USES")
                if "::" in e.target
            }
        )

    def readers_of_tag(self, tag_ref: str) -> list[str]:
        return sorted(
            {
                e.source.split("::", 1)[1]
                for e in self.in_edges(f"Tag::{tag_ref}", "READS")
                if "::" in e.source
            }
        )

    def writers_of_tag(self, tag_ref: str) -> list[str]:
        return sorted(
            {
                e.source.split("::", 1)[1]
                for e in self.in_edges(f"Tag::{tag_ref}", "WRITES")
                if "::" in e.source
            }
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "props": n.props} for n in self.nodes.values()
            ],
            "edges": [
                {"source": e.source, "target": e.target, "type": e.type, "props": e.props}
                for e in self.edges
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PlcKnowledgeGraph:
        graph = cls()
        for node in data.get("nodes") or []:
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            graph.add_node(str(node.get("id")), str(node.get("type") or "Node"), **props)
        for edge in data.get("edges") or []:
            props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
            graph.add_edge(
                str(edge.get("source")),
                str(edge.get("target")),
                str(edge.get("type") or "RELATED"),
                **props,
            )
        return graph


def _access_ref(access: Access) -> str:
    """Canonical reference string for accesses."""
    if access.scope == AccessScope.LOCAL:
        return f"#{access.root}" + (("." + ".".join(access.path)) if access.path else "")
    if access.path:
        return f"{access.root}.{'.'.join(access.path)}"
    return access.root or access.raw or access.absolute


def _access_bound_to_pin(network: Network, part_uuid: str, pin: str) -> Access | None:
    """Resolve Access on a pin regardless of wire direction (in or out)."""
    for wire in network.wires:
        for endpoint in wire.endpoints:
            if endpoint.kind != "namecon" or endpoint.uuid != part_uuid or endpoint.pin != pin:
                continue
            for other in wire.endpoints:
                if other.kind == "identcon":
                    return network.access_parts.get(other.uuid)
    return None


def _pin_source_access(network: Network, part_uuid: str, pin: str) -> Access | None:
    """Resolve the Access feeding a part pin via IdentCon → NameCon wiring."""
    for wire in network.wires:
        for ep in wire.targets:
            if ep.kind == "namecon" and ep.uuid == part_uuid and ep.pin == pin:
                src = wire.source
                if src and src.kind == "identcon":
                    return network.access_parts.get(src.uuid)
    return None


def _call_params_from_templates(template_values: dict[str, str]) -> list[dict[str, str]]:
    """Openness CallInfo Parameter → name / section / type (for interface enrichment)."""
    params: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, section in template_values.items():
        if not key.startswith("__sec__"):
            continue
        pname = key[7:].strip()
        if not pname or pname in seen:
            continue
        seen.add(pname)
        params.append(
            {
                "name": pname,
                "section": (section or "").strip(),
                "data_type": (template_values.get(f"__type__{pname}") or "").strip(),
            }
        )
    return params


def _network_block_refs(network: Network) -> list[tuple[str, dict[str, Any]]]:
    """Block calls from this network (FB/FC), with XML-derived evidence props.

    Prefer ``CallInfo`` / TemplateValue ``Call`` (the called block type/name).
    Never invent callees from network titles.
    """
    refs: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for part in network.parts.values():
        called = (
            part.template_values.get("Call")
            or part.template_values.get("calledBlock")
            or ""
        ).strip().strip('"')
        call_params = _call_params_from_templates(part.template_values)
        props: dict[str, Any] = {
            "part_uid": part.uuid,
            "block_type": part.template_values.get("BlockType") or "",
            "instance_db": part.template_values.get("InstanceDB") or "",
            "evidence": "xml_call",
        }
        if call_params:
            props["call_params"] = call_params
        if called:
            if called not in seen:
                seen.add(called)
                refs.append((called, props))
            continue
        if part.name in CALL_PARTS or (part.name or "").startswith("Call"):
            instance = (
                part.accesses.get("instance")
                or part.accesses.get("Instance")
                or _pin_source_access(network, part.uuid, "db")
                or _pin_source_access(network, part.uuid, "instance")
            )
            if instance and instance.root and instance.root not in seen:
                seen.add(instance.root)
                props["evidence"] = "xml_call_instance"
                props["instance_db"] = instance.root
                refs.append((instance.root, props))
    return refs


def _variable_node_id(block_name: str, section: str, var_name: str) -> str:
    """Stable Variable id; include section so Input/Static homonyms do not collide."""
    sec = (section or "").strip() or "_"
    return f"Variable::{block_name}::{sec}::{var_name}"


def _ensure_interface_variable(
    kg: PlcKnowledgeGraph,
    block_name: str,
    *,
    var_name: str,
    section: str,
    data_type: str = "",
    comment: str = "",
    inferred: bool = False,
) -> str:
    var_id = _variable_node_id(block_name, section, var_name)
    if var_id in kg.nodes:
        return var_id
    props: dict[str, Any] = {
        "name": var_name,
        "section": section,
        "data_type": data_type,
        "comment": comment,
    }
    if inferred:
        props["inferred_from"] = "call_site"
    kg.add_node(var_id, "Variable", **props)
    kg.add_edge(
        f"Block::{block_name}",
        var_id,
        "HAS_INTERFACE",
        section=section,
        **({"evidence": "call_site_parameter"} if inferred else {}),
    )
    return var_id


def _enrich_interface_from_call_params(
    kg: PlcKnowledgeGraph,
    project: PlcProject,
    callee: str,
    call_params: list[dict[str, str]],
) -> None:
    """Fill missing pins on callees (esp. interface-only / external) from CallInfo."""
    if not call_params:
        return
    known = project.blocks.get(callee)
    known_names = {v.name for v in known.interface} if known is not None else set()
    for p in call_params:
        pname = (p.get("name") or "").strip()
        if not pname:
            continue
        if pname in known_names:
            continue
        section = (p.get("section") or "").strip() or "Input"
        # Skip if any section already has this pin on the graph
        existing = False
        for sec_try in (section, "Input", "Output", "InOut", "Static", "_"):
            if _variable_node_id(callee, sec_try, pname) in kg.nodes:
                existing = True
                break
        if existing:
            continue
        _ensure_interface_variable(
            kg,
            callee,
            var_name=pname,
            section=section,
            data_type=(p.get("data_type") or "").strip(),
            inferred=True,
        )
        # Keep IR in sync for interface-only blocks that lack this pin
        if known is not None and known.is_interface_only():
            try:
                sec_enum = InterfaceSection(section)
            except ValueError:
                sec_enum = InterfaceSection.INPUT
            known.interface.append(
                Variable(name=pname, section=sec_enum, data_type=(p.get("data_type") or "").strip())
            )
            known_names.add(pname)


def _add_typed_as_block_edge(
    kg: PlcKnowledgeGraph,
    owner: str,
    type_name: str,
    *,
    member: str,
    section: str,
) -> None:
    """Block → Block TYPED_AS; merge extra member names on the same pair."""
    src, tgt = f"Block::{owner}", f"Block::{type_name}"
    key = (src, tgt, TYPED_AS)
    if key in kg._edge_keys:
        for edge in kg.edges:
            if edge.source == src and edge.target == tgt and edge.type == TYPED_AS:
                prev = str(edge.props.get("member") or "")
                names = [p for p in prev.split(",") if p]
                if member and member not in names:
                    names.append(member)
                    edge.props["member"] = ",".join(names)
                if section and not edge.props.get("section"):
                    edge.props["section"] = section
                return
        return
    kg.add_edge(
        src,
        tgt,
        TYPED_AS,
        kind="multi_instance",
        member=member,
        section=section,
        evidence="interface_data_type",
    )


def _emit_typed_as_edges(kg: PlcKnowledgeGraph, project: PlcProject) -> None:
    """Link interface members whose data_type names an FB/FC/UDT/DB in IR."""
    known_names = set(project.blocks)
    for block in project.blocks.values():
        for var in block.interface:
            section = var.section.value if hasattr(var.section, "value") else str(var.section or "")
            if section not in NEST_SECTIONS:
                continue
            type_name = strip_type_name(var.data_type)
            if not type_name or is_primitive_type(type_name) or type_name == block.name:
                continue
            if type_name not in known_names:
                continue
            var_id = _variable_node_id(block.name, section, var.name)
            kg.add_edge(
                var_id,
                f"Block::{type_name}",
                TYPED_AS,
                kind="multi_instance",
                member=var.name,
                section=section,
                evidence="interface_data_type",
            )
            _add_typed_as_block_edge(
                kg,
                block.name,
                type_name,
                member=var.name,
                section=section,
            )


def _annotate_nest_depth(kg: PlcKnowledgeGraph) -> None:
    """Store nest_depth on Block nodes (longest TYPED_AS hop count)."""
    from agents.plc.tia.typed_as import nest_depth_of

    payload = kg.to_json()
    memo: dict[str, int] = {}
    for node in kg.nodes.values():
        if node.type != "Block":
            continue
        name = str(node.props.get("name") or node.id.split("::", 1)[-1])
        if not name:
            continue
        depth = nest_depth_of(payload, name, _memo=memo)
        node.props["nest_depth"] = depth


def _ensure_block_node(
    kg: PlcKnowledgeGraph,
    name: str,
    *,
    block_type: str | None = None,
    external: bool | None = None,
    **props: Any,
) -> str:
    block_id = f"Block::{name}"
    kg.add_node(
        block_id,
        "Block",
        name=name,
        block_type=block_type,
        external=external,
        **props,
    )
    return block_id


def _link_uses_db(
    kg: PlcKnowledgeGraph,
    block_id: str,
    db_name: str,
    *,
    known_blocks: dict[str, Block],
    evidence: str,
    network: str = "",
) -> None:
    if not db_name or f"Block::{db_name}" == block_id:
        return
    known = known_blocks.get(db_name)
    btype = known.block_type.value if known is not None else "DB"
    _ensure_block_node(
        kg,
        db_name,
        block_type=btype,
        external=known is None,
    )
    kg.add_edge(
        block_id,
        f"Block::{db_name}",
        "USES",
        evidence=evidence,
        **({"network": network} if network else {}),
    )


def _classify_part_io(
    block: Block,
    network: Network,
    kg: PlcKnowledgeGraph,
    *,
    known_blocks: dict[str, Block],
) -> None:
    block_id = f"Block::{block.name}"
    write_access_ids: set[str] = set()

    # Coil / Move / Call / box outputs → WRITES
    for part in network.parts.values():
        write_accesses: list[Access] = []
        if canon_part(part.name) in {"Coil", "NegCoil", "NotCoil", "Set", "Reset", "Save"}:
            operand = _pin_source_access(network, part.uuid, "operand") or part.accesses.get("operand")
            if operand is not None:
                write_accesses.append(operand)
        elif part.name in MOVE_PARTS or (part.name or "").startswith("Move"):
            for pin in ("out", "out1", "OUT", "OUT1"):
                acc = _access_bound_to_pin(network, part.uuid, pin)
                if acc is not None:
                    write_accesses.append(acc)
                    break
        elif part.name in CALL_PARTS or part.template_values.get("Call"):
            for wire in network.wires:
                for ep in wire.endpoints:
                    if ep.kind != "namecon" or ep.uuid != part.uuid:
                        continue
                    pin = ep.pin or ""
                    if not (pin.lower().startswith("out") or pin in WRITE_PINS):
                        continue
                    acc = _access_bound_to_pin(network, part.uuid, pin)
                    if acc is not None:
                        write_accesses.append(acc)
        elif canon_part(part.name) in INSTANCE_BOX_PARTS:
            for pin in ("CV", "Q", "QU", "QD", "ET"):
                acc = _access_bound_to_pin(network, part.uuid, pin)
                if acc is not None:
                    write_accesses.append(acc)

        for access in write_accesses:
            if not access.root and not access.absolute:
                continue
            ref = _access_ref(access)
            kg.add_node(f"Tag::{ref}", "Tag", name=ref, scope=access.scope.value)
            kg.add_edge(block_id, f"Tag::{ref}", "WRITES", part=part.name, network=network.id)
            for uid, acc in network.access_parts.items():
                if acc is access:
                    write_access_ids.add(uid)
            # Global DB root → USES Block::DB
            if access.scope == AccessScope.GLOBAL and access.root:
                root_block = known_blocks.get(access.root)
                if root_block is not None and root_block.block_type == BlockType.DB:
                    _link_uses_db(
                        kg,
                        block_id,
                        access.root,
                        known_blocks=known_blocks,
                        evidence="xml_db_write",
                        network=network.id,
                    )

    # Remaining network accesses are reads (+ USES for DB roots)
    for uid, access in network.access_parts.items():
        if uid in write_access_ids or access.scope == AccessScope.LITERAL:
            continue
        if not access.root and not access.absolute:
            continue
        ref = _access_ref(access)
        kg.add_node(f"Tag::{ref}", "Tag", name=ref, scope=access.scope.value)
        kg.add_edge(block_id, f"Tag::{ref}", "READS", network=network.id)
        if access.scope == AccessScope.GLOBAL and access.root:
            root_block = known_blocks.get(access.root)
            if root_block is not None and root_block.block_type == BlockType.DB:
                _link_uses_db(
                    kg,
                    block_id,
                    access.root,
                    known_blocks=known_blocks,
                    evidence="xml_db_read",
                    network=network.id,
                )

    # Timer / counter / FB instance DB → USES
    for part in network.parts.values():
        inst = part.accesses.get("instance") or part.accesses.get("Instance")
        inst_name = ""
        if inst is not None and inst.root:
            inst_name = inst.root
        elif part.template_values.get("InstanceDB"):
            inst_name = str(part.template_values["InstanceDB"]).strip().strip('"')
        if not inst_name:
            continue
        if part.name in INSTANCE_BOX_PARTS or part.template_values.get("Call"):
            _link_uses_db(
                kg,
                block_id,
                inst_name,
                known_blocks=known_blocks,
                evidence="xml_instance",
                network=network.id,
            )


def _to_kind(to_type: str) -> str:
    """Coarse TechnologyObject kind from its Openness type (axis / cam / pid / ...)."""
    t = (to_type or "").lower().strip()
    for marker in ("axis", "cam", "pid", "servo", "kinematic"):
        if marker in t:
            return marker
    t = t.removeprefix("to_")
    return t or "to"


def _path_components(source_file: str) -> set[str]:
    """Lowercased path components of a source file (folder-ownership evidence)."""
    out: set[str] = set()
    for part in (source_file or "").replace("\\", "/").split("/"):
        part = part.strip()
        if part:
            out.add(part.lower())
    return out


def _owner_device(devices: list[HardwareDevice], source_file: str) -> HardwareDevice | None:
    """Best-effort owning device: the most specific device name in the file path.

    TechnologyObjects and alarms carry no explicit device reference in PLC-IR,
    but their exports live under ``plc/<device>/to|alarms``. Matching the longest
    device name against path components is real ownership evidence — when nothing
    matches we return None and no edge is created (never invented).
    """
    comps = _path_components(source_file)
    if not comps:
        return None
    best: HardwareDevice | None = None
    best_len = 0
    for device in devices:
        name = (device.name or "").strip().lower()
        if name and name in comps and len(name) > best_len:
            best = device
            best_len = len(name)
    return best


def build_knowledge_graph(project: PlcProject) -> PlcKnowledgeGraph:
    kg = PlcKnowledgeGraph()
    project_id = f"Project::{project.name}"
    kg.add_node(project_id, "Project", name=project.name, tia_version=project.tia_version)
    known_blocks = dict(project.blocks)

    # Tag tables
    for table in project.tag_tables.values():
        table_id = f"TagTable::{table.name}"
        kg.add_node(table_id, "TagTable", name=table.name)
        kg.add_edge(project_id, table_id, "CONTAINS")
        for tag in table.tags:
            tag_id = f"Tag::{tag.name}"
            kg.add_node(
                tag_id,
                "Tag",
                name=tag.name,
                data_type=tag.data_type,
                address=tag.logical_address,
                comment=tag.comment,
            )
            kg.add_edge(table_id, tag_id, "CONTAINS")

    # Blocks (declare first so USES can resolve DB types)
    for block in project.blocks.values():
        block_id = f"Block::{block.name}"
        kg.add_node(
            block_id,
            "Block",
            name=block.name,
            number=block.number,
            block_type=block.block_type.value,
            language=block.programming_language,
            comment=block.header_comment,
            protected=block.is_protected(),
            interface_only=block.is_interface_only(),
            body_available=block.has_program_body(),
            safety=bool(block.is_safety),
        )
        kg.add_edge(project_id, block_id, "CONTAINS")

        for var in block.interface:
            _ensure_interface_variable(
                kg,
                block.name,
                var_name=var.name,
                section=var.section.value,
                data_type=var.data_type,
                comment=var.comment,
            )

    # Networks / calls / IO / USES
    for block in project.blocks.values():
        block_id = f"Block::{block.name}"
        for net_idx, network in enumerate(block.networks, start=1):
            net_id = f"Network::{block.name}::{network.id or len(kg.edges)}"
            kg.add_node(
                net_id,
                "Network",
                title=network.title,
                language=network.programming_language,
            )
            kg.add_edge(block_id, net_id, "CONTAINS")
            _classify_part_io(block, network, kg, known_blocks=known_blocks)

            for callee, call_props in _network_block_refs(network):
                if not callee or callee == block.name:
                    continue
                callee_known = known_blocks.get(callee)
                callee_type = (
                    call_props.get("block_type")
                    or (callee_known.block_type.value if callee_known else None)
                )
                _ensure_block_node(
                    kg,
                    callee,
                    block_type=callee_type,
                    external=callee not in project.blocks,
                    protected=callee_known.is_protected() if callee_known else None,
                    interface_only=callee_known.is_interface_only() if callee_known else None,
                    body_available=callee_known.has_program_body() if callee_known else None,
                )
                edge_props = {
                    k: v
                    for k, v in call_props.items()
                    if v and k != "call_params"
                }
                # Keep call_params even when list (truthy check above drops empty; list is ok)
                if call_props.get("call_params"):
                    edge_props["call_params"] = call_props["call_params"]
                kg.add_edge(
                    block_id,
                    f"Block::{callee}",
                    "CALLS",
                    network=net_id,
                    seq=net_idx,
                    **edge_props,
                )
                _enrich_interface_from_call_params(
                    kg,
                    project,
                    callee,
                    list(call_props.get("call_params") or []),
                )
                # FB instance DB: USES + INSTANCE_OF
                inst = str(call_props.get("instance_db") or "")
                if inst and inst != callee:
                    _link_uses_db(
                        kg,
                        block_id,
                        inst,
                        known_blocks=known_blocks,
                        evidence="xml_call_instance",
                        network=net_id,
                    )
                    if (call_props.get("block_type") or "") == "FB" or (
                        callee_known is not None and callee_known.block_type == BlockType.FB
                    ):
                        _ensure_block_node(kg, inst, block_type="DB", external=inst not in project.blocks)
                        kg.add_edge(f"Block::{inst}", f"Block::{callee}", "INSTANCE_OF")

        # Runtime sequence within this block: NEXT between successive unique callees
        ordered_callees: list[str] = []
        for network in block.networks:
            for callee, _props in _network_block_refs(network):
                if callee and callee != block.name and callee not in ordered_callees:
                    ordered_callees.append(callee)
        for i in range(len(ordered_callees) - 1):
            kg.add_edge(
                f"Block::{ordered_callees[i]}",
                f"Block::{ordered_callees[i + 1]}",
                "NEXT",
                seq=i + 1,
                evidence="xml_call_order",
            )

    # DB <-> FB instance dependencies from DB attributes
    fb_names = {b.name for b in project.blocks.values() if b.block_type == BlockType.FB}
    for block in project.blocks.values():
        if block.block_type != BlockType.DB:
            continue
        type_attr = (
            block.attributes.get("InstanceOfName")
            or block.attributes.get("OfType")
            or block.attributes.get("OfBlock")
            or ""
        )
        if type_attr in fb_names:
            kg.add_edge(f"Block::{block.name}", f"Block::{type_attr}", "INSTANCE_OF")

    # Multi-instance member types (Variable.data_type → existing block). After
    # CALLS enrichment so inferred interface pins are included. Never invent types.
    _emit_typed_as_edges(kg, project)
    _annotate_nest_depth(kg)

    # -- Device layer -------------------------------------------------------
    # HardwareDevice → Device nodes owned by the Project (HAS_DEVICE).
    device_by_name: dict[str, str] = {}
    for hw in project.hardware:
        name = (hw.name or "").strip()
        if not name:
            continue
        device_id = f"Device::{name}"
        kg.add_node(
            device_id,
            "Device",
            name=name,
            type=hw.device_type,
            address=hw.address,
            failsafe=hw.failsafe,
            rack=hw.rack,
        )
        kg.add_edge(project_id, device_id, "HAS_DEVICE")
        device_by_name.setdefault(name.lower(), device_id)

    # Axis / Servo / cam … → TechnologyObject nodes (kind distinguishes them).
    for to in project.technology_objects:
        name = (to.name or "").strip()
        if not name:
            continue
        to_id = f"TechnologyObject::{name}"
        kg.add_node(
            to_id,
            "TechnologyObject",
            name=name,
            kind=_to_kind(to.to_type),
            to_type=to.to_type,
            version=to.version,
        )
        owner = _owner_device(list(project.hardware), to.source_file)
        if owner is not None and owner.name.lower() in device_by_name:
            kg.add_edge(
                device_by_name[owner.name.lower()],
                to_id,
                "RUNS_TO",
                evidence="path_ownership",
            )

    # Text lists + ProDiag supervisions → Alarm nodes owned by a device.
    for alarm in [*project.alarms, *project.prodiag]:
        name = (alarm.name or "").strip()
        if not name:
            continue
        alarm_id = f"Alarm::{name}"
        kg.add_node(
            alarm_id,
            "Alarm",
            name=name,
            kind=alarm.kind,
            texts="; ".join(alarm.texts),
        )
        owner = _owner_device(list(project.hardware), alarm.source_file)
        if owner is not None and owner.name.lower() in device_by_name:
            kg.add_edge(
                device_by_name[owner.name.lower()],
                alarm_id,
                "HAS_ALARM",
                evidence="path_ownership",
            )

    return kg
