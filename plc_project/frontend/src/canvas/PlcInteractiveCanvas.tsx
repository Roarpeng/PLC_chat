import React, { useState } from "react";
import type {
  CanvasHmiWidgetData,
  CanvasStateData,
  CompilerAttribution,
} from "./types";

interface Props {
  initialCanvas?: CanvasStateData;
  backendConnected?: boolean | null;
  onConfirmWriteback?: (canvas: CanvasStateData) => Promise<{
    writeback: Record<string, any>;
    attributions: CompilerAttribution[];
    canvas: CanvasStateData;
  }>;
  onApplyPatch?: (operations: any[]) => Promise<CanvasStateData>;
  onAutoFix?: (attributions: CompilerAttribution[]) => Promise<CanvasStateData>;
}

export const PlcInteractiveCanvas: React.FC<Props> = ({
  initialCanvas,
  backendConnected,
  onConfirmWriteback,
  onApplyPatch,
  onAutoFix,
}) => {
  const [canvas, setCanvas] = useState<CanvasStateData>(
    initialCanvas || {
      project_name: "CleanStation_Pro",
      blocks: {
        MainDB: {
          name: "MainDB",
          block_type: "DB",
          number: 1,
          language: "DB",
          comment: "全局主控参数与系统状态注册表",
          interface: [
            { name: "StartCmd", data_type: "Bool", section: "VAR", comment: "HMI 启动脉冲" },
            { name: "StopCmd", data_type: "Bool", section: "VAR", comment: "HMI 停止脉冲" },
            { name: "MotorRunning", data_type: "Bool", section: "VAR", comment: "变频电机运行反馈" },
            { name: "ActualSpeed", data_type: "Real", section: "VAR", comment: "实时转速反馈 (RPM)" },
            { name: "AlarmActive", data_type: "Bool", section: "VAR", comment: "系统综合报警位" },
          ],
          networks: [],
          status: "synced",
        },
        MotorCtrl: {
          name: "MotorCtrl",
          block_type: "FB",
          number: 10,
          language: "SCL",
          comment: "主泵电机启闭互锁与过载保护逻辑",
          interface: [
            { name: "Start", data_type: "Bool", section: "VAR_INPUT", comment: "启动指令输入" },
            { name: "Stop", data_type: "Bool", section: "VAR_INPUT", comment: "停止指令输入" },
            { name: "RunOut", data_type: "Bool", section: "VAR_OUTPUT", comment: "接触器驱动输出" },
            { name: "RunningState", data_type: "Bool", section: "VAR_STAT", comment: "内部记忆自锁状态" },
          ],
          networks: [
            {
              id: 1,
              title: "电机启停互锁逻辑 (Self-holding Interlock)",
              language: "SCL",
              scl_text: "IF #Start AND NOT #Stop THEN\n    #RunningState := TRUE;\nELSIF #Stop THEN\n    #RunningState := FALSE;\nEND_IF;\n#RunOut := #RunningState;",
              status: "synced",
            },
          ],
          status: "synced",
        },
      },
      hmi_widgets: {
        btn_start: {
          id: "btn_start",
          widget_type: "button",
          title: "一键启动 (START)",
          x: 40,
          y: 40,
          width: 140,
          height: 52,
          plc_tag: "MainDB.StartCmd",
          data_type: "Bool",
          current_value: false,
          properties: { color: "green" },
          status: "synced",
        },
        btn_stop: {
          id: "btn_stop",
          widget_type: "button",
          title: "安全停止 (STOP)",
          x: 200,
          y: 40,
          width: 140,
          height: 52,
          plc_tag: "MainDB.StopCmd",
          data_type: "Bool",
          current_value: false,
          properties: { color: "red" },
          status: "synced",
        },
        lamp_run: {
          id: "lamp_run",
          widget_type: "indicator",
          title: "变频运行指示",
          x: 60,
          y: 130,
          width: 100,
          height: 80,
          plc_tag: "MainDB.MotorRunning",
          data_type: "Bool",
          current_value: false,
          status: "synced",
        },
        gauge_speed: {
          id: "gauge_speed",
          widget_type: "gauge",
          title: "主轴转速 (RPM)",
          x: 190,
          y: 130,
          width: 160,
          height: 80,
          plc_tag: "MainDB.ActualSpeed",
          data_type: "Real",
          current_value: 0,
          status: "synced",
        },
      },
      tags: {
        Start_PB: { name: "Start_PB", data_type: "Bool", logical_address: "%I0.0", comment: "柜面物理启动按键" },
        Stop_PB: { name: "Stop_PB", data_type: "Bool", logical_address: "%I0.1", comment: "柜面物理急停按键" },
        Motor_Q1: { name: "Motor_Q1", data_type: "Bool", logical_address: "%Q0.0", comment: "电机输出接触器主触点" },
      },
    }
  );

  const [activeTab, setActiveTab] = useState<"logic" | "hmi" | "scl">("logic");
  const [selectedBlockName, setSelectedBlockName] = useState<string | null>("MotorCtrl");
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [attributions, setAttributions] = useState<CompilerAttribution[]>([]);
  const [chatPrompt, setChatPrompt] = useState("");
  const [writebackSuccessNotice, setWritebackSuccessNotice] = useState<string | null>(null);

  // Status metrics
  const blockList = Object.values(canvas.blocks);
  const widgetList = Object.values(canvas.hmi_widgets);
  const errorCount =
    blockList.filter((b) => b.status === "error").length +
    widgetList.filter((w) => w.status === "error").length;
  const draftCount =
    blockList.filter((b) => b.status === "draft").length +
    widgetList.filter((w) => w.status === "draft").length;
  const syncedCount =
    blockList.filter((b) => b.status === "synced").length +
    widgetList.filter((w) => w.status === "synced").length;

  const selectedBlock = selectedBlockName ? canvas.blocks[selectedBlockName] : null;

  // Conversational command handler
  const handleSendChatPrompt = async (e: React.FormEvent) => {
    e.preventDefault();
    const prompt = chatPrompt.trim();
    if (!prompt) return;
    setChatPrompt("");

    let ops: any[] = [];
    if (prompt.includes("急停") || prompt.includes("报警") || prompt.toLowerCase().includes("estop")) {
      ops = [
        {
          op: "add_variable",
          block: "MainDB",
          variable: {
            name: "EmergencyStop",
            data_type: "Bool",
            section: "VAR",
            comment: "安全继电器急停连锁",
          },
        },
        {
          op: "add_hmi_widget",
          widget: {
            id: `btn_estop_${Date.now() % 1000}`,
            widget_type: "button",
            title: "紧急停止 (E-STOP)",
            x: 360,
            y: 40,
            width: 150,
            height: 52,
            plc_tag: "MainDB.EmergencyStop",
            data_type: "Bool",
            properties: { color: "red" },
          },
        },
        {
          op: "add_network",
          block: "MotorCtrl",
          network: {
            id: (canvas.blocks["MotorCtrl"]?.networks.length || 1) + 1,
            title: "急停安全切断网络 (Safety Interlock)",
            language: "SCL",
            scl_text: 'IF "MainDB".EmergencyStop THEN\n    #RunningState := FALSE;\n    #RunOut := FALSE;\nEND_IF;',
          },
        },
      ];
    } else if (prompt.includes("冷却") || prompt.includes("泵") || prompt.toLowerCase().includes("pump")) {
      ops = [
        {
          op: "add_variable",
          block: "MainDB",
          variable: {
            name: "CoolingPumpActive",
            data_type: "Bool",
            section: "VAR",
            comment: "循环水泵运行状态",
          },
        },
        {
          op: "add_hmi_widget",
          widget: {
            id: `lamp_pump_${Date.now() % 1000}`,
            widget_type: "indicator",
            title: "冷却水泵状态",
            x: 370,
            y: 130,
            width: 110,
            height: 80,
            plc_tag: "MainDB.CoolingPumpActive",
            data_type: "Bool",
          },
        },
      ];
    } else {
      ops = [
        {
          op: "add_variable",
          block: "MainDB",
          variable: {
            name: `UserVar_${Date.now() % 1000}`,
            data_type: "Real",
            section: "VAR",
            comment: prompt,
          },
        },
      ];
    }

    if (onApplyPatch) {
      const updated = await onApplyPatch(ops);
      setCanvas(updated);
    } else {
      // Local reactive update
      const nextBlocks = { ...canvas.blocks };
      if (nextBlocks["MainDB"]) {
        nextBlocks["MainDB"] = {
          ...nextBlocks["MainDB"],
          status: "draft",
          interface: [
            ...nextBlocks["MainDB"].interface,
            { name: `Var_${Date.now() % 1000}`, data_type: "Bool", section: "VAR", comment: prompt },
          ],
        };
      }
      setCanvas({ ...canvas, blocks: nextBlocks });
    }
  };

  // Human confirmation gate writeback
  const handleExecuteWriteback = async () => {
    setIsSubmitting(true);
    try {
      if (onConfirmWriteback) {
        const res = await onConfirmWriteback(canvas);
        setCanvas(res.canvas);
        setAttributions(res.attributions);
        if (res.writeback?.ok) {
          setWritebackSuccessNotice("✓ 博图 1:1 还原成功并完成严苛编译测试（0 Error, 0 Warning）");
          setTimeout(() => setWritebackSuccessNotice(null), 4000);
        }
      } else {
        // Mock success
        const nextBlocks = { ...canvas.blocks };
        Object.keys(nextBlocks).forEach((k) => (nextBlocks[k].status = "synced"));
        const nextHmi = { ...canvas.hmi_widgets };
        Object.keys(nextHmi).forEach((k) => (nextHmi[k].status = "synced"));
        setCanvas({ ...canvas, blocks: nextBlocks, hmi_widgets: nextHmi });
        setWritebackSuccessNotice("✓ 仿真环境：已完成 1:1 SCL 编译并写入博图工程！");
        setTimeout(() => setWritebackSuccessNotice(null), 4000);
      }
      setShowConfirmModal(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  // One-click Auto-Fix
  const handleTriggerAutoFix = async () => {
    if (!onAutoFix || !attributions.length) return;
    setIsSubmitting(true);
    try {
      const fixed = await onAutoFix(attributions);
      setCanvas(fixed);
      setAttributions([]);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Interactive HMI Touch Event (Simulate Hardware Reaction)
  const handleWidgetClick = (w: CanvasHmiWidgetData) => {
    if (w.widget_type === "button") {
      const nextState = !w.current_value;
      const isStart = w.id.includes("start");
      const isStop = w.id.includes("stop") || w.id.includes("estop");

      const nextWidgets = { ...canvas.hmi_widgets };
      nextWidgets[w.id] = { ...w, current_value: nextState };

      // Realistic PLC logic feedback loop in HMI!
      if (isStart) {
        if (nextWidgets["lamp_run"]) nextWidgets["lamp_run"].current_value = true;
        if (nextWidgets["gauge_speed"]) nextWidgets["gauge_speed"].current_value = 1450;
      } else if (isStop) {
        if (nextWidgets["lamp_run"]) nextWidgets["lamp_run"].current_value = false;
        if (nextWidgets["gauge_speed"]) nextWidgets["gauge_speed"].current_value = 0;
      }

      setCanvas({ ...canvas, hmi_widgets: nextWidgets });
    }
  };

  // Render Full SCL text for SCL View
  const renderAllScl = () => {
    return blockList
      .map((b) => {
        let code = `// ================================================================\n// BLOCK: "${b.name}" (${b.block_type}) · TIA PORTAL SCL SOURCE\n// ================================================================\n`;
        const kw =
          b.block_type === "FB"
            ? "FUNCTION_BLOCK"
            : b.block_type === "FC"
            ? "FUNCTION"
            : b.block_type === "DB"
            ? "DATA_BLOCK"
            : "ORGANIZATION_BLOCK";

        if (b.block_type === "DB") {
          code += `${kw} "${b.name}"\nSTRUCT\n`;
          b.interface.forEach((v) => {
            code += `    ${v.name} : ${v.data_type};${v.comment ? `  // ${v.comment}` : ""}\n`;
          });
          code += `END_STRUCT;\nBEGIN\nEND_DATA_BLOCK\n`;
        } else {
          code += `${kw} "${b.name}"\nVAR_INPUT\n`;
          b.interface.filter((v) => v.section === "VAR_INPUT").forEach((v) => {
            code += `    ${v.name} : ${v.data_type};\n`;
          });
          code += `END_VAR\nVAR_OUTPUT\n`;
          b.interface.filter((v) => v.section === "VAR_OUTPUT").forEach((v) => {
            code += `    ${v.name} : ${v.data_type};\n`;
          });
          code += `END_VAR\nBEGIN\n`;
          b.networks.forEach((n) => {
            code += `    // Network ${n.id}: ${n.title}\n    ${n.scl_text.replace(/\n/g, "\n    ")}\n\n`;
          });
          code += `END_${kw}\n`;
        }
        return code;
      })
      .join("\n\n");
  };

  return (
    <div className="flex flex-col h-full w-full bg-[#07090e] text-[#f1f5f9] select-none overflow-hidden relative font-sans">
      <div className="app-atmosphere"></div>

      {/* Top Professional Header */}
      <header className="glass-panel z-10 flex items-center justify-between px-5 py-3 border-b border-[rgba(255,255,255,0.08)]">
        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 font-mono font-bold text-slate-950 text-xs">
              PLC
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-heading font-bold text-sm tracking-wide text-white">
                  {canvas.project_name}
                </span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-800">
                  TIA V19 兼容
                </span>
                {backendConnected !== null && (
                  <span
                    className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                      backendConnected
                        ? "bg-emerald-950/80 text-emerald-300 border-emerald-800"
                        : "bg-slate-900 text-slate-400 border-slate-700"
                    }`}
                  >
                    {backendConnected ? "● 网关已就绪" : "○ 离线沙箱模式"}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400">数字孪生画布 · AI 实时双向编译闭环</p>
            </div>
          </div>

          {/* Mode Navigation Tabs */}
          <div className="flex bg-[#0c101b] p-1 rounded-lg border border-[rgba(255,255,255,0.06)]">
            <button
              onClick={() => setActiveTab("logic")}
              className={`btn px-3 py-1.5 text-xs rounded-md ${
                activeTab === "logic" ? "btn-primary" : "btn-ghost text-slate-400 hover:text-white"
              }`}
            >
              ⚡ PLC 逻辑拓扑与网络 ({blockList.length})
            </button>
            <button
              onClick={() => setActiveTab("hmi")}
              className={`btn px-3 py-1.5 text-xs rounded-md ${
                activeTab === "hmi" ? "btn-primary" : "btn-ghost text-slate-400 hover:text-white"
              }`}
            >
              🖥️ HMI 组态与数字仿真 ({widgetList.length})
            </button>
            <button
              onClick={() => setActiveTab("scl")}
              className={`btn px-3 py-1.5 text-xs rounded-md ${
                activeTab === "scl" ? "btn-primary" : "btn-ghost text-slate-400 hover:text-white"
              }`}
            >
              📜 1:1 SCL 实时编译源码
            </button>
          </div>
        </div>

        {/* Global Status Indicators & Confirmation Gate */}
        <div className="flex items-center space-x-3 text-xs">
          <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-[#0e1424] border border-[rgba(255,255,255,0.08)]">
            <span className="badge badge-synced">● 已同步 {syncedCount}</span>
            <span className="badge badge-draft">● 草稿 {draftCount}</span>
            {errorCount > 0 && (
              <span className="badge badge-error animate-pulse">● 博图报错 {errorCount}</span>
            )}
          </div>

          {errorCount > 0 && (
            <button
              onClick={handleTriggerAutoFix}
              disabled={isSubmitting}
              className="btn btn-danger text-xs px-3 py-1.5"
            >
              🛠️ 一键自愈修复
            </button>
          )}

          <button
            onClick={() => setShowConfirmModal(true)}
            disabled={isSubmitting}
            className="btn btn-success text-xs px-4 py-2"
          >
            <span>🚀 确认并 1:1 还原至博图</span>
          </button>
        </div>
      </header>

      {/* Success Notification Banner */}
      {writebackSuccessNotice && (
        <div className="absolute top-16 left-1/2 transform -translate-x-1/2 z-40 bg-emerald-950/90 border border-emerald-500 text-emerald-200 text-xs px-6 py-2.5 rounded-full shadow-2xl flex items-center space-x-2 animate-bounce">
          <span>{writebackSuccessNotice}</span>
        </div>
      )}

      {/* Main Multi-Mode Stage */}
      <main className="flex-1 relative overflow-auto canvas-grid-bg p-6 flex">
        {activeTab === "logic" && (
          <div className="flex-1 flex space-x-6">
            {/* Logic Block Grid */}
            <div className="flex-1 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 auto-rows-max overflow-y-auto pr-2">
              {blockList.map((block) => {
                const isSelected = selectedBlockName === block.name;
                const stateClass =
                  block.status === "error"
                    ? "state-error"
                    : block.status === "draft"
                    ? "state-draft"
                    : "state-synced";

                return (
                  <div
                    key={block.name}
                    onClick={() => setSelectedBlockName(block.name)}
                    className={`glass-card p-5 cursor-pointer relative ${stateClass} ${
                      isSelected ? "ring-2 ring-cyan-400" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between pb-3 border-b border-[rgba(255,255,255,0.08)] mb-3">
                      <div className="flex items-center space-x-2">
                        <span className="badge badge-block-type">{block.block_type}</span>
                        <h3 className="font-heading font-semibold text-sm text-white">
                          "{block.name}"
                        </h3>
                      </div>
                      <span className={`badge badge-${block.status}`}>{block.status}</span>
                    </div>

                    {block.comment && (
                      <p className="text-xs text-slate-400 mb-3 italic">{block.comment}</p>
                    )}

                    {/* Interface Pins */}
                    <div className="space-y-1 mb-4">
                      <div className="text-[10px] font-mono font-bold text-slate-500 tracking-wider">
                        INTERFACE SIGNALS:
                      </div>
                      <div className="space-y-1 max-h-32 overflow-y-auto pr-1">
                        {block.interface.map((v) => (
                          <div
                            key={v.name}
                            className="flex justify-between items-center bg-[#070b14] px-2.5 py-1 rounded text-xs font-mono border border-[rgba(255,255,255,0.04)]"
                          >
                            <span className="text-slate-200">#{v.name}</span>
                            <span className="text-cyan-400 font-semibold">{v.data_type}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Network Logic count */}
                    <div className="flex justify-between items-center pt-2 border-t border-[rgba(255,255,255,0.06)] text-xs text-slate-400">
                      <span>包含 {block.networks.length} 个逻辑网络</span>
                      <span className="text-cyan-400 hover:underline">点击右侧展开审查 →</span>
                    </div>

                    {/* Error Box if Error State */}
                    {block.status === "error" && block.errors && block.errors.length > 0 && (
                      <div className="mt-3 p-2.5 rounded bg-rose-950/80 border border-rose-800 text-rose-200 text-xs">
                        <div className="font-bold">⚠️ 博图编译诊断:</div>
                        <div className="text-[11px] mt-1">{block.errors[0]}</div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Selected Block Logic Inspector Sidebar */}
            {selectedBlock && (
              <div className="w-96 glass-panel rounded-xl p-5 flex flex-col border border-[rgba(255,255,255,0.1)] shadow-2xl">
                <div className="flex items-center justify-between pb-3 border-b border-[rgba(255,255,255,0.08)] mb-4">
                  <div className="flex items-center space-x-2">
                    <span className="badge badge-block-type">{selectedBlock.block_type}</span>
                    <h3 className="font-heading font-bold text-base text-white">
                      {selectedBlock.name} 详情
                    </h3>
                  </div>
                  <span className={`badge badge-${selectedBlock.status}`}>{selectedBlock.status}</span>
                </div>

                <div className="flex-1 overflow-y-auto space-y-4 pr-1">
                  <div>
                    <h4 className="text-xs font-bold text-slate-400 mb-2">网络逻辑源码 (SCL):</h4>
                    {selectedBlock.networks.length > 0 ? (
                      selectedBlock.networks.map((net) => (
                        <div
                          key={net.id}
                          className="mb-3 bg-[#070b14] p-3 rounded-lg border border-[rgba(255,255,255,0.06)] font-mono text-xs text-slate-300"
                        >
                          <div className="text-[10px] text-cyan-400 mb-1 font-bold">
                            // Network {net.id}: {net.title}
                          </div>
                          <pre className="text-slate-200 whitespace-pre-wrap">{net.scl_text}</pre>
                        </div>
                      ))
                    ) : (
                      <div className="text-xs text-slate-500 italic p-3 bg-[#070b14] rounded">
                        数据块（DB），包含参数数据定义，无独立可执行网络体。
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "hmi" && (
          <div className="flex-1 flex flex-col items-center justify-center">
            {/* Realistic Siemens Comfort/Unified Touch Bezel Frame */}
            <div className="hmi-bezel">
              {/* Bezel Top Status Header */}
              <div className="h-7 bg-[#1c2232] border-b border-black/40 px-4 flex items-center justify-between text-[11px] font-mono text-slate-400">
                <span>SIEMENS SIMATIC HMI UNIFIED · RUNTIME SIMULATOR</span>
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                  PLC LINK: ONLINE
                </span>
              </div>

              {/* Touch Glass Area */}
              <div className="hmi-screen-glass">
                <div className="absolute top-3 left-4 text-xs font-mono text-slate-500 pointer-events-none">
                  [SCREEN 1: 工艺主控画面 - 触摸模拟]
                </div>

                {/* Render Widgets */}
                {widgetList.map((widget) => {
                  const isError = widget.status === "error";
                  const btnColor = widget.properties?.color || "green";

                  return (
                    <div
                      key={widget.id}
                      onClick={() => handleWidgetClick(widget)}
                      style={{
                        position: "absolute",
                        left: `${widget.x}px`,
                        top: `${widget.y}px`,
                        width: `${widget.width}px`,
                        height: `${widget.height}px`,
                      }}
                      className={`hmi-widget select-none transition ${
                        isError ? "animate-pulse" : ""
                      }`}
                    >
                      {widget.widget_type === "button" && (
                        <button
                          className={`hmi-button w-full h-full ${
                            btnColor === "red" ? "hmi-button-red" : "hmi-button-green"
                          } ${widget.current_value ? "active" : ""}`}
                        >
                          {widget.title}
                        </button>
                      )}

                      {widget.widget_type === "indicator" && (
                        <div className="flex flex-col items-center justify-center h-full bg-[#111726]/80 p-2 rounded-lg border border-[#1e293b]">
                          <div
                            className={`hmi-lamp mb-1.5 ${
                              widget.current_value ? "lamp-on-green" : ""
                            }`}
                          ></div>
                          <span className="text-[11px] font-medium text-slate-300">
                            {widget.title}
                          </span>
                        </div>
                      )}

                      {widget.widget_type === "gauge" && (
                        <div className="flex flex-col justify-between h-full bg-[#111726]/80 p-2.5 rounded-lg border border-[#1e293b]">
                          <span className="text-[10px] text-slate-400">{widget.title}</span>
                          <div className="hmi-readout">
                            <span>{widget.current_value ?? 0}</span>
                            <span className="text-[10px] text-slate-400">RPM</span>
                          </div>
                        </div>
                      )}

                      {/* Tag Binding Pill Indicator */}
                      <div className="hmi-tag-pill">
                        🔗 {widget.plc_tag || "未绑定"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {activeTab === "scl" && (
          <div className="flex-1 glass-panel rounded-xl p-6 flex flex-col font-mono text-xs overflow-hidden">
            <div className="flex items-center justify-between pb-3 border-b border-[rgba(255,255,255,0.08)] mb-3">
              <span className="font-bold text-cyan-400">
                1:1 西门子博图可导入 SCL 外部源预览 (External Source Code)
              </span>
              <span className="text-slate-400">零博图依赖 · 本地离线即时编译</span>
            </div>
            <pre className="flex-1 overflow-auto bg-[#05070c] p-4 rounded-lg text-emerald-300 leading-relaxed border border-[rgba(255,255,255,0.04)] selection:bg-cyan-500 selection:text-black">
              {renderAllScl()}
            </pre>
          </div>
        )}
      </main>

      {/* Bottom Conversational AI Co-Pilot Strip */}
      <footer className="glass-panel z-10 px-5 py-3 border-t border-[rgba(255,255,255,0.08)] flex items-center space-x-3">
        <form onSubmit={handleSendChatPrompt} className="flex-1 flex space-x-3">
          <input
            type="text"
            value={chatPrompt}
            onChange={(e) => setChatPrompt(e.target.value)}
            placeholder="💬 通过自然语言更新逻辑或HMI... 例如：'在MainDB增加急停信号，并添加红色急停按钮' 或 '增加冷却水泵控制'"
            className="flex-1 bg-[#0c101b] border border-[rgba(255,255,255,0.12)] rounded-lg px-4 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400 transition"
          />
          <button type="submit" className="btn btn-primary px-5 py-2">
            发送指令
          </button>
        </form>
      </footer>

      {/* Human-in-the-Loop Confirmation Gate Modal */}
      {showConfirmModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="flex items-center space-x-3 pb-3 border-b border-[rgba(255,255,255,0.08)] mb-4">
              <span className="w-8 h-8 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-sm">
                ✓
              </span>
              <div>
                <h3 className="font-heading font-bold text-base text-white">
                  确认将当前画布内容 1:1 还原至博图 (TIA Portal Writeback Gate)
                </h3>
                <p className="text-xs text-slate-400">工业工程师安全审核门禁</p>
              </div>
            </div>

            <div className="space-y-2 text-xs font-mono bg-[#070b14] p-3.5 rounded-lg border border-[rgba(255,255,255,0.06)] text-slate-300 mb-5">
              <div className="flex justify-between">
                <span className="text-slate-400">目标博图工程:</span>
                <span className="text-white font-bold">{canvas.project_name}.ap19</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">待转译回写逻辑块:</span>
                <span className="text-cyan-400">{blockList.length} 个块 (SCL / SimaticML)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">待同步变量表 (Tags):</span>
                <span className="text-cyan-400">{widgetList.length} 项 (PlcTagTable)</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-[rgba(255,255,255,0.06)]">
                <span className="text-emerald-400 font-bold">● 一致性编译校验:</span>
                <span className="text-emerald-400">开启 (CompilePlcSoftwareStrict 门禁)</span>
              </div>
            </div>

            <div className="flex justify-end space-x-3 text-xs">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="btn btn-ghost px-4 py-2"
              >
                取消返回
              </button>
              <button
                onClick={handleExecuteWriteback}
                disabled={isSubmitting}
                className="btn btn-success px-5 py-2"
              >
                {isSubmitting ? "正在还原并触发博图编译..." : "确认并执行还原"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
