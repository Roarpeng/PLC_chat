"""AF-Studio v5 backend verification, compilation, Merkle sync, Copilot, and Cut-Set services.

Mirrors the four spatio-temporal orthogonal hypergraph algorithms in ``docs/af_studio.md``
and provides optional, fail-closed bridging to the C# TIA Openness STA daemon on
``127.0.0.1:8791`` (or ``AF_STUDIO_STA_URL``).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from typing import Any
from urllib.parse import urlparse

from gateway.app.schemas.v2_af_studio import (
    GhostGraphTransactionIn,
    ProjectHyperGraphIn,
    SafetyGuardEdgeIn,
    SpatialInstanceNodeIn,
    StationHyperGraphIn,
    StepInvocationIn,
    TemporalStepHyperEdgeIn,
)

_DEFAULT_STA_URL = "http://127.0.0.1:8791"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MOTHER_CLASS_CACHE_TTL_S = 15.0

_CACHE_LOCK = threading.RLock()
_LAST_SYNCED_HASHES: dict[str, dict[str, str]] = {}
_MOTHER_CLASS_CACHE: dict[str, tuple[float, dict[str, Any], str]] = {}


def reset_af_studio_caches(project_id: str | None = None) -> None:
    """Clear in-memory Merkle sync and STA reflection caches (for test isolation)."""
    with _CACHE_LOCK:
        if project_id is None:
            _LAST_SYNCED_HASHES.clear()
        else:
            _LAST_SYNCED_HASHES.pop(project_id, None)
        _MOTHER_CLASS_CACHE.clear()


# --------------------------------------------------------------------------- #
# Built-in Mother-Class Registry & Radial Craft Methods (Offline Fallback)
# --------------------------------------------------------------------------- #

BUILTIN_MOTHER_CLASSES: list[dict[str, Any]] = [
    {
        "driverClass": "FB_AF_AxisMotion",
        "title": "伺服轴母版",
        "category": "SERVO",
        "theme": "klein",
        "description": "FB_AF_AxisMotion · 含离散配方点",
        "defaultDiscreteStates": ["Pos_Home_0", "Pos_Pick_120", "Pos_Press_245", "Pos_Reject_410"],
        "initialHomeState": "Pos_Home_0",
        "hasPartPresentSensor": False,
        "defaultInPorts": [
            {"id": "IN_EXEC", "label": "▶ 多位置伺服触发槽", "type": "SEQ"},
            {"id": "IN_GUARD", "label": "🛡️ 防撞护栏 (i_bInterlockOK)", "type": "GUARD"},
        ],
        "defaultOutPorts": [
            {"id": "OUT_DONE", "label": "● 伺服定位完成 →", "type": "SEQ"},
        ],
        "interfacePins": {
            "inputs": ["i_bCmdMoveAbs", "i_rTargetPos", "i_bInterlockOK", "i_bCmdHome"],
            "outputs": ["o_bDone", "o_bAtHome", "o_rActPos", "o_wBlockDiagCode"],
        },
    },
    {
        "driverClass": "FB_AF_Actuator2Pos",
        "title": "双位气缸母版",
        "category": "CYLINDER",
        "theme": "emerald",
        "description": "FB_AF_Actuator2Pos · 内聚双磁开",
        "defaultDiscreteStates": ["AtHome", "Extended"],
        "initialHomeState": "AtHome",
        "hasPartPresentSensor": False,
        "defaultInPorts": [
            {"id": "IN_EXEC", "label": "▶ 伸出/缩回触发槽", "type": "SEQ"},
        ],
        "defaultOutPorts": [
            {"id": "OUT_DONE", "label": "● 气缸动作到位 →", "type": "SEQ"},
            {"id": "OUT_AT_HOME", "label": "🛡️ 顶升原位状态", "type": "GUARD"},
        ],
        "interfacePins": {
            "inputs": ["i_bCmdWork", "i_bCmdHome", "i_bInterlockOK", "i_bFeedbackHome", "i_bFeedbackWork"],
            "outputs": ["o_bDoWork", "o_bAtHome", "o_bAtWork", "o_wBlockDiagCode"],
        },
    },
    {
        "driverClass": "FB_AF_Gripper",
        "title": "平行夹爪母版",
        "category": "GRIPPER",
        "theme": "emerald",
        "description": "FB_AF_Gripper · 含带料保护算子",
        "defaultDiscreteStates": ["Opened", "Gripped"],
        "initialHomeState": "Opened",
        "hasPartPresentSensor": True,
        "defaultInPorts": [
            {"id": "IN_EXEC", "label": "▶ 工艺动作触发槽", "type": "SEQ"},
        ],
        "defaultOutPorts": [
            {"id": "OUT_DONE", "label": "● 动作到位反馈 →", "type": "SEQ"},
        ],
        "interfacePins": {
            "inputs": ["i_bCmdClose", "i_bCmdOpen", "i_bPartPresent", "i_bInterlockOK"],
            "outputs": ["o_bGripped", "o_bOpened", "o_bMaintainGrip", "o_wBlockDiagCode"],
        },
    },
    {
        "driverClass": "FB_AF_VisionSensor",
        "title": "视觉/测高仪母版",
        "category": "VISION",
        "theme": "amber",
        "description": "FB_AF_VisionSensor · 工艺传感器",
        "defaultDiscreteStates": ["Idle", "InspectOK", "InspectNG"],
        "initialHomeState": "Idle",
        "hasPartPresentSensor": False,
        "defaultInPorts": [
            {"id": "IN_EXEC", "label": "▶ 触发拍照检测", "type": "SEQ"},
        ],
        "defaultOutPorts": [
            {"id": "OUT_OK", "label": "● 极性判定 OK →", "type": "SEQ"},
            {"id": "OUT_NG", "label": "● 极性判定 NG →", "type": "SEQ"},
        ],
        "interfacePins": {
            "inputs": ["i_bTrigger"],
            "outputs": ["o_bDone", "o_bResultOK", "o_bResultNG"],
        },
    },
    {
        "driverClass": "STATION_INPUT_PORT",
        "title": "工站左输入边界",
        "category": "BOUNDARY_IN",
        "theme": "ink",
        "description": "映射自 L1 产线接口的工站输入边界",
        "defaultDiscreteStates": ["Idle", "Ready"],
        "initialHomeState": "Idle",
        "hasPartPresentSensor": False,
        "defaultInPorts": [],
        "defaultOutPorts": [
            {"id": "OUT_PART_ARRIVED", "label": "● 托盘到位触发", "type": "SEQ"},
        ],
        "interfacePins": {"inputs": ["i_bUpstreamReady"], "outputs": ["o_bTriggerSeq"]},
    },
    {
        "driverClass": "STATION_OUTPUT_PORT",
        "title": "工站右输出边界",
        "category": "BOUNDARY_OUT",
        "theme": "ink",
        "description": "映射至 L1 下游接口的工站输出边界",
        "defaultDiscreteStates": ["Idle", "Released"],
        "initialHomeState": "Idle",
        "hasPartPresentSensor": False,
        "defaultInPorts": [
            {"id": "IN_CYCLE_END", "label": "▶ 成品放行下游", "type": "SEQ"},
        ],
        "defaultOutPorts": [],
        "interfacePins": {"inputs": ["i_bCycleDone"], "outputs": ["o_bCycleDone"]},
    },
]

MOTHER_CLASS_RADIAL_METHODS: dict[str, list[dict[str, Any]]] = {
    "FB_AF_AxisMotion": [
        {
            "methodId": "MovePick",
            "label": "🎯 移至取料位 (120mm)",
            "waitDesc": "到达取料位",
            "sclCmd": "MoveAbs(120.0)",
            "targetDiscreteState": "Pos_Pick_120",
        },
        {
            "methodId": "MovePress",
            "label": "🎯 移至压装位 (245mm)",
            "waitDesc": "到达压装位",
            "sclCmd": "MoveAbs(245.0)",
            "targetDiscreteState": "Pos_Press_245",
        },
        {
            "methodId": "MoveReject",
            "label": "🗑️ 移至NG抛料位 (410mm)",
            "waitDesc": "到达NG抛料位",
            "sclCmd": "MoveAbs(410.0)",
            "targetDiscreteState": "Pos_Reject_410",
        },
        {
            "methodId": "MoveHome",
            "label": "🏠 回待机原位 (0mm)",
            "waitDesc": "到达0mm待机位",
            "sclCmd": "MoveAbs(0.0)",
            "targetDiscreteState": "Pos_Home_0",
        },
        {
            "methodId": "GUARD",
            "label": "🛡️ 设为永久防撞护栏",
            "isGuard": True,
        },
    ],
    "FB_AF_Actuator2Pos": [
        {
            "methodId": "ExtendWork",
            "label": "⬇ 伸出下压并保压1.5s",
            "waitDesc": "动位磁开导通",
            "sclCmd": "ExtendWork()",
            "targetDiscreteState": "Extended",
        },
        {
            "methodId": "RetractHome",
            "label": "⬆ 缩回顶升安全原位",
            "waitDesc": "原位磁开导通",
            "sclCmd": "RetractHome()",
            "targetDiscreteState": "AtHome",
        },
        {
            "methodId": "GUARD",
            "label": "🛡️ 设为永久防撞护栏",
            "isGuard": True,
        },
    ],
    "FB_AF_Gripper": [
        {
            "methodId": "GripClose",
            "label": "✊ 闭合夹紧电芯",
            "waitDesc": "夹紧磁开导通",
            "sclCmd": "CloseGrip()",
            "targetDiscreteState": "Gripped",
        },
        {
            "methodId": "GripOpen",
            "label": "🖐️ 张开释放电芯",
            "waitDesc": "张开磁开导通",
            "sclCmd": "OpenGrip()",
            "targetDiscreteState": "Opened",
        },
        {
            "methodId": "GUARD",
            "label": "🛡️ 设为永久防撞护栏",
            "isGuard": True,
        },
    ],
    "FB_AF_VisionSensor": [
        {
            "methodId": "TrigInspect",
            "label": "📸 触发拍照极性检测",
            "waitDesc": "视觉判定完成",
            "sclCmd": "TriggerCam()",
            "targetDiscreteState": "InspectOK",
        },
    ],
    "STATION_OUTPUT_PORT": [
        {
            "methodId": "ReleaseNext",
            "label": "📦 放行成品至下游工站",
            "waitDesc": "下游接收握手",
            "sclCmd": "o_bCycleDone := TRUE",
            "targetDiscreteState": "Released",
        },
    ],
}


# --------------------------------------------------------------------------- #
# Seed Workspace (Exact Mirror of af_studio_v5.html AssyLine_01 + ST10/20/30)
# --------------------------------------------------------------------------- #

_SEED_WORKSPACE: dict[str, Any] = {
    "projectId": "AssyLine_01",
    "projectName": "AssyLine_01 · 新能源电芯视觉压装产线",
    "defaultStationId": "ST20",
    "projectGraph": {
        "projectId": "AssyLine_01",
        "projectName": "AssyLine_01 · 3 工站复合子网",
        "stations": [
            {
                "id": "NODE_ST10",
                "stationId": "ST10",
                "title": "ST10 · 来料移载工作站",
                "x": 75,
                "y": 120,
                "isPinned": True,
                "instances": [
                    "DB_ST10_CylStopper (阻挡缸)",
                    "DB_ST10_CylTransfer (移载缸)",
                    "DB_ST10_Barcode (读码器)",
                ],
                "outPorts": [
                    {"id": "P_HANDOVER", "label": "📦 托盘到位握手 →", "type": "SEQ"},
                    {"id": "P_SAFE_HOME", "label": "🛡️ 移载缸在原位 (%I0.4)", "type": "GUARD"},
                ],
                "inPorts": [
                    {"id": "P_UP", "label": "📦 上游来料就绪", "type": "SEQ"},
                ],
            },
            {
                "id": "NODE_ST20",
                "stationId": "ST20",
                "title": "ST20 · 视觉引导压装站",
                "x": 455,
                "y": 105,
                "isPinned": True,
                "instances": [
                    "DB_ST20_Gripper1 (平行夹爪)",
                    "DB_ST20_VisionCam (2D相机)",
                    "DB_ST20_AxisX (搬运伺服)",
                    "DB_ST20_CylZ (主压装缸)",
                ],
                "inPorts": [
                    {"id": "P_IN_HANDOVER", "label": "📦 接收ST10托盘到位", "type": "SEQ"},
                    {"id": "P_IN_ST10_HOME", "label": "🛡️ 跨站护栏: ST10移载缸在原位", "type": "GUARD"},
                ],
                "outPorts": [
                    {"id": "P_OUT_ST30", "label": "📦 压装完成放行下游 →", "type": "SEQ"},
                ],
            },
            {
                "id": "NODE_ST30",
                "stationId": "ST30",
                "title": "ST30 · 激光测高分拣站",
                "x": 845,
                "y": 125,
                "isPinned": True,
                "instances": [
                    "DB_ST30_LaserGauge (测高仪)",
                    "DB_ST30_RotaryAxis (分度盘)",
                ],
                "inPorts": [
                    {"id": "P_IN_ST20", "label": "📦 接收ST20成品握手", "type": "SEQ"},
                ],
                "outPorts": [
                    {"id": "P_OUT_END", "label": "📦 良品下线完成 →", "type": "SEQ"},
                ],
            },
        ],
        "edges": [
            {
                "id": "E_L1_1",
                "fromNode": "NODE_ST10",
                "fromPort": "P_HANDOVER",
                "toNode": "NODE_ST20",
                "toPort": "P_IN_HANDOVER",
                "kind": "SEQ",
                "label": "物流交接握手",
            },
            {
                "id": "E_L1_2",
                "fromNode": "NODE_ST10",
                "fromPort": "P_SAFE_HOME",
                "toNode": "NODE_ST20",
                "toPort": "P_IN_ST10_HOME",
                "kind": "GUARD",
                "label": "跨站护栏 #0203",
                "isFaultCutSet": True,
            },
            {
                "id": "E_L1_3",
                "fromNode": "NODE_ST20",
                "fromPort": "P_OUT_ST30",
                "toNode": "NODE_ST30",
                "toPort": "P_IN_ST20",
                "kind": "SEQ",
                "label": "物流交接握手",
            },
        ],
    },
    "stationHyperGraphs": {
        "ST20": {
            "stationId": "ST20",
            "stationName": "ST20 · 视觉引导压装站",
            "spatialNodes": [
                {
                    "id": "BOUND_IN_ST20",
                    "role": "BOUNDARY_IN",
                    "title": "ST20 · 左输入边界",
                    "driverClass": "STATION_INPUT_PORT",
                    "instanceDb": "映射自 L1 产线接口",
                    "position": {"x": 35, "y": 135},
                    "x": 35,
                    "y": 135,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "Ready"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {},
                    "inPorts": [],
                    "outPorts": [
                        {"id": "OUT_PART_ARRIVED", "label": "● 托盘到位触发", "type": "SEQ"},
                        {
                            "id": "OUT_ST10_CYL_HOME",
                            "label": "🛡️ ST10移载缸原位 (%I0.4)",
                            "type": "GUARD",
                            "isFaultLeaf": True,
                        },
                    ],
                },
                {
                    "id": "INST_ST20_GRIP",
                    "role": "ACTUATOR",
                    "title": "1号平行夹爪",
                    "driverClass": "FB_AF_Gripper",
                    "instanceDb": "DB_ST20_Gripper1",
                    "theme": "emerald",
                    "position": {"x": 285, "y": 65},
                    "x": 285,
                    "y": 65,
                    "isPinned": True,
                    "hasPartPresentSensor": True,
                    "hasPartSensor": True,
                    "discreteStates": ["Opened", "Gripped"],
                    "initialHomeState": "Opened",
                    "cohesiveIoMap": {"doClose": "%Q10.2", "diClosed": "%I10.4"},
                    "ioText": "闭合阀 %Q10.2 · 夹紧磁开 %I10.4",
                    "inPorts": [{"id": "IN_EXEC", "label": "▶ 工艺动作触发槽", "type": "SEQ"}],
                    "outPorts": [{"id": "OUT_DONE", "label": "● 动作到位反馈 →", "type": "SEQ"}],
                },
                {
                    "id": "INST_ST20_CAM",
                    "role": "ACTUATOR",
                    "title": "2D视觉引导相机",
                    "driverClass": "FB_AF_VisionSensor",
                    "instanceDb": "DB_ST20_VisionCam",
                    "theme": "amber",
                    "position": {"x": 285, "y": 285},
                    "x": 285,
                    "y": 285,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "InspectOK", "InspectNG"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {"proto": "TCP"},
                    "ioText": "TCP触发 · 极性判定结构体",
                    "inPorts": [{"id": "IN_EXEC", "label": "▶ 触发拍照检测", "type": "SEQ"}],
                    "outPorts": [
                        {"id": "OUT_OK", "label": "● 极性判定 OK →", "type": "SEQ"},
                        {"id": "OUT_NG", "label": "● 极性判定 NG →", "type": "SEQ"},
                    ],
                },
                {
                    "id": "INST_ST20_X",
                    "role": "ACTUATOR",
                    "title": "X轴搬运伺服",
                    "driverClass": "FB_AF_AxisMotion",
                    "instanceDb": "DB_ST20_AxisX",
                    "theme": "klein",
                    "position": {"x": 590, "y": 80},
                    "x": 590,
                    "y": 80,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Pos_Home_0", "Pos_Pick_120", "Pos_Press_245", "Pos_Reject_410"],
                    "initialHomeState": "Pos_Home_0",
                    "cohesiveIoMap": {},
                    "ioText": "配方: 待机0 / 取料120 / 压装245 / 抛料410mm",
                    "inPorts": [
                        {"id": "IN_EXEC", "label": "▶ 多位置伺服触发槽", "type": "SEQ"},
                        {"id": "IN_GUARD", "label": "🛡️ 防撞护栏 (i_bInterlockOK)", "type": "GUARD"},
                    ],
                    "outPorts": [{"id": "OUT_DONE", "label": "● 伺服定位完成 →", "type": "SEQ"}],
                },
                {
                    "id": "INST_ST20_Z",
                    "role": "ACTUATOR",
                    "title": "Z轴主压装气缸",
                    "driverClass": "FB_AF_Actuator2Pos",
                    "instanceDb": "DB_ST20_CylZ",
                    "theme": "emerald",
                    "position": {"x": 590, "y": 315},
                    "x": 590,
                    "y": 315,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["AtHome", "Extended"],
                    "initialHomeState": "AtHome",
                    "cohesiveIoMap": {"diHome": "%I10.0", "diWork": "%I10.1"},
                    "ioText": "顶升原位 %I10.0 · 下压动位 %I10.1",
                    "inPorts": [{"id": "IN_EXEC", "label": "▶ 伸出/缩回触发槽", "type": "SEQ"}],
                    "outPorts": [
                        {"id": "OUT_DONE", "label": "● 气缸动作到位 →", "type": "SEQ"},
                        {"id": "OUT_AT_HOME", "label": "🛡️ 顶升原位状态 (%I10.0)", "type": "GUARD"},
                    ],
                },
                {
                    "id": "BOUND_OUT_ST20",
                    "role": "BOUNDARY_OUT",
                    "title": "ST20 · 右输出边界",
                    "driverClass": "STATION_OUTPUT_PORT",
                    "instanceDb": "映射至 L1 下游接口",
                    "position": {"x": 910, "y": 165},
                    "x": 910,
                    "y": 165,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "Released"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {},
                    "inPorts": [{"id": "IN_CYCLE_END", "label": "▶ 成品放行下游 ST30", "type": "SEQ"}],
                    "outPorts": [],
                },
            ],
            "guardEdges": [
                {
                    "id": "G_ST20_Z_TO_X",
                    "fromNode": "INST_ST20_Z",
                    "fromPort": "OUT_AT_HOME",
                    "toNode": "INST_ST20_X",
                    "toPort": "IN_GUARD",
                    "requiredSourceState": "AtHome",
                    "diagCodeHex": "16#0201",
                    "diagCode": "#0201",
                    "humanDescription": "Z轴气缸处于顶升原位 (%I10.0=1)",
                    "humanRule": "Z轴气缸处于顶升原位 (%I10.0=1)",
                    "isHealthy": True,
                    "isCrossStation": False,
                },
                {
                    "id": "G_ST20_ST10_TO_X",
                    "fromNode": "BOUND_IN_ST20",
                    "fromPort": "OUT_ST10_CYL_HOME",
                    "toNode": "INST_ST20_X",
                    "toPort": "IN_GUARD",
                    "requiredSourceState": "AtHome",
                    "diagCodeHex": "16#0203",
                    "diagCode": "#0203",
                    "humanDescription": "上游 ST10 移载气缸退回原位 (%I0.4)",
                    "humanRule": "上游 ST10 移载气缸退回原位 (%I0.4)",
                    "isCrossStation": True,
                    "crossStationRef": {
                        "upstreamStationId": "ST10",
                        "upstreamInstanceId": "INST_ST10_TRANS",
                        "physicalTerminal": "%I0.4",
                        "cabinetWireTag": "X12:04",
                    },
                },
            ],
            "temporalSteps": [
                {
                    "id": "T_S10",
                    "stepNo": 10,
                    "title": "来料夹紧电芯",
                    "fromNode": "BOUND_IN_ST20",
                    "fromPort": "OUT_PART_ARRIVED",
                    "toNode": "INST_ST20_GRIP",
                    "toPort": "IN_EXEC",
                    "actionLabel": "闭合夹紧电芯",
                    "sclCall": "CloseGrip()",
                    "waitDesc": "夹紧磁开 %I10.4 导通",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST20_GRIP",
                            "methodId": "GripClose",
                            "actionLabel": "闭合夹紧电芯",
                            "targetDiscreteState": "Gripped",
                            "sclStatement": "CloseGrip()",
                            "waitPredicateScl": "#INST_ST20_GRIP.o_bGripped",
                        }
                    ],
                },
                {
                    "id": "T_S20",
                    "stepNo": 20,
                    "title": "视觉极性检测",
                    "fromNode": "INST_ST20_GRIP",
                    "fromPort": "OUT_DONE",
                    "toNode": "INST_ST20_CAM",
                    "toPort": "IN_EXEC",
                    "actionLabel": "触发拍照极性检测",
                    "sclCall": "TriggerCam()",
                    "waitDesc": "视觉返回 OK/NG",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST20_CAM",
                            "methodId": "TrigInspect",
                            "actionLabel": "触发拍照极性检测",
                            "targetDiscreteState": "InspectOK",
                            "sclStatement": "TriggerCam()",
                            "waitPredicateScl": "#INST_ST20_CAM.o_bDone",
                        }
                    ],
                },
                {
                    "id": "T_S30",
                    "stepNo": 30,
                    "title": "X轴横移至压装位",
                    "fromNode": "INST_ST20_CAM",
                    "fromPort": "OUT_OK",
                    "toNode": "INST_ST20_X",
                    "toPort": "IN_EXEC",
                    "actionLabel": "移至压装位 (245mm)",
                    "sclCall": "MoveAbs(245.0)",
                    "waitDesc": "到达 245.0mm 压装位",
                    "requiresZHomeGuard": True,
                    "branchPredicate": "OK",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST20_X",
                            "methodId": "MovePress",
                            "actionLabel": "移至压装位 (245mm)",
                            "targetDiscreteState": "Pos_Press_245",
                            "sclStatement": "MoveAbs(245.0)",
                            "waitPredicateScl": "#INST_ST20_X.o_bDone",
                        }
                    ],
                },
                {
                    "id": "T_S40",
                    "stepNo": 40,
                    "title": "Z轴下压保压1.5s",
                    "fromNode": "INST_ST20_X",
                    "fromPort": "OUT_DONE",
                    "toNode": "INST_ST20_Z",
                    "toPort": "IN_EXEC",
                    "actionLabel": "伸出下压并保压1.5s",
                    "sclCall": "ExtendWork()",
                    "waitDesc": "下压动位 %I10.1 & 保压完成",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST20_Z",
                            "methodId": "ExtendWork",
                            "actionLabel": "伸出下压并保压1.5s",
                            "targetDiscreteState": "Extended",
                            "sclStatement": "ExtendWork()",
                            "waitPredicateScl": "#INST_ST20_Z.o_bAtWork",
                        }
                    ],
                },
                {
                    "id": "T_S50",
                    "stepNo": 50,
                    "title": "Z轴回升并放行下游",
                    "fromNode": "INST_ST20_Z",
                    "fromPort": "OUT_DONE",
                    "toNode": "BOUND_OUT_ST20",
                    "toPort": "IN_CYCLE_END",
                    "parallelNode": "INST_ST20_Z",
                    "parallelActionLabel": "二次动作: 缩回顶升原位",
                    "actionLabel": "Z轴回顶升位 & 放行 ST30",
                    "sclCall": "RetractHome() + ReleaseNext",
                    "waitDesc": "Z轴回原位 %I10.0 & 下游握手",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST20_Z",
                            "methodId": "RetractHome",
                            "actionLabel": "二次动作: 缩回顶升原位",
                            "targetDiscreteState": "AtHome",
                            "sclStatement": "RetractHome()",
                            "waitPredicateScl": "#INST_ST20_Z.o_bAtHome",
                        },
                        {
                            "targetNodeId": "BOUND_OUT_ST20",
                            "methodId": "ReleaseNext",
                            "actionLabel": "Z轴回顶升位 & 放行 ST30",
                            "targetDiscreteState": "Released",
                            "sclStatement": "o_bCycleDone := TRUE",
                            "waitPredicateScl": "#BOUND_OUT_ST20.o_bCycleDone",
                        },
                    ],
                },
            ],
            "ghostEdges": [],
        },
        "ST10": {
            "stationId": "ST10",
            "stationName": "ST10 · 来料移载工作站",
            "spatialNodes": [
                {
                    "id": "INST_ST10_STOP",
                    "role": "ACTUATOR",
                    "title": "倍速链阻挡气缸",
                    "driverClass": "FB_AF_Actuator2Pos",
                    "instanceDb": "DB_ST10_CylStopper",
                    "theme": "emerald",
                    "position": {"x": 95, "y": 135},
                    "x": 95,
                    "y": 135,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["AtHome", "Extended"],
                    "initialHomeState": "AtHome",
                    "cohesiveIoMap": {"diHome": "%I0.0", "diWork": "%I0.1"},
                    "ioText": "阻挡原位 %I0.0 · 放行动位 %I0.1",
                    "inPorts": [{"id": "IN_EXEC", "label": "▶ 阻挡定位触发", "type": "SEQ"}],
                    "outPorts": [{"id": "OUT_DONE", "label": "● 定位完成 →", "type": "SEQ"}],
                },
                {
                    "id": "INST_ST10_TRANS",
                    "role": "ACTUATOR",
                    "title": "来料移载气缸",
                    "driverClass": "FB_AF_Actuator2Pos",
                    "instanceDb": "DB_ST10_CylTransfer",
                    "theme": "vermilion",
                    "position": {"x": 435, "y": 120},
                    "x": 435,
                    "y": 120,
                    "isPinned": True,
                    "isPhysicalRootCause": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["AtHome", "Extended"],
                    "initialHomeState": "AtHome",
                    "cohesiveIoMap": {"diHome": "%I0.4", "diWork": "%I0.5", "cabinetWireTag": "X12:04"},
                    "ioText": "原位磁开 %I0.4 (电柜端子 X12:04) · 动位 %I0.5",
                    "inPorts": [{"id": "IN_EXEC", "label": "▶ 送料推入触发", "type": "SEQ"}],
                    "outPorts": [
                        {"id": "OUT_DONE", "label": "● 送料完成握手 →", "type": "SEQ"},
                        {
                            "id": "OUT_HOME_DI",
                            "label": "🛡️ 原位磁开 %I0.4",
                            "type": "GUARD",
                            "isFaultLeaf": True,
                        },
                    ],
                },
                {
                    "id": "BOUND_OUT_ST10",
                    "role": "BOUNDARY_OUT",
                    "title": "ST10 · 右输出边界",
                    "driverClass": "STATION_OUTPUT_PORT",
                    "instanceDb": "输出至下游 ST20",
                    "position": {"x": 800, "y": 135},
                    "x": 800,
                    "y": 135,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "Released"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {},
                    "inPorts": [
                        {"id": "IN_HANDOVER", "label": "▶ 托盘到位握手 → ST20", "type": "SEQ"},
                        {"id": "IN_SAFE_OUT", "label": "🛡️ 移载缸原位 → ST20护栏", "type": "GUARD"},
                    ],
                    "outPorts": [],
                },
            ],
            "guardEdges": [
                {
                    "id": "G_ST10_OUT",
                    "fromNode": "INST_ST10_TRANS",
                    "fromPort": "OUT_HOME_DI",
                    "toNode": "BOUND_OUT_ST10",
                    "toPort": "IN_SAFE_OUT",
                    "requiredSourceState": "AtHome",
                    "diagCodeHex": "16#0101",
                    "diagCode": "#0101",
                    "humanDescription": "暴露 ST10 移载气缸原位信号 (%I0.4) 至跨站总线",
                    "humanRule": "暴露 ST10 移载气缸原位信号 (%I0.4) 至跨站总线",
                    "isCrossStation": True,
                    "crossStationRef": {
                        "upstreamStationId": "ST10",
                        "upstreamInstanceId": "INST_ST10_TRANS",
                        "physicalTerminal": "%I0.4",
                        "cabinetWireTag": "X12:04",
                    },
                },
            ],
            "temporalSteps": [
                {
                    "id": "T_ST10_10",
                    "stepNo": 10,
                    "title": "阻挡器顶升定位",
                    "fromNode": "INST_ST10_STOP",
                    "fromPort": "OUT_DONE",
                    "toNode": "INST_ST10_TRANS",
                    "toPort": "IN_EXEC",
                    "actionLabel": "伸出推料并退回原位",
                    "sclCall": "PushAndRetract()",
                    "waitDesc": "送料到位且退回 %I0.4",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST10_TRANS",
                            "methodId": "RetractHome",
                            "actionLabel": "伸出推料并退回原位",
                            "targetDiscreteState": "AtHome",
                            "sclStatement": "PushAndRetract()",
                            "waitPredicateScl": "#INST_ST10_TRANS.o_bAtHome",
                        }
                    ],
                },
                {
                    "id": "T_ST10_20",
                    "stepNo": 20,
                    "title": "通知ST20接收托盘",
                    "fromNode": "INST_ST10_TRANS",
                    "fromPort": "OUT_DONE",
                    "toNode": "BOUND_OUT_ST10",
                    "toPort": "IN_HANDOVER",
                    "actionLabel": "发送托盘就绪握手",
                    "sclCall": "o_bPartReady := TRUE",
                    "waitDesc": "ST20 接收确认",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "BOUND_OUT_ST10",
                            "methodId": "ReleaseNext",
                            "actionLabel": "发送托盘就绪握手",
                            "targetDiscreteState": "Released",
                            "sclStatement": "o_bPartReady := TRUE",
                            "waitPredicateScl": "#BOUND_OUT_ST10.o_bPartReady",
                        }
                    ],
                },
            ],
            "ghostEdges": [],
        },
        "ST30": {
            "stationId": "ST30",
            "stationName": "ST30 · 激光测高分拣站",
            "spatialNodes": [
                {
                    "id": "BOUND_IN_ST30",
                    "role": "BOUNDARY_IN",
                    "title": "ST30 · 左输入边界",
                    "driverClass": "STATION_INPUT_PORT",
                    "instanceDb": "来自 ST20 成品放行",
                    "position": {"x": 75, "y": 145},
                    "x": 75,
                    "y": 145,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "Ready"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {},
                    "inPorts": [],
                    "outPorts": [{"id": "OUT_ST20_IN", "label": "● 接收成品触发", "type": "SEQ"}],
                },
                {
                    "id": "INST_ST30_LASER",
                    "role": "ACTUATOR",
                    "title": "高精度激光测高仪",
                    "driverClass": "FB_AF_VisionSensor",
                    "instanceDb": "DB_ST30_LaserGauge",
                    "theme": "amber",
                    "position": {"x": 410, "y": 135},
                    "x": 410,
                    "y": 135,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "InspectOK", "InspectNG"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {"proto": "Profinet"},
                    "ioText": "Profinet 高度采集 · 公差 ±0.05mm",
                    "inPorts": [{"id": "IN_EXEC", "label": "▶ 触发测高采样", "type": "SEQ"}],
                    "outPorts": [{"id": "OUT_OK", "label": "● 高度合格 →", "type": "SEQ"}],
                },
                {
                    "id": "BOUND_OUT_ST30",
                    "role": "BOUNDARY_OUT",
                    "title": "ST30 · 右输出边界",
                    "driverClass": "STATION_OUTPUT_PORT",
                    "instanceDb": "整线良品下线",
                    "position": {"x": 760, "y": 145},
                    "x": 760,
                    "y": 145,
                    "isPinned": True,
                    "hasPartPresentSensor": False,
                    "discreteStates": ["Idle", "Released"],
                    "initialHomeState": "Idle",
                    "cohesiveIoMap": {},
                    "inPorts": [{"id": "IN_LINE_DONE", "label": "▶ 整线完成放行", "type": "SEQ"}],
                    "outPorts": [],
                },
            ],
            "guardEdges": [],
            "temporalSteps": [
                {
                    "id": "T_ST30_10",
                    "stepNo": 10,
                    "title": "激光测量电芯总高",
                    "fromNode": "BOUND_IN_ST30",
                    "fromPort": "OUT_ST20_IN",
                    "toNode": "INST_ST30_LASER",
                    "toPort": "IN_EXEC",
                    "actionLabel": "触发测高采样",
                    "sclCall": "TriggerMeasure()",
                    "waitDesc": "测高数据稳定",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "INST_ST30_LASER",
                            "methodId": "TrigInspect",
                            "actionLabel": "触发测高采样",
                            "targetDiscreteState": "InspectOK",
                            "sclStatement": "TriggerMeasure()",
                            "waitPredicateScl": "#INST_ST30_LASER.o_bDone",
                        }
                    ],
                },
                {
                    "id": "T_ST30_20",
                    "stepNo": 20,
                    "title": "良品流转下线",
                    "fromNode": "INST_ST30_LASER",
                    "fromPort": "OUT_OK",
                    "toNode": "BOUND_OUT_ST30",
                    "toPort": "IN_LINE_DONE",
                    "actionLabel": "放行成品至下料流道",
                    "sclCall": "o_bLineDone := TRUE",
                    "waitDesc": "流道光电通过",
                    "branchPredicate": "ALWAYS",
                    "invocations": [
                        {
                            "targetNodeId": "BOUND_OUT_ST30",
                            "methodId": "ReleaseNext",
                            "actionLabel": "放行成品至下料流道",
                            "targetDiscreteState": "Released",
                            "sclStatement": "o_bLineDone := TRUE",
                            "waitPredicateScl": "#BOUND_OUT_ST30.o_bLineDone",
                        }
                    ],
                },
            ],
            "ghostEdges": [],
        },
    },
}


# --------------------------------------------------------------------------- #
# STA Daemon Optional HTTP Bridge (127.0.0.1:8791)
# --------------------------------------------------------------------------- #

def _resolve_sta_url() -> tuple[str, bool]:
    """Return validated STA daemon base URL and whether it was explicitly configured."""
    explicit_af = os.getenv("AF_STUDIO_STA_URL", "").strip()
    explicit_tia = os.getenv("RESEARCHOS_TIA_SESSION_URL", "").strip()
    explicit = explicit_af or explicit_tia
    if not explicit:
        session_flag = os.getenv("RESEARCHOS_TIA_SESSION", "1").strip().lower()
        if session_flag in {"0", "false", "no", "off"}:
            return "", False
    url = (explicit or _DEFAULT_STA_URL).rstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return "", False
    if not explicit and host not in _LOOPBACK_HOSTS:
        return "", False
    return url, bool(explicit)


def _sta_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = (
        os.getenv("AF_STUDIO_STA_TOKEN", "").strip()
        or os.getenv("RESEARCHOS_TIA_SESSION_TOKEN", "").strip()
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _sta_request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout_s: float = 0.25,
) -> dict[str, Any] | None:
    """Best-effort JSON HTTP call to local Openness STA daemon with fail-closed fallback."""
    base_url, _ = _resolve_sta_url()
    if not base_url:
        return None
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=_sta_headers(),
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 1. Mother-Class Registry & Seed Workspace
# --------------------------------------------------------------------------- #

def get_mother_class_registry(*, force_refresh: bool = False) -> tuple[dict[str, Any], str]:
    """Return AF driver mother-class registry and radial craft menu table.

    Queries ``/reflect-af-library`` on the C# Openness STA daemon when reachable,
    and safely falls back to the built-in offline registry.
    """
    sta_url, is_explicit = _resolve_sta_url()
    now = time.monotonic()

    if sta_url and not force_refresh:
        with _CACHE_LOCK:
            cached = _MOTHER_CLASS_CACHE.get(sta_url)
            if cached and cached[0] > now:
                return copy.deepcopy(cached[1]), cached[2]

    if sta_url:
        resp = _sta_request_json(
            "GET",
            "/reflect-af-library",
            timeout_s=2.0 if is_explicit else 0.25,
        )
        if isinstance(resp, dict) and resp.get("ok") is True and (
            resp.get("motherClasses") or resp.get("classes")
        ):
            mother_classes = resp.get("motherClasses") or resp.get("classes") or BUILTIN_MOTHER_CLASSES
            radial_methods = resp.get("radialMethods") or copy.deepcopy(MOTHER_CLASS_RADIAL_METHODS)
            ev = str(resp.get("evidence_level") or ("V19_real" if resp.get("realTiaConnected") else "offline"))
            if ev not in {"offline", "mocked", "V19_real", "pending_real_machine"}:
                ev = "offline"
            payload = {
                "motherClasses": mother_classes,
                "radialMethods": radial_methods,
                "source": "tia_openness_sta",
                "staOnline": True,
                "staUrl": sta_url,
            }
            with _CACHE_LOCK:
                _MOTHER_CLASS_CACHE[sta_url] = (now + _MOTHER_CLASS_CACHE_TTL_S, copy.deepcopy(payload), ev)
            return payload, ev

    offline_payload = {
        "motherClasses": copy.deepcopy(BUILTIN_MOTHER_CLASSES),
        "radialMethods": copy.deepcopy(MOTHER_CLASS_RADIAL_METHODS),
        "source": "builtin",
        "staOnline": False,
        "staUrl": sta_url or _DEFAULT_STA_URL,
    }
    return offline_payload, "offline"


def get_seed_workspace() -> dict[str, Any]:
    """Return the AssyLine_01 + ST10/ST20/ST30 orthogonal hypergraph seed workspace."""
    return copy.deepcopy(_SEED_WORKSPACE)


# --------------------------------------------------------------------------- #
# Normalization Helpers (Bridging afHyperGraph.types.ts & af_studio_v5.html)
# --------------------------------------------------------------------------- #

def _coerce_station(station: StationHyperGraphIn | dict[str, Any]) -> StationHyperGraphIn:
    if isinstance(station, StationHyperGraphIn):
        return station.model_copy(deep=True)
    return StationHyperGraphIn.model_validate(station)


def _coerce_ghost_tx(
    ghost_tx: GhostGraphTransactionIn | dict[str, Any] | None,
) -> GhostGraphTransactionIn | None:
    if ghost_tx is None:
        return None
    if isinstance(ghost_tx, GhostGraphTransactionIn):
        return ghost_tx.model_copy(deep=True)
    return GhostGraphTransactionIn.model_validate(ghost_tx)


def _sanitized_station_id(station: StationHyperGraphIn) -> str:
    raw = (station.stationId or "").strip()
    if not raw and station.stationName:
        match = re.match(r"([A-Za-z0-9_]+)", station.stationName.strip())
        if match:
            raw = match.group(1)
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw or "ST20")
    return cleaned or "ST20"


def _default_home_state(driver_class: str) -> str:
    return {
        "FB_AF_AxisMotion": "Pos_Home_0",
        "FB_AF_Actuator2Pos": "AtHome",
        "FB_AF_Gripper": "Opened",
        "FB_AF_VisionSensor": "Idle",
        "STATION_INPUT_PORT": "Idle",
        "STATION_OUTPUT_PORT": "Idle",
    }.get(driver_class, "AtHome")


def _infer_discrete_state(
    target_node: SpatialInstanceNodeIn | None,
    method_id: str,
    scl_statement: str,
    action_label: str,
) -> str:
    text = f"{method_id} {scl_statement} {action_label}".lower()
    if "410" in text or "reject" in text or "抛料" in text:
        return "Pos_Reject_410"
    if "245" in text or "press" in text or "压装" in text:
        return "Pos_Press_245"
    if "120" in text or "pick" in text or "取料" in text:
        return "Pos_Pick_120"
    if "movehome" in text or "(0" in text or "待机" in text:
        return "Pos_Home_0"
    if "retract" in text or "athome" in text or "缩回" in text or "退回" in text or "顶升原位" in text:
        return "AtHome"
    if "extend" in text or "下压" in text or "伸出" in text or "剔除" in text:
        return "Extended"
    if "opengrip" in text or "gripopen" in text or "张开" in text or "释放" in text:
        return "Opened"
    if "closegrip" in text or "gripclose" in text or "闭合" in text or "夹紧" in text:
        return "Gripped"
    if "trigger" in text or "inspect" in text or "拍照" in text or "测高" in text:
        return "InspectNG" if "ng" in text else "InspectOK"
    if "release" in text or "cycledone" in text or "partready" in text or "放行" in text:
        return "Released"
    if target_node is not None and target_node.discreteStates:
        return target_node.discreteStates[-1]
    return "Active"


def _normalize_step_invocations(
    step: TemporalStepHyperEdgeIn,
    node_map: dict[str, SpatialInstanceNodeIn],
) -> list[StepInvocationIn]:
    """Normalize either rich `invocations` or flat `toNode`/`parallelNode` step fields."""
    if step.invocations:
        normalized: list[StepInvocationIn] = []
        for inv in step.invocations:
            target_id = inv.targetNodeId or step.toNode
            node = node_map.get(target_id)
            method_id = inv.methodId or step.actionLabel or "Execute"
            scl = inv.sclStatement or step.sclCall or f"{method_id}()"
            state = inv.targetDiscreteState or _infer_discrete_state(
                node, method_id, scl, inv.actionLabel or step.actionLabel
            )
            normalized.append(
                StepInvocationIn(
                    targetNodeId=target_id,
                    methodId=method_id,
                    actionLabel=inv.actionLabel or step.actionLabel or step.title,
                    targetDiscreteState=state,
                    sclStatement=scl,
                    waitPredicateScl=inv.waitPredicateScl or step.waitDesc or "TRUE",
                )
            )
        return normalized

    result: list[StepInvocationIn] = []
    if step.parallelNode and step.parallelNode != step.toNode:
        p_node = node_map.get(step.parallelNode)
        p_label = step.parallelActionLabel or step.actionLabel
        p_scl = step.sclCall.split("+")[0].strip() if "+" in step.sclCall else "RetractHome()"
        result.append(
            StepInvocationIn(
                targetNodeId=step.parallelNode,
                methodId="RetractHome" if "retract" in p_scl.lower() else "ParallelAction",
                actionLabel=p_label,
                targetDiscreteState=_infer_discrete_state(p_node, "", p_scl, p_label),
                sclStatement=p_scl,
                waitPredicateScl=step.waitDesc or "TRUE",
            )
        )
    if step.toNode:
        t_node = node_map.get(step.toNode)
        t_scl = step.sclCall.split("+")[-1].strip() if "+" in step.sclCall else (step.sclCall or "Execute()")
        result.append(
            StepInvocationIn(
                targetNodeId=step.toNode,
                methodId="Execute",
                actionLabel=step.actionLabel or step.title,
                targetDiscreteState=_infer_discrete_state(t_node, "", t_scl, step.actionLabel),
                sclStatement=t_scl,
                waitPredicateScl=step.waitDesc or "TRUE",
            )
        )
    return result


def _node_home_state(node: SpatialInstanceNodeIn) -> str:
    return node.initialHomeState or _default_home_state(node.driverClass)


def _node_pos(node: SpatialInstanceNodeIn) -> tuple[float, float]:
    if node.position is not None:
        return float(node.position.x), float(node.position.y)
    return float(node.x or 0.0), float(node.y or 0.0)


def _guard_diag_hex(guard: SafetyGuardEdgeIn) -> str:
    raw = (guard.diagCodeHex or getattr(guard, "diagCode", "") or "").strip()
    if not raw:
        return "16#0200"
    if raw.startswith("16#"):
        return raw
    return f"16#{raw.lstrip('#')}"


def _guard_human_text(guard: SafetyGuardEdgeIn) -> str:
    return (guard.humanDescription or getattr(guard, "humanRule", "") or "").strip()


def _merge_ghost_tx(
    station: StationHyperGraphIn,
    ghost_tx: GhostGraphTransactionIn | None,
) -> StationHyperGraphIn:
    if ghost_tx is None:
        return station
    merged = station.model_copy(deep=True)
    existing_node_ids = {n.id for n in merged.spatialNodes}
    for n in ghost_tx.addedNodes:
        if n.id not in existing_node_ids:
            merged.spatialNodes.append(n.model_copy(deep=True))
            existing_node_ids.add(n.id)
    existing_guard_ids = {g.id for g in merged.guardEdges}
    for g in ghost_tx.addedGuardEdges:
        if g.id not in existing_guard_ids:
            merged.guardEdges.append(g.model_copy(deep=True))
            existing_guard_ids.add(g.id)
    existing_step_ids = {s.id for s in merged.temporalSteps}
    for s in ghost_tx.addedTemporalSteps:
        if s.id not in existing_step_ids:
            merged.temporalSteps.append(s.model_copy(deep=True))
            existing_step_ids.add(s.id)
    return merged


# --------------------------------------------------------------------------- #
# 2. Algorithm 1: Tarjan SCC + Kahn Layered Auto-Homing Synthesis
# --------------------------------------------------------------------------- #

def _tarjan_cycles(node_ids: list[str], adj: dict[str, list[str]]) -> list[list[str]]:
    """Return all strongly connected components representing cycles (len >= 2 or self-loop)."""
    index_counter = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cyclic_sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index_counter
        indices[v] = index_counter
        lowlink[v] = index_counter
        index_counter += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) >= 2 or (len(scc) == 1 and scc[0] in adj.get(scc[0], [])):
                cyclic_sccs.append(list(reversed(scc)))

    for nid in node_ids:
        if nid not in indices:
            strongconnect(nid)

    return cyclic_sccs


def _synthesize_homing(station: StationHyperGraphIn) -> dict[str, Any]:
    """Run Tarjan SCC cycle detection and Kahn layered topological sort for safe homing."""
    station_id = _sanitized_station_id(station)
    actuators = [
        n
        for n in station.spatialNodes
        if n.role == "ACTUATOR" and n.driverClass != "FB_AF_VisionSensor"
    ]
    act_map = {n.id: n for n in actuators}
    act_ids = [n.id for n in actuators]

    adj: dict[str, list[str]] = {nid: [] for nid in act_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in act_ids}
    seen_edges: set[tuple[str, str]] = set()
    relevant_guard_edges: list[SafetyGuardEdgeIn] = []

    for g in station.guardEdges:
        if g.fromNode in act_map and g.toNode in act_map:
            relevant_guard_edges.append(g)
            pair = (g.fromNode, g.toNode)
            if pair not in seen_edges:
                seen_edges.add(pair)
                adj[g.fromNode].append(g.toNode)
                if g.fromNode != g.toNode:
                    in_degree[g.toNode] += 1

    cyclic_sccs = _tarjan_cycles(act_ids, adj)
    if cyclic_sccs:
        cycle_node_set = {nid for scc in cyclic_sccs for nid in scc}
        cycle_node_ids = [nid for nid in act_ids if nid in cycle_node_set]
        cycle_edge_ids = [
            g.id
            for g in relevant_guard_edges
            if g.fromNode in cycle_node_set and g.toNode in cycle_node_set
        ]
        return {
            "hasCycleDeadlock": True,
            "cycleNodeIds": cycle_node_ids,
            "cycleEdgeIds": cycle_edge_ids,
            "concurrentLayers": [],
            "generatedHomeScl": (
                f"// DEADLOCK ERROR in {station_id}: 护栏偏序图存在闭环死锁 "
                f"({', '.join(cycle_node_ids)})，禁止生成自动归航程序。\n"
            ),
        }

    # Kahn's layered topological sort
    layers_nodes: list[list[SpatialInstanceNodeIn]] = []
    queue = [act_map[nid] for nid in act_ids if in_degree[nid] == 0]
    while queue:
        layers_nodes.append(queue)
        next_queue: list[SpatialInstanceNodeIn] = []
        for u in queue:
            for v_id in adj.get(u.id, []):
                in_degree[v_id] -= 1
                if in_degree[v_id] == 0:
                    next_queue.append(act_map[v_id])
        queue = next_queue

    concurrent_layers: list[list[dict[str, Any]]] = []
    case_blocks: list[str] = []
    for idx, layer in enumerate(layers_nodes):
        step_no = (idx + 1) * 10
        next_step = (idx + 2) * 10 if idx + 1 < len(layers_nodes) else 999
        layer_dicts: list[dict[str, Any]] = []
        stmt_lines: list[str] = []
        done_exprs: list[str] = []

        for node in layer:
            db_name = node.instanceDb or f"DB_{station_id}_{node.id}"
            has_part = bool(node.hasPartPresentSensor)
            homing_op = "IF bPartPresent THEN MaintainGrip ELSE OpenGrip" if has_part else "RetractToHome"
            layer_dicts.append(
                {
                    "id": node.id,
                    "title": node.title,
                    "driverClass": node.driverClass,
                    "instanceDb": db_name,
                    "hasPartPresentSensor": has_part,
                    "initialHomeState": _node_home_state(node),
                    "homingAction": homing_op,
                }
            )
            if has_part:
                stmt_lines.append(
                    f'         IF "{db_name}".o_bPartPresent THEN\n'
                    f'            "{db_name}".i_bMaintainGrip := TRUE; // {node.title} 带料防跌落保持\n'
                    f'         ELSE\n'
                    f'            "{db_name}".i_bCmdHome := TRUE; // {node.title} 空载张开回原位\n'
                    f"         END_IF;"
                )
                done_exprs.append(f'("{db_name}".o_bAtHome OR "{db_name}".o_bPartPresent)')
            else:
                stmt_lines.append(f'         "{db_name}".i_bCmdHome := TRUE; // {node.title}')
                done_exprs.append(f'"{db_name}".o_bAtHome')

        concurrent_layers.append(layer_dicts)
        cond = " AND ".join(done_exprs) if done_exprs else "TRUE"
        case_blocks.append(
            f"      {step_no}: // Kahn 拓扑归航层 Layer {idx + 1}\n"
            + "\n".join(stmt_lines)
            + f"\n         IF {cond} THEN\n"
            + f"            #statHomeStep := {next_step};\n"
            + "         END_IF;"
        )

    if not case_blocks:
        case_blocks.append("      10: // 当前工站无机械执行器需回原位\n         #statHomeStep := 999;")

    home_scl = "\n".join(
        [
            f"// 目标 2: 算法一 (Tarjan + Kahn 偏序拓扑合成) 自动生成的零碰撞归航程序",
            f'FUNCTION_BLOCK "FB_{station_id}_HomeSeq"',
            "{ S7_Optimized_Access := 'TRUE' }",
            "VAR_INPUT",
            "   i_bStartHome : Bool;",
            "END_VAR",
            "VAR_OUTPUT",
            "   o_bHomingDone : Bool;",
            "END_VAR",
            "VAR",
            "   statHomeStep : Int := 10;",
            "END_VAR",
            "BEGIN",
            "   #o_bHomingDone := (#statHomeStep = 999);",
            "   IF NOT #i_bStartHome THEN",
            "      RETURN;",
            "   END_IF;",
            "   CASE #statHomeStep OF",
            "\n\n".join(case_blocks),
            "      999:\n         #o_bHomingDone := TRUE;",
            "   END_CASE;",
            "END_FUNCTION_BLOCK",
        ]
    )

    return {
        "hasCycleDeadlock": False,
        "cycleNodeIds": [],
        "cycleEdgeIds": [],
        "concurrentLayers": concurrent_layers,
        "generatedHomeScl": home_scl,
    }


# --------------------------------------------------------------------------- #
# 3. Algorithm 2: Discrete State-Space BFS Collision & Contention Verifier
# --------------------------------------------------------------------------- #

def _is_ng_branch_step(step: TemporalStepHyperEdgeIn) -> bool:
    if (step.branchPredicate or "").strip().upper() == "NG":
        return True
    if "NG" in (step.fromPort or "").upper():
        return True
    return False


def _build_step_cfg(
    steps: list[TemporalStepHyperEdgeIn],
    node_map: dict[str, SpatialInstanceNodeIn],
) -> tuple[list[int], dict[int, list[int]]]:
    """Build deterministic CFG adjacency across sorted temporal steps including NG branches."""
    ordered = sorted(steps, key=lambda s: (s.stepNo, s.id))
    if not ordered:
        return [], {}

    main_indices: list[int] = []
    ng_indices: list[int] = []

    for idx, step in enumerate(ordered):
        if _is_ng_branch_step(step):
            ng_indices.append(idx)
        else:
            # Also detect follow-up step chained exclusively off an NG branch step
            if (
                ng_indices
                and idx == ng_indices[-1] + 1
                and step.fromNode
                and step.fromNode in {inv.targetNodeId for inv in _normalize_step_invocations(ordered[ng_indices[-1]], node_map)}
                and step.stepNo - ordered[ng_indices[-1]].stepNo < 5
            ):
                ng_indices.append(idx)
            else:
                main_indices.append(idx)

    adj: dict[int, list[int]] = {i: [] for i in range(len(ordered))}
    for pos in range(len(main_indices) - 1):
        adj[main_indices[pos]].append(main_indices[pos + 1])

    # Attach NG chains after the producer step of their source node (or entry)
    ng_set = set(ng_indices)
    i = 0
    while i < len(ng_indices):
        cur_idx = ng_indices[i]
        cur_step = ordered[cur_idx]
        # Find main producer step for cur_step.fromNode prior to cur_step
        fork_idx: int | None = None
        for m_idx in main_indices:
            if ordered[m_idx].stepNo >= cur_step.stepNo:
                break
            targets = {inv.targetNodeId for inv in _normalize_step_invocations(ordered[m_idx], node_map)}
            if cur_step.fromNode and cur_step.fromNode in targets:
                fork_idx = m_idx
        if fork_idx is not None:
            adj[fork_idx].append(cur_idx)
        elif main_indices:
            # If no earlier producer, connect from predecessor main step or root
            prev_main = [m for m in main_indices if ordered[m].stepNo < cur_step.stepNo]
            if prev_main:
                adj[prev_main[-1]].append(cur_idx)

        # Chain consecutive NG steps inside this NG branch
        while i + 1 < len(ng_indices) and ng_indices[i + 1] == ng_indices[i] + 1:
            nxt_idx = ng_indices[i + 1]
            if nxt_idx in ng_set:
                adj[ng_indices[i]].append(nxt_idx)
            i += 1
        i += 1

    roots = [main_indices[0]] if main_indices else [0]
    if not main_indices and len(ordered) > 1:
        for k in range(len(ordered) - 1):
            adj[k].append(k + 1)
    else:
        # Ensure any unreferenced NG roots still get explored
        referenced = {dst for dsts in adj.values() for dst in dsts}
        for r in ng_indices:
            if r not in referenced and r not in roots:
                roots.append(r)

    return roots, adj


def _suggested_guard_edge(
    vertical_node: SpatialInstanceNodeIn,
    axis_node: SpatialInstanceNodeIn,
    existing_guards: list[SafetyGuardEdgeIn],
) -> dict[str, Any]:
    home_state = _node_home_state(vertical_node)
    diag_num = 201 + len(existing_guards)
    edge_id = (
        "G_ST20_Z_TO_X"
        if vertical_node.id == "INST_ST20_Z" and axis_node.id == "INST_ST20_X"
        else f"G_AUTO_{vertical_node.id}_TO_{axis_node.id}"
    )
    diag_hex = "16#0201" if edge_id == "G_ST20_Z_TO_X" else f"16#{diag_num:04d}"
    diag_short = "#0201" if edge_id == "G_ST20_Z_TO_X" else f"#{diag_num:04d}"
    di_home = vertical_node.cohesiveIoMap.get("diHome", "%I10.0")
    human = f"{vertical_node.title or vertical_node.id}处于安全原位 ({di_home}=1)"
    if edge_id == "G_ST20_Z_TO_X":
        human = "Z轴气缸处于顶升原位 (%I10.0=1)"

    from_port = next(
        (p.id for p in vertical_node.outPorts if p.type == "GUARD"),
        "OUT_AT_HOME",
    )
    to_port = next(
        (p.id for p in axis_node.inPorts if p.type == "GUARD"),
        "IN_GUARD",
    )
    return {
        "id": edge_id,
        "fromNode": vertical_node.id,
        "fromPort": from_port,
        "toNode": axis_node.id,
        "toPort": to_port,
        "requiredSourceState": home_state,
        "diagCodeHex": diag_hex,
        "diagCode": diag_short,
        "humanDescription": human,
        "humanRule": human,
        "isHealthy": True,
        "isCrossStation": False,
    }


def verify_hypergraph(
    station: StationHyperGraphIn | dict[str, Any],
    ghost_tx: GhostGraphTransactionIn | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run formal Tarjan+Kahn homing synthesis and discrete state-space BFS collision check."""
    t0 = time.perf_counter()
    st = _merge_ghost_tx(_coerce_station(station), _coerce_ghost_tx(ghost_tx))

    homing_result = _synthesize_homing(st)
    node_map: dict[str, SpatialInstanceNodeIn] = {n.id: n for n in st.spatialNodes}
    vertical_nodes = [
        n
        for n in st.spatialNodes
        if n.role == "ACTUATOR" and n.driverClass == "FB_AF_Actuator2Pos"
    ]

    # Map valid protective guardrails: (fromNode, toNode) -> list[SafetyGuardEdgeIn]
    guard_edges_by_pair: dict[tuple[str, str], list[SafetyGuardEdgeIn]] = {}
    for g in st.guardEdges:
        guard_edges_by_pair.setdefault((g.fromNode, g.toNode), []).append(g)

    issues: list[dict[str, Any]] = []
    seen_issue_keys: set[tuple[Any, ...]] = set()
    suggested_patches: list[dict[str, Any]] = []
    seen_patch_ids: set[str] = set()

    def _add_issue(key: tuple[Any, ...], issue: dict[str, Any]) -> None:
        if key not in seen_issue_keys:
            seen_issue_keys.add(key)
            issues.append(issue)
        patch = issue.get("suggestedGuardEdge")
        if isinstance(patch, dict) and patch.get("id") not in seen_patch_ids:
            seen_patch_ids.add(str(patch["id"]))
            suggested_patches.append(patch)

    if homing_result["hasCycleDeadlock"]:
        _add_issue(
            ("GUARDRAIL_CYCLE_DEADLOCK", tuple(homing_result["cycleNodeIds"])),
            {
                "code": "GUARDRAIL_CYCLE_DEADLOCK",
                "severity": "ERROR",
                "message": (
                    "护栏偏序图存在闭环死锁，Tarjan SCC 检测到循环依赖节点: "
                    + ", ".join(homing_result["cycleNodeIds"])
                ),
                "cycleNodeIds": homing_result["cycleNodeIds"],
                "cycleEdgeIds": homing_result["cycleEdgeIds"],
            },
        )

    ordered_steps = sorted(st.temporalSteps, key=lambda s: (s.stepNo, s.id))

    # 1. Actuator Contention check within each temporal step
    for step in ordered_steps:
        invs = _normalize_step_invocations(step, node_map)
        by_target: dict[str, list[StepInvocationIn]] = {}
        for inv in invs:
            if inv.targetNodeId:
                by_target.setdefault(inv.targetNodeId, []).append(inv)
        for target_id, target_invs in by_target.items():
            if len(target_invs) < 2:
                continue
            states = {inv.targetDiscreteState for inv in target_invs if inv.targetDiscreteState}
            methods = {inv.methodId for inv in target_invs if inv.methodId}
            if len(states) > 1 or (not states and len(methods) > 1):
                _add_issue(
                    ("ACTUATOR_CONTENTION", step.stepNo, target_id),
                    {
                        "code": "ACTUATOR_CONTENTION",
                        "severity": "ERROR",
                        "stepNo": step.stepNo,
                        "stepId": step.id,
                        "nodeId": target_id,
                        "conflictingStates": sorted(states or methods),
                        "message": (
                            f"工步 S{step.stepNo} 对同一执行器 {target_id} 下发冲突动作状态: "
                            + " vs ".join(sorted(states or methods))
                        ),
                    },
                )

    # 2. Discrete State-Space BFS Reachability & Collision Check
    initial_state: dict[str, str] = {
        n.id: _node_home_state(n) for n in st.spatialNodes
    }
    roots, cfg_adj = _build_step_cfg(ordered_steps, node_map)

    explored_keys: set[tuple[int, frozenset[tuple[str, str]]]] = set()
    states_explored = 1  # initial home vector
    bfs_queue: deque[tuple[int, dict[str, str]]] = deque((r, dict(initial_state)) for r in roots)
    max_bfs_states = 4096

    while bfs_queue and states_explored < max_bfs_states:
        step_idx, state = bfs_queue.popleft()
        state_key = (step_idx, frozenset(state.items()))
        if state_key in explored_keys:
            continue
        explored_keys.add(state_key)
        states_explored += 1

        step = ordered_steps[step_idx]
        invs = _normalize_step_invocations(step, node_map)

        # Check horizontal axis motions against vertical actuators
        for inv in invs:
            target_node = node_map.get(inv.targetNodeId)
            if target_node is None or target_node.driverClass != "FB_AF_AxisMotion":
                continue

            for z_node in vertical_nodes:
                z_home = _node_home_state(z_node)
                guards = guard_edges_by_pair.get((z_node.id, target_node.id), [])
                has_home_guard = any(
                    (g.requiredSourceState or z_home) == z_home for g in guards
                )
                z_current = state.get(z_node.id, z_home)

                if not has_home_guard:
                    patch = _suggested_guard_edge(z_node, target_node, st.guardEdges)
                    _add_issue(
                        ("MISSING_GUARDRAIL", step.stepNo, target_node.id, z_node.id),
                        {
                            "code": "MISSING_GUARDRAIL",
                            "severity": "ERROR",
                            "stepNo": step.stepNo,
                            "stepId": step.id,
                            "nodeId": target_node.id,
                            "verticalNodeId": z_node.id,
                            "reachableVerticalState": z_current,
                            "message": (
                                f"Step {step.stepNo} 触发「{target_node.title or target_node.id}」动作时，"
                                f"「{z_node.title or z_node.id}」缺少安全护栏边 (SafetyGuardEdge)，存在碰撞风险！"
                            ),
                            "suggestedGuardEdge": patch,
                        },
                    )

                if z_current != z_home:
                    patch = (
                        None
                        if has_home_guard
                        else _suggested_guard_edge(z_node, target_node, st.guardEdges)
                    )
                    issue_payload: dict[str, Any] = {
                        "code": "COLLISION_REACHABLE",
                        "severity": "ERROR",
                        "stepNo": step.stepNo,
                        "stepId": step.id,
                        "nodeId": target_node.id,
                        "verticalNodeId": z_node.id,
                        "reachableVerticalState": z_current,
                        "expectedSafeState": z_home,
                        "message": (
                            f"BFS 状态可达性碰撞告警: Step {step.stepNo} 驱动水平轴 "
                            f"「{target_node.title or target_node.id}」时，"
                            f"垂直执行器「{z_node.title or z_node.id}」处于非原位状态 {z_current} (安全原位: {z_home})！"
                        ),
                    }
                    if patch is not None:
                        issue_payload["suggestedGuardEdge"] = patch
                    _add_issue(
                        ("COLLISION_REACHABLE", step.stepNo, target_node.id, z_node.id),
                        issue_payload,
                    )

        # Advance discrete state vector
        next_state = dict(state)
        for inv in invs:
            if inv.targetNodeId and inv.targetDiscreteState:
                next_state[inv.targetNodeId] = inv.targetDiscreteState

        for nxt_idx in cfg_adj.get(step_idx, []):
            bfs_queue.append((nxt_idx, dict(next_state)))

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    passed = not any(item.get("severity", "ERROR") == "ERROR" for item in issues)
    warnings = [item["message"] for item in issues]

    return {
        "stationId": _sanitized_station_id(st),
        "passed": passed,
        "verificationTimeMs": elapsed_ms,
        "statesExplored": states_explored,
        "issues": issues,
        "warnings": warnings,
        "suggestedPatches": suggested_patches,
        "homingResult": homing_result,
    }


