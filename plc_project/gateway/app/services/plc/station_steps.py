"""Build station action steps from common Chinese instructions and the device catalog."""
from __future__ import annotations

import re
from uuid import uuid4

from plc_engine.engineering_ir.station_catalog import ACTIONS, PROFILES
from plc_engine.engineering_ir.station_ports import NON_EXECUTABLE
from plc_engine.engineering_ir.station_design import Device, DeviceAction, Edge, Feedback, Flow, Node, Station, outcomes

DURATION = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(毫秒|ms|秒|s)(?![a-z])", re.I)


def duration_ms(text: str) -> int | None:
    match = DURATION.search(text)
    if not match:
        return None
    value = round(float(match[1]) * (1 if match[2].lower() in ("毫秒", "ms") else 1000))
    if not 0 < value <= 86_400_000:
        raise ValueError("请输入大于零且不超过一天的时间。")
    return value


def _id(prefix: str) -> str:
    return prefix + "_" + uuid4().hex[:12]


def _words(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _named(device: Device, text: str) -> int:
    label = _words(device.name)
    return len(label) if label and label in text else 0


def _action_in(station: Station, clause: str) -> DeviceAction | None:
    text = _words(clause)
    candidates_by_device = [
        ((_named(device, text), max((len(name) for name in PROFILES[device.driver]["aliases"]
                                     if _words(name) in text), default=0)), device)
        for device in station.devices
    ]
    best_device = max((rank for rank, _ in candidates_by_device), default=(0, 0))
    candidates = []
    for rank, device in candidates_by_device:
        if rank != best_device:
            continue
        for action in ACTIONS[device.driver].values():
            matching = max((len(name) for name in action["aliases"] if _words(name) in text), default=0)
            if matching:
                candidates.append((matching, device, action))
    if not candidates:
        return None
    best = max(item[0] for item in candidates)
    matches = [(device, action) for score, device, action in candidates if score == best]
    if len(matches) > 1:
        labels = "、".join(dict.fromkeys(device.name for device, _ in matches))
        raise ValueError(f"「{clause}」可对应 {labels}，请写出要使用的设备名称。")
    device, preset = matches[0]
    return DeviceAction(device_id=device.id, action_id=preset["id"])


def _action_step(station: Station, references: list[DeviceAction]) -> Node:
    devices = {item.id: item for item in station.devices}
    names = []
    feedback = []
    timeouts = []
    for item in references:
        device = devices[item.device_id]
        preset = ACTIONS[device.driver][item.action_id]
        names.append(f"{device.name} · {preset['label']}")
        feedback.extend(Feedback(device_id=device.id, port=port, value=value) for port, value in preset["feedback"].items())
        if preset["feedback"]:
            timeouts.append(device.timeout_ms or preset["timeout_ms"])
    return Node(id=_id("step"), name=" + ".join(names)[:100], kind="action",
                actions=references, completion=feedback, timeout_ms=max(timeouts, default=0))


def _waiting(station: Station, text: str, previous: Node | None) -> Node | None:
    description = re.sub(r"^(等待|等到|等)|(?:后|以后)$", "", text).strip()
    if not description:
        raise ValueError("请描述要等待的反馈。")
    phrase = _words(description)
    devices = {item.id: item for item in station.devices}
    if re.search(r"未|没有|不在|不到|无料|未触发|=false", phrase):
        return Node(id=_id("step"), name=f"等待{description}"[:100], kind="wait",
                    pending_feedback=True, timeout_ms=2000)
    most_specific_name = max((_named(item, phrase) for item in station.devices), default=0)
    if previous and any(
        _named(devices[item.device_id], phrase) == most_specific_name
        and _words(PROFILES[devices[item.device_id].driver]["port_labels"].get(item.port, item.port)) in phrase
        for item in previous.completion if item.device_id in devices and item.value
    ):
        return None  # The preceding action already waits for this condition.
    candidates = []
    for device in station.devices:
        profile = PROFILES[device.driver]
        for port, direction in profile["ports"].items():
            if direction != "input":
                continue
            named = _named(device, phrase)
            condition = _words(profile["port_labels"][port])
            if named or condition in phrase:
                candidates.append(((named, len(condition) if condition in phrase else 0), device.id, port))
    if not candidates and re.search(r"工件到位|物料到位|有料", phrase):
        sensors = [item for item in station.devices if PROFILES[item.driver]["ports"] == {"active": "input"}]
        candidates.extend(((1, 0), item.id, "active") for item in sensors)
    ranked = [item for item in candidates if item[0] == max(entry[0] for entry in candidates)] if candidates else []
    if len(ranked) != 1:
        return Node(id=_id("step"), name=f"等待{description}"[:100], kind="wait",
                    pending_feedback=True, timeout_ms=2000)
    _, device_id, port = ranked[0]
    return Node(id=_id("step"), name=f"等待{description}"[:100], kind="wait",
                device_id=device_id, port=port, timeout_ms=devices[device_id].timeout_ms or 2000)


def _find_steps(station: Station, label: str, selection: str) -> list[Node]:
    phrase = _words(label)
    matches = []
    for node in station.flow.nodes:
        if node.kind in ("done", "fault"):
            continue
        if phrase and phrase in _words(node.name):
            matches.append(node)
        elif not phrase and node.id == selection:
            matches.append(node)
    return matches


def named_duration_step(station: Station, message: str) -> Node | None:
    match = re.match(r"^(?:把|将)?(.+?)(?:的)?(?:超时(?:时间)?|等待时间|保持时间)(?:改|设|调整|从)", message)
    if not match:
        return None
    label = match[1].strip(" 「」“”")
    choices = _find_steps(station, label, "")
    if len(choices) != 1:
        raise ValueError(f"「{label}」没有唯一匹配的步骤，请写出完整步骤名称。")
    return choices[0]


def insert_step(station: Station, selected: str, message: str) -> str | None:
    match = re.search(r"(?:在)?[「“]?([^，。；「」“”]+?)[」”]?(前|后)(?:面|方)?(?:先)?(?:插入|加一个|增加|加上|加个)(.+)", message)
    if not match and not (selected and re.match(r"^(?:插入|加一个|增加|加上|加个)(?:等待|延时)", message)):
        return None
    anchor = match[1].strip().removeprefix("在") if match else ""
    candidates = _find_steps(station, anchor, selected)
    if len(candidates) != 1:
        raise ValueError("请选择要插入等待的步骤，或说「在松开前插入等待 300 ms」。")
    step = candidates[0]
    description = match[3].strip() if match else re.sub(r"^(?:插入|加一个|增加|加上|加个)", "", message)
    if description.startswith(("等待", "延时")):
        ms = duration_ms(description)
        added = Node(id=_id("step"), name=f"等待 {ms} ms", kind="wait", duration_ms=ms) if ms else _waiting(station, description, None)
    else:
        reference = _action_in(station, description)
        added = _action_step(station, [reference]) if reference else None
    if not added:
        raise ValueError("请指定要插入的设备动作或等待条件。")
    flow = station.flow
    before = not match or match[2] == "前"
    if before:
        flow.edges = [edge.model_copy(update={"to_id": added.id}) if edge.to_id == step.id else edge for edge in flow.edges]
        flow.edges.append(Edge(id=_id("edge"), from_id=added.id, to_id=step.id, outcome="next"))
        if flow.start == step.id:
            flow.start = added.id
    else:
        outgoing = next((edge for edge in flow.edges if edge.from_id == step.id and edge.outcome == "next"), None)
        if not outgoing:
            raise ValueError("此步骤有多个分支，请在逻辑图上选择要插入等待的出口。")
        end = outgoing.to_id
        outgoing.to_id = added.id
        flow.edges.append(Edge(id=_id("edge"), from_id=added.id, to_id=end, outcome="next"))
    at = flow.nodes.index(step) + (0 if before else 1)
    flow.nodes.insert(at, added)
    if "timeout" in outcomes(added):
        fault = next((node for node in flow.nodes if node.kind == "fault" and node.name == "动作超时"), None)
        if not fault:
            fault = Node(id=_id("step"), name="动作超时", kind="fault")
            flow.nodes.append(fault)
        flow.edges.append(Edge(id=_id("edge"), from_id=added.id, to_id=fault.id, outcome="timeout"))
    return f"在「{step.name}」{'前' if before else '后'}插入「{added.name}」。"


def describe_steps(station: Station, message: str) -> str | None:
    if re.fullmatch(r"(?:添加|新增|加入)(?:一个|一台|一只)?[^，,。；;\n]{1,30}[。！!]?", message.strip()):
        return None
    replace = bool(re.match(r"^(?:重新生成|重建|替换)(?:工位流程|工位逻辑|流程)?", message))
    if any(node.kind not in NON_EXECUTABLE for node in station.flow.nodes) and not replace:
        return None
    clauses = re.split(r"[，,。；;\n]+|然后|接着|随后|(?:再|并)(?=松开|启动|停止|收回|伸出|缩回|回零|回原位|等待)", message)
    steps: list[Node] = []
    for raw in clauses:
        clause = re.sub(r"^(?:重新生成|重建|替换|生成)(?:工位流程|工位逻辑|流程)?[：:\s]*|^先", "", raw.strip())
        if not clause:
            continue
        if re.search(r"超时|超过", clause) and re.search("故障|报警", clause):
            ms = duration_ms(clause)
            match = re.split(r"的?等待(?:超过|超时)|(?:超过|超时)", clause, maxsplit=1)[0].strip()
            choices = [item for item in steps if "timeout" in outcomes(item) and (not match or _words(match) in _words(item.name))]
            if not choices and not match:
                choices = [item for item in steps if "timeout" in outcomes(item)]
            if ms is not None and len(choices) == 1:
                choices[0].timeout_ms = ms
                continue
            raise ValueError(f"请明确「{clause}」对应的动作和超时时间。")
        if re.fullmatch(r"两?个?都完成(?:再继续)?|全部完成(?:后继续)?|流程结束|结束", clause):
            continue
        if re.search(r"如果|否则|若是?|除非|人为|手动确认|失败|报警时", clause):
            raise ValueError(f"「{clause}」需要条件分支。请补充判断信号与各分支动作。")
        if "后" in clause:
            condition, rest = clause.split("后", 1)
            if re.search("到位|完成|就绪|有料|无料|夹紧", condition):
                waiting = _waiting(station, condition, steps[-1] if steps else None)
                if waiting:
                    steps.append(waiting)
                clause = rest.removeprefix("先").strip()
                if not clause:
                    continue
        ms = duration_ms(clause)
        if ms is not None and re.match(r"^(?:等待|保持|延时)", clause):
            steps.append(Node(id=_id("step"), name=f"等待 {ms} ms", kind="wait", duration_ms=ms))
            continue
        if clause.startswith("等待"):
            waiting = _waiting(station, clause, steps[-1] if steps else None)
            if waiting:
                steps.append(waiting)
            continue
        parallel = bool(re.search("并行|同时", clause))
        pieces = re.split(r"与|和|并且|并(?=启动|回零|回位|松开|夹紧)", clause.replace("并行", "").replace("同时", "")) if parallel else [clause]
        references = [_action_in(station, part) for part in pieces]
        if all(references) and (not parallel or len(references) > 1):
            steps.append(_action_step(station, [item for item in references if item]))
            continue
        raise ValueError(f"「{clause}」未关联到工位设备的动作。请检查设备名称或补充动作细节。")
    if not any(node.actions for node in steps):
        return None
    end = Node(id=_id("step"), name="工位完成", kind="done")
    fault = Node(id=_id("step"), name="动作超时", kind="fault")
    edges = [Edge(id=_id("edge"), from_id=a.id, to_id=b.id, outcome="next") for a, b in zip(steps, [*steps[1:], end])]
    on_timeout = [step for step in steps if "timeout" in outcomes(step)]
    edges.extend(Edge(id=_id("edge"), from_id=step.id, to_id=fault.id, outcome="timeout") for step in on_timeout)
    interfaces = [item for item in station.flow.nodes if item.kind in NON_EXECUTABLE]
    keep = {item.id for item in interfaces}
    wires = [item for item in station.flow.wires if item.from_id in keep and item.to_id in keep]
    station.flow = Flow(start=steps[0].id, nodes=[*steps, end, *([fault] if on_timeout else []), *interfaces], edges=edges, wires=wires)
    pending = sum(step.pending_feedback for step in steps)
    return f"在「{station.name}」编排 {len(steps)} 个动作与等待步骤。" + (f"有 {pending} 项反馈待关联。" if pending else "")
