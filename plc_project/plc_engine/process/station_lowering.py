"""Compile the station canvas into AF-organized SCL, with one FB per driver."""
from __future__ import annotations

from plc_engine.engineering_ir.hashing import sha256_prefixed
from plc_engine.engineering_ir.station_catalog import ACTIONS, PROFILES
from plc_engine.engineering_ir.station_design import DRIVERS, Flow, StationDesign, design_issues
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.scl_lowering import SclBuilder
from plc_engine.process.source_map import SourceMap


def _new_block(name: str, block_type: str) -> SclBuilder:
    return SclBuilder(scl_file=f"scl/{name}.scl", tia_block=name, block_type=block_type)


def _fb(name: str, inputs: list[str], outputs: list[str], local: list[str]) -> SclBuilder:
    block = _new_block(name, "FB")
    block.emit(f'FUNCTION_BLOCK "{name}"')
    block.emit("{ S7_Optimized_Access := 'TRUE' }")
    for section, fields in (("VAR_INPUT", inputs), ("VAR_OUTPUT", outputs), ("VAR", local)):
        block.emit(section)
        for field in fields:
            block.emit(f"    {field};")
        block.emit("END_VAR")
    block.emit("BEGIN")
    return block


def _instance(name: str, block_name: str) -> SclBuilder:
    block = _new_block(name, "DB")
    block.emit(f'DATA_BLOCK "{name}"')
    block.emit("{ S7_Optimized_Access := 'TRUE' }")
    block.emit(f'    "{block_name}"')
    block.emit("BEGIN")
    block.emit("END_DATA_BLOCK")
    return block


def _driver(kind: str) -> SclBuilder:
    ports = DRIVERS[kind]
    outputs = [name for name, direction in ports.items() if direction == "output"]
    feedback = [name for name, direction in ports.items() if direction == "input"]
    block = _fb(
        f"FB_AF_DRV_{kind}", ["Permit : Bool", "Timeout : Time",
                              *[f"Req_{port} : Bool" for port in outputs],
                              *[f"In_{port} : Bool" for port in feedback]],
        ["Fault : Bool", *[f"Q_{port} : Bool" for port in outputs],
         *[f"State_{port} : Bool" for port in feedback]],
        ["Watchdog : TON_TIME"] if outputs else [],
    )
    for port in feedback:
        block.emit(f"    #State_{port} := #In_{port};")
    profile = PROFILES[kind]
    waiting = []
    for preset in profile["actions"]:
        if not any(preset["outputs"].values()) or not preset["feedback"]:
            continue
        requests = " AND ".join(("" if value else "NOT ") + f"#Req_{port}" for port, value in preset["outputs"].items())
        completion = " AND ".join(("" if value else "NOT ") + f"#In_{port}" for port, value in preset["feedback"].items())
        waiting.append(f"({requests} AND NOT ({completion}))")
    hazards = [f"(#Req_{left} AND #Req_{right})" for left, right in profile["exclusive"]]
    if profile["fault_port"]:
        hazards.append(f"#In_{profile['fault_port']}")
    if outputs:
        block.emit(f"    #Watchdog(IN := #Permit AND (#Timeout > T#0ms) AND ({' OR '.join(waiting) or 'FALSE'}), PT := #Timeout);")
        block.emit(f"    #Fault := #Permit AND ({' OR '.join([*hazards, '#Watchdog.Q'])});")
        for port in outputs:
            block.emit(f"    #Q_{port} := #Permit AND NOT #Fault AND #Req_{port};")
    else:
        block.emit("    #Fault := FALSE;")
    block.emit("END_FUNCTION_BLOCK")
    return block


def _numbers(flow: Flow) -> dict[str, int]:
    return {node.id: (index + 1) * 10 for index, node in enumerate(flow.nodes)}


def _links(flow: Flow, numbers: dict[str, int]) -> dict[tuple[str, str], int]:
    return {(edge.from_id, edge.outcome): numbers[edge.to_id] for edge in flow.edges}


