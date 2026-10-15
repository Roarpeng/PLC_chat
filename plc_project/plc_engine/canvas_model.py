"""Interactive PLC & HMI Canvas Data Model, Mutation Engine, and Attribution System.

Supports dual-layer canvas (PLC logic and HMI screens), conversational patch operations,
compiler error back-attribution, and automated self-healing patches.
"""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

NodeStatus = Literal["synced", "draft", "error"]


@dataclass
class CanvasVariable:
    name: str
    data_type: str
    section: str = "VAR"  # VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_STAT, VAR_TEMP
    comment: str = ""
    initial_value: str = ""


@dataclass
class CanvasNetwork:
    id: int
    title: str = ""
    language: str = "LAD"  # LAD, FBD, SCL
    scl_text: str = ""
    status: NodeStatus = "draft"
    errors: list[str] = field(default_factory=list)


@dataclass
class CanvasBlock:
    name: str
    block_type: str  # FB, FC, DB, OB, UDT
    number: int = 1
    language: str = "SCL"
    comment: str = ""
    interface: list[CanvasVariable] = field(default_factory=list)
    networks: list[CanvasNetwork] = field(default_factory=list)
    scl_body: str = ""
    status: NodeStatus = "draft"
    errors: list[str] = field(default_factory=list)

    # 外部源（External Source）SCL 的合法声明区关键字；VAR_STAT 须映射为 VAR
    _SCL_SECTION_KEYWORD = {
        "VAR_INPUT": "VAR_INPUT",
        "VAR_OUTPUT": "VAR_OUTPUT",
        "VAR_IN_OUT": "VAR_IN_OUT",
        "VAR_STAT": "VAR",
        "VAR_TEMP": "VAR_TEMP",
        "VAR": "VAR",
    }

    def get_full_scl(self) -> str:
        """Render complete SCL compilation unit text (TIA External Source dialect).

        外部源语法约束（由真实 GenerateBlocksFromSource 编译反馈确认）：
        - 声明区结束符统一为 END_VAR（不是 END_VAR_INPUT 等变体）；
        - 静态区写作 VAR（VAR_STAT 在外部源中非法）；
        - 声明区不允许行内 // 注释（注释由 SimaticML XML 承载）；
        - 块头（FUNCTION_BLOCK 等）之后只允许属性块，// 注释非法。
        """
        lines: list[str] = []
        btype = self.block_type.upper()
        if btype in {"FB", "FC", "OB"}:
            kw = "FUNCTION_BLOCK" if btype == "FB" else "FUNCTION" if btype == "FC" else "ORGANIZATION_BLOCK"
            lines.append(f'{kw} "{self.name}"')

            # Group variables by section
            sections: dict[str, list[CanvasVariable]] = {}
            for v in self.interface:
                sections.setdefault(v.section.upper(), []).append(v)

            for sec, vars_list in sections.items():
                keyword = self._SCL_SECTION_KEYWORD.get(sec, "VAR")
                lines.append(keyword)
                for v in vars_list:
                    init = f" := {v.initial_value}" if v.initial_value else ""
                    lines.append(f"    {v.name} : {v.data_type}{init};")
                lines.append("END_VAR")

            lines.append("BEGIN")
            if self.scl_body.strip():
                lines.append(self.scl_body.strip())
            elif self.networks:
                for net in self.networks:
                    if net.title:
                        lines.append(f"    // Network {net.id}: {net.title}")
                    if net.scl_text.strip():
                        lines.append("    " + net.scl_text.strip())
            lines.append(f"END_{kw}")

        elif btype == "DB":
            lines.append(f'DATA_BLOCK "{self.name}"')
            lines.append("STRUCT")
            for v in self.interface:
                init = f" := {v.initial_value}" if v.initial_value else ""
                lines.append(f"    {v.name} : {v.data_type}{init};")
            lines.append("END_STRUCT;")
            lines.append("BEGIN")
            lines.append("END_DATA_BLOCK")

        return "\n".join(lines) + "\n"


@dataclass
class CanvasHmiWidget:
    id: str
    widget_type: str  # button, indicator, io_field, slider, gauge, alarm_banner
    title: str
    x: int = 0
    y: int = 0
    width: int = 120
    height: int = 60
    plc_tag: str = ""  # e.g. "MainDB.StartCmd" or "MotorCtrl.Running"
    data_type: str = "Bool"
    current_value: Any = False
    properties: dict[str, Any] = field(default_factory=dict)
    status: NodeStatus = "draft"
    errors: list[str] = field(default_factory=list)


