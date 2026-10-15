import type { CanvasStateData } from "../canvas/types";

/**
 * 离线默认画布：CleanStation_Pro 演示工程。
 * 作为无后端连接 / 无历史会话时的初始 CanvasStateData 快照。
 */
export const defaultCanvas: CanvasStateData = {
  project_name: "CleanStation_Pro",
  blocks: {
    MainDB: {
      name: "MainDB", block_type: "DB", number: 1, language: "DB",
      comment: "全局主控参数与系统状态注册表",
      interface: [
        { name: "StartCmd", data_type: "Bool", section: "VAR", comment: "HMI 启动脉冲" },
        { name: "StopCmd", data_type: "Bool", section: "VAR", comment: "HMI 停止脉冲" },
        { name: "MotorRunning", data_type: "Bool", section: "VAR", comment: "变频电机运行反馈" },
        { name: "ActualSpeed", data_type: "Real", section: "VAR", comment: "实时转速反馈 (RPM)" },
        { name: "AlarmActive", data_type: "Bool", section: "VAR", comment: "系统综合报警位" },
      ],
      networks: [], status: "synced",
    },
    MotorCtrl: {
      name: "MotorCtrl", block_type: "FB", number: 10, language: "SCL",
      comment: "主泵电机启闭互锁与过载保护逻辑",
      interface: [
        { name: "Start", data_type: "Bool", section: "VAR_INPUT", comment: "启动指令输入" },
        { name: "Stop", data_type: "Bool", section: "VAR_INPUT", comment: "停止指令输入" },
        { name: "RunOut", data_type: "Bool", section: "VAR_OUTPUT", comment: "接触器驱动输出" },
        { name: "RunningState", data_type: "Bool", section: "VAR_STAT", comment: "内部记忆自锁状态" },
      ],
      networks: [
        { id: 1, title: "电机启停互锁逻辑 (Self-holding Interlock)", language: "SCL",
          scl_text: "IF #Start AND NOT #Stop THEN\n    #RunningState := TRUE;\nELSIF #Stop THEN\n    #RunningState := FALSE;\nEND_IF;\n#RunOut := #RunningState;", status: "synced" },
      ],
      status: "synced",
    },
  },
  hmi_widgets: {
    btn_start: { id: "btn_start", widget_type: "button", title: "一键启动 (START)", x: 40, y: 40, width: 150, height: 52, plc_tag: "MainDB.StartCmd", data_type: "Bool", current_value: false, properties: { color: "green" }, status: "synced" },
    btn_stop: { id: "btn_stop", widget_type: "button", title: "安全停止 (STOP)", x: 210, y: 40, width: 150, height: 52, plc_tag: "MainDB.StopCmd", data_type: "Bool", current_value: false, properties: { color: "red" }, status: "synced" },
    lamp_run: { id: "lamp_run", widget_type: "indicator", title: "变频运行指示", x: 60, y: 140, width: 110, height: 86, plc_tag: "MainDB.MotorRunning", data_type: "Bool", current_value: false, status: "synced" },
    gauge_speed: { id: "gauge_speed", widget_type: "gauge", title: "主轴转速 (RPM)", x: 190, y: 140, width: 170, height: 86, plc_tag: "MainDB.ActualSpeed", data_type: "Real", current_value: 0, status: "synced" },
  },
  tags: {
    Start_PB: { name: "Start_PB", data_type: "Bool", logical_address: "%I0.0", comment: "柜面物理启动按键" },
    Stop_PB: { name: "Stop_PB", data_type: "Bool", logical_address: "%I0.1", comment: "柜面物理急停按键" },
    Motor_Q1: { name: "Motor_Q1", data_type: "Bool", logical_address: "%Q0.0", comment: "电机输出接触器主触点" },
  },
};