# --------------------------------------------------------------------------- #
# 4. Deterministic Multi-Target SCL Compiler & Merkle AST Hasher
# --------------------------------------------------------------------------- #

def _short_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def compile_hypergraph(station: StationHyperGraphIn | dict[str, Any]) -> dict[str, Any]:
    """Deterministically compile StationHyperGraph into 4 TIA SCL blocks with Merkle hashes."""
    st = _coerce_station(station)
    station_id = _sanitized_station_id(st)
    node_map = {n.id: n for n in st.spatialNodes}
    homing_result = _synthesize_homing(st)

    # --- Block 1: DB_<stationId>_Instances ---
    canonical_nodes = [
        {
            "id": n.id,
            "role": n.role,
            "driverClass": n.driverClass,
            "instanceDb": n.instanceDb,
            "initialHomeState": _node_home_state(n),
            "discreteStates": list(n.discreteStates),
            "hasPartPresentSensor": bool(n.hasPartPresentSensor),
            "cohesiveIoMap": dict(sorted(n.cohesiveIoMap.items())),
        }
        for n in st.spatialNodes
    ]
    db_name = f"DB_{station_id}_Instances"
    db_decls: list[str] = []
    for item in canonical_nodes:
        if item["role"] == "ACTUATOR":
            inst_name = item["instanceDb"] or f"inst_{item['id']}"
            io_comment = (
                " // " + ", ".join(f"{k}={v}" for k, v in item["cohesiveIoMap"].items())
                if item["cohesiveIoMap"]
                else ""
            )
            db_decls.append(f'      "{inst_name}" : "{item["driverClass"]}";{io_comment}')
    db_scl = "\n".join(
        [
            f"// 目标 4: 空间唯一实例数据块 ({db_name})",
            f'DATA_BLOCK "{db_name}"',
            "{ S7_Optimized_Access := 'TRUE' }",
            "VERSION : 0.1",
            "   STRUCT",
            "\n".join(db_decls) if db_decls else "      _reserved : Bool;",
            "   END_STRUCT;",
            "BEGIN",
            "END_DATA_BLOCK",
        ]
    )
    db_interface = [{"id": item["id"], "driverClass": item["driverClass"], "instanceDb": item["instanceDb"]} for item in canonical_nodes]
    db_block = {
        "name": db_name,
        "kind": "INSTANCES_DB",
        "blockType": "DB",
        "merkleHash": _short_hash({"ast": canonical_nodes, "scl": db_scl}),
        "interfaceHash": _short_hash(db_interface),
        "sclCode": db_scl,
    }

    # --- Block 2: FB_<stationId>_AutoSeq ---
    ordered_steps = sorted(st.temporalSteps, key=lambda s: (s.stepNo, s.id))
    canonical_steps: list[dict[str, Any]] = []
    case_sections: list[str] = []
    for idx, step in enumerate(ordered_steps):
        invs = _normalize_step_invocations(step, node_map)
        next_step = ordered_steps[idx + 1].stepNo if idx + 1 < len(ordered_steps) else 999
        canon_invs = [
            {
                "targetNodeId": inv.targetNodeId,
                "methodId": inv.methodId,
                "actionLabel": inv.actionLabel,
                "targetDiscreteState": inv.targetDiscreteState,
                "sclStatement": inv.sclStatement,
                "waitPredicateScl": inv.waitPredicateScl,
            }
            for inv in invs
        ]
        canonical_steps.append(
            {
                "id": step.id,
                "stepNo": step.stepNo,
                "title": step.title,
                "fromNode": step.fromNode,
                "fromPort": step.fromPort,
                "branchPredicate": step.branchPredicate,
                "invocations": canon_invs,
            }
        )
        call_lines = [
            f'         #{inv["targetNodeId"]}.{inv["sclStatement"]}; // {inv["actionLabel"]}'
            for inv in canon_invs
        ]
        waits = " AND ".join(f'({inv["waitPredicateScl"]})' for inv in canon_invs) or "TRUE"
        case_sections.append(
            f"      {step.stepNo}: // [{step.title}]\n"
            + ("\n".join(call_lines) if call_lines else "         ;")
            + f"\n         IF ({waits}) THEN\n"
            + f"            #statStep := {next_step};\n"
            + "         END_IF;"
        )

    auto_name = f"FB_{station_id}_AutoSeq"
    auto_scl = "\n".join(
        [
            "// 目标 1: 由时序超边 T_seq 100% 确定性生成的自动步 FB",
            f'FUNCTION_BLOCK "{auto_name}"',
            "{ S7_Optimized_Access := 'TRUE' }",
            "VAR_INPUT",
            "   i_bAutoEnable : Bool;",
            "END_VAR",
            "VAR_OUTPUT",
            "   o_bCycleDone : Bool;",
            "END_VAR",
            "VAR",
            "   statStep : Int := 10;",
            "END_VAR",
            "BEGIN",
            "   #o_bCycleDone := (#statStep = 999);",
            "   IF NOT #i_bAutoEnable THEN",
            "      RETURN;",
            "   END_IF;",
            "   CASE #statStep OF",
            "\n\n".join(case_sections) if case_sections else "      10:\n         #statStep := 999;",
            "      999:\n         #o_bCycleDone := TRUE;",
            "   END_CASE;",
            "END_FUNCTION_BLOCK",
        ]
    )
    auto_interface = {
        "name": auto_name,
        "inputs": ["i_bAutoEnable"],
        "outputs": ["o_bCycleDone"],
        "stat": ["statStep"],
    }
    auto_block = {
        "name": auto_name,
        "kind": "AUTO_SEQ",
        "blockType": "FB",
        "merkleHash": _short_hash({"steps": canonical_steps, "scl": auto_scl}),
        "interfaceHash": _short_hash(auto_interface),
        "sclCode": auto_scl,
    }

    # --- Block 3: FB_<stationId>_HomeSeq ---
    home_name = f"FB_{station_id}_HomeSeq"
    home_scl = homing_result["generatedHomeScl"]
    home_ast = {
        "hasCycleDeadlock": homing_result["hasCycleDeadlock"],
        "cycleNodeIds": homing_result["cycleNodeIds"],
        "layers": homing_result["concurrentLayers"],
    }
    home_interface = {
        "name": home_name,
        "inputs": ["i_bStartHome"],
        "outputs": ["o_bHomingDone"],
        "stat": ["statHomeStep"],
    }
    home_block = {
        "name": home_name,
        "kind": "HOME_SEQ",
        "blockType": "FB",
        "merkleHash": _short_hash({"homing": home_ast, "scl": home_scl}),
        "interfaceHash": _short_hash(home_interface),
        "sclCode": home_scl,
    }

    # --- Block 4: FC_<stationId>_GuardDiag ---
    diag_name = f"FC_{station_id}_GuardDiag"
    ordered_guards = sorted(st.guardEdges, key=lambda g: g.id)
    canonical_guards = [
        {
            "id": g.id,
            "fromNode": g.fromNode,
            "fromPort": g.fromPort,
            "toNode": g.toNode,
            "toPort": g.toPort,
            "requiredSourceState": g.requiredSourceState,
            "diagCodeHex": _guard_diag_hex(g),
            "humanDescription": _guard_human_text(g),
            "isCrossStation": bool(g.isCrossStation),
        }
        for g in ordered_guards
    ]
    diag_regions: list[str] = []
    for cg in canonical_guards:
        diag_regions.append(
            f"   // 护栏 {cg['diagCodeHex']}: {cg['humanDescription']}\n"
            f"   IF NOT (#{cg['fromNode']}_{cg['fromPort']}) THEN\n"
            f"      #{cg['toNode']}.o_wBlockDiagCode := {cg['diagCodeHex']};\n"
            f"   END_IF;"
        )
    diag_scl = "\n".join(
        [
            "// 目标 3: 安全约束图 E_guard 编译的互锁引脚与离线 HMI 阻断追因码",
            f'FUNCTION "{diag_name}" : Void',
            "{ S7_Optimized_Access := 'TRUE' }",
            "BEGIN",
            "   REGION Safety_Invariants_And_Diagnostic_Bitmask",
            "\n\n".join(diag_regions) if diag_regions else "      ; // 当前工站无额外跨机构护栏",
            "   END_REGION",
            "END_FUNCTION",
        ]
    )
    diag_interface = {
        "name": diag_name,
        "guardTargets": sorted({g["toNode"] for g in canonical_guards}),
    }
    diag_block = {
        "name": diag_name,
        "kind": "GUARD_DIAG",
        "blockType": "FC",
        "merkleHash": _short_hash({"guards": canonical_guards, "scl": diag_scl}),
        "interfaceHash": _short_hash(diag_interface),
        "sclCode": diag_scl,
    }

    blocks = [db_block, auto_block, home_block, diag_block]
    combined_scl = "\n\n".join(b["sclCode"] for b in blocks)
    return {
        "stationId": station_id,
        "blocks": blocks,
        "blockHashes": {b["name"]: b["merkleHash"] for b in blocks},
        "homingResult": homing_result,
        "combinedScl": combined_scl,
    }


