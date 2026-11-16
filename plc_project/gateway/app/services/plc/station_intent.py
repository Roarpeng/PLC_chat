"""Natural-language proposals for the versioned station canvas."""
from __future__ import annotations

import json
import re
from uuid import uuid4

from gateway.app.services.plc.llm_explain import chat_completion_raw, llm_settings
from gateway.app.services.plc.canvas_intent import connect_signal, describe_permission, describe_project_flow, reconnect_flow
from gateway.app.services.plc.station_steps import describe_steps, duration_ms, insert_step, named_duration_step
from plc_engine.engineering_ir.models import EngineeringIRV2
from plc_engine.engineering_ir.station_catalog import PROFILES
from plc_engine.engineering_ir.station_design import Device, Node, Station, StationDesign, design_issues


def _offline_edit(design: StationDesign, station_id: str, node_id: str, message: str) -> str:
    station = next((item for item in design.stations if item.id == station_id), None)
    flow = station.flow if station else design.flow
    node = next((item for item in flow.nodes if item.id == node_id), None)
    signal = connect_signal(design, station, message)
    if signal:
        return signal
    connected = reconnect_flow(flow, message, node_id)
    if connected:
        return connected
    if station:
        permission = describe_permission(station, message)
        if permission:
            return permission
        inserted = insert_step(station, node_id, message)
        if inserted:
            return inserted
        generated = describe_steps(station, message)
        if generated:
            return generated
    else:
        generated = describe_project_flow(design, message)
        if generated:
            return generated
    duration = duration_ms(re.split(r"改为|改成|设为|设置为|调整为|调整到", message)[-1])
    if station and duration:
        node = named_duration_step(station, message) or node
    if node and duration and re.search("超时|等待|保持", message):
        if node.kind != "wait" and not node.completion:
            raise ValueError("请选择等待节点后修改等待时间。")
        if node.device_id or node.completion or node.pending_feedback:
            node.timeout_ms = duration
            return f"将「{node.name}」的超时设为 {duration} ms。"
        if "超时" in message:
            raise ValueError("定时等待使用保持时间，信号等待才使用超时。")
        node.duration_ms = duration
        if re.fullmatch(r"等待 \d+ ms", node.name):
            node.name = f"等待 {duration} ms"
        return f"将「{node.name}」的保持时间设为 {duration} ms。"
    created = re.findall(r"[「“]([^」”]+)[」”]", message)
    if re.search(r"(?:创建|新建|新增|添加).{0,30}工位", message):
        if not created:
            tail = re.search(r"(?:创建|新建|新增|添加)\s*([^，。；\n]{1,48}工位[^，。；\n]{0,12})", message)
            created = [tail[1].strip()] if tail else []
        if created and not station:
            for name in dict.fromkeys(created):
                if any(item.name == name for item in design.stations):
                    raise ValueError(f"已有同名工位「{name}」，请明确要编辑的工位。")
                item = Station(id=f"st_{uuid4().hex[:10]}", name=name)
                design.stations.append(item)
                call = Node(id=f"node_{uuid4().hex[:12]}", name=name, kind="station", station_ids=[item.id])
                flow.nodes.append(call)
                if not flow.start:
                    flow.start = call.id
            return f"新增工位 {'、'.join(created)}。"
    if station and re.match("添加|新增|加入", message):
        ranked = [(len(name), profile) for profile in PROFILES.values() for name in profile["aliases"] if name.casefold() in message.casefold()]
        if ranked:
            best = max(length for length, _ in ranked)
            matches = {profile["id"]: profile for length, profile in ranked if length == best}
            if len(matches) != 1:
                raise ValueError("请指定设备规格，例如双作用气缸、气动夹爪或电动夹爪。")
            item = next(iter(matches.values()))
            station.devices.append(Device(id=f"dev_{uuid4().hex[:10]}", name=item["label"], driver=item["id"]))
            return f"在「{station.name}」新增 {item['label']}。"
    raise ValueError("请选择要修改的节点后描述时间，或用引号标出新工位名称。复杂指令需要配置语言模型。")