def _station(station, signals, index: int) -> tuple[SclBuilder, SclBuilder, str]:
    # A stable EM name maps to the confirmed station ID. Instances live in its DB.
    name = f"U1Em{index}_{station.id}"
    devices = {device.id: device for device in station.devices}
    requests = [
        f"R_{device.id}_{port}" for device in station.devices
        for port, direction in DRIVERS[device.driver].items() if direction == "output"
    ]
    numbers = _numbers(station.flow)
    links = _links(station.flow, numbers)
    timers = {node.id: node.timeout_ms if node.device_id or node.completion else node.duration_ms
              for node in station.flow.nodes if node.kind == "wait" or (node.actions and node.completion)}
    tracks_entry = any(node.actions and node.completion for node in station.flow.nodes)
    preset_devices = {item.device_id for node in station.flow.nodes for item in node.actions}
    block = _fb(
        f"FB_{name}", ["Run : Bool"], ["Done : Bool", "Fault : Bool", "StepNo : Int"],
        ["Step : Int", *(["PreviousStep : Int", "FirstScan : Bool"] if tracks_entry else []),
         *[f"{item} : Bool" for item in requests],
         *[f'D_{device.id} : "FB_AF_DRV_{device.driver}"' for device in station.devices],
         *[f"T_{key} : TON_TIME" for key in timers]],
    )
    for key, timeout in timers.items():
        block.emit(f"    #T_{key}(IN := #Run AND (#Step = {numbers[key]}), PT := T#{timeout}ms);", ir_id=key)
    if tracks_entry:
        block.emit("    #FirstScan := #Step <> #PreviousStep;")
        block.emit("    #PreviousStep := #Step;")
    block.emit("    IF NOT #Run THEN", ir_id=station.id)
    block.emit("        #Step := 0;")
    block.emit("        #Done := FALSE;")
    block.emit("        #Fault := FALSE;")
    for req in requests:
        block.emit(f"        #{req} := FALSE;")
    if station.interlocks:
        terms = []
        for condition in station.interlocks:
            address = signals[devices[condition.device_id].bindings[condition.port]].address
            terms.append(address if condition.value else f"NOT {address}")
        block.emit(f"    ELSIF NOT ({' AND '.join(terms)}) THEN", ir_id=station.interlocks[0].id)
        for condition in station.interlocks:
            block.emit("        #Fault := TRUE;", ir_id=condition.id)
    block.emit("    ELSE")
    block.emit("        CASE #Step OF")
    block.emit(f"            0: #Step := {numbers[station.flow.start]};", ir_id=station.id)
    for node in station.flow.nodes:
        block.emit(f"            {numbers[node.id]}:", ir_id=node.id)
        target = lambda outcome: links[(node.id, outcome)]
        match node.kind:
            case "done":
                block.emit("                #Done := TRUE;", ir_id=node.id)
            case "fault":
                block.emit("                #Fault := TRUE;", ir_id=node.id)
            case "action":
                if node.actions:
                    for reference in node.actions:
                        preset = ACTIONS[devices[reference.device_id].driver][reference.action_id]
                        for port, value in preset["outputs"].items():
                            block.emit(f"                #R_{reference.device_id}_{port} := {'TRUE' if value else 'FALSE'};", ir_id=node.id)
                else:
                    block.emit(f"                #R_{node.device_id}_{node.port} := {'TRUE' if node.value else 'FALSE'};", ir_id=node.id)
                if node.completion:
                    conditions = []
                    for condition in node.completion:
                        address = signals[devices[condition.device_id].bindings[condition.port]].address
                        conditions.append(address if condition.value else f"NOT {address}")
                    block.emit(f"                IF NOT #FirstScan AND ({' AND '.join(conditions)}) THEN", ir_id=node.id)
                    block.emit(f"                    #Step := {target('next')};", ir_id=node.id)
                    block.emit(f"                ELSIF #T_{node.id}.Q THEN #Step := {target('timeout')};", ir_id=node.id)
                    block.emit("                END_IF;")
                else:
                    block.emit(f"                #Step := {target('next')};", ir_id=node.id)
            case "wait" | "decision":
                if node.device_id:
                    device = devices[node.device_id]
                    address = signals[device.bindings[node.port]].address
                    condition = address if node.value else f"NOT {address}"
                else:
                    condition = f"#T_{node.id}.Q"
                yes = "true" if node.kind == "decision" else "next"
                block.emit(f"                IF {condition} THEN", ir_id=node.id)
                block.emit(f"                    #Step := {target(yes)};", ir_id=node.id)
                if node.kind == "decision":
                    block.emit(f"                ELSE #Step := {target('false')};", ir_id=node.id)
                elif node.device_id:
                    block.emit(f"                ELSIF #T_{node.id}.Q THEN #Step := {target('timeout')};", ir_id=node.id)
                block.emit("                END_IF;")
    block.emit("            ELSE #Fault := TRUE;")
    block.emit("        END_CASE;")
    block.emit("    END_IF;")
    for device in station.devices:
        timeout = 0 if device.id in preset_devices else device.timeout_ms
        args = ["Permit := #Run AND NOT #Fault AND NOT #Done", f"Timeout := T#{timeout}ms"]
        for port, direction in DRIVERS[device.driver].items():
            address = signals[device.bindings[port]].address
            if direction == "output":
                args.append(f"Req_{port} := #R_{device.id}_{port}")
            else:
                args.append(f"In_{port} := {address}")
        block.emit(f"    #D_{device.id}({', '.join(args)});", ir_id=device.id)
    for device in station.devices:
        block.emit(f"    IF #D_{device.id}.Fault THEN #Fault := TRUE; END_IF;", ir_id=device.id)
    for device in station.devices:
        for port, direction in DRIVERS[device.driver].items():
            if direction == "output":
                address = signals[device.bindings[port]].address
                block.emit(f"    {address} := #D_{device.id}.Q_{port} AND NOT #Fault;", ir_id=device.id)
    block.emit("    #StepNo := #Step;", ir_id=station.id)
    block.emit("END_FUNCTION_BLOCK")
    db = _instance(f"DB_{name}", block.tia_block)
    return block, db, name


