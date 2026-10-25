# PLC Intelligence Platform (西门子 TIA / SimaticML 工业 PLC 智能分析平台)

本工程为从 ResearchOS 中独立剥离出的 **全栈工业 PLC 智能分析、数字孪生画布与博图闭环研发系统**。专注于西门子 TIA Portal 工程文件的离线解析、PLC-IR 统一中间表示构建、结构化 SCL 代码生成、逻辑知识图谱推理、安全检查、数字孪生 HMI 触控仿真以及 1:1 博图物理回写编译自愈闭环。

---

## 🌟 核心特性与架构

```
plc_project/
├── agents/             # 多智能体运行时 (citation / planner / writer / supervisor)
│   └── plc/tia/        # 【解析核心】SimaticML 解析、IR 模型、SCL 转换器、知识图谱、Review 规则
├── plc_engine/         # 数字孪生画布引擎与脱机独立 API (解析核心位于 agents/plc/tia)
│   ├── standalone_api.py# 100% 脱离博图的跨平台离线分析/翻译/审计 API
│   ├── canvas_model.py  # 数字孪生画布 (PLC 逻辑 + HMI 组态) 与错误归因模型
│   ├── canvas_tia_transpiler.py # 画布 1:1 SCL 转译、打包与博图回写驱动
│   ├── tia/             # 【兼容占位】仅重导出 agents/plc/tia 公共入口，勿在此新增实现
│   └── cli.py           # 命令行工具主入口 (plc-cli / researchos-tia-cli)
├── frontend/            # 现代工业级数字孪生 Web 前端 (React 19 / Vite / TypeScript)
│   ├── index.html       # Web 模板与 Google Fonts (Outfit, Inter, JetBrains Mono)
│   ├── package.json     # 前端依赖配置
│   └── src/
│       ├── index.css    # 现代深色工业主题系统 (毛玻璃、拟真西门子机壳、触感按键)
│       ├── App.tsx      # 顶层工作台容器 (双向连接后端网关与离线沙箱降级)
│       └── canvas/
│           ├── PlcInteractiveCanvas.tsx # 三模态画板 (PLC逻辑 / HMI仿真 / 1:1 SCL预览)
│           └── types.ts # 画布与控件 TypeScript 接口定义
├── gateway/             # 独立 FastAPI 网关后端 (含 PLC 专用路由与服务)
│   ├── app/main.py      # 网关应用入口 (启动端口 8000)
│   ├── app/routers/plc.py # PLC Ingest、Canvas 补丁、1:1 回写、自愈、审计路由
│   └── app/services/plc/# Handover Brief、Evidence、Logic Graph、Device Cards
├── industrial/          # 工业侧车、连接器与驱动
│   ├── openness_worker/ # Windows 宿主机 TIA Openness 侧车导出/回写微服务 (FastAPI)
│   ├── tia_adapter/     # PowerShell 自动化导出脚本 (ExportProject.ps1)
│   ├── connectors/      # PLC 手册与故障诊断知识库连接器
│   └── tia_openness_cli/# C# .NET Openness 解决方案 (TiaOpenness.Server.exe)
│       └── src/         # 支持设备创建、全局库复用、变量表细粒度提取与编译门禁
├── tests/               # 完整测试套件与真实工业 Fixtures (46 个测试文件，320 个测试通过)
│   ├── fixtures/        # tia_ce, tia_dc, tia_exports, tia_openness_surface 等用例
│   └── unit/            # 46 个单元测试文件
└── docs/                # 工业架构与技术规范文档 (含 09-digital-twin-canvas 闭环文档)
```

---

## 🚀 核心功能亮点