@dataclass
class CanvasTag:
    name: str
    data_type: str
    logical_address: str  # %I0.0, %Q0.0, %M10.0
    comment: str = ""


@dataclass
class CanvasState:
    project_name: str
    blocks: dict[str, CanvasBlock] = field(default_factory=dict)
    hmi_widgets: dict[str, CanvasHmiWidget] = field(default_factory=dict)
    tags: dict[str, CanvasTag] = field(default_factory=dict)
    last_compile_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "blocks": {k: asdict(v) for k, v in self.blocks.items()},
            "hmi_widgets": {k: asdict(v) for k, v in self.hmi_widgets.items()},
            "tags": {k: asdict(v) for k, v in self.tags.items()},
            "last_compile_result": self.last_compile_result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanvasState":
        proj_name = data.get("project_name", "UntitledPLC")
        state = cls(project_name=proj_name)

        for b_name, b_data in (data.get("blocks") or {}).items():
            if not isinstance(b_data, dict):
                continue
            vars_list = [
                CanvasVariable(**v) for v in b_data.get("interface", []) if isinstance(v, dict)
            ]
            nets_list = [
                CanvasNetwork(**n) for n in b_data.get("networks", []) if isinstance(n, dict)
            ]
            state.blocks[b_name] = CanvasBlock(
                name=b_data.get("name", b_name),
                block_type=b_data.get("block_type", "FB"),
                number=b_data.get("number", 1),
                language=b_data.get("language", "SCL"),
                comment=b_data.get("comment", ""),
                interface=vars_list,
                networks=nets_list,
                scl_body=b_data.get("scl_body", ""),
                status=b_data.get("status", "draft"),
                errors=b_data.get("errors", []),
            )

        for w_id, w_data in (data.get("hmi_widgets") or {}).items():
            if isinstance(w_data, dict):
                state.hmi_widgets[w_id] = CanvasHmiWidget(
                    id=w_data.get("id", w_id),
                    widget_type=w_data.get("widget_type", "indicator"),
                    title=w_data.get("title", ""),
                    x=w_data.get("x", 0),
                    y=w_data.get("y", 0),
                    width=w_data.get("width", 120),
                    height=w_data.get("height", 60),
                    plc_tag=w_data.get("plc_tag", ""),
                    data_type=w_data.get("data_type", "Bool"),
                    current_value=w_data.get("current_value", False),
                    properties=w_data.get("properties", {}),
                    status=w_data.get("status", "draft"),
                    errors=w_data.get("errors", []),
                )

        for t_name, t_data in (data.get("tags") or {}).items():
            if isinstance(t_data, dict):
                state.tags[t_name] = CanvasTag(
                    name=t_data.get("name", t_name),
                    data_type=t_data.get("data_type", "Bool"),
                    logical_address=t_data.get("logical_address", ""),
                    comment=t_data.get("comment", ""),
                )

        state.last_compile_result = data.get("last_compile_result")
        return state