def _dispatch(design: StationDesign, station_names: dict[str, str]) -> list[SclBuilder]:
    flow = design.flow
    numbers = _numbers(flow)
    links = _links(flow, numbers)
    block = _fb("FB_U1_AF_Project", ["Start : Bool", "Reset : Bool"], ["Done : Bool", "Fault : Bool"],
                ["Step : Int", "LastStart : Bool", "ResetScan : Bool"])
    block.emit("    IF #Reset THEN")
    block.emit("        #Step := 0; #Done := FALSE; #Fault := FALSE; #ResetScan := FALSE;")
    block.emit("    ELSIF #Start AND NOT #LastStart AND (#Step = 0) THEN")
    block.emit(f"        #Step := {numbers[flow.start]}; #Done := FALSE; #Fault := FALSE;")
    block.emit("    END_IF;")
    block.emit("    #LastStart := #Start;")
    for station_id, name in station_names.items():
        active = [f"(#Step = {numbers[node.id]})" for node in flow.nodes if station_id in node.station_ids]
        condition = " OR ".join(active) or "FALSE"
        block.emit(f'    "DB_{name}"(Run := NOT #Reset AND NOT #ResetScan AND ({condition}));', ir_id=station_id)
    block.emit("    IF #ResetScan THEN")
    block.emit("        #ResetScan := FALSE;")
    block.emit("    ELSIF NOT #Reset THEN")
    block.emit("        CASE #Step OF")
    block.emit("            0: ;")
    for node in flow.nodes:
        block.emit(f"            {numbers[node.id]}:", ir_id=node.id)
        if node.kind == "done":
            block.emit("                #Done := TRUE; #Step := 0;", ir_id=node.id)
        elif node.kind == "fault":
            block.emit("                #Fault := TRUE; #Step := 0;", ir_id=node.id)
        else:
            names = [station_names[key] for key in node.station_ids]
            fault = " OR ".join(f'"DB_{name}".Fault' for name in names)
            done = " AND ".join(f'"DB_{name}".Done' for name in names)
            block.emit(f"                IF {fault} THEN", ir_id=node.id)
            block.emit(f"                    #Step := {links[(node.id, 'fault')]}; #ResetScan := TRUE;", ir_id=node.id)
            block.emit(f"                ELSIF {done} THEN", ir_id=node.id)
            block.emit(f"                    #Step := {links[(node.id, 'done')]}; #ResetScan := TRUE;", ir_id=node.id)
            block.emit("                END_IF;")
    block.emit("            ELSE #Fault := TRUE; #Step := 0;")
    block.emit("        END_CASE;")
    block.emit("    END_IF;")
    block.emit("END_FUNCTION_BLOCK")
    db = _instance("DB_U1_AF_Project", block.tia_block)
    interface = _new_block("DB_U1_AF_Control", "DB")
    interface.emit('DATA_BLOCK "DB_U1_AF_Control"')
    interface.emit("NON_RETAIN")
    interface.emit("STRUCT")
    for field in ("Start", "Reset", "Done", "Fault"):
        interface.emit(f"    {field} : Bool;")
    interface.emit("END_STRUCT;")
    interface.emit("BEGIN")
    interface.emit("END_DATA_BLOCK")
    main = _new_block("OB_U1_AF_Main", "OB")
    # Use the CPU's existing cyclic OB1. A new symbol alone leaves the OB
    # without an event assignment when imported via TIA external sources.
    main.tia_block = "Main"
    main.emit('ORGANIZATION_BLOCK "Main"')
    main.emit("{ S7_Optimized_Access := 'TRUE' }")
    main.emit("VERSION : 0.1")
    main.emit("BEGIN")
    main.emit('    "DB_U1_AF_Project"(Start := "DB_U1_AF_Control".Start, Reset := "DB_U1_AF_Control".Reset,')
    main.emit('        Done => "DB_U1_AF_Control".Done, Fault => "DB_U1_AF_Control".Fault);')
    main.emit("END_ORGANIZATION_BLOCK")
    return [block, db, interface, main]