### 1. ⚡ 纯离线脱机独立 API (零博图依赖 / 跨平台)
无需 Windows 环境或西门子博图授权，可直接运行在 Linux / Docker / macOS / Web 服务端：
- **`translate_simaticml_to_scl(xml)`**：梯形图/函数块 SimaticML 秒级转换为西门子标准 SCL 源码。
- **`parse_simaticml_block_content(xml)`**：精确抽取块接口引脚、网络与调用元数据。
- **`extract_tag_table_content(xml)`**：解析符号名、数据类型与绝对物理地址（`%I`, `%Q`, `%M`）。
- **`audit_block_content(xml)`**：静态确定性代码审查（双线圈覆盖、未配对置位复位、孤立变量探测）。

### 2. 🖥️ 数字孪生画布与 HMI 仿真 (Web Canvas)
- **双模态无缝切换**：
  - **⚡ PLC 逻辑网络视图**：展示 FB/FC/DB 块、接口信号区、网络逻辑折叠与实时诊断。
  - **🖥️ HMI 组态仿真视图**：拟真西门子 SIMATIC HMI 触摸面板，支持触控联动（点击启动按钮，运行指示灯点亮，转速仪表升至 1450 RPM）。
  - **📜 1:1 SCL 实时编译源码视图**：实时查看由画布生成的合规 SCL 外部源。
- **对话驱动增量更新**：通过自然语言输入（如：“*在 MainDB 增加急停信号，并在 HMI 上添加红色急停按钮*”），AI 自动将变更增量打补丁到画布。

### 3. 🔄 1:1 博图物理回写与编译器错误闭环自愈
- **工程师安全审核门禁**：画布上的草稿内容（`draft`）需经工程师确认后方可触发 1:1 回写。
- **严苛一致性编译校验**：回写后自动调用 `CompilePlcSoftwareStrict` 门禁。
- **编译器错误逆向归因**：若编译报错，将错误准确定位至画布出错节点（红框呼吸闪烁高亮）。
- **一键自愈修复**：点击【🛠️ 一键自愈修复】，AI 结合博图真实错误日志自动补齐未声明变量与修正数据类型。

---

## 🛠️ 快速上手与运行

### 1. 环境准备与后端启动
```bash
# 进入项目目录
cd plc_project

# 安装 Python 依赖
pip install -e .

# 启动 FastAPI 独立网关服务 (端口 8000)
python -m uvicorn gateway.app.main:app --port 8000 --host 127.0.0.1
```
服务启动后可访问：
- API 交互文档 (Swagger UI)：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

### 2. 启动前端数字孪生 Web UI
```bash
# 进入前端目录
cd frontend

# 安装前端依赖
npm install

# 启动 Vite 开发服务器 (端口 5173)
npm run dev -- --port 5173 --host 127.0.0.1
```
在浏览器中打开：`http://127.0.0.1:5173/` 即可体验全套数字孪生交互！

### 3. 运行全量单元测试
```bash
python -m pytest tests/unit -q
```
测试涵盖：
- SimaticML 块结构（OB、FB、FC、DB、UDT、TagTable）解析
- 梯形图 (LAD) 自保持、比较、跳转、计数器、定时器向 SCL 翻译
- 知识图谱调用链 (CALLS / USES / INSTANCE_OF) 与读写信号流追踪
- 扩展 Openness CLI 与 Worker HTTP 侧车交互
- 脱机独立 API 与 REST 端点
- 交互式数字孪生画布、补丁应用、错误归因与自愈闭环（**320 项测试全部通过**）

---

## 🏭 Windows TIA Openness 侧车对接 (可选)

如果需要直接处理 `.ap17` ~ `.ap20` 的原始 TIA 工程项目文件：
1. 在装有 TIA Portal 的 Windows 电脑上运行管理员脚本注册 Openness 白名单：
   ```powershell
   powershell -ExecutionPolicy Bypass -File industrial/scripts/Register-TiaOpennessWhitelist.ps1
   ```
2. 启动 Openness Worker 侧车：
   ```bash
   python -m industrial.openness_worker.server
   ```
3. C# 解决方案编译：
   ```bash
   cd industrial/tia_openness_cli
   dotnet build -c Release
   ```
   生成目标文件：`industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe`
