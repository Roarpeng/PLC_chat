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
    software_unit: str = ""
    namespace: str = ""
    af_role: str = ""
    # Bug1:know-how/加密块(TIA 只导出接口、体未离开原工程)。protected 块
    # 写回时被硬跳过;get_full_scl 只发接口 + KNOW-HOW 说明,绝不发翻译空壳。
    protected: bool = False

    # 外部源（External Source）SCL 的合法声明区关键字；VAR_STAT 须映射为 VAR
    _SCL_SECTION_KEYWORD = {
        "VAR_INPUT": "VAR_INPUT",
        "VAR_OUTPUT": "VAR_OUTPUT",
        "VAR_IN_OUT": "VAR_IN_OUT",
        "VAR_STAT": "VAR",
        "VAR_TEMP": "VAR_TEMP",
        "VAR": "VAR",
    }

    # protected 块意外被导出时的显式说明（双保险第 2 层）
    _PROTECTED_NOTICE = (
        "// [KNOW-HOW PROTECTED - interface only, body not exported. "
        "Original block in TIA project must not be overwritten.]"
    )

    def get_full_scl(self) -> str:
        """Render complete SCL compilation unit text (TIA External Source dialect).

        外部源语法约束（由真实 GenerateBlocksFromSource 编译反馈确认）：
        - 声明区结束符统一为 END_VAR（不是 END_VAR_INPUT 等变体）；
        - 静态区写作 VAR（VAR_STAT 在外部源中非法）；
        - 声明区不允许行内 // 注释（注释由 SimaticML XML 承载）；
        - 块头（FUNCTION_BLOCK 等）之后只允许属性块，// 注释非法。

        protected=True（know-how/体未导出）时只发完整接口声明 + 空 BEGIN/END +
        顶部 KNOW-HOW 说明 —— 画布上根本没有真体，任何"翻译体"都是空壳，
        写出去就会覆盖 TIA 原始块。即使意外被写出，也必须是可读说明而非静默空壳。
        """
        if self.protected:
            return f"{self._PROTECTED_NOTICE}\n{self._render_scl(include_body=False)}"
        return self._render_scl()

    def _render_scl(self, *, include_body: bool = True) -> str:
        """实际渲染;``include_body=False`` 供 protected 分支输出空体接口壳。"""
        lines: list[str] = []
        btype = self.block_type.upper()
        if btype in {"FB", "FC", "OB"}:
            kw = (
                "FUNCTION_BLOCK"
                if btype == "FB"
                else "FUNCTION"
                if btype == "FC"
                else "ORGANIZATION_BLOCK"
            )
            # TIA 外部源方言：FUNCTION 必须带返回类型（真机编译反馈
            # Row 000001: The specified value "VAR_INPUT" is invalid）。
            # canvas 把 Return 段并入 VAR_OUTPUT，故统一 Void（无返回）。
            ret = " : Void" if btype == "FC" else ""
            lines.append(f'{kw} "{self.name}"{ret}')

            sections: dict[str, list[CanvasVariable]] = {}
            for v in self.interface:
                sections.setdefault(v.section.upper(), []).append(v)

            for sec, vars_list in sections.items():
                # Void 无值不可声明（hr001 FC_BlockMove.Ret_Val 系统形态），
                # TIA External Source 解析会直接拒绝 —— 发射层丢弃。
                vars_list = [v for v in vars_list if str(v.data_type or "").strip().upper() != "VOID"]
                if not vars_list:
                    continue
                keyword = self._SCL_SECTION_KEYWORD.get(sec, "VAR")
                lines.append(keyword)
                for v in vars_list:
                    init = f" := {v.initial_value}" if v.initial_value else ""
                    lines.append(f"    {v.name} : {v.data_type}{init};")
                lines.append("END_VAR")

            lines.append("BEGIN")
            if include_body and self.scl_body.strip():
                lines.append(self.scl_body.strip())
            elif include_body and self.networks:
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

        elif btype == "UDT":
            if include_body and self.scl_body.strip():
                return self.scl_body.strip() + "\n"
            lines.append(f'TYPE "{self.name}"')
            lines.append("STRUCT")
            for v in self.interface:
                init = f" := {v.initial_value}" if v.initial_value else ""
                lines.append(f"    {v.name} : {v.data_type}{init};")
            lines.append("END_STRUCT;")
            lines.append("END_TYPE")

        return "\n".join(lines) + "\n"


