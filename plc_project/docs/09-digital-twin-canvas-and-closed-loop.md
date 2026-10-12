# 09 - 数字孪生画布、HMI 仿真与博图闭环自愈架构规范

## 一、 系统定位与交互范式

本系统构建了一个**“对话协同驱动的数字孪生工作台 + 真实工程 1:1 还原 + 物理编译器闭环自愈（AI-in-the-Loop PLC Engineering）”**的高可靠工业研发工作流。

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Web 交互端 (Chat + Interactive Canvas)                    │
│                                                                                        │
│  [ 自然语言对话输入 ] ──> [ AST 补丁引擎 ] ──> [ 数字孪生画布 (PLC 逻辑 + HMI 仿真) ]   │
│                                                               │                        │
│                                                     (工程师审核确认门禁)                 │
│                                                               ▼                        │
│                                              [ 1:1 SCL / SimaticML 外部源转译 ]         │
└──────────────────────────────────────────────┬─────────────────────────────────────────┘
                                               │ HTTP / Openness CLI
                                               ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        TIA Portal / Openness 物理层 (HostGateway / Worker)             │
│                                                                                        │
│  [ Blocks.Import / GenerateFromSource ] ──> [ CompilePlcSoftwareStrict 严苛一致性编译 ] │
│                                                               │                        │
│                                                        (真实编译日志回传)                │
│                                                               ▼                        │
│  [ 编译器错误逆向归因器 ] ──> [ Canvas 节点红标诊断 ] ──> [ AI 自愈引擎自动修复补丁 ]  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 核心子系统与实现

### 1. 双模态画布数据模型 (`plc_engine/canvas_model.py`)
- **PLC 逻辑域 (Logic Domain)**：
  - `CanvasBlock`：定义西门子 FB、FC、DB、OB、UDT 的接口签名（`VAR_INPUT`, `VAR_OUTPUT`, `VAR_STAT`）、多段网络（`CanvasNetwork`）与内部 SCL 逻辑。
  - `CanvasNetwork`：支持 LAD/FBD 逻辑与 SCL 混合表达。
- **HMI 组态域 (HMI Domain)**：
  - `CanvasHmiWidget`：支持按钮（Button）、凸透镜指示灯（PilotLamp）、转速/液位仪表（Gauge）、数值输入显示（IOField）。
  - **标签双向绑定**：每个控件具备 `plc_tag` 属性（如 `MainDB.StartCmd`），实时绑定到具体的 PLC 块与变量。
- **状态流转机制**：
  - `synced`（已同步）：已成功写入博图并完成编译。
  - `draft`（草稿态）：由 AI 对话生成或用户微调的未确认状态。
  - `error`（报错态）：博图编译失败或存在断链引脚，带脉冲呼吸闪烁高亮。

### 2. 1:1 博图 SCL 转译与物理回写 (`plc_engine/canvas_tia_transpiler.py`)
- **零博图依赖离线转译**：
  - `preview_canvas_scl`：将画布上的逻辑块无缝转译为完全兼容西门子官方规范的 SCL 外部源程序。
  - `preview_canvas_tags_xml`：将变量与绑定的标签生成为标准 `SW.Tags.PlcTagTable` SimaticML XML。
- **安全回写流水线**：
  - 打包生成标准 `import_bundle`（含 `external_sources/*.scl` 与清单）。
  - 调用 `execute_writeback` 写入目标博图工程，并触发 `CompilePlcSoftwareStrict` 门禁。

### 3. 编译器错误逆向归因与一键自愈 (Feedback & Self-Healing Loop)
- **逆向归因 (`attribute_compiler_errors`)**：
  - 拦截博图的 `InconsistentBlocks`、行号错误以及未声明变量提示。
  - 将错误准确定位到具体的 Canvas 块、网络或 HMI 控件。
- **自愈补丁合成 (`generate_canvas_autofix_patch`)**：
  - 针对编译报错自动生成修复操作（例如：检测到 HMI 引用了未声明变量时，自动在对应的 DB 中声明该变量并设定合适数据类型）。

### 4. 现代工业级前端设计系统 (`frontend/src/`)
- **设计规范**：
  - 现代工业深色主题（`#07090e`），辅以 Neon Cyan、Industrial Emerald、High-Voltage Amber、Fault Rose 荧光状态色。
  - Google Fonts（Outfit 标题、Inter 正文、JetBrains Mono 代码）。
  - 毛玻璃效果与 CRT 微扫描线质感。
- **三模态工作台**：
  - `⚡ PLC 逻辑网络拓扑视图`：程序块卡片、信号接口区、展开式网络与 SCL 逻辑。
  - `🖥️ HMI 组态与仿真运行视图`：西门子 SIMATIC HMI 触摸屏拟真，点击按钮可动态联动 PLC 逻辑（例如按下启动按钮，运行灯亮起，转速仪表升至 1450 RPM）。
  - `📜 1:1 SCL 实时编译源码视图`：在线预览生成的西门子标准 SCL 外部源。
  - `🚀 1:1 还原博图确认门禁`：安全审计弹窗，核对 SCL 外部源与 Tag 表差异。

---

## 三、 API 路由清单与调用格式

| 路由端点 | 方法 | 作用 |
| :--- | :--- | :--- |
| `/api/v1/plc/canvas/default` | GET | 获取初始默认画布状态（含示例 DB、FB 与 HMI 控件） |
| `/api/v1/plc/canvas/patch` | POST | 对话 Agent 提交增量修改操作包 |
| `/api/v1/plc/canvas/to-scl` | POST | 实时预览画布生成的 SCL 代码与 TagTable XML |
| `/api/v1/plc/canvas/confirm-writeback` | POST | 工程师确认门禁，执行 1:1 写入博图并触发编译测试 |
| `/api/v1/plc/canvas/auto-fix` | POST | 基于博图编译反馈自动生成并应用修复补丁 |