def propose_station_edit(ir: EngineeringIRV2, message: str, context: dict) -> dict:
    original = StationDesign.model_validate(ir.station_design)
    draft = original.model_copy(deep=True)
    station_id = str(context.get("station_id") or "")
    node_id = str(context.get("node_id") or "")
    scoped = next((item for item in original.stations if item.id == station_id), None)
    if station_id and scoped is None:
        return {"ops": [], "questions": ["当前工位已变化，请重新选择工位。"]}
    settings = llm_settings()
    mode = "offline"
    try:
        try:
            explanation = _offline_edit(draft, station_id, node_id, message)
        except ValueError:
            if not settings:
                raise
            # Scope restricts what can be updated and limits data sent to the model.
            selected = {
                "station": scoped.model_dump() if scoped else None,
                "stations": [{"id": item.id, "name": item.name} for item in original.stations],
                "flow": None if scoped else original.flow.model_dump(),
                "available_signal_ids": [item.id for item in original.hardware.signals],
                "selected_node_id": node_id,
                "device_profiles": [PROFILES[key] for key in sorted({item.driver for item in scoped.devices})] if scoped else [],
            }
            schema = Station.model_json_schema() if scoped else {
                "stations": "optional array of {id,name} additions",
                "flow": type(original.flow).model_json_schema(),
            }
            raw, _ = chat_completion_raw(
                [
                    {"role": "system", "content": (
                        "你编辑 AF 工程画布。只返回 JSON，字段 explanation、questions 和 scope。"
                        "工位范围返回完整更新后的 station 为 scope。项目范围返回 flows 的 flow 对象和新增 stations 数组为 scope。"
                        "保留现有对象 ID、调用引用与未涉及内容。新 ID 用英文和下划线。"
                        "工位动作使用 actions 的 device_id、action_id 引用现有设备及目录动作。"
                        "把动作反馈转换为 completion 条件，并为所有等待反馈的步骤指定 timeout 出口。"
                        "工艺许可用 permissions；持续检查或立即故障需要 blocked 出口。"
                        "信号连线存放在 wires，端口使用稳定 ID、匹配方向和类型；执行线继续使用 edges。"
                        "并行可用 fork 的 branch 连线直接指向多个工位或设备动作；各完成出口连到同一个 join。"
                        "找不到设备或信号时用 questions，或创建 pending_feedback=true 的待关联等待。"
                        "严禁猜测 I/O 绑定或输出 SCL。schema=" + json.dumps(schema, ensure_ascii=False)
                    )},
                    {"role": "user", "content": json.dumps({"request": message, "canvas": selected}, ensure_ascii=False)},
                ], settings, timeout_s=25, max_tokens=3200, json_mode=True,
            )
            reply = json.loads(raw)
            if reply.get("questions"):
                return {"ops": [], "questions": [str(item)[:300] for item in reply["questions"][:8]]}
            scope = reply["scope"]
            draft = original.model_copy(deep=True)
            if scoped:
                updated = Station.model_validate(scope)
                if updated.id != scoped.id:
                    raise ValueError("候选变更更改了工位标识。")
                old_bindings = {item.id: item.bindings for item in scoped.devices}
                if any(item.bindings and item.bindings != old_bindings.get(item.id) for item in updated.devices):
                    raise ValueError("请在检查器确认并绑定 I/O。")
                draft.stations = [updated if item.id == station_id else item for item in draft.stations]
            else:
                if "flow" in scope:
                    draft.flow = type(original.flow).model_validate(scope["flow"])
                draft.stations.extend(Station(id=item["id"], name=item["name"]) for item in scope.get("stations", []))
            explanation = str(reply.get("explanation") or "更新画布")[:500]
            mode = "model"
        previous_flows = {item.id: item.flow for item in original.stations}
        for current, previous in [(draft.flow, original.flow), *[(item.flow, previous_flows[item.id]) for item in draft.stations if item.id in previous_flows]]:
            positions = {node.id: node.position for node in previous.nodes}
            for item in current.nodes:
                item.position = positions.get(item.id)
        draft = StationDesign.model_validate(draft.model_dump())
        issues = design_issues(draft)
        if issues:
            return {"ops": [], "questions": [item["reason"] for item in issues[:8]]}
        if draft == original:
            return {"ops": [], "questions": ["当前画布已经包含该修改。"]}
        return {
            "base_revision": ir.revision, "explanation": explanation, "mode": mode, "questions": [],
            "ops": [{"op": "set_station_design", "design": draft.model_dump()}],
        }
    except RuntimeError:
        return {"ops": [], "questions": ["语言模型暂时不可用。请重试或直接编辑画布。"]}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"ops": [], "questions": [str(exc).splitlines()[0][:240]]}