@dataclass
class CanvasSource:
    """Persistent engineering workspace reference for 1:1 writeback."""

    project_id: str = ""
    project_path: str = ""  # absolute .apxx under work/
    plc_name: str = ""
    hmi_device_names: list[str] = field(default_factory=list)
    export_mode: str = "canvas"  # blocks-only | canvas | full


@dataclass
class CanvasHmiScreen:
    name: str
    start_screen: bool = False
    width: int = 0
    height: int = 0


@dataclass
class CanvasHmiDevice:
    name: str
    kind: str = "classic"  # classic | unified
    width: int = 800
    height: int = 480
    screens: list[CanvasHmiScreen] = field(default_factory=list)


@dataclass
class CanvasHmiWidget:
    id: str
    widget_type: str  # button, indicator, io_field, text, bar, gauge, slider, rect, alarm_banner, placeholder
    title: str
    x: int = 0
    y: int = 0
    width: int = 120
    height: int = 60
    plc_tag: str = ""  # e.g. "MainDB.StartCmd" or "MotorCtrl.Running"
    hmi_tag: str = ""  # HMI-side tag name before connection resolve
    data_type: str = "Bool"
    current_value: Any = False
    properties: dict[str, Any] = field(default_factory=dict)
    device: str = ""
    screen: str = ""
    source_name: str = ""  # original TIA control name
    source_type: str = ""  # original TIA type (Button, HmiButton, …)
    text: str = ""
    supported: bool = True
    status: NodeStatus = "draft"
    errors: list[str] = field(default_factory=list)


@dataclass
class CanvasTag:
    name: str
    data_type: str
    logical_address: str  # %I0.0, %Q0.0, %M10.0
    comment: str = ""
    # 与块同样的最小破坏原则：导入的标签 synced 不回写，只有 draft 标签
    # 触发标签表重写（TIA 对手工生成的标签 XML 导入挑剔，整表重写未改动
    # 数据只会平添失败面——真机 HR001 复现）。
    status: str = "synced"


@dataclass
class CanvasRevision:
    """One applied ops batch for undo / diff / writeback delta."""

    id: int
    source: str  # nl | fix | manual | import | migrate
    ops: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    ts: float = 0.0


