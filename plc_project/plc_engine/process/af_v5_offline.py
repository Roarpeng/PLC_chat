"""Lower the KUKA V5 workspace into a callable V19 offline acceptance project."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from plc_engine.process.station_cylinder import emit_cylinder
from plc_engine.process.station_lowering import _fb, _instance


_BIT_ADDRESS = re.compile(r"%([IQ])([0-9]+)\.([0-7])\Z")
_SYMBOL = re.compile(r"#([A-Za-z][A-Za-z0-9_]*)")
_ASSIGNMENT = re.compile(r"#([A-Za-z][A-Za-z0-9_]*)\s*:=\s*(.+)\Z")
_BOOL_TOKEN = re.compile(r"#[A-Za-z][A-Za-z0-9_]*|[A-Za-z]+|[()]")
_BOOL_OPERATORS = {"AND", "OR", "XOR", "NOT", "TRUE", "FALSE", "(", ")"}
_STATIONS = ("ST10", "ST20", "ST30", "ST40", "ST50", "ST60", "ST70")
_CM_CYLINDER = "FB_CM_Cylinder2Pos"
_CM_SENSOR = "FB_CM_DigitalInput"
_PORT_SYMBOLS = {
    "diHome": ("DI", "Retracted"),
    "diWork": ("DI", "Extended"),
    "diSignal": ("DI", "Present"),
    "doWork": ("DO", "ExtendValve"),
    "doHome": ("DO", "RetractValve"),
}
_ROLE_SYMBOLS = {
    "气缸 1": "DustCoverCylinder",
    "气缸 2": "StandCylinder",
    "工具到位 1": "ToolPresentLeft",
    "工具到位 2": "ToolPresentRight",
    "附件位气缸 1": "OldAttachmentGripCylinder",
    "附件位气缸 2": "OldAttachmentRemovalCylinder",
    "附件位气缸 3": "NewAttachmentFeedCylinder",
    "附件位气缸 4": "NewAttachmentInstallCylinder",
    "作业对象在位传感器": "WorkObject",
}


@dataclass
class EquipmentModule:
    station_id: str
    source: str
    inputs: list[str]
    outputs: list[str]


@dataclass
class AfFolderProject:
    sources: list[tuple[str, str]]
    tag_tables: dict[str, list[dict[str, str]]]
_ATTACHMENT_COMMANDS = (
    "HoldOldAttachmentRequest", "RemoveOldAttachmentRequest",
    "FeedNewAttachmentRequest", "InstallNewAttachmentRequest",
)


def _bool_expression(text: str) -> str:
    expr = re.sub(r"\(\*.*?\*\)", "", text, flags=re.S).strip()
    tokens = _BOOL_TOKEN.findall(expr)
    if not tokens or "".join(tokens) != re.sub(r"\s+", "", expr) or any(
        not token.startswith("#") and token.upper() not in _BOOL_OPERATORS for token in tokens
    ):
        raise ValueError(f"Unsupported V5 Boolean expression: {text!r}")
    return expr


def _db(name: str, fields: list[str]) -> str:
    return "\n".join([
        f'DATA_BLOCK "{name}"', "{ S7_Optimized_Access := 'TRUE' }", "VAR",
        *(f"    {field};" for field in fields), "END_VAR", "BEGIN", "END_DATA_BLOCK",
    ])


def _field_addresses(workspace: Mapping) -> dict[str, str]:
    points = {}
    used = set()
    for point in workspace.get("fieldIoPoints", []):
        address = point["address"].upper()
        match = _BIT_ADDRESS.fullmatch(address)
        if point["type"] != "BOOL" or not match:
            raise ValueError(f"Unsupported I/O point {point['name']}: {address}")
        bank, byte, bit = match.groups()
        address = f"%{bank}{int(byte)}.{bit}"
        if point["id"] in points or address in used:
            raise ValueError(f"Duplicate point: {address}")
        used.add(address)
        points[point["id"]] = address
    return points


def _field_io(tag_tables: Mapping) -> str:
    pins = [point for table in tag_tables.values() for point in table]
    db = _db("DB_IO_KukaCell", [f"{point['name']} : Bool" for point in pins])
    lines = [
        'FUNCTION "FC_IO_KukaCell" : Void', "{ S7_Optimized_Access := 'TRUE' }",
        "VAR_INPUT", "    PermitOutputs : Bool;", "END_VAR", "BEGIN",
    ]
    for point in pins:
        symbol = point["name"]
        field = f'"DB_IO_KukaCell".{symbol}'
        if point["address"].startswith("%I"):
            lines.append(f'    {field} := "{symbol}";')
        else:
            lines.append(f'    "{symbol}" := #PermitOutputs AND {field};')
    return db + "\n\n" + "\n".join([*lines, "END_FUNCTION"])


def _station_source(station: Mapping, points: Mapping, claimed: set[str], tags: list) -> EquipmentModule:
    sid = station["stationId"]
    if station["guardEdges"]:
        raise ValueError(f"{sid}: offline profile does not lower authored guard edges")
    aliases: dict[str, str] = {}
    cylinders = []
    sensors = []
    for node in station["spatialNodes"]:
        profile = node.get("cmProfile")
        if node["role"] != "ACTUATOR":
            continue
        if profile == "Robot6Axis@1" and sid == "ST50":
            continue  # The KUKA link is symbolic at the PLC boundary.
        if profile == "Cylinder2Pos@1":
            ports = {"diHome": "I", "diWork": "I", "doWork": "Q"}
            if node["fieldBindings"].get("doHome"):
                ports["doHome"] = "Q"
        elif profile == "DigitalInput@1":
            ports = {"diSignal": "I"}
        else:
            raise ValueError(f"{sid}: unsupported device profile {profile!r}")
        fields = {}
        for port, bank in ports.items():
            point_id = node.get("fieldBindings", {}).get(port)
            if point_id not in points or point_id in claimed or not points[point_id].startswith("%" + bank):
                raise ValueError(f"{sid}/{node['title']}: invalid binding for {port}")
            role = _ROLE_SYMBOLS.get(node["title"])
            if role is None:
                raise ValueError(f"{sid}: unknown device role {node['title']!r}")
            direction, suffix = _PORT_SYMBOLS[port]
            symbol = f"{direction}_{sid}_{role}_{suffix}"
            if any(point["name"] == symbol for point in tags):
                raise ValueError(f"{sid}: duplicate device role {role}")
            tags.append({"name": symbol, "address": points[point_id]})
            claimed.add(point_id)
            fields[port] = f'"DB_IO_KukaCell".{symbol}'
        if profile == "Cylinder2Pos@1":
            cylinders.append((node, fields))
        else:
            role = _ROLE_SYMBOLS[node["title"]]
            sensors.append((node, role, fields["diSignal"]))

    steps = sorted(station["temporalSteps"], key=lambda step: step["stepNo"])
    assignments = {}
    waits = {}
    symbols = set()
    assigned = set()
    command_pins = {}
    for step in steps:
        number = step["stepNo"]
        if type(number) is not int or not 0 < number < 999 or number in assignments or step.get("branchPredicate") not in (None, "ALWAYS"):
            raise ValueError(f"{sid}: unsupported step number or branch")
        if len(step["invocations"]) != 1 or step.get("requiresGuardNodeIds"):
            raise ValueError(f"{sid}/S{number}: unsupported invocation or guard")
        invocation = step["invocations"][0]
        step_assignments = {}
        for part in invocation["sclStatement"].split(";"):
            if not part.strip():
                continue
            match = _ASSIGNMENT.fullmatch(part.strip())
            if not match:
                raise ValueError(f"{sid}/S{number}: unsupported statement {part!r}")
            name, expr = match.groups()
            expr = _bool_expression(expr)
            step_assignments[name] = expr
            symbols.update(_SYMBOL.findall(expr))
        wait = _bool_expression(invocation["waitPredicateScl"])
        symbols.update(_SYMBOL.findall(wait))
        assigned.update(step_assignments)
        assignments[number] = step_assignments
        waits[number] = wait
        target = invocation["targetNodeId"]
        method = invocation["methodId"]
        if any(node["id"] == target for node, _ in cylinders):
            if sid == "ST40" and method == "ExtendWork":
                known_commands = set(_ATTACHMENT_COMMANDS) & step_assignments.keys()
                if len(known_commands) != 1 or target in command_pins:
                    raise ValueError(f"{sid}/S{number}: ambiguous attachment cylinder request")
                command_pins[target] = (f"#{known_commands.pop()}", "FALSE")
            elif sid in _STATIONS[:3] and method in ("ExtendWork", "RetractHome"):
                if not {"DustCoverOpenRequest", "DustCoverCloseRequest"} <= step_assignments.keys():
                    raise ValueError(f"{sid}/S{number}: missing dust cover request")
                command_pins[target] = ("#DustCoverCloseRequest", "#DustCoverOpenRequest")
            else:
                raise ValueError(f"{sid}/S{number}: unsupported actuator action {method}")
        elif target != f"BOUND_OUT_{sid}" or method != "ReleaseNext":
            raise ValueError(f"{sid}/S{number}: unsupported operation target")
    if sid in _STATIONS[:3]:
        if len(command_pins) != 1 or len(sensors) != 2:
            raise ValueError(f"{sid}: expected one commanded cover and two tool sensors")
        cover = next(fields for node, fields in cylinders if node["id"] in command_pins)
        aliases["DustCoverOpenConfirmed"] = f'{cover["diHome"]} AND NOT {cover["diWork"]}'
        aliases["DustCoverLockConfirmed"] = f'{cover["diWork"]} AND NOT {cover["diHome"]}'
        for node, role, _ in sensors:
            if node["title"] not in {"工具到位 1", "工具到位 2"}:
                raise ValueError(f"{sid}: verify tool sensor roles")
            aliases["ToolPresentSensor" + node["title"][-1]] = f"#{role}.Present"
    if sid == "ST40" and len(command_pins) != 4:
        raise ValueError("ST40: expected four distinct attachment cylinders")
    if sid == "ST50":
        if len(sensors) != 1 or len(steps) != 1 or next(iter(waits.values())).upper() != "FALSE":
            raise ValueError("ST50: expected one work-object monitor")
        aliases["WorkObjectPresent"] = f"#{sensors[0][1]}.Present"
    if assigned & aliases.keys():
        raise ValueError(f"{sid}: assignment attempts to write a bound feedback")

    inputs = ["Permit : Bool", "Reset : Bool"]
    if sid in _STATIONS[:3]:
        start = "ToolRestRequest"
    elif sid == "ST40":
        start = "AttachmentChangeRequest"
    else:
        start = ""
    external = symbols - assigned - aliases.keys()
    if start:
        external.add(start)
    inputs += [f"{name} : Bool" for name in sorted(external)]
    outputs = ["ActiveStep : Int", "CycleComplete : Bool", "CmFault : Bool"]
    outputs += [f"{name} : Bool" for name in sorted(assigned)]
    local = ["Step : Int", *(f"{name} : Bool" for name in sorted(aliases))]
    local += [f'{_ROLE_SYMBOLS[node["title"]]} : "{_CM_CYLINDER}"' for node, _ in cylinders]
    local += [f'{role} : "{_CM_SENSOR}"' for _, role, _ in sensors]
    name = f"FB_EM_{sid}"
    result = _fb(name, inputs, outputs, local)
    for _, role, signal in sensors:
        result.emit(f"    #{role}(Signal := {signal});")
    for alias, expr in sorted(aliases.items()):
        result.emit(f"    #{alias} := {expr};")
    if not start:
        for symbol, expr in next(iter(assignments.values())).items():
            result.emit(f"    #{symbol} := {expr};")
        result.emit(f"    #ActiveStep := {steps[0]['stepNo']};")
    else:
        result.emit("    IF #Reset OR NOT #Permit THEN")
        result.emit("        #Step := 0;")
        for symbol in sorted(assigned):
            result.emit(f"        #{symbol} := FALSE;")
        result.emit("    ELSE")
        result.emit("        CASE #Step OF")
        numbers = list(assignments)
        result.emit(f"            0: IF #{start} THEN #Step := {numbers[0]}; END_IF;")
        for index, number in enumerate(numbers):
            result.emit(f"            {number}:")
            for symbol, expr in assignments[number].items():
                result.emit(f"                #{symbol} := {expr};")
            next_step = numbers[index + 1] if index + 1 < len(numbers) else 999
            result.emit(f"                IF {waits[number]} THEN #Step := {next_step}; END_IF;")
        result.emit(f"            999: IF NOT #{start} THEN #Step := 0; END_IF;")
        result.emit("        END_CASE;")
        result.emit("    END_IF;")
        result.emit("    #ActiveStep := #Step;")
        result.emit("    #CycleComplete := #Step = 999;")
    result.emit("    #CmFault := FALSE;")
    for node, fields in cylinders:
        role = _ROLE_SYMBOLS[node["title"]]
        extend, retract = command_pins.get(node["id"], ("FALSE", "FALSE"))
        result.emit(f'    #{role}(Permit := #Permit, Enable := TRUE, Mode := 0, ManualRequest := 0,')
        result.emit(f'        Reset := #Reset, ExtendTimeout := T#0ms, RetractTimeout := T#0ms,')
        result.emit(f'        Req_extend := {extend}, Req_retract := {retract},')
        result.emit(f'        In_extended := {fields["diWork"]}, In_retracted := {fields["diHome"]});')
        result.emit(f'    {fields["doWork"]} := #{role}.Q_extend;')
        if "doHome" in fields:
            result.emit(f'    {fields["doHome"]} := #{role}.Q_retract;')
        result.emit(f"    #CmFault := #CmFault OR #{role}.Fault;")
    result.emit("END_FUNCTION_BLOCK")
    source = result.content() + "\n" + _instance(f"DB_EM_{sid}", name).content()
    return EquipmentModule(sid, source, inputs, outputs)


def _unit_source(modules: list[EquipmentModule]) -> str:
    name = "FB_Unit_KukaCell"
    inputs = ["CellPermit : Bool", "Reset : Bool"]
    outputs = ["AnyCmFault : Bool"]
    for module in modules:
        inputs.extend(f"{module.station_id}_{field}" for field in module.inputs if field not in ("Permit : Bool", "Reset : Bool"))
        outputs.extend(f"{module.station_id}_{field}" for field in module.outputs)
    block = _fb(name, inputs, outputs, [])
    for module in modules:
        sid = module.station_id
        args = ["Permit := #CellPermit", "Reset := #Reset"]
        args.extend(f"{key} := #{sid}_{key}" for key in (field.split(" :", 1)[0] for field in module.inputs) if key not in ("Permit", "Reset"))
        args.extend(f"{key} => #{sid}_{key}" for key in (field.split(" :", 1)[0] for field in module.outputs))
        block.emit(f'    "DB_EM_{sid}"(' + ",\n        ".join(args) + ");")
        block.emit(f'    "DB_HMI_KukaCell".{sid}_ActiveStep := #{sid}_ActiveStep;')
        block.emit(f'    "DB_HMI_KukaCell".{sid}_CmFault := #{sid}_CmFault;')
    block.emit("    #AnyCmFault := " + " OR ".join(f"#{mod.station_id}_CmFault" for mod in modules) + ";")
    block.emit("END_FUNCTION_BLOCK")
    return block.content() + "\n" + _instance("DB_Unit_KukaCell", name).content()


def compile_kuka_offline(workspace: Mapping) -> AfFolderProject:
    """Lower the as-authored KUKA cell into named I/O, CM drivers, EMs and a Unit."""
    stations = workspace["stationGraphs"]
    if set(stations) != set(_STATIONS) or any(stations[sid]["stationId"] != sid for sid in _STATIONS):
        raise ValueError("This offline profile requires KUKA stations ST10 through ST70")
    dispatch = stations["ST70"]["orchestration"]["jobDispatch"]
    duration = dispatch.get("durationSeconds", 0)
    if (dispatch["stationId"] != "ST60" or type(duration) not in (int, float)
            or not 0 <= duration <= 2_147_483.647 or abs(duration * 1000 - round(duration * 1000)) > 1e-7):
        raise ValueError("ST70: expected a job duration in seconds with millisecond precision for ST60")
    if stations["ST60"]["orchestration"]["operations"] or stations["ST60"]["orchestration"].get("interrupt"):
        raise ValueError("This offline profile does not lower configured ST60 operations")
    points = _field_addresses(workspace)
    claimed: set[str] = set()
    tag_tables: dict[str, list[dict[str, str]]] = {}
    modules = []
    for sid in _STATIONS[:5]:
        tags: list[dict[str, str]] = []
        modules.append(_station_source(stations[sid], points, claimed, tags))
        tag_tables[f"IO_{sid}"] = tags
    if claimed != points.keys():
        raise ValueError("I/O point table contains unbound points")

    sensor = _fb(_CM_SENSOR, ["Signal : Bool"], ["Present : Bool"], [])
    sensor.emit("    #Present := #Signal;")
    sensor.emit("END_FUNCTION_BLOCK")
    hmi = _db("DB_HMI_KukaCell", [
        f"ST70_WorkDurationMs : DInt := {round(duration * 1000)}",
        "ST70_JobRequest : Bool", "ST60_JobAccepted : Bool", "ST60_JobFinished : Bool",
        *(f"{mod.station_id}_ActiveStep : Int" for mod in modules),
        *(f"{mod.station_id}_CmFault : Bool" for mod in modules),
    ])
    return AfFolderProject(
        sources=[
            ("AF/ControlModules/Drivers", emit_cylinder(_fb, _CM_CYLINDER).content() + "\n" + sensor.content()),
            ("AF/IO", _field_io(tag_tables)),
            *((f"AF/EquipmentModules/{mod.station_id}", mod.source) for mod in modules),
            ("AF/HMI", hmi),
            ("AF/Units/KukaCell", _unit_source(modules)),
        ],
        tag_tables=tag_tables,
    )
