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

# scl_body 以块头关键字开头 = 携带完整编译单元(AF 引擎模板产物),渲染时直通
_FULL_SCL_UNIT_RE = re.compile(
    r"^(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\b", re.IGNORECASE
)


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
        # scl_body 携带完整编译单元(AF 引擎模板产物等)时直通——否则会自渲染
        # 外壳再嵌一层 FUNCTION_BLOCK/DATA_BLOCK,真机 GenerateBlocksFromSource
        # 直接拒绝(实测自举块 24/24 全失败的双头根因)。
        body_text = self.scl_body.strip()
        if include_body and body_text and _FULL_SCL_UNIT_RE.match(body_text):
            return body_text + "\n"
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
            # 修②:真机案例(51c23082…)"详情戛然而止于 Plc"即此处旧 300 截断吃掉了
            # InnerMessages/编译诊断(前缀+工程路径已占 ~290 字符)。放大到 2000,
            # 让 know-how/行号级根因透出;attributions.detail 同步放大。
            shown, more = detail[:2000], ""
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
                "detail": detail[:2000],
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


# ---------------------------------------------------------------------------
# 规则化自愈规则库（HR001 真机交付缺陷清单回流，治存量）
# 4 类人工 regex 修法中可无类型证据安全规则化的部分：
#   R1  自实例 DB 绝对引用 → ``#`` 前缀（自动补丁 op）
#   R2-lite  疑似数组成员裸访问 → 仅 diagnostic 标注（不自动改）
#   R3  多实例调用形态重构 → 明确跳过（见 generate_canvas_autofix_patch 注释）
# 有 TIA Openness XML 证据（evidence_dir）时的升级规则：
#   R2-full  XML 确证数组成员 → 自动补下标（update_block_scl/update_network）
#   R4  接口对账：body 引用 ``#X`` 未声明 → 按 XML 类型补 add_variable；
#       证据也没有 → diagnostic 警告（不误补）
# ---------------------------------------------------------------------------

#: R2-lite 疑似数组成员名清单（可配置）：对这些成员名的"裸访问"（不带
#: ``[下标]``）只生成 diagnostic 供修复循环提示 LLM/人工，绝不自动改——
#: 数组性丢失需要类型证据（如 ``EdgeDetc.Pulse`` 实为 Array[0..15]），
#: 盲加下标会改出错误语义。
ARRAY_MEMBER_HINTS: tuple[str, ...] = ("Pulse", "Para", "Auto_Force")

#: R1 判定：FB 程序体里绝对引用自己的实例 DB（如 FB1080 里写
#: ``"DB1080_Component".x``，应为 ``#x``）。可判定特征：引用的
#: ``"DB<数字>_<后缀>"`` 的数字与当前 FB 编号相同（编号取块名前缀
#: FB<数字>）。跨块引用（数字不同）绝不能改——FB1040 引用 DB1080 是
#: 合法的全局 DB 访问（HR001 FB1040 真实存在）。
_FB_NAME_NUMBER_RE = re.compile(r"^FB(\d+)", re.IGNORECASE)