@dataclass
class CanvasState:
    project_name: str
    blocks: dict[str, CanvasBlock] = field(default_factory=dict)
    hmi_widgets: dict[str, CanvasHmiWidget] = field(default_factory=dict)
    hmi_devices: list[CanvasHmiDevice] = field(default_factory=list)
    tags: dict[str, CanvasTag] = field(default_factory=dict)
    source: CanvasSource | None = None
    revisions: list[CanvasRevision] = field(default_factory=list)
    last_compile_result: dict[str, Any] | None = None
    software_unit_manifests: dict[str, Any] = field(default_factory=dict)

    def find_block(self, name_or_key: str, software_unit: str = "") -> CanvasBlock | None:
        if name_or_key in self.blocks:
            return self.blocks[name_or_key]
        if software_unit:
            compound = f"{software_unit}::{name_or_key}"
            if compound in self.blocks:
                return self.blocks[compound]
        for b in self.blocks.values():
            if b.name == name_or_key and (not software_unit or b.software_unit == software_unit):
                return b
        return None

    def blocks_in_unit(self, software_unit: str) -> list[CanvasBlock]:
        return [b for b in self.blocks.values() if b.software_unit == software_unit]

    def software_units(self) -> list[str]:
        units = {b.software_unit for b in self.blocks.values() if b.software_unit}
        return sorted(units)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "blocks": {k: asdict(v) for k, v in self.blocks.items()},
            "hmi_widgets": {k: asdict(v) for k, v in self.hmi_widgets.items()},
            "hmi_devices": [asdict(d) for d in self.hmi_devices],
            "tags": {k: asdict(v) for k, v in self.tags.items()},
            "source": asdict(self.source) if self.source else None,
            "revisions": [asdict(r) for r in self.revisions],
            "last_compile_result": self.last_compile_result,
            "software_unit_manifests": self.software_unit_manifests,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanvasState:
        proj_name = data.get("project_name", "UntitledPLC")
        state = cls(project_name=proj_name)

        for b_name, b_data in (data.get("blocks") or {}).items():
            if not isinstance(b_data, dict):
                continue
            vars_list = [
                CanvasVariable(**{k: v for k, v in v.items() if k in CanvasVariable.__dataclass_fields__})
                for v in b_data.get("interface", [])
                if isinstance(v, dict)
            ]
            nets_list = [
                CanvasNetwork(**{k: v for k, v in n.items() if k in CanvasNetwork.__dataclass_fields__})
                for n in b_data.get("networks", [])
                if isinstance(n, dict)
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
                software_unit=b_data.get("software_unit", ""),
                namespace=b_data.get("namespace", ""),
                af_role=b_data.get("af_role", ""),
                # Bug1:protected 标记必须随画布持久化往返,否则写回防线失效
                protected=bool(b_data.get("protected", False)),
            )

        for w_id, w_data in (data.get("hmi_widgets") or {}).items():
            if isinstance(w_data, dict):
                fields = CanvasHmiWidget.__dataclass_fields__
                kwargs = {k: w_data[k] for k in fields if k in w_data}
                kwargs.setdefault("id", w_id)
                kwargs.setdefault("widget_type", "indicator")
                kwargs.setdefault("title", "")
                state.hmi_widgets[w_id] = CanvasHmiWidget(**kwargs)

        for d in data.get("hmi_devices") or []:
            if not isinstance(d, dict):
                continue
            screens = [
                CanvasHmiScreen(**{k: s[k] for k in CanvasHmiScreen.__dataclass_fields__ if k in s})
                for s in d.get("screens") or []
                if isinstance(s, dict)
            ]
            state.hmi_devices.append(
                CanvasHmiDevice(
                    name=d.get("name", ""),
                    kind=d.get("kind", "classic"),
                    width=int(d.get("width") or 800),
                    height=int(d.get("height") or 480),
                    screens=screens,
                )
            )

        for t_name, t_data in (data.get("tags") or {}).items():
            if isinstance(t_data, dict):
                state.tags[t_name] = CanvasTag(
                    name=t_data.get("name", t_name),
                    data_type=t_data.get("data_type", "Bool"),
                    logical_address=t_data.get("logical_address", ""),
                    comment=t_data.get("comment", ""),
                )

        src = data.get("source")
        if isinstance(src, dict) and (src.get("project_id") or src.get("project_path")):
            state.source = CanvasSource(
                project_id=str(src.get("project_id") or ""),
                project_path=str(src.get("project_path") or ""),
                plc_name=str(src.get("plc_name") or ""),
                hmi_device_names=list(src.get("hmi_device_names") or []),
                export_mode=str(src.get("export_mode") or "canvas"),
            )

        state.software_unit_manifests = dict(data.get("software_unit_manifests") or {})

        for r in data.get("revisions") or []:
            if isinstance(r, dict):
                state.revisions.append(
                    CanvasRevision(
                        id=int(r.get("id") or 0),
                        source=str(r.get("source") or "manual"),
                        ops=list(r.get("ops") or []),
                        message=str(r.get("message") or ""),
                        ts=float(r.get("ts") or 0),
                    )
                )

        state.last_compile_result = data.get("last_compile_result")
        return state

    def append_revision(
        self,
        ops: list[dict[str, Any]],
        *,
        source: str = "manual",
        message: str = "",
    ) -> CanvasRevision:
        import time

        rev = CanvasRevision(
            id=len(self.revisions) + 1,
            source=source,
            ops=copy.deepcopy(ops),
            message=message,
            ts=time.time(),
        )
        self.revisions.append(rev)
        return rev


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
        status="draft",
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
                status="draft",
            )
        ],
        status="draft",
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
        status="draft",
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
        status="draft",
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
        status="draft",
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
        status="draft",
    )

    # Initial Physical Tags
    state.tags["Start_PB"] = CanvasTag(name="Start_PB", data_type="Bool", logical_address="%I0.0", comment="Cabinet Start")
    state.tags["Stop_PB"] = CanvasTag(name="Stop_PB", data_type="Bool", logical_address="%I0.1", comment="Cabinet Stop")
    state.tags["Motor_Contactor"] = CanvasTag(name="Motor_Contactor", data_type="Bool", logical_address="%Q0.0", comment="Motor Contactor Q1")

    state.hmi_devices = [
        CanvasHmiDevice(
            name="HMI_1",
            kind="classic",
            width=800,
            height=480,
            screens=[CanvasHmiScreen(name="Screen_1", start_screen=True, width=800, height=480)],
        )
    ]
    for w in state.hmi_widgets.values():
        w.device = "HMI_1"
        w.screen = "Screen_1"
        w.supported = True

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
    - op: "add_screen", device: str, screen: dict
    - op: "update_block_scl", name: str, scl_body: str  (alias for update_block patch.scl_body)
    - op: "add_tag", tag: dict
    - op: "clear_errors"
    """
    for op_item in operations:
        op = op_item.get("op", "")

        if op == "add_block":
            b_dict = op_item.get("block") or {}
            name = b_dict.get("name")
            if name:
                vars_list = [
                    CanvasVariable(**{k: v for k, v in v.items() if k in CanvasVariable.__dataclass_fields__})
                    for v in b_dict.get("interface", [])
                    if isinstance(v, dict)
                ]
                nets_list = [
                    CanvasNetwork(**{k: v for k, v in n.items() if k in CanvasNetwork.__dataclass_fields__})
                    for n in b_dict.get("networks", [])
                    if isinstance(n, dict)
                ]
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

        elif op in {"update_block", "update_block_scl"}:
            name = op_item.get("name", "")
            if name in canvas.blocks:
                patch = dict(op_item.get("patch") or {})
                if op == "update_block_scl" and "scl_body" in op_item:
                    patch["scl_body"] = op_item["scl_body"]
                block = canvas.blocks[name]
                if "comment" in patch:
                    block.comment = patch["comment"]
                if "scl_body" in patch:
                    block.scl_body = patch["scl_body"]
                    block.language = "SCL"
                if "language" in patch:
                    block.language = patch["language"]
                if "interface" in patch and isinstance(patch["interface"], list):
                    block.interface = [
                        CanvasVariable(**{k: v for k, v in v.items() if k in CanvasVariable.__dataclass_fields__})
                        for v in patch["interface"]
                        if isinstance(v, dict)
                    ]
                if "networks" in patch and isinstance(patch["networks"], list):
                    block.networks = [
                        CanvasNetwork(**{k: v for k, v in n.items() if k in CanvasNetwork.__dataclass_fields__})
                        for n in patch["networks"]
                        if isinstance(n, dict)
                    ]
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
            fields = CanvasHmiWidget.__dataclass_fields__
            kwargs = {k: w_dict[k] for k in fields if k in w_dict}
            kwargs["id"] = w_id
            kwargs.setdefault("widget_type", "indicator")
            kwargs.setdefault("title", "Widget")
            kwargs["status"] = "draft"
            canvas.hmi_widgets[w_id] = CanvasHmiWidget(**kwargs)

        elif op == "update_hmi_widget":
            w_id = op_item.get("id", "")
            if w_id in canvas.hmi_widgets:
                patch = op_item.get("patch", {})
                widget = canvas.hmi_widgets[w_id]
                # Placeholder widgets: only allow move/delete (delete handled separately).
                if not widget.supported:
                    patch = {k: v for k, v in patch.items() if k in {"x", "y"}}
                for k, v in patch.items():
                    if hasattr(widget, k) and k != "id":
                        setattr(widget, k, v)
                widget.status = "draft"
                widget.errors = []

        elif op == "remove_hmi_widget":
            w_id = op_item.get("id", "")
            canvas.hmi_widgets.pop(w_id, None)

        elif op == "add_screen":
            device_name = str(op_item.get("device") or "").strip()
            screen_dict = op_item.get("screen") or {}
            screen_name = str(screen_dict.get("name") or "").strip()
            if device_name and screen_name:
                device = next((d for d in canvas.hmi_devices if d.name == device_name), None)
                if device is None:
                    device = CanvasHmiDevice(name=device_name, kind="classic")
                    canvas.hmi_devices.append(device)
                if not any(s.name == screen_name for s in device.screens):
                    device.screens.append(
                        CanvasHmiScreen(
                            name=screen_name,
                            start_screen=bool(screen_dict.get("start_screen")),
                            width=int(screen_dict.get("width") or device.width),
                            height=int(screen_dict.get("height") or device.height),
                        )
                    )

        elif op == "add_tag":
            t_dict = op_item.get("tag", {})
            name = t_dict.get("name")
            if name:
                canvas.tags[name] = CanvasTag(
                    **{k: v for k, v in t_dict.items() if k in CanvasTag.__dataclass_fields__}
                )
                canvas.tags[name].status = "draft"

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

    # 0. SCL 外部源生成失败：TIA 在 GenerateBlocksFromSource 阶段就直接报错。
    #    必须最先处理——此时编译被跳过（inconsistent_blocks 为空、message 只有
    #    "Compile skipped because import failed."），漏掉这段用户就只能看到
    #    「编译失败」四个字，不知道是哪个块、错在哪一行。
    for entry in compile_result.get("scl_results") or []:
        if not isinstance(entry, dict):
            continue
        res = entry.get("result") or {}
        if res.get("ok"):
            continue
        scl_path = str(entry.get("scl") or "")
        blk = scl_path.replace("\\", "/").rsplit("/", 1)[-1]
        if blk.lower().endswith(".scl"):
            blk = blk[: -len(".scl")]
        detail = str(res.get("error") or res.get("message") or "").strip()
        # TIA 输出形如：… 行 000014: 语法错误：设定值"FUNCTION_BLOCK"无效。   行 000017: …
        issues = [
            (ln.strip(), txt.strip())
            for ln, txt in re.findall(r"行\s*0*(\d+)[:：]\s*(.*?)(?=行\s*0*\d+[:：]|$)", detail)
        ]
        if issues:
            shown = "；".join(f"行 {ln}：{txt}" for ln, txt in issues[:3])
            more = f"（共 {len(issues)} 条）" if len(issues) > 3 else ""
        else:
            shown, more = detail[:300], ""
        msg = f"博图生成失败：块 [{blk or '?'}] {shown}{more}".strip()
        if blk and blk in canvas.blocks:
            canvas.blocks[blk].status = "error"
            if msg not in canvas.blocks[blk].errors:
                canvas.blocks[blk].errors.append(msg)
        attributions.append(
            {
                "target_type": "block",
                "target_id": blk,
                "severity": "error",
                "message": msg,
                "detail": detail[:1000],
            }
        )

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

    # 3. Structured messages from compile-plc / compile-hmi
    messages = compile_result.get("messages") or []
    if isinstance(compile_result.get("hmi"), dict):
        messages = list(messages) + list(compile_result["hmi"].get("messages") or [])
    if isinstance(compile_result.get("compile"), dict):
        messages = list(messages) + list(compile_result["compile"].get("Messages") or [])
    for m in messages:
        if not isinstance(m, dict):
            continue
        path = str(m.get("path") or "")
        desc = str(m.get("description") or m.get("message") or "")
        sev = "warning" if "warn" in str(m.get("severity") or "").lower() else "error"
        # HMI path often Screen/Control
        matched_widget = None
        for w_id, widget in canvas.hmi_widgets.items():
            if widget.source_name and widget.source_name in path:
                matched_widget = w_id
                break
            if widget.screen and widget.screen in path and widget.title in path:
                matched_widget = w_id
                break
        if matched_widget:
            widget = canvas.hmi_widgets[matched_widget]
            widget.status = "error"
            if desc and desc not in widget.errors:
                widget.errors.append(desc)
            attributions.append(
                {
                    "target_type": "hmi_widget",
                    "target_id": matched_widget,
                    "severity": sev,
                    "message": desc or path,
                }
            )
            continue
        for name, block in canvas.blocks.items():
            if name in path or name in desc:
                block.status = "error"
                if desc and desc not in block.errors:
                    block.errors.append(desc)
                attributions.append(
                    {
                        "target_type": "block",
                        "target_id": name,
                        "severity": sev,
                        "message": desc or path,
                    }
                )
                break

    # 4. Check HMI tags referencing non-existent block variables
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
