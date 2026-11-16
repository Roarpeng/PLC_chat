"""Device profiles, typed ports and reusable actions for the station canvas."""
from __future__ import annotations

from itertools import combinations
from typing import TypedDict


class ActionProfile(TypedDict):
    id: str
    label: str
    aliases: list[str]
    outputs: dict[str, bool]
    feedback: dict[str, bool]
    timeout_ms: int


class DeviceProfile(TypedDict):
    id: str
    label: str
    category: str
    interface: str
    aliases: list[str]
    ports: dict[str, str]
    port_labels: dict[str, str]
    actions: list[ActionProfile]
    supported: bool
    exclusive: list[list[str]]
    fault_port: str | None


def action(id_: str, label: str, outputs: dict[str, bool], feedback: dict[str, bool] | None = None,
           timeout: int = 2000, *, aliases: tuple[str, ...] = ()) -> ActionProfile:
    return {"id": id_, "label": label, "aliases": [label, *aliases], "outputs": outputs,
            "feedback": feedback or {}, "timeout_ms": timeout if feedback else 0}


def device(id_: str, label: str, category: str, port_labels: dict[str, str],
           outputs: tuple[str, ...] = (), actions: tuple[ActionProfile, ...] = (),
           *, aliases: tuple[str, ...] = (), interface: str = "数字 I/O",
           exclusive: bool = False, fault: str | None = None, supported: bool = True) -> DeviceProfile:
    return {"id": id_, "label": label, "category": category, "interface": interface,
            "aliases": [label, *aliases], "ports": {key: "output" if key in outputs else "input" for key in port_labels},
            "port_labels": port_labels, "actions": list(actions), "supported": supported,
            "exclusive": [list(pair) for pair in combinations(outputs, 2)] if exclusive else [], "fault_port": fault}


def gripper(id_: str, label: str, electric: bool = False) -> DeviceProfile:
    ports = {"close": "夹紧命令", "open": "松开命令", "closed": "夹紧到位", "opened": "松开到位"}
    if electric:
        ports["fault"] = "控制器故障"
    return device(id_, label, "夹持与搬运", ports, ("close", "open"), (
        action("clamp", "夹紧", {"close": True, "open": False}, {"closed": True}, aliases=("抓紧", "闭合", "夹住")),
        action("release", "松开", {"close": False, "open": True}, {"opened": True}, aliases=("张开", "释放")),
    ), aliases=("夹爪",), exclusive=True, fault="fault" if electric else None,
        interface="外部控制器数字 I/O 握手" if electric else "双线圈与到位反馈")


def digital_sensor(id_: str, label: str, *aliases: str) -> DeviceProfile:
    return device(id_, label, "检测与识别", {"active": "信号有效"}, aliases=aliases)


def planned(id_: str, label: str, category: str, interface: str, *aliases: str) -> DeviceProfile:
    return device(id_, label, category, {}, aliases=aliases, interface=interface, supported=False)