def create_empty_canvas(project_name: str = "PlcDemoProject") -> CanvasState:
    """Create a default starting canvas with basic DB, FB, and HMI layout."""
    state = CanvasState(project_name=project_name)

    # Initial Main DB
    main_db = CanvasBlock(
        name="MainDB",
        block_type="DB",
        number=1,
        comment="Global plant parameters and state registers",
        interface=[
            CanvasVariable(name="StartCmd", data_type="Bool", section="VAR", comment="HMI Start PB"),
            CanvasVariable(name="StopCmd", data_type="Bool", section="VAR", comment="HMI Stop PB"),
            CanvasVariable(name="AutoMode", data_type="Bool", section="VAR", comment="Auto/Manual mode"),
            CanvasVariable(name="MotorRunning", data_type="Bool", section="VAR", comment="Running feedback"),
            CanvasVariable(name="ActualSpeed", data_type="Real", section="VAR", comment="Speed RPM"),
            CanvasVariable(name="AlarmActive", data_type="Bool", section="VAR", comment="Alarm status"),
        ],
        status="synced",
    )
    state.blocks["MainDB"] = main_db

    # Initial Motor Control FB
    motor_fb = CanvasBlock(
        name="MotorCtrl",
        block_type="FB",
        number=10,
        comment="Main motor starter and interlock logic",
        interface=[
            CanvasVariable(name="Start", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="Stop", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="FaultReset", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="RunOut", data_type="Bool", section="VAR_OUTPUT"),
            CanvasVariable(name="FaultOut", data_type="Bool", section="VAR_OUTPUT"),
            CanvasVariable(name="RunningState", data_type="Bool", section="VAR_STAT"),
        ],
        networks=[
            CanvasNetwork(
                id=1,
                title="Start/Stop Interlock",
                scl_text='IF #Start AND NOT #Stop THEN\n    #RunningState := TRUE;\nELSIF #Stop THEN\n    #RunningState := FALSE;\nEND_IF;\n#RunOut := #RunningState;',
                status="synced",
            )
        ],
        status="synced",
    )
    state.blocks["MotorCtrl"] = motor_fb

    # Initial HMI screen widgets
    state.hmi_widgets["btn_start"] = CanvasHmiWidget(
        id="btn_start",
        widget_type="button",
        title="启动 (Start)",
        x=50,
        y=50,
        width=120,
        height=50,
        plc_tag="MainDB.StartCmd",
        data_type="Bool",
        properties={"color": "emerald", "action": "set_momentary"},
        status="synced",
    )
    state.hmi_widgets["btn_stop"] = CanvasHmiWidget(
        id="btn_stop",
        widget_type="button",
        title="停止 (Stop)",
        x=190,
        y=50,
        width=120,
        height=50,
        plc_tag="MainDB.StopCmd",
        data_type="Bool",
        properties={"color": "rose", "action": "set_momentary"},
        status="synced",
    )
    state.hmi_widgets["lamp_run"] = CanvasHmiWidget(
        id="lamp_run",
        widget_type="indicator",
        title="运行指示灯 (Run)",
        x=50,
        y=130,
        width=120,
        height=70,
        plc_tag="MainDB.MotorRunning",
        data_type="Bool",
        properties={"color": "green", "shape": "circle"},
        status="synced",
    )
    state.hmi_widgets["gauge_speed"] = CanvasHmiWidget(
        id="gauge_speed",
        widget_type="gauge",
        title="转速仪表 (Speed RPM)",
        x=190,
        y=130,
        width=150,
        height=100,
        plc_tag="MainDB.ActualSpeed",
        data_type="Real",
        properties={"min": 0, "max": 3000, "unit": "RPM"},
        status="synced",
    )

    # Initial Physical Tags
    state.tags["Start_PB"] = CanvasTag(name="Start_PB", data_type="Bool", logical_address="%I0.0", comment="Cabinet Start")
    state.tags["Stop_PB"] = CanvasTag(name="Stop_PB", data_type="Bool", logical_address="%I0.1", comment="Cabinet Stop")
    state.tags["Motor_Contactor"] = CanvasTag(name="Motor_Contactor", data_type="Bool", logical_address="%Q0.0", comment="Motor Contactor Q1")

    return state


