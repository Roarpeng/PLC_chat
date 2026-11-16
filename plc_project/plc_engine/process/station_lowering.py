"""Compile the station canvas into AF-organized SCL, with one FB per driver."""
from __future__ import annotations

from plc_engine.engineering_ir.hashing import sha256_prefixed
from plc_engine.engineering_ir.station_catalog import ACTIONS, PROFILES
from plc_engine.engineering_ir.station_design import DRIVERS, Flow, StationDesign, design_issues
from plc_engine.engineering_ir.station_parallel import parallel_regions
from plc_engine.engineering_ir.station_ports import DEFAULTS, NON_EXECUTABLE, SCL_TYPES, scl_value
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.scl_lowering import SclBuilder
from plc_engine.process.station_cylinder import ALARM_EXTEND_TIMEOUT, ALARM_RETRACT_TIMEOUT, emit_cylinder
from plc_engine.process.station_signal_lowering import SignalLowering
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
    if kind == "cylinder":
        return emit_cylinder(_fb)
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


def _input(condition, devices, signals) -> str:
    address = signals[devices[condition.device_id].bindings[condition.port]].address
    return address if condition.value else f"NOT {address}"


def _writes(node, devices) -> dict[str, bool]:
    if not node.actions:
        return {f"R_{node.device_id}_{node.port}": node.value}
    return {
        f"R_{reference.device_id}_{port}": value
        for reference in node.actions
        for port, value in ACTIONS[devices[reference.device_id].driver][reference.action_id]["outputs"].items()
    }


def _action(block, node, devices, signals, *, started, next_step, timeout, blocked, stop, indent, permit=None):
    def emit(line, level=0, ref=None):
        block.emit(indent + "    " * level + line, ir_id=ref or node.id)

    conditions = [(rule, _input(rule, devices, signals)) for rule in node.permissions]
    faults = [
        f"(NOT ({term}))" if rule.mode == "continuous" and rule.blocked == "fault"
        else f"({started} AND NOT ({term}))" if rule.mode == "continuous"
        else f"(NOT {started} AND NOT ({term}))"
        for rule, term in conditions if rule.mode == "continuous" or rule.blocked == "fault"
    ]
    waits = [f"(NOT ({term}))" for rule, term in conditions if rule.blocked == "wait"]
    if permit:
        waits.append(f"(NOT ({permit}))")
    writes = _writes(node, devices)
    level = 0
    if faults:
        emit("IF " + " OR ".join(faults) + " THEN")
        for rule, _ in conditions:
            emit("// Action permission", 1, rule.id)
        emit(stop, 1)
        emit(blocked, 1)
        level = 1
    if waits:
        emit(("ELSIF " if faults else "IF ") + f"NOT {started} AND (" + " OR ".join(waits) + ") THEN")
        for name in writes:
            emit(f"#{name} := FALSE;", 1)
        level = 1
    if level:
        emit("ELSE")
    for name, value in writes.items():
        emit(f"#{name} := {'TRUE' if value else 'FALSE'};", level)
    if node.completion:
        cylinder_actions = [(item.device_id, item.action_id) for item in node.actions if devices[item.device_id].driver == "cylinder"]
        commands = {"extend": (1, ALARM_EXTEND_TIMEOUT), "retract": (2, ALARM_RETRACT_TIMEOUT)}
        device_done = [f"(#D_{key}.Done AND (#D_{key}.ActiveRequest = {commands[action][0]}))" for key, action in cylinder_actions]
        driver_timeouts = [f"(#D_{key}.AlarmId = {commands[action][1]})" for key, action in cylinder_actions]
        completion = " AND ".join([*(_input(item, devices, signals) for item in node.completion), *device_done])
        emit(f"IF {started} AND ({completion}) THEN", level)
        emit(next_step, level + 1)
        emit("ELSIF " + " OR ".join([f"#T_{node.id}.Q", *driver_timeouts]) + " THEN", level)
        emit(stop, level + 1)
        emit(timeout, level + 1)
        emit("END_IF;", level)
    else:
        emit(next_step, level)
    if started.startswith("#A_"):
        emit(f"{started} := TRUE;", level)
    if level:
        emit("END_IF;")


def _manual_fields(devices):
    return [f"{prefix}_{item.id} : USInt" for item in devices for prefix in ("M_Mode", "M_Request")]