PROFILES: dict[str, DeviceProfile] = {item["id"]: item for item in [
    device("cylinder", "双作用气缸", "气动执行",
           {"extend": "伸出命令", "retract": "缩回命令", "extended": "伸出到位", "retracted": "缩回到位"},
           ("extend", "retract"), (
               action("extend", "伸出", {"extend": True, "retract": False}, {"extended": True}, aliases=("推出",)),
               action("retract", "缩回", {"extend": False, "retract": True}, {"retracted": True}, aliases=("回缩", "退回")),
           ), aliases=("气缸",), exclusive=True),
    device("single_cylinder", "单作用气缸", "气动执行",
           {"extend": "伸出命令", "extended": "伸出到位", "retracted": "缩回到位"}, ("extend",), (
               action("extend", "伸出", {"extend": True}, {"extended": True}),
               action("retract", "缩回", {"extend": False}, {"retracted": True}, aliases=("回缩", "退回")),
           ), aliases=("气缸",), interface="单线圈与到位反馈"),
    device("solenoid", "电磁阀", "气动执行", {"energize": "线圈命令"}, ("energize",), (
        action("open", "通电", {"energize": True}, aliases=("打开", "开启")),
        action("close", "断电", {"energize": False}, aliases=("关闭",)),
    )),
    planned("rotary_cylinder", "旋转气缸", "气动执行", "需匹配阀组和到位反馈", "旋转执行器"),
    device("motor", "普通电机", "电动执行", {"run": "运行命令", "running": "运行反馈"}, ("run",), (
        action("start", "启动", {"run": True}, {"running": True}, aliases=("运行", "开机")),
        action("stop", "停止", {"run": False}, {"running": False}, aliases=("停机",)),
    ), aliases=("电机", "电机启停")),
    device("servo", "伺服轴", "电动执行", {
        "home": "回零请求", "work": "预置工作位请求", "homed": "回零完成", "in_position": "工作位到位",
        "busy": "轴忙碌", "fault": "控制器故障",
    }, ("home", "work"), (
        action("home", "回原位", {"home": True, "work": False}, {"homed": True, "busy": False}, 8000,
               aliases=("回零", "回到原位", "返回原位", "回位")),
        action("work", "到工作位", {"home": False, "work": True}, {"in_position": True, "busy": False}, 8000,
               aliases=("移动到工作位", "移动至工作位", "到达工作位", "移动到预置位置", "定位")),
        action("stop", "撤销运动请求", {"home": False, "work": False}, aliases=("撤销运动",)),
    ), aliases=("伺服", "伺服电机"), exclusive=True, fault="fault", interface="外部定位控制器 · 预置位置数字 I/O 握手"),
    planned("servo_to", "伺服轴 · 工艺对象", "电动执行", "需配套 TIA 工艺对象和运动指令", "MC_MoveAbsolute", "绝对定位"),
    planned("vfd", "变频电机", "电动执行", "需配套变频器型号和报文", "变频器"),
    planned("stepper", "步进电机", "电动执行", "需配套 PTO 或总线驱动", "步进轴"),
    planned("electric_cylinder", "电缸 / 电动推杆", "电动执行", "需配套位置控制器", "电缸"),
    gripper("pneumatic_gripper", "气动夹爪"),
    gripper("electric_gripper", "电动夹爪", electric=True),
    device("vacuum", "真空吸附", "夹持与搬运", {"suction": "吸附命令", "vacuum": "真空到位"}, ("suction",), (
        action("grip", "吸附", {"suction": True}, {"vacuum": True}, aliases=("吸取",)),
        action("release", "释放吸附", {"suction": False}, {"vacuum": False}, aliases=("关闭真空", "释放")),
    ), aliases=("吸盘", "真空发生器")),
    device("conveyor", "皮带输送机", "夹持与搬运", {"run": "启动命令", "running": "运行反馈"}, ("run",), (
        action("start", "启动", {"run": True}, {"running": True}, aliases=("输送", "运行")),
        action("stop", "停止", {"run": False}, {"running": False}, aliases=("停机",)),
    ), aliases=("输送线", "输送机", "皮带机")),
    planned("roller_conveyor", "滚筒输送机", "夹持与搬运", "需匹配分区或驱动接口", "滚筒线"),
    planned("index_table", "分度转台", "夹持与搬运", "需配套定位与原位反馈", "转台"),
    digital_sensor("sensor", "数字传感器", "传感器", "到位传感器"),
    digital_sensor("photoelectric", "光电传感器", "光电", "工件检测"),
    digital_sensor("proximity", "接近开关", "接近传感器"),
    digital_sensor("reed", "磁性开关", "磁性传感器", "磁簧开关"),
    digital_sensor("limit", "限位开关", "行程开关"),
    digital_sensor("pressure_switch", "压力开关", "压力到位"),
    digital_sensor("vacuum_switch", "真空开关", "真空传感器"),
    planned("analog_sensor", "模拟量传感器", "检测与识别", "需配套量程和模拟量标定", "压力传感器", "位移传感器", "温度传感器"),
    planned("encoder", "编码器", "检测与识别", "需配套高速计数或驱动反馈"),
    planned("scanner", "扫码器", "检测与识别", "需配套触发和结果协议", "条码枪"),
    planned("rfid", "RFID 读写器", "检测与识别", "需配套读写接口", "RFID"),
    planned("vision", "视觉相机", "外部设备", "需配套任务与结果握手", "相机"),
    planned("robot", "机器人", "外部设备", "需配套程序选择和运行握手", "机械臂"),
    planned("screwdriver", "自动拧紧机", "外部设备", "需配套扭矩结果与状态握手", "拧紧机"),
    planned("welder", "焊接控制器", "外部设备", "需配套工艺控制器状态与握手", "焊机"),
]}

DRIVERS = {id_: profile["ports"] for id_, profile in PROFILES.items()}
ACTIONS = {id_: {item["id"]: item for item in profile["actions"]} for id_, profile in PROFILES.items()}