# --------------------------------------------------------------------------- #
# 5. Merkle Block-Level Incremental Sync + Optional STA Bridge
# --------------------------------------------------------------------------- #

def sync_merkle_blocks(
    project_id: str,
    station: StationHyperGraphIn | dict[str, Any],
    *,
    previous_hashes: dict[str, str] | None = None,
    project_path: str | None = None,
    plc_name: str = "",
    software_unit: str = "",
) -> tuple[dict[str, Any], str]:
    """Compute Merkle block diffs and optionally sync dirty blocks via TIA Openness STA."""
    compiled = compile_hypergraph(station)
    blocks = compiled["blocks"]
    station_id = compiled["stationId"]
    pid = (project_id or "AssyLine_01").strip() or "AssyLine_01"

    with _CACHE_LOCK:
        if previous_hashes is not None:
            baseline = dict(previous_hashes)
        else:
            baseline = dict(_LAST_SYNCED_HASHES.get(pid, {}))

    sync_blocks: list[dict[str, Any]] = []
    dirty_blocks: list[str] = []
    unchanged_blocks: list[str] = []

    for blk in blocks:
        name = blk["name"]
        prev_hash = baseline.get(name)
        is_dirty = prev_hash != blk["merkleHash"]
        status = "DIRTY" if is_dirty else "UNCHANGED"
        if is_dirty:
            dirty_blocks.append(name)
        else:
            unchanged_blocks.append(name)
        sync_blocks.append(
            {
                "name": name,
                "kind": blk["kind"],
                "blockType": blk["blockType"],
                "merkleHash": blk["merkleHash"],
                "interfaceHash": blk["interfaceHash"],
                "previousHash": prev_hash,
                "status": status,
            }
        )

    current_hashes = {b["name"]: b["merkleHash"] for b in blocks}
    clean_project_path = (project_path or "").strip()

    if not clean_project_path:
        with _CACHE_LOCK:
            entry = _LAST_SYNCED_HASHES.setdefault(pid, {})
            entry.update(current_hashes)
        payload = {
            "projectId": pid,
            "stationId": station_id,
            "blocks": sync_blocks,
            "dirtyBlocks": dirty_blocks,
            "unchangedBlocks": unchanged_blocks,
            "dirtyCount": len(dirty_blocks),
            "unchangedCount": len(unchanged_blocks),
            "currentHashes": current_hashes,
            "tiaSynced": False,
            "compileOk": None,
            "notice": "离线 Merkle 缓存同步完成（未指定博途工程路径，未写入真实 TIA Portal）。",
        }
        return payload, "offline"

    # Real TIA Openness STA bridge requested via project_path
    sta_payload = {
        "projectPath": clean_project_path,
        "stationId": station_id,
        "plcName": plc_name,
        "softwareUnit": software_unit,
        "dirtyBlocks": dirty_blocks,
        "unchangedBlocks": unchanged_blocks,
        "blocks": [
            {
                "name": b["name"],
                "blockType": b["blockType"],
                "merkleHash": b["merkleHash"],
                "interfaceHash": b["interfaceHash"],
                "sclCode": b["sclCode"],
                "status": "DIRTY" if b["name"] in dirty_blocks else "UNCHANGED",
            }
            for b in blocks
        ],
    }
    _, is_explicit = _resolve_sta_url()
    sta_resp = _sta_request_json(
        "POST",
        "/merkle-sync",
        sta_payload,
        timeout_s=15.0 if is_explicit else 0.5,
    )

    if isinstance(sta_resp, dict) and sta_resp.get("compileOk") is True:
        with _CACHE_LOCK:
            entry = _LAST_SYNCED_HASHES.setdefault(pid, {})
            entry.update(current_hashes)
        payload = {
            "projectId": pid,
            "stationId": station_id,
            "blocks": sync_blocks,
            "dirtyBlocks": dirty_blocks,
            "unchangedBlocks": unchanged_blocks,
            "dirtyCount": len(dirty_blocks),
            "unchangedCount": len(unchanged_blocks),
            "currentHashes": current_hashes,
            "tiaSynced": True,
            "compileOk": True,
            "staReceipt": sta_resp,
            "notice": f"已通过博途 Openness STA 完成 {len(dirty_blocks)} 个变更块增量编译。",
        }
        return payload, "V19_real"

    # Never fabricate V19_real when STA is unreachable or compileOk is not True
    reason = (
        str(sta_resp.get("error") or sta_resp.get("message") or "STA 守护服务未返回 compileOk=True")
        if isinstance(sta_resp, dict)
        else "未连接博途 TIA Openness STA 守护服务 (127.0.0.1:8791)"
    )
    payload = {
        "projectId": pid,
        "stationId": station_id,
        "blocks": sync_blocks,
        "dirtyBlocks": dirty_blocks,
        "unchangedBlocks": unchanged_blocks,
        "dirtyCount": len(dirty_blocks),
        "unchangedCount": len(unchanged_blocks),
        "currentHashes": current_hashes,
        "tiaSynced": False,
        "compileOk": False,
        "staReceipt": sta_resp,
        "notice": f"未连博途 / 实机编译未完成：{reason}",
    }
    return payload, "pending_real_machine"