def apply_canvas_patch(canvas: CanvasState, operations: list[dict[str, Any]]) -> CanvasState:
    """Apply conversational delta mutations onto the canvas state.

    Supported operations:
    - op: "add_block", block: dict
    - op: "update_block", name: str, patch: dict
    - op: "remove_block", name: str
    - op: "add_network", block: str, network: dict
    - op: "update_network", block: str, network_id: int, scl_text: str
    - op: "add_variable", block: str, variable: dict
    - op: "add_hmi_widget", widget: dict
    - op: "update_hmi_widget", id: str, patch: dict
    - op: "remove_hmi_widget", id: str
    - op: "add_tag", tag: dict
    - op: "clear_errors"
    """
    for op_item in operations:
        op = op_item.get("op", "")

        if op == "add_block":
            b_dict = op_item.get("block") or {}
            name = b_dict.get("name")
            if name:
                vars_list = [CanvasVariable(**v) for v in b_dict.get("interface", []) if isinstance(v, dict)]
                nets_list = [CanvasNetwork(**n) for n in b_dict.get("networks", []) if isinstance(n, dict)]
                canvas.blocks[name] = CanvasBlock(
                    name=name,
                    block_type=b_dict.get("block_type", "FB"),
                    number=b_dict.get("number", len(canvas.blocks) + 1),
                    language=b_dict.get("language", "SCL"),
                    comment=b_dict.get("comment", ""),
                    interface=vars_list,
                    networks=nets_list,
                    scl_body=b_dict.get("scl_body", ""),
                    status="draft",
                )

        elif op == "update_block":
            name = op_item.get("name", "")
            if name in canvas.blocks:
                patch = op_item.get("patch", {})
                block = canvas.blocks[name]
                if "comment" in patch:
                    block.comment = patch["comment"]
                if "scl_body" in patch:
                    block.scl_body = patch["scl_body"]
                if "interface" in patch and isinstance(patch["interface"], list):
                    block.interface = [CanvasVariable(**v) for v in patch["interface"] if isinstance(v, dict)]
                if "networks" in patch and isinstance(patch["networks"], list):
                    block.networks = [CanvasNetwork(**n) for n in patch["networks"] if isinstance(n, dict)]
                block.status = "draft"
                block.errors = []

        elif op == "remove_block":
            name = op_item.get("name", "")
            canvas.blocks.pop(name, None)

        elif op == "add_network":
            b_name = op_item.get("block", "")
            if b_name in canvas.blocks:
                net_dict = op_item.get("network", {})
                new_id = net_dict.get("id", len(canvas.blocks[b_name].networks) + 1)
                net = CanvasNetwork(
                    id=new_id,
                    title=net_dict.get("title", f"Network {new_id}"),
                    language=net_dict.get("language", "SCL"),
                    scl_text=net_dict.get("scl_text", ""),
                    status="draft",
                )
                canvas.blocks[b_name].networks.append(net)
                canvas.blocks[b_name].status = "draft"

        elif op == "update_network":
            b_name = op_item.get("block", "")
            net_id = op_item.get("network_id")
            if b_name in canvas.blocks and net_id is not None:
                for net in canvas.blocks[b_name].networks:
                    if net.id == net_id:
                        if "scl_text" in op_item:
                            net.scl_text = op_item["scl_text"]
                        if "title" in op_item:
                            net.title = op_item["title"]
                        net.status = "draft"
                        net.errors = []
                        canvas.blocks[b_name].status = "draft"
                        break

        elif op == "add_variable":
            b_name = op_item.get("block", "")
            var_dict = op_item.get("variable", {})
            if b_name in canvas.blocks and var_dict.get("name"):
                v = CanvasVariable(**var_dict)
                canvas.blocks[b_name].interface.append(v)
                canvas.blocks[b_name].status = "draft"

        elif op == "add_hmi_widget":
            w_dict = op_item.get("widget", {})
            w_id = w_dict.get("id") or f"widget_{len(canvas.hmi_widgets) + 1}"
            canvas.hmi_widgets[w_id] = CanvasHmiWidget(
                id=w_id,
                widget_type=w_dict.get("widget_type", "indicator"),
                title=w_dict.get("title", "Widget"),
                x=w_dict.get("x", 100),
                y=w_dict.get("y", 100),
                width=w_dict.get("width", 120),
                height=w_dict.get("height", 60),
                plc_tag=w_dict.get("plc_tag", ""),
                data_type=w_dict.get("data_type", "Bool"),
                current_value=w_dict.get("current_value", False),
                properties=w_dict.get("properties", {}),
                status="draft",
            )

        elif op == "update_hmi_widget":
            w_id = op_item.get("id", "")
            if w_id in canvas.hmi_widgets:
                patch = op_item.get("patch", {})
                widget = canvas.hmi_widgets[w_id]
                for k, v in patch.items():
                    if hasattr(widget, k):
                        setattr(widget, k, v)
                widget.status = "draft"
                widget.errors = []

        elif op == "remove_hmi_widget":
            w_id = op_item.get("id", "")
            canvas.hmi_widgets.pop(w_id, None)

        elif op == "add_tag":
            t_dict = op_item.get("tag", {})
            name = t_dict.get("name")
            if name:
                canvas.tags[name] = CanvasTag(**t_dict)

        elif op == "clear_errors":
            for b in canvas.blocks.values():
                b.errors = []
                if b.status == "error":
                    b.status = "draft"
                for n in b.networks:
                    n.errors = []
                    if n.status == "error":
                        n.status = "draft"
            for w in canvas.hmi_widgets.values():
                w.errors = []
                if w.status == "error":
                    w.status = "draft"

    return canvas