class AutofixPatch(list):
    """``generate_canvas_autofix_patch`` 的返回值：ops 列表 + 诊断标注。

    向后兼容契约（fix_loop 等既有调用方零改动）：
    - 本类型是普通 ``list[dict]`` 子类——``list(result)``、``len()``、迭代、
      直接喂给 ``apply_canvas_patch`` 行为与旧的裸 list 完全一致；
    - ``diagnostics`` 属性携带"不自动改、仅供 LLM/人工复核"的标注项
      （R2-lite 等），不进入 ops 列表，也就不会被 ``apply_canvas_patch``
      执行、不影响 ``clear_errors`` 的触发条件。
    """

    def __init__(
        self,
        ops: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> None:
        super().__init__(ops)
        self.diagnostics: list[dict[str, Any]] = list(diagnostics)


def _self_instance_ref_pattern(fb_number: str) -> re.Pattern[str]:
    """R1 补丁正则：``"DB<fb_number>_<后缀>"``.成员链 → ``#成员链``。"""
    return re.compile(
        rf'"DB{fb_number}_[A-Za-z0-9_]+"\s*\.\s*([A-Za-z_][A-Za-z0-9_.]*)'
    )


def _autofix_self_instance_db_refs(canvas: CanvasState) -> list[dict[str, Any]]:
    """R1：自实例 DB 绝对引用 → ``#`` 前缀补丁（块 SCL 文本 regex op）。

    仅作用于 FB 块（块名前缀 FB<数字> 且引用 DB 同编号）；protected
    （know-how 加密）块绝不改写。体优先级与 ``CanvasBlock._render_scl``
    一致：``scl_body`` 非空时补 ``update_block_scl``，否则逐网络补
    ``update_network``。正则替换幂等，无命中不产 op。
    """
    ops: list[dict[str, Any]] = []
    for key, block in canvas.blocks.items():
        if (block.block_type or "").upper() != "FB" or block.protected:
            continue
        m = _FB_NAME_NUMBER_RE.match(block.name or "")
        if not m:
            continue
        pattern = _self_instance_ref_pattern(m.group(1))
        if block.scl_body.strip():
            patched = pattern.sub(r"#\1", block.scl_body)
            if patched != block.scl_body:
                ops.append({"op": "update_block_scl", "name": key, "scl_body": patched})
            continue
        for net in block.networks:
            if not net.scl_text.strip():
                continue
            patched = pattern.sub(r"#\1", net.scl_text)
            if patched != net.scl_text:
                ops.append({
                    "op": "update_network",
                    "block": key,
                    "network_id": net.id,
                    "scl_text": patched,
                })
    return ops


def _diagnose_unindexed_array_members(canvas: CanvasState) -> list[dict[str, Any]]:
    """R2-lite：疑似数组下标丢失 → diagnostic 标注（不自动改）。

    对 ``ARRAY_MEMBER_HINTS`` 中成员名的裸成员访问（``.Pulse``、
    ``.Para``…，其后不跟 ``[``）逐行生成诊断条目；注释行忽略。
    仅标注——真数组（如 ``EdgeDetc.Pulse`` 实为 Array[0..15]）需要
    类型证据才能补对下标，无证据时自动改必然引入错误语义。
    """
    member_patterns = [
        (member, re.compile(rf"\.{re.escape(member)}\b(?!\s*\[)"))
        for member in ARRAY_MEMBER_HINTS
    ]
    diagnostics: list[dict[str, Any]] = []
    for block in canvas.blocks.values():
        if block.protected:
            continue
        if block.scl_body.strip():
            sources: list[tuple[int | None, str]] = [(None, block.scl_body)]
        else:
            sources = [(net.id, net.scl_text) for net in block.networks if net.scl_text.strip()]
        for net_id, text in sources:
            for line_no, line in enumerate((text or "").splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith(("//", "(*")):
                    continue
                for member, pattern in member_patterns:
                    if pattern.search(line):
                        diagnostics.append({
                            "rule": "R2_lite_array_unindexed",
                            "block": block.name,
                            "network": net_id,
                            "member": member,
                            "line_no": line_no,
                            "evidence": stripped,
                            "severity": "warning",
                        "message": (
                            f"疑似数组下标丢失：.{member} 在常见数组成员清单中但未带 [ 下标；"
                            "需接口/类型证据确认（如 Array[0..15]），未自动修改"
                        ),
                    })
    return diagnostics


# ---------------------------------------------------------------------------
# XML 证据驱动规则（R2-full / R4）——evidence_dir 提供 TIA Openness 导出时启用
# ---------------------------------------------------------------------------

#: 证据接口缓存（键 = abspath(export_dir)）。缓存归本模块（调用方）管理，
#: 真机导出目录解析一次全量复用；失效靠进程重启或清空该 dict。
_EVIDENCE_INTERFACE_CACHE: dict[str, dict[str, Any]] = {}

#: XML 声明区名 → canvas VAR 段名（对齐 canvas_import 的既有映射约定）
_XML_SECTION_TO_CANVAS: dict[str, str] = {
    "": "VAR",
    "None": "VAR",
    "Constant": "VAR",
    "Input": "VAR_INPUT",
    "Output": "VAR_OUTPUT",
    "Return": "VAR_OUTPUT",
    "InOut": "VAR_IN_OUT",
    "Static": "VAR_STAT",
    "Temp": "VAR_TEMP",
}

#: body 里 ``#X`` 实例根符号提取（R4 接口对账的引用侧）
_BODY_ROOT_REF_RE = re.compile(r"#([A-Za-z_]\w*)")

#: 回溯访问表达式头部时属于标识符链的字符（字母数字/下划线/点）
_IDENT_CHAIN_CHARS = set("_.") | {chr(c) for c in range(ord("0"), ord("9") + 1)}


def _load_evidence_interfaces(evidence_dir: str | None) -> dict[str, Any]:
    """加载（并缓存）Openness 导出目录的块接口证据树。

    任何失败（目录不存在 / XML 全部非法）都返回空 dict——规则层自然降级
    回 R2-lite 的仅诊断行为，绝不让证据问题打断修复循环。
    """
    if not evidence_dir:
        return {}
    import os

    from plc_engine.array_evidence import load_block_interfaces

    key = os.path.abspath(evidence_dir)
    hit = _EVIDENCE_INTERFACE_CACHE.get(key)
    if hit is None:
        try:
            hit = load_block_interfaces(evidence_dir)
        except Exception:  # noqa: BLE001 — 证据缺失只降级不炸修复循环
            hit = {}
        _EVIDENCE_INTERFACE_CACHE[key] = hit
    return hit


def _patched_text_view(
    canvas: CanvasState, prior_ops: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[tuple[str, Any], str]]:
    """当前文本视图：原始 scl_body / 网络 scl_text 叠加先行 op 的改写。

    R1 与 R2-full/R4 可能命中同一段文本（自实例 DB 引用改成 ``#`` 后又
    暴露出数组裸访问 / 未声明根符号）——后行规则必须基于先行规则改写后
    的文本计算补丁，否则两条 update_block_scl 互相覆盖、先改的补丁被
    静默丢弃。
    """
    bodies = {key: blk.scl_body for key, blk in canvas.blocks.items()}
    nets: dict[tuple[str, Any], str] = {
        (key, net.id): net.scl_text
        for key, blk in canvas.blocks.items()
        for net in blk.networks
    }
    for op in prior_ops:
        if not isinstance(op, dict):
            continue
        if op.get("op") == "update_block_scl" and op.get("name") in bodies:
            bodies[op["name"]] = str(op.get("scl_body") or "")
        elif (
            op.get("op") == "update_network"
            and (op.get("block"), op.get("network_id")) in nets
        ):
            nets[(op["block"], op["network_id"])] = str(op.get("scl_text") or "")
    return bodies, nets


def _evidence_context_for_match(line: str, match: re.Match[str]) -> tuple[str, str] | None:
    """从裸成员匹配处向前回溯所属访问表达式 → ``(证据块名, 成员路径)``。

    支持两种 SCL 访问形态：
    - ``#A.B.Member``（本块实例访问，返回特殊块名 ``@self``）；
    - ``"DBxxx".A.B.Member``（全局 DB 访问，返回引号里的 DB 名）。
    两者都不是（裸局部名、表达式残段等）→ None（无证据上下文，
    只诊断不改文）。
    """
    i = match.start()
    while i > 0 and (line[i - 1].isalnum() or line[i - 1] in _IDENT_CHAIN_CHARS):
        i -= 1
    path = line[i:match.end()].lstrip(".")
    head = line[:i].rstrip()
    if not path:
        return None
    if head.endswith("#"):
        return "@self", path
    db = re.search(r'"([A-Za-z0-9_]+)"\s*$', head)
    if db:
        return db.group(1), path
    return None


def _fix_unindexed_arrays_in_text(
    text: str,
    *,
    canvas_block_name: str,
    interfaces: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """R2-full 单文本修补：证据确证的数组成员补下标。

    返回 ``(新文本, R2_array_evidence_fixed 记录, 未确证的 R2-lite 记录)``。
    逐行处理（注释行跳过），每行的多处在匹配尾部右起插入下标，保持
    行首缩进 / 行尾换行原样。插入 ``[..]`` 后负向前瞻不再命中 → 幂等。
    """
    from plc_engine.array_evidence import resolve_member

    member_patterns = [
        (member, re.compile(rf"\.{re.escape(member)}\b(?!\s*\[)"))
        for member in ARRAY_MEMBER_HINTS
    ]
    fixed_records: list[dict[str, Any]] = []
    lite_records: list[dict[str, Any]] = []
    out_lines: list[str] = []
    for line_no, raw_line in enumerate((text or "").splitlines(keepends=True), start=1):
        core = raw_line.rstrip("\r\n")
        tail = raw_line[len(core):]
        stripped = core.strip()
        if not stripped or stripped.startswith(("//", "(*")):
            out_lines.append(raw_line)
            continue
        insertions: list[tuple[int, str]] = []
        for member, pattern in member_patterns:
            for m in pattern.finditer(core):
                ctx = _evidence_context_for_match(core, m)
                resolved: dict[str, Any] | None = None
                evidence_block = ""
                if ctx is not None:
                    evidence_block, path = ctx
                    tree = (
                        interfaces.get(canvas_block_name)
                        if evidence_block == "@self"
                        else interfaces.get(evidence_block)
                    )
                    if tree is not None:
                        resolved = resolve_member(tree, path)
                if resolved and resolved.get("found") and resolved.get("is_array"):
                    subscript = str(resolved.get("subscript") or "[0]")
                    insertions.append((m.end(), subscript))
                    fixed_records.append({
                        "rule": "R2_array_evidence_fixed",
                        "block": canvas_block_name,
                        "network": None,  # 由调用方按来源补网络号
                        "member": member,
                        "path": ctx[1] if ctx else member,
                        "evidence": str(resolved.get("data_type") or ""),
                        "subscript": subscript,
                        "evidence_block": "@self" if evidence_block == "@self" else evidence_block,
                        "line_no": line_no,
                        "severity": "info",
                        "message": (
                            f"XML 证据确证数组：{ctx[1] if ctx else member} 实为 "
                            f"{resolved.get('data_type')}，已自动补下标 {subscript}"
                        ),
                    })
                else:
                    lite_records.append({
                        "rule": "R2_lite_array_unindexed",
                        "block": canvas_block_name,
                        "network": None,
                        "member": member,
                        "line_no": line_no,
                        "evidence": stripped,
                        "severity": "warning",
                        "message": (
                            f"疑似数组下标丢失：.{member} 在常见数组成员清单中但未带 [ 下标；"
                            "XML 证据未能确证其数组性，未自动修改"
                        ),
                    })
        new_core = core
        for pos, subscript in sorted(insertions, key=lambda t: t[0], reverse=True):
            new_core = new_core[:pos] + subscript + new_core[pos:]
        out_lines.append(new_core + tail)
    return "".join(out_lines), fixed_records, lite_records


def _autofix_array_subscript_promotion(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R6：数组下标提升——翻译层把 ``[idx]`` 拍平成路径尾段 ``.idx`` 的还原。

    真机 FB1010 案例：READ_DBL/WRT_DBL 的 ANY 指针实参原为
    ``"DB5000".AryTypePara[Index].Aux.WriteTypeParaDBL``（AryTypePara 是
    ``Array[0..300] of "UDT_TypePara"``），翻译产物成了
    ``"DB5000".AryTypePara.Aux.WriteTypeParaDBL.Index``。三重证据门：
    ① 路径首段在 DB 证据中为数组类型；② 尾段是本块声明的整型变量；
    ③ 整条路径按成员解析失败（可解析的是正常访问，绝不动）。
    """
    from plc_engine.array_evidence import is_array_type

    int_types = {"int", "dint", "uint", "udint", "sint", "usint", "byte", "word"}
    pat = re.compile(r'"([^"]+)"\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)')
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    def _resolve_chain(root: Any, segs: list[str]) -> bool:
        cur = root
        for s in segs:
            members = getattr(cur, "members", None) or {}
            nxt = members.get(s)
            if nxt is None:
                low = s.lower()
                for k, v in members.items():
                    if k.lower() == low:
                        nxt = v
                        break
            if nxt is None:
                return False
            cur = nxt
        return True

    def _fix_text(text: str, block_key: str, block_name: str, int_vars: dict[str, str]) -> tuple[str, int]:
        count = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal count
            db, path = m.group(1), m.group(2)
            db_iface = interfaces.get(db)
            if not db_iface:
                return m.group(0)
            segs = path.split(".")
            if len(segs) < 3:
                return m.group(0)
            tail = segs[-1]
            int_var = int_vars.get(tail.lower())
            if not int_var:
                return m.group(0)
            node = db_iface.get(segs[0])
            if node is None:
                return m.group(0)
            if not is_array_type(str(getattr(node, "data_type", "") or "")):
                return m.group(0)
            if _resolve_chain(node, segs[1:]):
                return m.group(0)  # 全程可按成员解析 → 正常访问,不是拍平形态
            count += 1
            diagnostics.append({
                "rule": "R6_array_subscript_promoted",
                "block": block_name,
                "network": None,
                "path": path,
                "evidence": str(getattr(node, "data_type", "")),
                "subscript": f"[{int_var}]",
                "severity": "info",
                "message": f"数组下标提升：\"{db}\".{path} → \"{db}\".{segs[0]}[{int_var}].{'.'.join(segs[1:-1])}（证据：数组类型成员 + 尾段为本块整型变量）",
            })
            return f'"{db}".{segs[0]}[{int_var}].{".".join(segs[1:-1])}'

        return pat.sub(repl, text), count

    bodies, nets = _patched_text_view(canvas, prior_ops)
    for key, block in canvas.blocks.items():
        if block.protected:
            continue
        int_vars = {
            v.name.lower(): v.name
            for v in block.interface
            if (v.data_type or "").strip().lower() in int_types
        }
        if not int_vars:
            continue
        if bodies.get(key, "").strip():
            new_text, n = _fix_text(bodies[key], key, block.name or key, int_vars)
            if n:
                ops.append({"op": "update_block_scl", "name": key, "scl_body": new_text})
        else:
            for net in block.networks:
                cur = nets.get((key, net.id), "")
                if not cur.strip():
                    continue
                new_text, n = _fix_text(cur, key, block.name or key, int_vars)
                if n:
                    for d in diagnostics[-n:]:
                        d["network"] = net.id
                    ops.append({
                        "op": "update_network",
                        "block": key,
                        "network_id": net.id,
                        "scl_text": new_text,
                    })
    return ops, diagnostics


def _autofix_bool_sr_latch_rewrite(
    canvas: CanvasState,
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R7：Bool 声明上的 SR 实例调用/取 Q → 等价手写锁存。

    真机 FB2009 案例：翻译体发出 ``#X.SR(R1 := a, R := b)`` 与 ``#X.Q``，
    但 X 在块声明中是 ``Bool``——对 Bool 变量做实例调用/成员取值非法。
    SR(置位优先)语义等价改写：``#X := ((a) OR (#X) AND NOT (b));``、
    ``#X.Q`` → ``#X``。真值门 = 块自身 interface 声明为 Bool（无需外部证据）；
    IEC_TIMER/FB 实例上的合法调用绝不触碰。
    """
    bodies, nets = _patched_text_view(canvas, prior_ops)
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    def _bool_roots(block: CanvasBlock, text: str) -> set[str]:
        """Bool 声明根集合：块结构化 interface + 当前文本声明区(两者取并集)。

        R5 重建后声明区在 scl_body 文本里，结构化 interface 是旧扁平形态——
        只看一侧都会漏(真机 FB2009:SR 调用改写没触发即此因)。
        """
        roots = {
            v.name.lower()
            for v in block.interface
            if (v.data_type or "").strip().lower() == "bool"
        }
        for m in re.finditer(r'^\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*:\s*Bool\s*;', text, re.MULTILINE):
            roots.add((m.group(1) or m.group(2)).lower())
        return roots

    def _split_args(argstr: str) -> dict[str, str]:
        args: dict[str, str] = {}
        depth = 0
        cur = ""
        for ch in argstr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                _take(args, cur)
                cur = ""
            else:
                cur += ch
        _take(args, cur)
        return args

    def _take(args: dict[str, str], raw: str) -> None:
        m = re.match(r"^\s*(\w+)\s*:=\s*(.+?)\s*$", raw, re.DOTALL)
        if m:
            args[m.group(1).upper()] = m.group(2)

    def _fix_text(text: str, block_key: str, block_name: str, block: CanvasBlock) -> tuple[str, int]:
        bools = _bool_roots(block, text)
        count = 0
        # 1) #X.Q → #X（X 为 Bool 声明）
        def q_repl(m: re.Match[str]) -> str:
            nonlocal count
            if m.group(1).lower() not in bools:
                return m.group(0)
            count += 1
            diagnostics.append({
                "rule": "R7_bool_q_rewrite",
                "block": block_name,
                "member": m.group(1),
                "severity": "info",
                "message": f"Bool 取 Q 改写：{m.group(0)} → #{m.group(1)}（Bool 声明无 .Q 成员）",
            })
            return f"#{m.group(1)}"

        text = re.sub(r"#(\w+)\.Q\b", q_repl, text)
        # 2) #X.SR(R1 := a, R := b) → 手写锁存（括号平衡扫描取实参）
        out: list[str] = []
        i = 0
        pat = re.compile(r"#(\w+)\.SR\(")
        while True:
            m = pat.search(text, i)
            if not m:
                out.append(text[i:])
                break
            root = m.group(1)
            if root.lower() not in bools:
                out.append(text[i : m.end()])
                i = m.end()
                continue
            # 扫到配对右括号
            depth = 1
            j = m.end()
            while j < len(text) and depth:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            argstr = text[m.end() : j - 1]
            args = _split_args(argstr)
            # TIA SR 指令实参:S=置位,R1=复位,置位优先(文档语义;历史人工清单
            # 警告"写错方向会静默翻转机台行为"——方向必须以此为准)
            s_set, r1_reset = args.get("S"), args.get("R1")
            if s_set is None or r1_reset is None:
                out.append(text[i:j])
                i = j
                continue
            stmt = f"#{root} := (({s_set}) OR (#{root}) AND NOT ({r1_reset}));"
            count += 1
            diagnostics.append({
                "rule": "R7_bool_sr_latch",
                "block": block_name,
                "member": root,
                "severity": "info",
                "message": f"Bool 上的 SR 调用改写为手写锁存（置位优先 S/R1）：#{root}.SR(...) → {stmt}",
            })
            out.append(text[i : m.start()])
            out.append(stmt)
            i = j
        return "".join(out), count

    for key, block in canvas.blocks.items():
        if block.protected:
            continue
        if not _bool_roots(block, bodies.get(key, "")):
            continue
        if bodies.get(key, "").strip():
            new_text, n = _fix_text(bodies[key], key, block.name or key, block)
            if n:
                ops.append({"op": "update_block_scl", "name": key, "scl_body": new_text})
        else:
            for net in block.networks:
                cur = nets.get((key, net.id), "")
                if not cur.strip():
                    continue
                new_text, n = _fix_text(cur, key, block.name or key, block)
                if n:
                    for d in diagnostics[-n:]:
                        d["network"] = net.id
                    ops.append({
                        "op": "update_network",
                        "block": key,
                        "network_id": net.id,
                        "scl_text": new_text,
                    })
    return ops, diagnostics


def _autofix_quote_spacey_db_segments(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R8：DB 路径中含空格的成员段引号化。

    真机 FC2400 案例：``"DB2100 Modbus Value".ROS Para.Status Word``——语义上
    证据树可解析（成员名本就带空格），但 TIA SCL 语法要求含空格段必须写成
    ``"DB2100 Modbus Value"."ROS Para"."Status Word"``。证据驱动的逐段
    引号化：段名在证据树中存在且含空格 → 包引号。
    """
    bodies, nets = _patched_text_view(canvas, prior_ops)
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    pat = re.compile(r'"([^"]+)"\.([A-Za-z_][\w. ]*(?:\.[A-Za-z_][\w. ]*)*)')

    def _quote_segments(db: str, path: str) -> str | None:
        """逐段对照证据树引号化;任一段含空格且证据确证 → 返回新路径,否则 None。"""
        db_iface = interfaces.get(db)
        if db_iface is None:
            return None
        segs = path.split(".")
        node: Any = _DbRoot(db_iface)
        out_segs: list[str] = []
        changed = False
        for seg in segs:
            stripped = seg.strip()
            if not stripped:
                return None
            members = getattr(node, "members", None) or {}
            hit = members.get(stripped)
            if hit is None:
                low = stripped.lower()
                for k, v in members.items():
                    if k.lower() == low:
                        hit = v
                        break
            if hit is None:
                return None  # 证据无法确证该段——不动(宁缺毋错)
            if " " in stripped:
                out_segs.append(f'"{stripped}"')
                changed = True
            else:
                out_segs.append(stripped)
            node = hit
        return ".".join(out_segs) if changed else None

    class _DbRoot:
        def __init__(self, members: dict[str, Any]):
            self.members = members

    def _fix_text(text: str, block_key: str, block_name: str) -> tuple[str, int]:
        count = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal count
            db, path = m.group(1), m.group(2)
            new_path = _quote_segments(db, path)
            if new_path is None:
                return m.group(0)
            count += 1
            diagnostics.append({
                "rule": "R8_spacey_db_path_quoted",
                "block": block_name,
                "path": path,
                "severity": "info",
                "message": f"DB 路径空格段引号化：\"{db}\".{path} → \"{db}\".{new_path}",
            })
            return f'"{db}".{new_path}'

        return pat.sub(repl, text), count

    for key, block in canvas.blocks.items():
        if block.protected:
            continue
        if bodies.get(key, "").strip():
            new_text, n = _fix_text(bodies[key], key, block.name or key)
            if n:
                ops.append({"op": "update_block_scl", "name": key, "scl_body": new_text})
        else:
            for net in block.networks:
                cur = nets.get((key, net.id), "")
                if not cur.strip():
                    continue
                new_text, n = _fix_text(cur, key, block.name or key)
                if n:
                    for d in diagnostics[-n:]:
                        d["network"] = net.id
                    ops.append({
                        "op": "update_network",
                        "block": key,
                        "network_id": net.id,
                        "scl_text": new_text,
                    })
    return ops, diagnostics


def _load_native_scl_bodies(evidence_dir: str | None) -> dict[str, str]:
    """加载（并缓存）原生 SCL 正文（仅原生 SCL 语言块；LAD 块不含）。"""
    if not evidence_dir:
        return {}
    import os

    from plc_engine.array_evidence import load_native_scl_bodies

    key = os.path.abspath(evidence_dir) + "#native"
    hit = _EVIDENCE_INTERFACE_CACHE.get(key)
    if hit is None:
        try:
            hit = load_native_scl_bodies(evidence_dir) or {}
        except Exception:  # noqa: BLE001 — 原生正文缺失只降级不炸修复循环
            hit = {}
        _EVIDENCE_INTERFACE_CACHE[key] = hit
    return hit


def _autofix_native_scl_restore(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    native_bodies: dict[str, str],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R10：原生 SCL 块逐字还原。

    原项目中的原生 SCL 语言块，其 XML ``<StructuredText>`` 携带原始正文
    （Token/Access 五要素完整）——按文档顺序还原即得到**天然可编译**的
    原始代码，严格优于任何翻译产物（真机 FB1010/FB5715 案例：翻译体的
    READ_DBL 指针形态等语义缺陷在原生正文中根本不存在）。声明区沿用
    R5 的 XML 证据重建，正文整体替换为原生文本。
    """
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    bodies, _nets = _patched_text_view(canvas, prior_ops)
    for key, block in canvas.blocks.items():
        if block.block_type.upper() not in {"FB", "FC"}:
            continue
        if block.protected:
            continue
        native = native_bodies.get(block.name) or native_bodies.get(key.split("::")[-1])
        if not native or not native.strip():
            continue
        iface = interfaces.get(block.name) or interfaces.get(key.split("::")[-1])
        if not iface:
            continue
        unit = _rebuild_unit_from_evidence(block, iface, native)
        if not unit or not unit.strip():
            continue
        if bodies.get(key, "").strip() == unit.strip():
            continue  # 已是原生还原形态 → 幂等
        ops.append({"op": "update_block_scl", "name": key, "scl_body": unit})
        diagnostics.append({
            "rule": "R10_native_scl_restored",
            "block": block.name or key,
            "severity": "info",
            "lines": len(native.splitlines()),
            "message": (
                f"原生 SCL 逐字还原（XML StructuredText "
                f"{len(native.splitlines())} 行，替代翻译体——原始代码天然可编译）"
            ),
        })
    return ops, diagnostics


def _autofix_t_conv_wrap(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R9：DTL→Time_Of_Day 赋值插入 T_CONV 转换。

    真机 FB5008 案例：原 LAD 的 T_CONV 指令被翻译层丢弃(只留注释),
    ``"SyS_Time"(Time_Of_Day) := "DB…".CurPLCTime(DTL)`` 类型不匹配编译错。
    证据门:LHS 是画布 tag 且类型为 Time_Of_Day、RHS 是 DB 路径且证据类型
    为 DTL → 包装为 ``T_CONV(IN := rhs)``(TIA 日期/时间转换指令,SCL 可调)。
    """
    bodies, nets = _patched_text_view(canvas, prior_ops)
    tags = canvas.tags or {}
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    # LHS tag := RHS "DB".path;  (RHS 到行尾或注释前)
    pat = re.compile(r'^(\s*)"([^"]+)"\s*:=\s*("(?:[^"]+)"(?:\.\w+)+)\s*;', re.MULTILINE)

    def _rhs_type(db: str, path: str) -> str | None:
        db_iface = interfaces.get(db)
        if not db_iface:
            return None
        node: Any = None
        segs = path.split(".")
        members: dict[str, Any] = db_iface  # type: ignore[assignment]
        for s in segs:
            hit = members.get(s.strip('"'))
            if hit is None:
                low = s.strip('"').lower()
                for k, v in members.items():
                    if k.lower() == low:
                        hit = v
                        break
            if hit is None:
                return None
            node = hit
            members = getattr(hit, "members", None) or {}
        return str(getattr(node, "data_type", "") or "").strip() if node else None

    def _fix_text(text: str, block_key: str, block_name: str) -> tuple[str, int]:
        count = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal count
            indent, lhs, rhs = m.group(1), m.group(2), m.group(3)
            tag = tags.get(lhs)
            if tag is None:
                return m.group(0)
            lhs_t = str(getattr(tag, "data_type", "") or "").strip()
            if lhs_t.lower() != "time_of_day":
                return m.group(0)
            db = rhs.split('"')[1]
            path = rhs.split(".", 1)[1]
            rhs_t = _rhs_type(db, path)
            if rhs_t is None or rhs_t.lower() != "dtl":
                return m.group(0)
            count += 1
            diagnostics.append({
                "rule": "R9_t_conv_wrap",
                "block": block_name,
                "path": path,
                "severity": "info",
                "message": f"DTL→Time_Of_Day 类型不匹配赋值插入 T_CONV：{lhs} := {rhs}(DTL)",
            })
            return f'{indent}"{lhs}" := T_CONV(IN := {rhs});'

        return pat.sub(repl, text), count

    for key, block in canvas.blocks.items():
        if block.protected:
            continue
        if bodies.get(key, "").strip():
            new_text, n = _fix_text(bodies[key], key, block.name or key)
            if n:
                ops.append({"op": "update_block_scl", "name": key, "scl_body": new_text})
        else:
            for net in block.networks:
                cur = nets.get((key, net.id), "")
                if not cur.strip():
                    continue
                new_text, n = _fix_text(cur, key, block.name or key)
                if n:
                    ops.append({
                        "op": "update_network",
                        "block": key,
                        "network_id": net.id,
                        "scl_text": new_text,
                    })
    return ops, diagnostics


def _autofix_array_subscripts_with_evidence(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R2-full：XML 证据确证的数组裸访问 → 补下标（update_block_scl / update_network）。

    体优先级与 R1 一致（``scl_body`` 非空补整块、否则逐网络）；文本基于
    ``prior_ops`` 叠加后的视图计算，保证与 R1 同块协作不互相覆盖。protected
    块绝不改写。返回 ``(ops, diagnostics)``——diagnostics 含已修复
    （R2_array_evidence_fixed）与未确证（R2_lite_array_unindexed）两类。
    """
    bodies, nets = _patched_text_view(canvas, prior_ops)
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for key, block in canvas.blocks.items():
        if block.protected:
            continue
        if bodies.get(key, "").strip():
            new_text, fixed, lite = _fix_unindexed_arrays_in_text(
                bodies[key], canvas_block_name=block.name or key, interfaces=interfaces
            )
            for d in fixed + lite:
                d["network"] = None
            diagnostics.extend(fixed + lite)
            if new_text != bodies[key]:
                ops.append({"op": "update_block_scl", "name": key, "scl_body": new_text})
        else:
            for net in block.networks:
                cur = nets.get((key, net.id), "")
                if not cur.strip():
                    continue
                new_text, fixed, lite = _fix_unindexed_arrays_in_text(
                    cur, canvas_block_name=block.name or key, interfaces=interfaces
                )
                for d in fixed + lite:
                    d["network"] = net.id
                diagnostics.extend(fixed + lite)
                if new_text != cur:
                    ops.append({
                        "op": "update_network",
                        "block": key,
                        "network_id": net.id,
                        "scl_text": new_text,
                    })
    return ops, diagnostics


def _member_scl_type(node: Any) -> str:
    """XML 成员节点 → SCL data_type 串（Struct 按证据展开成内联类型）。

    canvas 的 ``CanvasVariable`` 是扁平单串，嵌套 Struct 只能内联展开——
    渲染层 ``{name} : {data_type};`` 会在末尾补 ``;``，恰与
    ``End_Struct;`` 的合法句法闭合（历史人工修复 round 3 的同款写法）。
    UDT / 多实例 FB 引用（``"FB1061_RobotAutoStep"``）与 IEC_TIMER
    保持 XML 原始类型串，不展开（多实例成员由 TIA 按类型自建）。
    """
    base = str(getattr(node, "data_type", "") or "").strip()
    children = getattr(node, "members", None) or {}
    if not children or not base.lower().endswith("struct"):
        return base
    inner = [
        f"    {child.name} : {_member_scl_type(child)};"
        for child in children.values()
    ]
    return base + "\n" + "\n".join(inner) + "\nEnd_Struct"


def _reconcile_body_interface_with_evidence(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R4 接口对账：body 引用 ``#X`` 未声明 → 按 XML 证据补 add_variable。

    防误伤边界：
    - 只对 FB/FC 的 body（``scl_body`` 优先，退网络 scl_text）、protected 跳过；
    - 块自身必须存在于 XML 证据（无块级证据时逐符号全量告警只会误伤，跳过）；
    - 只补证据确凿的根符号（画布接口未声明、XML 已声明），已声明不重复补
      （大小写不敏感比较，幂等）；证据也没有的只进 warning 诊断；
    - 全局 DB 引用（``"DBxxx".y``）不补——那是 DB 的接口，不是本块的。
    """
    from plc_engine.array_evidence import find_member

    bodies, nets = _patched_text_view(canvas, prior_ops)
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for key, block in canvas.blocks.items():
        if (block.block_type or "").upper() not in {"FB", "FC"} or block.protected:
            continue
        tree = interfaces.get(block.name) or interfaces.get(key)
        if tree is None:
            continue
        text = bodies.get(key, "")
        if not text.strip():
            text = "\n".join(
                nets.get((key, net.id), "") for net in block.networks
            )
        # 引用侧：逐行提取 #X 根符号（跳过注释行）
        roots: list[str] = []
        seen: set[str] = set()
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "(*")):
                continue
            for m in _BODY_ROOT_REF_RE.finditer(line):
                root = m.group(1)
                if root.lower() not in seen:
                    seen.add(root.lower())
                    roots.append(root)
        if not roots:
            continue
        declared = {v.name.lower() for v in block.interface}
        for root in roots:
            if root.lower() in declared:
                continue
            node = find_member(tree, root)
            if node is not None:
                data_type = _member_scl_type(node)
                section = _XML_SECTION_TO_CANVAS.get(
                    str(getattr(node, "section", "") or "").strip(), "VAR"
                )
                ops.append({
                    "op": "add_variable",
                    "block": key,
                    "variable": {
                        "name": root,
                        "data_type": data_type,
                        "section": section,
                        "comment": "Auto-declared from Openness XML evidence (R4)",
                    },
                })
                xml_type = str(getattr(node, "data_type", "") or "")
                diagnostics.append({
                    "rule": "R4_interface_member_added",
                    "block": block.name or key,
                    "member": root,
                    "data_type": data_type,
                    "section": section,
                    "evidence": xml_type,
                    "severity": "info",
                    "message": (
                        f"接口对账：body 引用 #{root} 未声明，按 XML 证据补声明 "
                        f"{root} : {xml_type}（{section}）"
                    ),
                })
            else:
                diagnostics.append({
                    "rule": "R4_interface_member_no_evidence",
                    "block": block.name or key,
                    "member": root,
                    "severity": "warning",
                    "message": f"接口缺失且无证据：body 引用 #{root}，画布接口未声明，XML 证据中也未找到",
                })
    return ops, diagnostics


# ---------------------------------------------------------------------------
# R5：接口整备——XML 证据重建声明区（治导入层"拍平损坏"接口）
# ---------------------------------------------------------------------------

# XML 声明区名 → SCL 声明区关键字（external source 方言；静态区写 VAR）
_XML_SECTION_TO_SCL = {
    "input": "VAR_INPUT",
    "output": "VAR_OUTPUT",
    "inout": "VAR_IN_OUT",
    "static": "VAR",
    "temp": "VAR_TEMP",
    "constant": "VAR",
    "return": "VAR_OUTPUT",
    "none": "VAR",
}
_SCL_SECTION_ORDER = ("VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR", "VAR_TEMP")


def _interface_damage_signals(block: CanvasBlock) -> list[str]:
    """画布接口的损坏信号（R5 触发条件）。

    真机 FB1080 案例（62 个 TIA 错误全来自声明区）：导入层把嵌套 Struct
    拍平——父成员只剩 ``Struct`` 空壳、嵌套成员平铺成同级且大量重复，
    另有类型 ``Undef``/缺失成员。body 修复对这类损伤无效。
    """
    signals: list[str] = []
    seen: set[str] = set()
    for v in block.interface:
        dt = (v.data_type or "").strip()
        low = dt.lower()
        if low in {"", "undef"}:
            signals.append(f"unknown-type:{v.name}")
        elif low == "struct":
            signals.append(f"flattened-struct-shell:{v.name}")
        dedup = f"{(v.section or '').upper()}:{v.name.lower()}"
        if dedup in seen:
            signals.append(f"duplicate:{v.name}")
        seen.add(dedup)
    return signals


#: SCL 保留字/类型名集合——成员名撞车时必须引号化(真机 FB1061 ``AT : Word``
#: 与 FB1081 ``Time : Struct`` 案例:TIA 报 "The specified value \"AT\" is invalid")
_SCL_RESERVED_WORDS = {
    "AT", "TIME", "DATE", "TIME_OF_DAY", "DATE_AND_TIME", "DT", "TOD", "DTL",
    "BOOL", "BYTE", "WORD", "DWORD", "INT", "DINT", "SINT", "USINT", "UINT",
    "UDINT", "REAL", "LREAL", "CHAR", "WCHAR", "STRING", "WSTRING", "TIMER",
    "COUNTER", "ARRAY", "OF", "STRUCT", "ANY", "VOID", "POINTER", "REF_TO",
    "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR_STAT",
    "VAR_GLOBAL", "CONSTANT", "RETAIN", "NON_RETAIN", "BEGIN", "END_VAR",
    "END_FUNCTION", "END_FUNCTION_BLOCK", "END_DATA_BLOCK", "END_TYPE",
    "IF", "THEN", "ELSE", "ELSIF", "END_IF", "FOR", "TO", "BY", "DO",
    "END_FOR", "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT",
    "CASE", "END_CASE", "RETURN", "EXIT", "GOTO", "TRUE", "FALSE",
    "AND", "OR", "XOR", "NOT", "MOD", "REGION", "END_REGION", "SUPER", "THIS",
}


def _needs_quoting(ident: str) -> bool:
    """标识符是否需要 SCL 引号包裹。

    两类:①含空格/非标识符字符(真机 FB2008:``A Station CoolingFan`` 被拆词);
    ②撞 SCL 保留字/类型名(真机 FB1061 ``AT``/FB1081 ``Time``:TIA 报
    ``The specified value "AT" is invalid``)。引号化对声明与 body 引用
    同步生效(R5 的路径收集共用本判定)。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident or ""):
        return True
    return ident.upper() in _SCL_RESERVED_WORDS


def _collect_quoted_member_paths(members: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """递归收集需加引号的成员路径：``(原始路径, 加引号路径)``。

    顶层形如 ``("A Station CoolingFan", '"A Station CoolingFan"')``；
    嵌套形如 ``("Aux.Heart Fail", 'Aux."Heart Fail"')``。
    """
    pairs: list[tuple[str, str]] = []
    for name, mem in (members or {}).items():
        path = f"{prefix}{name}"
        if _needs_quoting(name):
            head, _, _ = path.rpartition(name)
            pairs.append((path, f'{head}"{name}"'))
        child_members = getattr(mem, "members", None) or {}
        if child_members:
            pairs.extend(_collect_quoted_member_paths(child_members, path + "."))
    return pairs


def _render_evidence_member(mem: Any, indent: str = "    ") -> list[str]:
    """按证据成员节点渲染声明行：嵌套 Struct 内联展开，其余按权威类型串。

    证据树把 UDT/多实例的 ``Sections`` 也展开进 ``members``——但带引号的
    UDT/FB 引用必须按引用渲染（类型真实存在于工程），只有字面 ``Struct``
    才内联展开。证据为空/``Undef``/``Void`` 的成员跳过：前两者无类型可写，
    ``Void`` 在声明区非法（真机 FB2008/FC2400 案例：TIA 报 "Data type
    Void is not allowed here"）——与旧渲染器"Void 成员发射层丢弃"同款约定。
    """
    dt = str(getattr(mem, "data_type", "") or "").strip()
    if dt.lower() in {"", "undef", "void"}:
        return []
    members = getattr(mem, "members", None) or {}
    nm = f'"{mem.name}"' if _needs_quoting(mem.name) else mem.name
    if members and dt.lower() == "struct":
        lines = [f"{indent}{nm} : Struct"]
        for child in members.values():
            lines.extend(_render_evidence_member(child, indent + "    "))
        lines.append(f"{indent}end_struct;")
        return lines
    return [f"{indent}{nm} : {dt};"]


def _render_decl_sections_from_evidence(top_members: dict[str, Any]) -> str:
    """顶层证据成员按声明区分组渲染（固定顺序，全部以 END_VAR 闭合）。"""
    by_section: dict[str, list[str]] = {}
    for mem in top_members.values():
        scl_sec = _XML_SECTION_TO_SCL.get(
            str(getattr(mem, "section", "") or "static").strip().lower(), "VAR"
        )
        lines = _render_evidence_member(mem)
        if lines:
            by_section.setdefault(scl_sec, []).extend(lines)
    out: list[str] = []
    for sec in _SCL_SECTION_ORDER:
        body = by_section.pop(sec, [])
        if body:
            out.append(sec)
            out.extend(body)
            out.append("END_VAR")
    rest = [ln for lines in by_section.values() for ln in lines]
    if rest:  # 未知 section 名残余（理论不出现）并入 VAR,宁多勿漏
        out.extend(["VAR", *rest, "END_VAR"])
    return "\n".join(out)


def _rebuild_unit_from_evidence(block: CanvasBlock, top_members: dict[str, Any], body_text: str) -> str:
    """证据接口 + 现行 body → 完整编译单元文本（走完整单元直通渲染）。

    body 中对带空格成员的引用同步加引号（``#A Station CoolingFan(`` →
    ``#"A Station CoolingFan"(``），与声明区渲染口径一致。
    """
    btype = block.block_type.upper()
    if btype == "FB":
        head, tail = f'FUNCTION_BLOCK "{block.name}"', "END_FUNCTION_BLOCK"
    elif btype == "FC":
        head, tail = f'FUNCTION "{block.name}" : Void', "END_FUNCTION"
    else:
        return ""
    decls = _render_decl_sections_from_evidence(top_members)
    body = (body_text or "").strip()
    for raw_path, quoted_path in _collect_quoted_member_paths(top_members):
        body = re.sub(
            re.escape(raw_path) + r"(?![\w])",
            lambda _m, q=quoted_path: q,  # lambda 防替换串转义歧义
            body,
        )
    parts = [head]
    if decls:
        parts.append(decls)
    parts.append("BEGIN")
    if body:
        parts.append(body)
    parts.append(tail)
    return "\n".join(parts) + "\n"


def _autofix_rebuild_damaged_interfaces(
    canvas: CanvasState,
    interfaces: dict[str, Any],
    prior_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """R5 主规则：接口有损坏信号且 XML 证据持有该块 → 整块重建为完整单元。

    body 取叠加先行 op 后的视图（R1 等已改写的文本不被覆盖丢弃）；
    已是完整单元（R5 幂等）/无证据/protected → 跳过。
    """
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    bodies, _nets = _patched_text_view(canvas, prior_ops)
    for key, block in canvas.blocks.items():
        if block.block_type.upper() not in {"FB", "FC"}:
            continue
        if getattr(block, "protected", False):
            continue
        current = bodies.get(key, "")
        if current.strip() and _FULL_SCL_UNIT_RE.match(current.strip()):
            continue  # 已是完整单元（R5 重建产物/引擎模板）→ 幂等
        iface = interfaces.get(block.name) or interfaces.get(key.split("::")[-1])
        if not iface:
            continue
        damage = _interface_damage_signals(block)
        if not damage:
            continue
        unit = _rebuild_unit_from_evidence(block, iface, current)
        if not unit or not unit.strip():
            continue
        ops.append({"op": "update_block_scl", "name": key, "scl_body": unit})
        diagnostics.append({
            "rule": "R5_interface_rebuilt",
            "block": block.name or key,
            "severity": "info",
            "signals": damage[:8],
            "signal_count": len(damage),
            "evidence_members": len(iface),
            "message": (
                f"接口整备：声明区按 XML 证据重建（损坏信号 {len(damage)} 处，"
                f"如 {damage[0]}；证据成员 {len(iface)} 个）"
            ),
        })
    return ops, diagnostics


def generate_canvas_autofix_patch(
    canvas: CanvasState,
    attributions: list[dict[str, Any]],
    evidence_dir: str | None = None,
) -> AutofixPatch:
    """Synthesize deterministic self-healing patch operations from compiler/binding attributions.

    For instance:
    - If HMI widget references missing variable in DB -> automatically declare it in DB interface.
    - If a block has undefined timer or missing declaration -> patch interface.

    HR001 缺陷清单回流新增（治存量，无需类型证据即可安全实施）：
    - R1  自实例 DB 绝对引用（``"DB<本FB编号>_<后缀>".x``）→ ``#x``，
          以块 SCL 文本 regex 补丁 op（update_block_scl / update_network）实施；
    - R2-lite  常见数组成员名裸访问 → 仅 diagnostic（返回值 ``.diagnostics``），
          不进 ops、不触发 clear_errors，供修复循环提示 LLM/人工；
    - R3  多实例调用形态（``#SR.SR(R1:=..)`` 改手写锁存、定时器 ``.TON(``
          参数形态重建）明确跳过：``#X.SR(...)`` / ``#X.TON(...)`` 本身是
          合法 SCL，HR001 的真缺陷在于实例实为数组（R2 类型证据缺失）或
          参数被折叠丢失——两种情形都需要被调 FB 的接口/接线证据才能等价
          重写（SR 置位优先 / RS 复位优先，写错方向会静默翻转机台行为；
          TON 缺参补 ``()`` 会把定时器静默清零）。无证据规则化只会把编译
          错误换成更隐蔽的语义错误，故不实现。

    evidence_dir（可选，TIA Openness XML 导出目录）提供类型证据时的升级：
    - R2-full  ``ARRAY_MEMBER_HINTS`` 成员裸访问经 XML 确证为数组 →
          自动补下标 op（update_block_scl / update_network），下标取各维
          下界（``Array[0..15]`` → ``[0]``、``Array[1..200]`` → ``[1]``、
          双维 → ``[0,1]``）；未确证的保持 R2-lite 仅诊断。已带 ``[`` 的
          负向前瞻天然跳过 → 幂等。诊断 rule=R2_array_evidence_fixed，
          evidence 字段为 XML 权威类型串（如 ``Array[0..15] of Bool``）。
    - R4  接口对账：FB/FC body 引用 ``#X`` 但画布接口未声明 → 按 XML
          证据补 ``add_variable``（Struct 按证据展开内联类型，多实例 FB /
          UDT 引用原样带引号）；证据也没有 → 仅 warning 诊断
          （rule=R4_interface_member_no_evidence）。已声明不重复补 → 幂等。
    - ``evidence_dir=None``（默认）与旧行为完全一致——fix_loop 等既有
          调用方零改动兼容。

    返回 ``AutofixPatch``（list 子类，向后兼容旧调用方），
    诊断标注挂 ``.diagnostics``。
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

    # R1：自实例 DB 绝对引用 → # 前缀（幂等 regex 补丁，跨块引用不受影响）
    fix_ops.extend(_autofix_self_instance_db_refs(canvas))

    diagnostics: list[dict[str, Any]] = []
    if evidence_dir is None:
        # 无证据模式：R2-lite 疑似数组未下标仅诊断（不产生 op、不触发 clear_errors）
        diagnostics = _diagnose_unindexed_array_members(canvas)
    else:
        # R2-full / R4 / R5：XML 证据确证才改文；文本基于先行 op 视图，规则间不互相覆盖
        interfaces = _load_evidence_interfaces(evidence_dir)
        # R5 先行：拍平损坏的声明区按证据整块重建（R1 之后的 body 视图入单元）；
        # 后行 R2-full/R4 在重建后的完整单元文本上继续叠加
        r5_ops, r5_diags = _autofix_rebuild_damaged_interfaces(canvas, interfaces, prior_ops=fix_ops)
        fix_ops.extend(r5_ops)
        diagnostics.extend(r5_diags)
        # R10：原生 SCL 块逐字还原(在 R5 声明重建之后、文本规则之前——
        # 原生正文替代翻译体,后行规则在原生视图上扫描为无害空转)
        native_bodies = _load_native_scl_bodies(evidence_dir)
        r10_ops, r10_diags = _autofix_native_scl_restore(
            canvas, interfaces, native_bodies, prior_ops=fix_ops
        )
        fix_ops.extend(r10_ops)
        diagnostics.extend(r10_diags)
        r2_ops, r2_diags = _autofix_array_subscripts_with_evidence(
            canvas, interfaces, prior_ops=fix_ops
        )
        fix_ops.extend(r2_ops)
        diagnostics.extend(r2_diags)
        # R6：数组下标提升(R2 之后——R2 兜常规裸访问,R6 兜拍平成 .idx 尾段的形态)
        r6_ops, r6_diags = _autofix_array_subscript_promotion(canvas, interfaces, prior_ops=fix_ops)
        fix_ops.extend(r6_ops)
        diagnostics.extend(r6_diags)
        # R7：Bool 声明上的 SR 调用/.Q 取值 → 等价手写锁存(块自身声明即真值门)
        r7_ops, r7_diags = _autofix_bool_sr_latch_rewrite(canvas, prior_ops=fix_ops)
        fix_ops.extend(r7_ops)
        diagnostics.extend(r7_diags)
        # R8：DB 路径含空格段引号化(证据确证段名;TIA 语法要求,与解析无关)
        r8_ops, r8_diags = _autofix_quote_spacey_db_segments(canvas, interfaces, prior_ops=fix_ops)
        fix_ops.extend(r8_ops)
        diagnostics.extend(r8_diags)
        # R9：DTL→Time_Of_Day 赋值插入 T_CONV(翻译层丢指令的类型不匹配)
        r9_ops, r9_diags = _autofix_t_conv_wrap(canvas, interfaces, prior_ops=fix_ops)
        fix_ops.extend(r9_ops)
        diagnostics.extend(r9_diags)
        r4_ops, r4_diags = _reconcile_body_interface_with_evidence(
            canvas, interfaces, prior_ops=fix_ops
        )
        fix_ops.extend(r4_ops)
        diagnostics.extend(r4_diags)

    if fix_ops:
        fix_ops.append({"op": "clear_errors"})

    return AutofixPatch(fix_ops, diagnostics)