# --------------------------------------------------------------------------- #
# 6. Neuro-Symbolic Copilot Ghost Wire Diff & Excel Table Cold Start
# --------------------------------------------------------------------------- #

def _infer_driver_class(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ("伺服", "servo", "axis", "移载轴", "搬运轴", "x轴", "y轴")):
        return "FB_AF_AxisMotion"
    if any(k in lower for k in ("夹爪", "抓手", "gripper", "卡爪")):
        return "FB_AF_Gripper"
    if any(k in lower for k in ("相机", "视觉", "测高", "激光", "扫码", "vision", "laser", "sensor", "cam")):
        return "FB_AF_VisionSensor"
    return "FB_AF_Actuator2Pos"


def _find_free_slot(existing_nodes: list[SpatialInstanceNodeIn]) -> tuple[float, float]:
    """Find a non-overlapping canvas slot without shifting any pinned nodes."""
    coords = [_node_pos(n) for n in existing_nodes]
    slot_x = 410.0
    slot_y = 290.0
    for step in range(24):
        if not any(abs(nx - slot_x) < 120 and abs(ny - slot_y) < 95 for nx, ny in coords):
            return slot_x, slot_y
        slot_x = 260.0 + ((step * 145) % 520)
        slot_y = 95.0 + ((step // 3) * 110 % 320)
    return slot_x, slot_y


def _default_ports_for_driver(driver_class: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    for mc in BUILTIN_MOTHER_CLASSES:
        if mc["driverClass"] == driver_class:
            return copy.deepcopy(mc["defaultInPorts"]), copy.deepcopy(mc["defaultOutPorts"])
    return (
        [{"id": "IN_EXEC", "label": "▶ 动作触发槽", "type": "SEQ"}],
        [{"id": "OUT_DONE", "label": "● 动作到位 →", "type": "SEQ"}],
    )


def _row_str(row: dict[str, Any], *keys: str) -> str:
    for k in keys:
        val = row.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _parse_table_cold_start(
    st: StationHyperGraphIn,
    timing_rows: list[dict[str, Any]] | None,
    io_rows: list[dict[str, Any]] | None,
) -> tuple[list[SpatialInstanceNodeIn], list[TemporalStepHyperEdgeIn]]:
    """Deduplicate mechanical timing + IO rows into unique SpatialInstanceNodes & steps."""
    station_id = _sanitized_station_id(st)
    added_nodes: list[SpatialInstanceNodeIn] = []
    added_steps: list[TemporalStepHyperEdgeIn] = []

    # Index existing and newly synthesized devices by normalized name / DB / ID
    device_index: dict[str, SpatialInstanceNodeIn] = {}
    all_nodes = list(st.spatialNodes)

    def _register_node(n: SpatialInstanceNodeIn) -> None:
        for key in (n.id, n.instanceDb, n.title):
            if key and key.strip():
                device_index[key.strip().lower()] = n

    for existing in st.spatialNodes:
        _register_node(existing)

    def _ensure_device(
        name: str,
        driver_hint: str = "",
        db_hint: str = "",
        io_map: dict[str, str] | None = None,
        has_part_sensor: bool = False,
    ) -> SpatialInstanceNodeIn:
        for candidate in (db_hint, name):
            if candidate and candidate.strip().lower() in device_index:
                node = device_index[candidate.strip().lower()]
                if io_map:
                    node.cohesiveIoMap.update(io_map)
                return node

        driver = driver_hint or _infer_driver_class(f"{name} {db_hint}")
        seq = len(all_nodes) + 1
        slug = re.sub(r"[^A-Za-z0-9]+", "_", db_hint or name).strip("_").upper() or f"DEV_{seq}"
        node_id = f"INST_{station_id}_{slug}"
        if node_id.lower() in device_index:
            node_id = f"{node_id}_{seq}"
        inst_db = db_hint or f"DB_{station_id}_{slug}"
        sx, sy = _find_free_slot(all_nodes)
        in_ports, out_ports = _default_ports_for_driver(driver)
        home = _default_home_state(driver)
        states = next(
            (mc["defaultDiscreteStates"] for mc in BUILTIN_MOTHER_CLASSES if mc["driverClass"] == driver),
            [home, "Active"],
        )
        io_desc = " · ".join(f"{k} {v}" for k, v in (io_map or {}).items()) or "表格冷启动自动生成"
        new_node = SpatialInstanceNodeIn.model_validate(
            {
                "id": node_id,
                "role": "ACTUATOR",
                "title": name or inst_db,
                "driverClass": driver,
                "instanceDb": inst_db,
                "position": {"x": sx, "y": sy},
                "x": sx,
                "y": sy,
                "isPinned": False,
                "hasPartPresentSensor": has_part_sensor,
                "discreteStates": list(states),
                "initialHomeState": home,
                "cohesiveIoMap": dict(io_map or {}),
                "ioText": io_desc,
                "inPorts": in_ports,
                "outPorts": out_ports,
            }
        )
        all_nodes.append(new_node)
        added_nodes.append(new_node)
        _register_node(new_node)
        return new_node

    # 1. Process IO table rows first (builds cohesive device map)
    for row in io_rows or []:
        name = _row_str(row, "name", "title", "device", "设备名称", "机构名称", "instanceDb")
        db_hint = _row_str(row, "instanceDb", "db", "背景DB")
        driver_hint = _row_str(row, "driverClass", "driver", "motherClass", "母版")
        if not name and not db_hint:
            continue
        io_map: dict[str, str] = {}
        for k_src, k_dst in (
            ("diHome", "diHome"),
            ("原位", "diHome"),
            ("diWork", "diWork"),
            ("动位", "diWork"),
            ("doWork", "doWork"),
            ("输出", "doWork"),
            ("terminal", "terminal"),
            ("地址", "terminal"),
        ):
            val = _row_str(row, k_src)
            if val:
                io_map[k_dst] = val
        has_part = bool(row.get("hasPartPresentSensor") or row.get("带料检测"))
        _ensure_device(name or db_hint, driver_hint=driver_hint, db_hint=db_hint, io_map=io_map, has_part_sensor=has_part)

    # 2. Process timing table rows (reuses deduplicated spatial nodes)
    max_step = max((s.stepNo for s in st.temporalSteps), default=0)
    prev_target_id = st.spatialNodes[0].id if st.spatialNodes else ""
    for idx, row in enumerate(timing_rows or []):
        raw_step = row.get("stepNo") or row.get("step") or row.get("工步")
        try:
            step_no = int(raw_step) if raw_step is not None else max_step + (idx + 1) * 10
        except (TypeError, ValueError):
            step_no = max_step + (idx + 1) * 10

        target_name = _row_str(
            row, "target", "targetNodeId", "device", "instanceDb", "title", "执行器", "设备名称"
        )
        driver_hint = _row_str(row, "driverClass", "driver")
        db_hint = _row_str(row, "instanceDb", "db")
        if not target_name and not db_hint:
            continue
        target_node = _ensure_device(target_name or db_hint, driver_hint=driver_hint, db_hint=db_hint)

        action_label = _row_str(row, "actionLabel", "action", "methodId", "动作", "title") or f"{target_node.title}动作"
        method_id = _row_str(row, "methodId", "method") or "Execute"
        scl_call = _row_str(row, "sclCall", "sclStatement", "scl") or f"{method_id}()"
        wait_desc = _row_str(row, "waitDesc", "waitPredicateScl", "wait") or f"#{target_node.id}.o_bDone"
        target_state = _row_str(row, "targetDiscreteState") or _infer_discrete_state(
            target_node, method_id, scl_call, action_label
        )
        step_title = _row_str(row, "title", "name", "步骤名称") or action_label
        from_node = _row_str(row, "fromNode", "predecessor") or prev_target_id or target_node.id
        from_port = _row_str(row, "fromPort") or (
            "OUT_OK" if node_map_has_port(all_nodes, from_node, "OUT_OK") else "OUT_DONE"
        )
        branch = _row_str(row, "branchPredicate") or "ALWAYS"

        added_steps.append(
            TemporalStepHyperEdgeIn.model_validate(
                {
                    "id": f"GW_TBL_{station_id}_{step_no}_{idx + 1}",
                    "stepNo": step_no,
                    "title": step_title,
                    "fromNode": from_node,
                    "fromPort": from_port,
                    "toNode": target_node.id,
                    "toPort": "IN_EXEC",
                    "actionLabel": action_label,
                    "sclCall": scl_call,
                    "waitDesc": wait_desc,
                    "branchPredicate": branch,
                    "invocations": [
                        {
                            "targetNodeId": target_node.id,
                            "methodId": method_id,
                            "actionLabel": action_label,
                            "targetDiscreteState": target_state,
                            "sclStatement": scl_call,
                            "waitPredicateScl": wait_desc,
                        }
                    ],
                }
            )
        )
        prev_target_id = target_node.id

    return added_nodes, added_steps


def node_map_has_port(nodes: list[SpatialInstanceNodeIn], node_id: str, port_id: str) -> bool:
    for n in nodes:
        if n.id == node_id:
            return any(p.id == port_id for p in n.outPorts)
    return False


def propose_ghost_transaction(
    station: StationHyperGraphIn | dict[str, Any],
    *,
    prompt: str | None = None,
    timing_table_rows: list[dict[str, Any]] | None = None,
    io_table_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Synthesize a neuro-symbolic GhostGraphTransaction and verify it via BFS + Kahn."""
    st = _coerce_station(station)
    station_id = _sanitized_station_id(st)
    added_nodes: list[SpatialInstanceNodeIn] = []
    added_guards: list[SafetyGuardEdgeIn] = []
    added_steps: list[TemporalStepHyperEdgeIn] = []
    summary_parts: list[str] = []

    if timing_table_rows or io_table_rows:
        tbl_nodes, tbl_steps = _parse_table_cold_start(st, timing_table_rows, io_table_rows)
        added_nodes.extend(tbl_nodes)
        added_steps.extend(tbl_steps)
        summary_parts.append(
            f"表格冷启动去重生成 {len(tbl_nodes)} 个唯一空间实例节点与 {len(tbl_steps)} 条虚影时序超边"
        )

    clean_prompt = (prompt or "").strip()
    if clean_prompt:
        upper = clean_prompt.upper()
        if any(k in upper for k in ("NG", "抛料", "剔除", "REJECT")):
            cam = next((n for n in st.spatialNodes if n.driverClass == "FB_AF_VisionSensor"), None)
            axis = next((n for n in st.spatialNodes if n.driverClass == "FB_AF_AxisMotion"), None)
            grip = next((n for n in st.spatialNodes if n.driverClass == "FB_AF_Gripper"), None)

            used_steps = {s.stepNo for s in st.temporalSteps}
            s35 = 35 if 35 not in used_steps else max(used_steps, default=30) + 5
            s36 = s35 + 1

            cam_id = cam.id if cam else (st.spatialNodes[0].id if st.spatialNodes else f"BOUND_IN_{station_id}")
            axis_id = axis.id if axis else (
                next((n.id for n in st.spatialNodes if n.role == "ACTUATOR"), cam_id)
            )
            grip_id = grip.id if grip else axis_id

            added_steps.append(
                TemporalStepHyperEdgeIn.model_validate(
                    {
                        "id": f"GW_NG_{s35}",
                        "stepNo": s35,
                        "title": "NG移至抛料位",
                        "fromNode": cam_id,
                        "fromPort": "OUT_NG",
                        "toNode": axis_id,
                        "toPort": "IN_EXEC",
                        "actionLabel": "移至NG抛料位 (410mm)",
                        "sclCall": "MoveAbs(410.0)",
                        "waitDesc": "到达 410mm 抛料口",
                        "branchPredicate": "NG",
                        "invocations": [
                            {
                                "targetNodeId": axis_id,
                                "methodId": "MoveReject",
                                "actionLabel": "移至NG抛料位 (410mm)",
                                "targetDiscreteState": "Pos_Reject_410",
                                "sclStatement": "MoveAbs(410.0)",
                                "waitPredicateScl": f"#{axis_id}.o_bDone",
                            }
                        ],
                    }
                )
            )
            added_steps.append(
                TemporalStepHyperEdgeIn.model_validate(
                    {
                        "id": f"GW_NG_{s36}",
                        "stepNo": s36,
                        "title": "NG张开夹爪抛料",
                        "fromNode": axis_id,
                        "fromPort": "OUT_DONE",
                        "toNode": grip_id,
                        "toPort": "IN_EXEC",
                        "actionLabel": "张开释放NG电芯",
                        "sclCall": "OpenGrip()",
                        "waitDesc": "夹爪张开到位",
                        "branchPredicate": "NG",
                        "invocations": [
                            {
                                "targetNodeId": grip_id,
                                "methodId": "GripOpen",
                                "actionLabel": "张开释放NG电芯",
                                "targetDiscreteState": "Opened",
                                "sclStatement": "OpenGrip()",
                                "waitPredicateScl": f"#{grip_id}.o_bOpened",
                            }
                        ],
                    }
                )
            )
            summary_parts.append(f"生成视觉 NG 抛料虚影分支 (S{s35} X轴去410mm → S{s36} 夹爪张开)")

        elif any(k in clean_prompt for k in ("护栏", "防撞", "互锁", "guard", "interlock")):
            report = verify_hypergraph(st)
            for patch in report.get("suggestedPatches", []):
                added_guards.append(SafetyGuardEdgeIn.model_validate(patch))
            if added_guards:
                summary_parts.append(f"生成 {len(added_guards)} 条安全防撞护栏建议补丁")
            else:
                summary_parts.append("当前工站机械护栏已完备，无需额外补充防撞边")

        else:
            max_step = max((s.stepNo for s in st.temporalSteps), default=0)
            next_step = max_step + 10
            act = next((n for n in st.spatialNodes if n.role == "ACTUATOR"), None)
            if act is not None:
                is_home_cmd = any(k in clean_prompt.lower() for k in ("回原", "归位", "home"))
                if act.driverClass == "FB_AF_AxisMotion":
                    method_id = "MoveHome" if is_home_cmd else "MovePick"
                    scl = "MoveAbs(0.0)" if is_home_cmd else "MoveAbs(120.0)"
                    state = "Pos_Home_0" if is_home_cmd else "Pos_Pick_120"
                elif act.driverClass == "FB_AF_Gripper":
                    method_id = "GripOpen" if is_home_cmd else "GripClose"
                    scl = "OpenGrip()" if is_home_cmd else "CloseGrip()"
                    state = "Opened" if is_home_cmd else "Gripped"
                else:
                    method_id = "RetractHome" if is_home_cmd else "ExtendWork"
                    scl = "RetractHome()" if is_home_cmd else "ExtendWork()"
                    state = "AtHome" if is_home_cmd else "Extended"
                added_steps.append(
                    TemporalStepHyperEdgeIn.model_validate(
                        {
                            "id": f"GW_NL_{next_step}",
                            "stepNo": next_step,
                            "title": clean_prompt[:32],
                            "fromNode": act.id,
                            "fromPort": "OUT_DONE",
                            "toNode": act.id,
                            "toPort": "IN_EXEC",
                            "actionLabel": clean_prompt[:32],
                            "sclCall": scl,
                            "waitDesc": f"#{act.id}.o_bDone",
                            "branchPredicate": "ALWAYS",
                            "invocations": [
                                {
                                    "targetNodeId": act.id,
                                    "methodId": method_id,
                                    "actionLabel": clean_prompt[:32],
                                    "targetDiscreteState": state,
                                    "sclStatement": scl,
                                    "waitPredicateScl": f"#{act.id}.o_bDone",
                                }
                            ],
                        }
                    )
                )
            summary_parts.append(f"根据口述指令「{clean_prompt[:36]}」生成虚影超边")

    tx_id = f"tx_{uuid.uuid4().hex[:10]}"
    tx = GhostGraphTransactionIn(
        txId=tx_id,
        summary="；".join(summary_parts) if summary_parts else "未识别到增量变更条目",
        addedNodes=added_nodes,
        addedGuardEdges=added_guards,
        addedTemporalSteps=added_steps,
    )

    verification_report = verify_hypergraph(st, ghost_tx=tx)
    tx.verificationPassed = bool(verification_report["passed"])
    tx.verifierWarnings = list(verification_report["warnings"])

    result = tx.model_dump()
    result["verificationReport"] = verification_report
    return result


# --------------------------------------------------------------------------- #
# 7. Algorithm 3: Cross-Station Minimal Falsifying Cut-Set & Camera Fly-To
# --------------------------------------------------------------------------- #

_TERMINAL_RE = re.compile(r"%[IQM]\d+\.\d+", re.IGNORECASE)


def _pull_live_signals(overrides: dict[str, bool] | None) -> tuple[dict[str, bool], str]:
    signals: dict[str, bool] = {
        "ST20_CylZ.%I10.0": True,
        "ST10_CylTrans.%I0.4": False,
        "%I10.0": True,
        "%I0.4": False,
    }
    source = "simulated_snapshot"
    if overrides is None:
        sta_resp = _sta_request_json("GET", "/live-signals", timeout_s=0.25)
        if isinstance(sta_resp, dict) and isinstance(sta_resp.get("signals"), dict):
            for k, v in sta_resp["signals"].items():
                signals[str(k)] = bool(v)
            source = "sta_live_snapshot"
    else:
        for k, v in overrides.items():
            key = str(k)
            val = bool(v)
            signals[key] = val
            if key == "%I0.4":
                signals["ST10_CylTrans.%I0.4"] = val
            elif key == "ST10_CylTrans.%I0.4":
                signals["%I0.4"] = val
            elif key == "%I10.0":
                signals["ST20_CylZ.%I10.0"] = val
            elif key == "ST20_CylZ.%I10.0":
                signals["%I10.0"] = val
        source = "caller_live_signals"
    return signals, source


def _evaluate_guard_edge(
    guard: SafetyGuardEdgeIn,
    station: StationHyperGraphIn,
    signals: dict[str, bool],
) -> tuple[bool, str]:
    """Evaluate boolean status and terminal label for a SafetyGuardEdge."""
    node_map = {n.id: n for n in station.spatialNodes}
    terminal = ""

    if guard.crossStationRef and guard.crossStationRef.physicalTerminal:
        terminal = guard.crossStationRef.physicalTerminal
    else:
        src_node = node_map.get(guard.fromNode)
        if src_node and src_node.cohesiveIoMap.get("diHome"):
            terminal = src_node.cohesiveIoMap["diHome"]
        else:
            match = _TERMINAL_RE.search(_guard_human_text(guard))
            if match:
                terminal = match.group(0)

    # Explicit signal lookup by guard id, node/terminal composite, or raw terminal
    if guard.id in signals:
        return bool(signals[guard.id]), terminal or guard.id
    for k, v in signals.items():
        if terminal and (k == terminal or k.endswith(f".{terminal}")):
            return bool(v), terminal
    if guard.isHealthy is not None:
        return bool(guard.isHealthy), terminal
    return True, terminal


def trace_cutset_snapshot(
    project_graph: ProjectHyperGraphIn | dict[str, Any] | None,
    station_graphs: dict[str, StationHyperGraphIn | dict[str, Any]],
    fault_station_id: str,
    fault_step_no: int,
    live_signals: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Prune TRUE guardrails and penetrate FALSE minimal cut-set across L2 -> L1 -> upstream L2."""
    seed = get_seed_workspace()
    proj = (
        ProjectHyperGraphIn.model_validate(seed["projectGraph"])
        if project_graph is None
        else (
            project_graph
            if isinstance(project_graph, ProjectHyperGraphIn)
            else ProjectHyperGraphIn.model_validate(project_graph)
        )
    )
    if not station_graphs:
        stations = {
            sid: _coerce_station(sg) for sid, sg in seed["stationHyperGraphs"].items()
        }
    else:
        stations = {sid: _coerce_station(sg) for sid, sg in station_graphs.items()}

    if fault_station_id not in stations:
        raise KeyError(f"unknown fault station {fault_station_id!r}")

    fault_station = stations[fault_station_id]
    node_map = {n.id: n for n in fault_station.spatialNodes}
    step = next((s for s in fault_station.temporalSteps if s.stepNo == fault_step_no), None)
    if step is None:
        raise LookupError(f"step {fault_step_no} not found in station {fault_station_id!r}")

    target_node_ids = [
        inv.targetNodeId for inv in _normalize_step_invocations(step, node_map) if inv.targetNodeId
    ]
    focus_node_id = target_node_ids[0] if target_node_ids else ""
    signals, signal_source = _pull_live_signals(live_signals)

    guard_candidates = [
        g for g in fault_station.guardEdges if g.toNode in set(target_node_ids)
    ]

    pruned_healthy_edges: list[dict[str, Any]] = []
    falsified_edges: list[dict[str, Any]] = []
    root_causes: list[dict[str, Any]] = []

    for g in guard_candidates:
        is_true, terminal = _evaluate_guard_edge(g, fault_station, signals)
        diag_short = f"#{_guard_diag_hex(g).replace('16#', '')}"
        if is_true:
            pruned_healthy_edges.append(
                {
                    "edgeId": g.id,
                    "fromNode": g.fromNode,
                    "toNode": g.toNode,
                    "diagCode": diag_short,
                    "terminal": terminal,
                    "signalValue": True,
                    "prunedReason": f"✔ 已剪枝健康项 {diag_short} ({terminal}=True)",
                }
            )
            continue

        falsified_entry: dict[str, Any] = {
            "edgeId": g.id,
            "fromNode": g.fromNode,
            "toNode": g.toNode,
            "diagCode": diag_short,
            "terminal": terminal,
            "signalValue": False,
            "isCrossStation": bool(g.isCrossStation or g.crossStationRef),
            "humanDescription": _guard_human_text(g),
        }
        falsified_edges.append(falsified_entry)

        # Penetrate across L1 boundary if cross-station guardrail
        if g.crossStationRef or g.isCrossStation:
            up_station_id = (
                g.crossStationRef.upstreamStationId
                if g.crossStationRef and g.crossStationRef.upstreamStationId
                else ""
            )
            if not up_station_id:
                # Resolve via L1 GUARD edge
                station_node_by_id = {s.stationId: s.id for s in proj.stations}
                station_id_by_node = {s.id: s.stationId for s in proj.stations}
                target_l1_node = station_node_by_id.get(fault_station_id, f"NODE_{fault_station_id}")
                for pe in proj.edges:
                    if pe.kind == "GUARD" and pe.toNode == target_l1_node:
                        up_station_id = station_id_by_node.get(pe.fromNode, "")
                        break

            up_station = stations.get(up_station_id)
            up_node_id = (
                g.crossStationRef.upstreamInstanceId
                if g.crossStationRef and g.crossStationRef.upstreamInstanceId
                else ""
            )
            up_terminal = (
                g.crossStationRef.physicalTerminal
                if g.crossStationRef and g.crossStationRef.physicalTerminal
                else terminal
            )
            cabinet_tag = (
                g.crossStationRef.cabinetWireTag
                if g.crossStationRef and g.crossStationRef.cabinetWireTag
                else ""
            )

            up_node: SpatialInstanceNodeIn | None = None
            if up_station:
                up_node_map = {n.id: n for n in up_station.spatialNodes}
                if up_node_id and up_node_id in up_node_map:
                    up_node = up_node_map[up_node_id]
                else:
                    for ug in up_station.guardEdges:
                        cand = up_node_map.get(ug.fromNode)
                        if cand and cand.role == "ACTUATOR":
                            up_node = cand
                            up_node_id = cand.id
                            break
                if up_node:
                    up_terminal = up_terminal or up_node.cohesiveIoMap.get("diHome", "")
                    cabinet_tag = cabinet_tag or up_node.cohesiveIoMap.get("cabinetWireTag", "")

            root_causes.append(
                {
                    "stationId": up_station_id or fault_station_id,
                    "nodeId": up_node_id or g.fromNode,
                    "nodeTitle": up_node.title if up_node else g.fromNode,
                    "instanceDb": up_node.instanceDb if up_node else "",
                    "physicalTerminal": up_terminal,
                    "cabinetWireTag": cabinet_tag,
                    "signalValue": False,
                    "diagCode": diag_short,
                }
            )
        else:
            src_node = node_map.get(g.fromNode)
            root_causes.append(
                {
                    "stationId": fault_station_id,
                    "nodeId": g.fromNode,
                    "nodeTitle": src_node.title if src_node else g.fromNode,
                    "instanceDb": src_node.instanceDb if src_node else "",
                    "physicalTerminal": terminal,
                    "cabinetWireTag": src_node.cohesiveIoMap.get("cabinetWireTag", "") if src_node else "",
                    "signalValue": False,
                    "diagCode": diag_short,
                }
            )

    camera_fly_steps: list[dict[str, Any]] = []
    if falsified_edges and root_causes:
        rc = root_causes[0]
        l1_fault_edge = next((e.id for e in proj.edges if e.kind == "GUARD"), "E_L1_2")
        pruned_desc = ", ".join(
            f"{p['terminal']}=True" if p["terminal"] else p["edgeId"]
            for p in pruned_healthy_edges
        ) or "无"
        camera_fly_steps = [
            {
                "stage": 1,
                "layer": "STATION",
                "stationId": fault_station_id,
                "focusNodeId": focus_node_id,
                "prunedEdgeIds": [p["edgeId"] for p in pruned_healthy_edges],
                "faultEdgeIds": [f["edgeId"] for f in falsified_edges],
                "tag": f"巡航 1/3 · {fault_station_id} 受阻现场",
                "description": (
                    f"最小证伪割集已剪枝健康分支 ({pruned_desc})，"
                    f"锁定 FALSE 输入来自护栏 {falsified_edges[0]['diagCode']}，镜头拉出至产线总图..."
                ),
            },
            {
                "stage": 2,
                "layer": "PROJECT",
                "stationId": None,
                "focusEdgeId": l1_fault_edge,
                "fromStationId": fault_station_id,
                "toStationId": rc["stationId"],
                "tag": "巡航 2/3 · L1 跨工站割集穿越",
                "description": (
                    f"沿产线跨站安全边逆向飞跃：从 {fault_station_id} 穿透至上游 {rc['stationId']}，"
                    "准备推入锁定物理传感器端子..."
                ),
            },
            {
                "stage": 3,
                "layer": "STATION",
                "stationId": rc["stationId"],
                "focusNodeId": rc["nodeId"],
                "physicalTerminal": rc["physicalTerminal"],
                "cabinetWireTag": rc["cabinetWireTag"],
                "tag": "巡航 3/3 · 真凶物理端子已锁定",
                "description": (
                    f"根因定位完成：上游 {rc['stationId']}「{rc['nodeTitle']} ({rc['instanceDb']})」"
                    f"原位信号丢失 ({rc['physicalTerminal']}=False，电柜端子 {rc['cabinetWireTag']})！"
                ),
            },
        ]

    return {
        "faultStationId": fault_station_id,
        "faultStepNo": fault_step_no,
        "blockedNodeId": focus_node_id,
        "signalSource": signal_source,
        "liveSignals": signals,
        "faultResolved": len(falsified_edges) == 0,
        "prunedHealthyEdges": pruned_healthy_edges,
        "falsifiedEdges": falsified_edges,
        "rootCauses": root_causes,
        "cameraFlySteps": camera_fly_steps,
    }