def lower_station_design(ir) -> tuple[ArtifactManifest, SourceMap]:
    design = StationDesign.model_validate(ir.station_design)
    validation = design_issues(design, release=True)
    names: dict[str, str] = {}
    builders: list[SclBuilder] = []
    if not validation:
        types = sorted({item.driver for station in design.stations for item in station.devices})
        builders.extend(_driver(kind) for kind in types)
        signals = {item.id: item for item in design.hardware.signals}
        station_blocks = [_station(item, signals, index) for index, item in enumerate(design.stations, start=1)]
        names = {item.id: data[2] for item, data in zip(design.stations, station_blocks)}
        builders.extend(block for block, _, _ in station_blocks)
        scheduler, scheduler_db, interface, main = _dispatch(design, names)
        builders.append(scheduler)
        builders.extend(db for _, db, _ in station_blocks)
        builders.extend([scheduler_db, interface, main])
    digest = ir.ir_sha256 or ir.semantic_hash()
    profile = ir.af_profile
    source = SourceMap(map_id=f"smap_{digest[7:19]}", ir_sha256=digest, template_sha256=profile.template_sha256)
    files = []
    for block in builders:
        content = block.content()
        files.append(ArtifactFile(
            path=block.scl_file, sha256=sha256_prefixed(content), role=block.block_type,
            content=content, source_ids=sorted({row[2] for row in block.emissions}), tia_block=block.tia_block,
        ))
        for line, ir_id, source_id in block.emissions:
            source.add(ir_id=ir_id, scl_file=block.scl_file, scl_line=line, tia_block=block.tia_block,
                       tia_block_type=block.block_type, canvas_node_id=ir_id, source_id=source_id)
    manifest = ArtifactManifest(
        manifest_id="", af_profile_id=profile.profile_id, template_sha256=profile.template_sha256,
        ir_sha256=digest, files=files, import_order=[file.path for file in files],
        receipt={"generator": "StationCanvas/1", "software_units": {"U1": names}, "hardware": design.hardware.model_dump()},
    )
    manifest.refresh_hash()
    manifest.manifest_id = f"man_{manifest.sha256[7:19]}"
    return manifest, source
