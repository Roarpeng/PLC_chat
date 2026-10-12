"""PLC-IR — language-agnostic intermediate representation for TIA projects.

Pipeline position: TIA Project -> Openness export (SimaticML XML) -> Extract
-> **PLC-IR** -> Knowledge Graph / SCL translation / LLM Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BlockType(StrEnum):
    FB = "FB"
    FC = "FC"
    OB = "OB"
    DB = "DB"
    UDT = "UDT"


class InterfaceSection(StrEnum):
    INPUT = "Input"
    OUTPUT = "Output"
    IN_OUT = "InOut"
    STATIC = "Static"
    TEMP = "Temp"
    CONSTANT = "Constant"
    RETURN = "Return"


class AccessScope(StrEnum):
    LOCAL = "local"      # #Variable
    GLOBAL = "global"    # "TagTable".Tag / direct address
    LITERAL = "literal"  # constant value
    UNKNOWN = "unknown"


@dataclass
class Access:
    """A variable/constant reference inside an instruction."""

    scope: AccessScope = AccessScope.UNKNOWN
    root: str = ""        # "#Var" -> Var ; global -> tag table name
    path: tuple[str, ...] = ()  # member chain after the root
    data_type: str = ""
    negated: bool = False
    raw: str = ""
    absolute: str = ""  # e.g. %M0.5 when AbsoluteAddress is present

    @property
    def name(self) -> str:
        if self.absolute and not self.root:
            return self.absolute
        base = self.root or self.raw or self.absolute
        if self.path:
            return ".".join([base, *self.path]) if self.scope != AccessScope.LOCAL else (
                base + "." + ".".join(self.path)
            )
        return base

    def as_scl(self) -> str:
        """Render the access as an SCL operand."""
        if self.scope == AccessScope.LITERAL:
            return self.raw or self.absolute
        if self.absolute and not self.root:
            core = self.absolute
        elif self.scope == AccessScope.LOCAL:
            core = "#" + self.root
        else:
            core = f'"{self.root}"' if self.root else (self.absolute or self.raw)
        if self.path and self.root:
            core = core + "." + ".".join(self.path)
        return f"NOT ({core})" if self.negated else core


@dataclass(frozen=True)
class Expr:
    """Boolean / value expression node (PLC-IR logic layer)."""


@dataclass(frozen=True)
class Lit(Expr):
    value: bool | str  # True/False or raw literal string


@dataclass(frozen=True)
class Ref(Expr):
    access: Access


@dataclass(frozen=True)
class Not(Expr):
    operand: Expr


@dataclass(frozen=True)
class And(Expr):
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class Or(Expr):
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class Compare(Expr):
    op: str  # = <> > >= < <=
    lhs: Expr
    rhs: Expr


@dataclass(frozen=True)
class Arith(Expr):
    """Arithmetic / word-logic chain: ``a + b * c`` (op applied left-fold)."""

    op: str  # + - * / MOD AND OR XOR MIN MAX ** …
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class Func(Expr):
    """Function-style value: ``SIN(x)``, ``SWAP(w)``."""

    name: str
    args: tuple[Expr, ...]


@dataclass(frozen=True)
class Raw(Expr):
    """Verbatim SCL text captured from source (e.g. CALCULATE equation)."""

    text: str


@dataclass(frozen=True)
class AssignStmt:
    target: Access | None
    value: Expr
    kind: str = "coil"  # coil | neg_coil | set | reset | move | call
    target_scl: str = ""  # fallback when Access missing; full SCL for kind=call
    enable: Expr | None = None  # Move EN / conditional assignment


@dataclass
class GraphStep:
    """One S7-GRAPH step (SCL may only be a commented sequence)."""

    name: str
    number: int = 0
    uuid: str = ""
    actions: list[str] = field(default_factory=list)
    comment: str = ""
    interlock: str = ""
    supervision: str = ""
    evidence: str = "graph_xml"


@dataclass
class GraphTransition:
    """One S7-GRAPH transition between steps."""

    name: str
    number: int = 0
    uuid: str = ""
    source_step: str = ""
    target_step: str = ""
    condition: str = ""
    comment: str = ""
    evidence: str = "graph_xml"


@dataclass
class FoldedNetwork:
    network_id: str = ""
    title: str = ""
    statements: list[AssignStmt] = field(default_factory=list)
    unresolved_parts: list[str] = field(default_factory=list)  # part uuids or names
    evidence: str = "flgnet_fold"


@dataclass
class Variable:
    name: str
    section: InterfaceSection = InterfaceSection.STATIC
    data_type: str = ""
    start_value: str = ""
    comment: str = ""
    is_retain: bool = False
    logical_address: str = ""


@dataclass
class Part:
    """One instruction element in a network (contact, coil, call, timer...)."""

    name: str
    part_type: str
    uuid: str = ""
    version: str = ""
    accesses: dict[str, Access] = field(default_factory=dict)
    template_values: dict[str, str] = field(default_factory=dict)
    negated: bool = False
    programming_language: str = ""


@dataclass
class WireEndpoint:
    """One endpoint of a SimaticML wire.

    kind: powerrail | namecon | identcon | opencon
    - namecon: named pin of a Part (uuid + pin)
    - identcon: reference to a top-level Access part (uuid)
    """

    kind: str
    uuid: str = ""
    pin: str = ""


@dataclass
class Wire:
    """SimaticML wire: first endpoint is the source, rest are targets."""

    uid: str
    endpoints: list[WireEndpoint] = field(default_factory=list)

    @property
    def source(self) -> WireEndpoint | None:
        return self.endpoints[0] if self.endpoints else None

    @property
    def targets(self) -> list[WireEndpoint]:
        return self.endpoints[1:]


@dataclass
class Network:
    id: str = ""
    title: str = ""
    comment: str = ""
    programming_language: str = ""
    parts: dict[str, Part] = field(default_factory=dict)
    access_parts: dict[str, Access] = field(default_factory=dict)
    rails: dict[str, Part] = field(default_factory=dict)
    wires: list[Wire] = field(default_factory=list)
    source_text: str = ""  # SCL/STL body when the unit is textual
    folded: FoldedNetwork | None = None
    graph_steps: list[GraphStep] = field(default_factory=list)
    graph_transitions: list[GraphTransition] = field(default_factory=list)

    def accesses(self) -> list[Access]:
        out: list[Access] = list(self.access_parts.values())
        for part in self.parts.values():
            out.extend(part.accesses.values())
        return out


@dataclass
class Block:
    name: str
    number: int = 0
    block_type: BlockType = BlockType.FB
    programming_language: str = ""
    namespace: str = ""
    header_comment: str = ""
    interface: list[Variable] = field(default_factory=list)
    networks: list[Network] = field(default_factory=list)
    source_text: str = ""  # original SCL/STL body when language is textual
    attributes: dict[str, str] = field(default_factory=dict)
    source_file: str = ""  # path to original SimaticML XML export
    is_safety: bool = False  # F-OB / F-FB / F-FC / F-DB — never mixed into std scan

    def interface_section(self, section: InterfaceSection) -> list[Variable]:
        return [v for v in self.interface if v.section == section]

    def find_variable(self, name: str) -> Variable | None:
        for v in self.interface:
            if v.name == name:
                return v
        return None

    def is_protected(self) -> bool:
        """True when know-how / password protection should block SCL conversion."""
        truthy = {"true", "1", "yes", "on", "protected", "enabled"}
        for key, raw in self.attributes.items():
            k = key.lower().replace("-", "").replace("_", "")
            v = (raw or "").strip().lower()
            if "knowhow" in k or "protect" in k:
                if v in truthy or v == "":
                    return True
        blob = f"{self.header_comment} {self.source_text}".lower()
        return "know-how" in blob or "knowhow protect" in blob

    def has_program_body(self) -> bool:
        """True when networks or source text are present (export includes logic)."""
        if self.networks:
            return True
        return bool((self.source_text or "").strip())

    def is_interface_only(self) -> bool:
        """FB/FC with open interface but no program body (typical Know-how export).

        Siemens often exports Interface members while omitting CompileUnit/SCL body.
        ``KnowHowProtection`` may be absent from XML even when the body is locked.
        """
        if self.block_type not in {BlockType.FB, BlockType.FC}:
            return False
        if self.has_program_body():
            return False
        return bool(self.interface)


@dataclass
class HardwareDevice:
    """Best-effort device / rack / Profinet row from Openness HW XML / AML."""

    name: str
    device_type: str = ""
    address: str = ""
    slot: str = ""
    comment: str = ""
    source_file: str = ""
    failsafe: bool = False
    rack: str = ""
    modules: list[str] = field(default_factory=list)
    subnets: list[str] = field(default_factory=list)
    network_interfaces: list[str] = field(default_factory=list)


@dataclass
class Tag:
    name: str
    data_type: str = ""
    logical_address: str = ""
    comment: str = ""


@dataclass
class TagTable:
    name: str
    tags: list[Tag] = field(default_factory=list)


@dataclass
class WatchEntry:
    name: str = ""
    address: str = ""
    tag: str = ""
    comment: str = ""


@dataclass
class WatchTable:
    name: str
    kind: str = "watch"  # watch | force
    entries: list[WatchEntry] = field(default_factory=list)
    source_file: str = ""


@dataclass
class TechnologyObject:
    name: str
    to_type: str = ""
    version: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    source_file: str = ""


@dataclass
class AlarmObject:
    name: str
    kind: str = ""  # text_list | class | instance | supervision | prodiag
    texts: list[str] = field(default_factory=list)
    source_file: str = ""


@dataclass
class CfcChart:
    name: str
    folder: str = ""
    blocks: list[str] = field(default_factory=list)
    wires: list[str] = field(default_factory=list)
    password_protected: bool = False
    source_file: str = ""


@dataclass
class SafetyUnitInfo:
    name: str
    failsafe: bool = True
    supervisions: list[str] = field(default_factory=list)
    source_file: str = ""
    skipped_reason: str = ""


@dataclass
class HmiScreen:
    name: str
    folder: str = ""
    kind: str = "screen"  # screen | template | popup | slidein | faceplate | permanent
    linked_tags: list[str] = field(default_factory=list)
    source_file: str = ""


@dataclass
class HmiDevice:
    name: str
    kind: str = "hmi"  # hmi | hmi_unified
    tag_tables: dict[str, TagTable] = field(default_factory=dict)
    scripts: list[str] = field(default_factory=list)
    text_lists: list[str] = field(default_factory=list)
    graphic_lists: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    cycles: list[str] = field(default_factory=list)
    screens: list[HmiScreen] = field(default_factory=list)
    source_file: str = ""


@dataclass
class PlcProject:
    """Top-level PLC-IR container."""

    name: str = "TiaProject"
    tia_version: str = ""
    source_path: str = ""
    blocks: dict[str, Block] = field(default_factory=dict)
    tag_tables: dict[str, TagTable] = field(default_factory=dict)
    extraction_notes: list[str] = field(default_factory=list)
    hardware: list[HardwareDevice] = field(default_factory=list)
    watch_tables: dict[str, WatchTable] = field(default_factory=dict)
    force_tables: dict[str, WatchTable] = field(default_factory=dict)
    technology_objects: list[TechnologyObject] = field(default_factory=list)
    alarms: list[AlarmObject] = field(default_factory=list)
    prodiag: list[AlarmObject] = field(default_factory=list)
    cfc_charts: list[CfcChart] = field(default_factory=list)
    safety_units: list[SafetyUnitInfo] = field(default_factory=list)
    hmi_devices: list[HmiDevice] = field(default_factory=list)
    opcua_nodes: list[str] = field(default_factory=list)
    project_texts: dict[str, str] = field(default_factory=dict)
    export_manifest: dict[str, Any] = field(default_factory=dict)
    export_journal: list[dict[str, Any]] = field(default_factory=list)
    parse_gaps: list[dict[str, Any]] = field(default_factory=list)

    def add_block(self, block: Block) -> None:
        self.blocks[block.name] = block

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for block in self.blocks.values():
            counts[block.block_type.value] = counts.get(block.block_type.value, 0) + 1
        counts["TagTables"] = len(self.tag_tables)
        counts["Networks"] = sum(len(b.networks) for b in self.blocks.values())
        counts["SafetyBlocks"] = sum(1 for b in self.blocks.values() if b.is_safety)
        counts["Hardware"] = len(self.hardware)
        counts["WatchTables"] = len(self.watch_tables)
        counts["ForceTables"] = len(self.force_tables)
        counts["TechnologyObjects"] = len(self.technology_objects)
        counts["Alarms"] = len(self.alarms)
        counts["ProDiag"] = len(self.prodiag)
        counts["CfcCharts"] = len(self.cfc_charts)
        counts["SafetyUnits"] = len(self.safety_units)
        counts["HmiDevices"] = len(self.hmi_devices)
        counts["OpcUaNodes"] = len(self.opcua_nodes)
        return counts