def _station(station, signals, index: int) -> tuple[SclBuilder, SclBuilder, str]:
    # A stable EM name maps to the confirmed station ID. Instances live in its DB.
    name = f"U1Em{index}_{station.id}"
    devices = {device.id: device for device in station.devices}
    cylinders = [item for item in station.devices if item.driver == "cylinder"]
    interface = next((item for item in station.flow.nodes if item.kind == "interface"), None)
    signals_ir = SignalLowering(station.flow, station, {})
    device_interfaces = {entry.device_id: entry.id for entry in station.flow.nodes if entry.kind == "device"}
    requests = [
        f"R_{device.id}_{port}" for device in station.devices
        for port, direction in DRIVERS[device.driver].items() if direction == "output"
    ]
    numbers = _numbers(station.flow)
    links = _links(station.flow, numbers)
    regions, _ = parallel_regions(station.flow, project=False)
    members = {item.id: fork for fork, region in regions.items() for item in region.branches}
    started = {node.id: f"#A_{numbers[node.id]}" for node in station.flow.nodes
               if node.permissions or node.id in members or signals_ir.graph.wired(node.id, "permit")}
    completed = {key: f"#C_{numbers[key]}" for key in members}
    timers = {node.id: node.timeout_ms if node.device_id or node.completion else node.duration_ms
              for node in station.flow.nodes if node.kind == "wait" or (node.actions and node.completion)}
    tracks_entry = any(node.actions and node.completion and node.id not in started for node in station.flow.nodes)
    preset_devices = {item.device_id for node in station.flow.nodes for item in node.actions}
    cylinder_modes, cylinder_args = {}, {}
    for device in cylinders:
        def port(key, fallback):
            owner = device_interfaces.get(device.id)
            return signals_ir.input(owner, key, fallback) if owner else fallback

        def default_timeout(action):
            return max((node.timeout_ms for node in station.flow.nodes for call in node.actions
                        if call.device_id == device.id and call.action_id == action), default=device.timeout_ms)

        extend = device.extend_timeout_ms or default_timeout("extend")
        retract = device.retract_timeout_ms or default_timeout("retract")
        mode = port("mode", f"#M_Mode_{device.id}")
        cylinder_modes[device.id] = mode
        cylinder_args[device.id] = [
            f"Mode := {mode}", f"ManualRequest := {port('manual_request', f'#M_Request_{device.id}')}",
            f"Enable := {port('enable', 'TRUE')}", f"Reset := #Reset OR ({port('reset', 'FALSE')})",
            f"ExtendTimeout := {port('extend_timeout', f'T#{extend}ms')}",
            f"RetractTimeout := {port('retract_timeout', f'T#{retract}ms')}",
        ]
    permit_conditions = ["#Permit", *(f"({value}) = 0" for value in cylinder_modes.values()),
                         *(_input(item, devices, signals) for item in station.interlocks)]
    automatic = " AND ".join(f"({item})" for item in permit_conditions)
    manual_interlocks = " AND ".join(_input(item, devices, signals) for item in station.interlocks) or "TRUE"
    extras_in = [f"X_{item.id} : {SCL_TYPES[item.type]}" for item in station.public_ports if item.direction == "input"]
    extras_out = [f"X_{item.id} : {SCL_TYPES[item.type]}" for item in station.public_ports if item.direction == "output"]
    block = _fb(
        f"FB_{name}", ["Run : Bool", "Permit : Bool := TRUE", "Reset : Bool",
                       *(["ManualPermit : Bool", *_manual_fields(cylinders)] if cylinders else []), *extras_in],
        ["Done : Bool", "Fault : Bool", "StepNo : Int", "Ready : Bool", "Busy : Bool", "Accepted : Bool",
         "AlarmId : DInt", *extras_out],
        ["Step : Int", *(["PreviousStep : Int", "FirstScan : Bool"] if tracks_entry else []),
         *[f"{value[1:]} : Bool" for value in [*started.values(), *completed.values()]],
         *[f"{item} : Bool" for item in requests],
         *[f'D_{device.id} : "FB_AF_DRV_{device.driver}"' for device in station.devices],
         *[f"T_{key} : TON_TIME" for key in timers]],
    )
    for key, flag in started.items():
        finished = f" {completed[key]} := FALSE;" if key in completed else ""
        block.emit(f"    IF NOT #Run OR (#Step <> {numbers[members.get(key, key)]}) THEN {flag} := FALSE;{finished} END_IF;", ir_id=key)
    for key, timeout in timers.items():
        gate = f" AND {started[key]}" if key in started else ""
        if key in completed:
            gate += f" AND NOT {completed[key]}"
        block.emit(f"    #T_{key}(IN := #Run AND (#Step = {numbers[members.get(key, key)]}){gate}, PT := T#{timeout}ms);", ir_id=key)
    if tracks_entry:
        block.emit("    #FirstScan := #Step <> #PreviousStep;")
        block.emit("    #PreviousStep := #Step;")
    block.emit("    IF NOT #Run OR #Reset THEN", ir_id=station.id)
    block.emit("        #Step := 0;")
    block.emit("        IF #Reset THEN #Done := FALSE; #Fault := FALSE; END_IF;")
    for req in requests:
        block.emit(f"        #{req} := FALSE;")
    block.emit(f"    ELSIF NOT ({automatic}) THEN", ir_id=station.interlocks[0].id if station.interlocks else station.id)
    block.emit("        #Fault := TRUE;")
    block.emit("    ELSIF NOT #Fault THEN")
    block.emit("        CASE #Step OF")
    block.emit(f"            0: #Done := FALSE; #Step := {numbers[station.flow.start]};", ir_id=station.id)
    for node in station.flow.nodes:
        if node.id in members or node.kind in NON_EXECUTABLE:
            continue
        block.emit(f"            {numbers[node.id]}:", ir_id=node.id)
        target = lambda outcome: links[(node.id, outcome)]
        match node.kind:
            case "done":
                block.emit("                #Done := TRUE;", ir_id=node.id)
            case "fault":
                block.emit("                #Fault := TRUE;", ir_id=node.id)
            case "start" | "join":
                block.emit(f"                #Step := {target('next')};", ir_id=node.id)
            case "action":
                stop = " ".join(f"#{name} := FALSE;" for name in _writes(node, devices))
                _action(block, node, devices, signals, started=started.get(node.id, "NOT #FirstScan"),
                        next_step=f"#Step := {target('next')};",
                        timeout=f"#Step := {links.get((node.id, 'timeout'), 0)};",
                        blocked=f"#Step := {links.get((node.id, 'blocked'), 0)};", stop=stop, indent="                ",
                        permit=signals_ir.input(node.id, "permit") if signals_ir.graph.wired(node.id, "permit") else None)
            case "fork":
                region = regions[node.id]
                stop = " ".join(f"#{name} := FALSE;" for arm in region.branches for name in _writes(arm, devices))
                for arm in region.branches:
                    block.emit(f"                IF (#Step = {numbers[node.id]}) AND NOT {completed[arm.id]} THEN", ir_id=arm.id)
                    _action(block, arm, devices, signals, started=started[arm.id],
                            next_step=f"{completed[arm.id]} := TRUE;",
                            timeout=f"#Step := {links.get((arm.id, 'timeout'), 0)};",
                            blocked=f"#Step := {links.get((arm.id, 'blocked'), 0)};", stop=stop, indent="                    ",
                            permit=signals_ir.input(arm.id, "permit") if signals_ir.graph.wired(arm.id, "permit") else None)
                    monitoring = [_input(rule, devices, signals) for rule in arm.permissions if rule.mode == "continuous"]
                    if monitoring:
                        block.emit(f"                ELSIF (#Step = {numbers[node.id]}) AND NOT ({' AND '.join(monitoring)}) THEN", ir_id=arm.id)
                        block.emit(f"                    {stop} #Step := {links[arm.id, 'blocked']};", ir_id=arm.id)
                    block.emit("                END_IF;")
                all_done = " AND ".join(completed[arm.id] for arm in region.branches)
                block.emit(f"                IF (#Step = {numbers[node.id]}) AND {all_done} THEN #Step := {numbers[region.join_id]}; END_IF;", ir_id=node.id)
            case "wait" | "decision":
                if signals_ir.graph.wired(node.id, "condition"):
                    term = signals_ir.input(node.id, "condition")
                    condition = f"({term})" if node.value else f"NOT ({term})"
                elif node.device_id:
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
    block.emit("    #AlarmId := 0;")
    for device in station.devices:
        timeout = 0 if device.id in preset_devices else device.timeout_ms
        auto = f"#Run AND NOT #Reset AND NOT #Fault AND NOT #Done AND ({automatic})"
        if device.id in cylinder_args:
            manual = f"#ManualPermit AND #Permit AND NOT #Run AND NOT #Reset AND ({manual_interlocks}) AND (({cylinder_modes[device.id]}) = 1)"
            args = [f"Permit := ({auto}) OR ({manual})", *cylinder_args[device.id]]
        else:
            args = [f"Permit := {auto}", f"Timeout := T#{timeout}ms"]
        for port, direction in DRIVERS[device.driver].items():
            address = signals[device.bindings[port]].address
            if direction == "output":
                args.append(f"Req_{port} := #R_{device.id}_{port}")
            else:
                args.append(f"In_{port} := {address}")
        block.emit(f"    #D_{device.id}({', '.join(args)});", ir_id=device.id)
    for device in station.devices:
        if device.id in cylinder_args:
            code = f"#D_{device.id}.AlarmId"
            block.emit(f"    IF #D_{device.id}.Fault THEN", ir_id=device.id)
            block.emit(f"        IF #AlarmId = 0 THEN #AlarmId := {code}; END_IF;")
            exemptions = []
            for node in station.flow.nodes:
                matches = [item for item in node.actions if item.device_id == device.id]
                if not matches:
                    continue
                alarm = ALARM_EXTEND_TIMEOUT if matches[0].action_id == "extend" else ALARM_RETRACT_TIMEOUT
                exemptions.append(f"((#Step = {numbers[members.get(node.id, node.id)]}) AND ({code} = {alarm}))")
                next_id = next((edge.to_id for edge in station.flow.edges if edge.from_id == node.id and edge.outcome == "timeout"), None)
                if next_id:
                    exemptions.append(f"((#Step = {numbers[next_id]}) AND ({code} = {alarm}))")
            handled = " OR ".join(exemptions) or "FALSE"
            block.emit(f"        IF #Run AND NOT ({handled}) THEN #Fault := TRUE; END_IF;")
            block.emit("    END_IF;")
        else:
            block.emit(f"    IF #D_{device.id}.Fault THEN #Fault := TRUE; IF #AlarmId = 0 THEN #AlarmId := 9000; END_IF; END_IF;", ir_id=device.id)
    for device in station.devices:
        for port, direction in DRIVERS[device.driver].items():
            if direction == "output":
                address = signals[device.bindings[port]].address
                block.emit(f"    {address} := #D_{device.id}.Q_{port} AND NOT #Fault;", ir_id=device.id)
    block.emit("    #StepNo := #Step;", ir_id=station.id)
    block.emit("    IF #Fault AND (#AlarmId = 0) THEN #AlarmId := 9000; END_IF;")
    block.emit(f"    #Ready := NOT #Run AND NOT #Reset AND NOT #Fault AND (#AlarmId = 0) AND ({automatic});")
    block.emit("    #Accepted := #Run AND (#Step <> 0) AND NOT #Fault;")
    block.emit("    #Busy := #Accepted AND NOT #Done;")
    for item in station.public_ports:
        if item.direction == "output":
            fallback = scl_value(item.type, DEFAULTS[item.type] if item.default is None else item.default)
            term = signals_ir.input(interface.id, item.id, fallback) if interface else fallback
            block.emit(f"    IF #Reset THEN #X_{item.id} := {fallback}; ELSIF #Run THEN #X_{item.id} := {term}; END_IF;",
                       ir_id=interface.id if interface else station.id)
    block.emit("END_FUNCTION_BLOCK")
    db = _instance(f"DB_{name}", block.tia_block)
    return block, db, name