def attribute_compiler_errors(canvas: CanvasState, compile_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Attribute TIA Portal compilation/writeback errors to specific Canvas blocks, networks, and HMI tags.

    Parses error messages, inconsistent block lists, and maps them to concrete canvas elements.
    Sets status = "error" on offending nodes and attaches diagnostic messages.
    """
    canvas.last_compile_result = compile_result
    attributions: list[dict[str, Any]] = []

    # 1. Inconsistent blocks reported directly by TIA Portal
    inconsistent = compile_result.get("inconsistent") or compile_result.get("inconsistent_blocks") or []
    if isinstance(compile_result.get("compile"), dict):
        inc_sub = compile_result["compile"].get("InconsistentBlocks") or []
        inconsistent.extend(inc_sub)

    for blk_name in inconsistent:
        name = str(blk_name).strip()
        if name in canvas.blocks:
            msg = f"博图编译报错：块 [{name}] 结构不一致或引用的接口已被修改"
            canvas.blocks[name].status = "error"
            if msg not in canvas.blocks[name].errors:
                canvas.blocks[name].errors.append(msg)
            attributions.append({
                "target_type": "block",
                "target_id": name,
                "severity": "error",
                "message": msg,
            })

    # 2. General error message / text parsing (e.g., "Block 'MotorCtrl': Line 4, Variable 'Timer1' not defined")
    raw_msg = str(compile_result.get("message") or "")
    if compile_result.get("error") and isinstance(compile_result["error"], dict):
        raw_msg += " " + str(compile_result["error"].get("message") or "")
    if compile_result.get("compile") and isinstance(compile_result["compile"], dict):
        compile_sub = compile_result["compile"]
        raw_msg += " " + str(compile_sub.get("Message") or "")
        err_obj = compile_sub.get("Error")
        if isinstance(err_obj, dict):
            raw_msg += " " + str(err_obj.get("Message") or "")

    for name, block in canvas.blocks.items():
        if name in raw_msg:
            block.status = "error"
            if raw_msg not in block.errors:
                block.errors.append(raw_msg)
            attributions.append({
                "target_type": "block",
                "target_id": name,
                "severity": "error",
                "message": raw_msg,
            })

    # 3. Check HMI tags referencing non-existent block variables
    for w_id, widget in canvas.hmi_widgets.items():
        if widget.plc_tag and "." in widget.plc_tag:
            blk_ref, var_ref = widget.plc_tag.split(".", 1)
            if blk_ref in canvas.blocks:
                target_block = canvas.blocks[blk_ref]
                declared_vars = {v.name for v in target_block.interface}
                if var_ref not in declared_vars:
                    err_text = f"HMI 变量绑定错误：块 [{blk_ref}] 中未声明变量 [{var_ref}]"
                    widget.status = "error"
                    widget.errors.append(err_text)
                    attributions.append({
                        "target_type": "hmi_widget",
                        "target_id": w_id,
                        "severity": "error",
                        "message": err_text,
                    })

    return attributions


def generate_canvas_autofix_patch(canvas: CanvasState, attributions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Synthesize deterministic self-healing patch operations from compiler/binding attributions.

    For instance:
    - If HMI widget references missing variable in DB -> automatically declare it in DB interface.
    - If a block has undefined timer or missing declaration -> patch interface.
    """
    fix_ops: list[dict[str, Any]] = []

    for attr in attributions:
        msg = attr.get("message", "")
        # Check missing HMI variable pattern
        match = re.search(r"块 \[([a-zA-Z0-9_]+)\] 中未声明变量 \[([a-zA-Z0-9_]+)\]", msg)
        if match:
            blk_name, var_name = match.group(1), match.group(2)
            if blk_name in canvas.blocks:
                widget_id = attr.get("target_id", "")
                widget = canvas.hmi_widgets.get(widget_id)
                dtype = widget.data_type if widget else "Bool"
                fix_ops.append({
                    "op": "add_variable",
                    "block": blk_name,
                    "variable": {
                        "name": var_name,
                        "data_type": dtype,
                        "section": "VAR",
                        "comment": f"Auto-fixed for HMI binding ({widget_id})",
                    },
                })

    if fix_ops:
        fix_ops.append({"op": "clear_errors"})

    return fix_ops