def _dispatch(design: StationDesign, station_names: dict[str, str]) -> list[SclBuilder]:
    flow = design.flow
    numbers = _numbers(flow)
    links = _links(flow, numbers)
    regions, _ = parallel_regions(flow, project=True)
    members = {item.id: fork for fork, region in regions.items() for item in region.branches}
    signals = {item.id: item for item in design.hardware.signals}
    stations = {item.id: item for item in design.stations}
    typed = SignalLowering(flow, None, stations, names=station_names)
    cylinders = [item for station in design.stations for item in station.devices if item.driver == "cylinder"]
    manual = ["ManualPermit : Bool", *_manual_fields(cylinders)] if cylinders else []
    handoffs = [node for node in flow.nodes if node.kind == "handoff"]
    handoff_vars = [f"{prefix}_{numbers[node.id]} : {kind}" for node in handoffs
                    for prefix, kind in (("H_Run", "Bool"), ("H_Ack", "Bool"), ("H_Time", "TON_TIME"))]
    wiring = {(wire.to_id, wire.to_port): (f"W_{index}", wire) for index, wire in enumerate(flow.wires, 1)}
    wire_vars = [f"{name} : {SCL_TYPES[typed.graph.ports[wire.to_id][wire.to_port].type]}"
                 for name, wire in wiring.values()]
    custom_inputs = {
        (station.id, port.id): (f"P_{index}_{port.id}", SCL_TYPES[port.type])
        for index, station in enumerate(design.stations, 1) for port in station.public_ports if port.direction == "input"
    }
    block = _fb("FB_U1_AF_Project", ["Start : Bool", "Reset : Bool", *manual], ["Done : Bool", "Fault : Bool"],
                ["Step : Int", "LastStart : Bool", "ResetScan : Bool", *handoff_vars, *wire_vars,
                 *[f"{name} : {type_}" for name, type_ in custom_inputs.values()]])

    def input_value(node, key, fallback):
        entry = wiring.get((node.id, key))
        return f"#{entry[0]}" if entry else fallback

    def select_option(nodes, key, fallback):
        options = [(item, input_value(item, key, fallback)) for item in nodes if typed.graph.wired(item.id, key)]
        return options
    block.emit("    IF #Reset THEN")
    block.emit("        #Step := 0; #Done := FALSE; #Fault := FALSE; #ResetScan := FALSE;")
    block.emit("    ELSIF #Start AND NOT #LastStart AND (#Step = 0) THEN")
    block.emit(f"        #Step := {numbers[flow.start]}; #Done := FALSE; #Fault := FALSE;")
    block.emit("    END_IF;")
    block.emit("    #LastStart := #Start;")
    for name, wire in wiring.values():
        value = typed.input(wire.to_id, wire.to_port)
        block.emit(f"    #{name} := {value};", ir_id=wire.id)
    for node in handoffs:
        step = numbers[node.id]
        station_name = station_names[node.station_ids[0]]
        permit = input_value(node, "permit", "TRUE")
        block.emit(f"    IF #Reset OR #ResetScan OR (#Step <> {step}) THEN", ir_id=node.id)
        block.emit(f"        #H_Run_{step} := FALSE; #H_Ack_{step} := FALSE;")
        block.emit(f'    ELSIF ({permit}) AND "DB_{station_name}".Ready THEN #H_Run_{step} := TRUE;')
        block.emit("    END_IF;")
        block.emit(f"    #H_Time_{step}(IN := (#Step = {step}) AND NOT #H_Ack_{step} AND NOT #Reset, PT := T#{node.timeout_ms}ms);")
    for station_id, name in station_names.items():
        callers = [item for item in flow.nodes if station_id in item.station_ids]
        active = [f"(#Step = {numbers[members.get(node.id, node.id)]})" for node in callers if node.kind != "handoff"]
        active.extend(f"((#Step = {numbers[node.id]}) AND #H_Run_{numbers[node.id]})" for node in callers if node.kind == "handoff")
        condition = " OR ".join(active) or "FALSE"
        # Inline the selected call's permit and reset. Custom values use the snapshot
        # taken before running any EM so station ordering does not affect data sampling.
        bad = " OR ".join(f"((#Step = {numbers[members.get(item.id, item.id)]}) AND NOT {value})"
                          for item, value in select_option(callers, "permit", "TRUE")) or "FALSE"
        resets = " OR ".join(f"((#Step = {numbers[members.get(item.id, item.id)]}) AND {value})"
                             for item, value in select_option(callers, "reset", "FALSE")) or "FALSE"
        args = [f"Run := NOT #Reset AND NOT #ResetScan AND ({condition})", f"Permit := NOT ({bad})",
                f"Reset := #Reset OR ({resets})"]
        local = [item for item in stations[station_id].devices if item.driver == "cylinder"]
        if local:
            args.append("ManualPermit := #ManualPermit AND (#Step = 0) AND NOT #Start")
            args.extend(f"{prefix}_{item.id} := #{prefix}_{item.id}" for item in local for prefix in ("M_Mode", "M_Request"))
        for item in stations[station_id].public_ports:
            if item.direction != "input":
                continue
            fallback = scl_value(item.type, DEFAULTS[item.type] if item.default is None else item.default)
            cases = select_option(callers, item.id, fallback)
            if cases:
                token = custom_inputs[station_id, item.id][0]
                block.emit(f"    #{token} := {fallback};")
                for caller, value in cases:
                    block.emit(f"    IF #Step = {numbers[members.get(caller.id, caller.id)]} THEN #{token} := {value}; END_IF;",
                               ir_id=caller.id)
                fallback = f"#{token}"
            args.append(f"X_{item.id} := {fallback}")
        block.emit(f'    "DB_{name}"({", ".join(args)});', ir_id=station_id)
    block.emit("    IF #ResetScan THEN")
    block.emit("        #ResetScan := FALSE;")
    block.emit("    ELSIF NOT #Reset THEN")
    block.emit("        CASE #Step OF")
    block.emit("            0: ;")
    for node in flow.nodes:
        if node.id in members or node.kind in NON_EXECUTABLE:
            continue
        block.emit(f"            {numbers[node.id]}:", ir_id=node.id)
        if node.kind == "done":
            block.emit("                #Done := TRUE; #Step := 0;", ir_id=node.id)
        elif node.kind == "fault":
            block.emit("                #Fault := TRUE; #Step := 0;", ir_id=node.id)
        elif node.kind in ("start", "join"):
            block.emit(f"                #Step := {links[node.id, 'next']};", ir_id=node.id)
        elif node.kind == "decision":
            source = input_value(node, "condition", signals[node.signal_id].address if node.signal_id else "FALSE")
            condition = source if node.value else f"NOT ({source})"
            block.emit(f"                IF {condition} THEN #Step := {links[node.id, 'true']};", ir_id=node.id)
            block.emit(f"                ELSE #Step := {links[node.id, 'false']}; END_IF;", ir_id=node.id)
        elif node.kind == "fork":
            region = regions[node.id]
            done = []
            for index, arm in enumerate(region.branches):
                name = station_names[arm.station_ids[0]]
                block.emit(f'                {"IF" if index == 0 else "ELSIF"} "DB_{name}".Fault THEN', ir_id=arm.id)
                block.emit(f"                    #Step := {links[arm.id, 'fault']}; #ResetScan := TRUE;", ir_id=arm.id)
                done.append(f'"DB_{name}".Done')
            block.emit(f"                ELSIF {' AND '.join(done)} THEN")
            block.emit(f"                    #Step := {numbers[region.join_id]}; #ResetScan := TRUE;", ir_id=region.join_id)
            block.emit("                END_IF;")
        elif node.kind == "handoff":
            step = numbers[node.id]
            name = station_names[node.station_ids[0]]
            block.emit(f'                IF "DB_{name}".Fault THEN', ir_id=node.id)
            block.emit(f"                    #Step := {links[node.id, 'fault']}; #ResetScan := TRUE;")
            block.emit(f"                ELSIF #H_Time_{step}.Q AND NOT #H_Ack_{step} THEN")
            block.emit(f"                    #Step := {links[node.id, 'timeout']}; #ResetScan := TRUE;")
            block.emit(f'                ELSIF #H_Run_{step} AND "DB_{name}".Accepted THEN')
            block.emit(f"                    #H_Ack_{step} := TRUE;")
            block.emit(f'                    IF "DB_{name}".Done THEN #Step := {links[node.id, "done"]}; #ResetScan := TRUE; END_IF;')
            block.emit("                END_IF;")
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
    for declaration in manual:
        interface.emit(f"    {declaration};")
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
    for declaration in manual:
        field = declaration.split(" ", 1)[0]
        main.emit(f'        {field} := "DB_U1_AF_Control".{field},')
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
        receipt={"generator": "StationCanvas/2", "driver_interfaces": {
            key: "2.0" if key == "cylinder" else "1.0" for key in sorted({device.driver for station in design.stations for device in station.devices})
        }, "software_units": {"U1": names}, "hardware": design.hardware.model_dump()},
    )
    manifest.refresh_hash()
    manifest.manifest_id = f"man_{manifest.sha256[7:19]}"
    return manifest, source
