# PLC_chat — 可验证的西门子 TIA / SimaticML 工业 PLC 智能工程系统

从自然语言对话到博图真实编译闭环的全栈工业 PLC 工程 workbench:**离线解析 → PLC-IR → 知识图谱 → 数字孪生画布 → NL 编辑 → 带证据的变更事务(PCEC)→ TIA Openness 1:1 回写与严格编译**。老项目 LAD 逆向转 SCL 在真实工程上等价性抽样 9/9。

---

## 架构

```
plc_project/
├── agents/             # 多智能体运行时 (citation / planner / writer / supervisor)
│   └── plc/tia/        # 【解析核心】SimaticML 解析、IR、FlgNet 折叠、SCL 转换、知识图谱
├── plc_engine/
│   ├── canvas_model.py           # 数字孪生画布模型(PLC + HMI)与错误归因
│   ├── canvas_tia_transpiler.py  # 画布 1:1 SCL 转译、回写打包(最小破坏/draft-only)
│   ├── pcec.py                   # PCEC 变更事务:状态机/基线哈希/事务账本
│   ├── standalone_api.py         # 100% 脱离博图的跨平台离线分析/翻译/审计 API
│   └── tia/                      # 【兼容占位】仅重导出 agents/plc/tia,勿在此新增实现
├── gateway/app/        # 唯一 FastAPI 网关 (端口 8000)
│   ├── routers/plc.py            # ingest/canvas/回写/编译/会话历史/变更账本 路由
│   └── services/plc/             # session_store(跨浏览器会话+墓碑)/compile_jobs(PCEC 接入)
│                                 # / chat_ops(双模式路由+历史压缩+命名规范)/llm_explain
├── frontend/           # React 19 + Vite + TS 工业工作台
│   └── src/           # 画布/全局图/SCL 面板/ChatDock(时间戳·复制·Markdown)/
│                       # ChangeLogDrawer(V0-V3 变更记录)/SourceCompareDrawer(</> 源码下钻)
├── industrial/
│   └── tia_openness_cli/         # C# .NET Openness CLI (导出/外部源生成/严格编译)
├── tests/              # 514 项后端测试 + 真实工业 fixtures;frontend 100 项 vitest
└── docs/               # 编号文档 01-20(见下)
```

> 历史副本 `plc_gateway/` 已弃用,权威网关为 `gateway/app`。

## 核心能力

| 能力 | 说明 |
|---|---|
| **LAD→SCL 高保真逆向** | SimaticML FlgNet 折叠为表达式 IR 再直译 SCL;真实工程(HR001, 89 块)等价性抽样 **9/9**;归约过程可下钻(`</>` 源码对比抽屉:原始 XML / 直译 SCL / 归约追踪) |
| **NL 编辑与意图路由** | 简单/复杂问句直答,编辑指令走 ops;**指代性指令**(「按步骤全部修改」)依据分级压缩的对话历史解析;绝不捏造 UserVar 占位变量;变量命名遵循工程惯例(输入 i_ / 输出 o_ / 静态 stat_) |
| **双模式 LLM(工业可靠优先)** | 简单任务直答(thinking 关),复杂任务自动深想(按复杂信号/长度/跨块引用判定),回答页脚标注「深度思考」 |
| **PCEC 变更事务** | 每次回写都是可审计事务:`created→analyzed→validated→approved→applied`,change_id 贯穿 UI→编译→账本;**基线门禁**(工程 original 副本哈希变化 → 变更过期拒绝);V0-V3 分级验证(结构/静态/TIA 编译/行为),未知≠通过;前端「变更记录」面板 |
| **真机回写闭环** | 确认门禁 → 写前备份 fail-closed → 外部源导入 → CompilePlcSoftwareStrict → 错误逆向归因 → 一键自愈;已在真实 TIA V19 + HR001 工程验证全绿 |
| **跨浏览器会话历史** | 服务端账本 + 本地缓存双写,启动自动合并(占位懒加载);**删除墓碑**防陈旧副本复活 |
| **成熟 Chat UX** | 消息时间标签、一键复制、Markdown 渲染、流式打字机 |
| **HMI 仿真** | 画布内软 PLC 联动(按钮/指示灯/仪表),对话创建控件 |

## 快速启动

```bash
cd plc_project
python tools/devctl.py up gateway   # 网关 :8000(uv 免装依赖)
python tools/devctl.py up web       # 前端 :5173(Vite)
python tools/devctl.py status       # 状态 / down --all 一键归零
```

图形化一键启动/停止:`启动项目.vbs` / `停止项目.vbs`。浏览器打开 `http://127.0.0.1:5173/`。

> 打开即空白画布;在左侧「历史对话」选择导入的工程会话进入项目上下文(会话历史跨浏览器同步)。

## 测试

```bash
python -m pytest tests/unit -q      # 后端 514 项
cd frontend && npm run test         # 前端 100 项
```

覆盖:SimaticML 解析(OB/FB/FC/DB/UDT/标签表)、LAD→SCL 等价回归、知识图谱调用链、PCEC 状态机/基线/账本、会话同步与墓碑、意图路由与命名规范、历史压缩、编译作业与守卫、架构治理防漂移。

## Windows TIA Openness(可选,处理 .ap17~.ap20 原生工程)

```powershell
# 1. 注册 Openness 白名单(管理员)
powershell -ExecutionPolicy Bypass -File industrial/scripts/Register-TiaOpennessWhitelist.ps1
# 2. C# CLI
cd industrial/tia_openness_cli && dotnet build -c Release
# 产物: src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe
```

网关按需 spawn 一次性 CLI(进程树可杀、工程锁可释放);常驻会话默认关闭(services.toml 可调)。

## 文档索引(docs/)

| 编号 | 主题 |
|---|---|
| 01-13 | 架构基础:Windows Openness Worker、PLC 离线分析器、数字孪生画布、微服务化、LLM 深度解释、前置评估等 |
| 14 | Chat2PLC V2.5 蓝图存档(四层架构/LAD→SCL/Openness 桥) |
| 15 | LAD→SCL 后端静默契约(源码工件+按需取源 API) |
| 16 | LAD→SCL 离线验证报告(S1-S10 修复,等价性 9/9) |
| 17 | Siemens Automation Framework 深度调研报告 |
| 18 | AF 集成行动计划(A 方案:自举 AF Profile→官方库对齐) |
| 19 | PCEC 契约(变更事务对象/状态机/V0-V3/接口) |
| 20 | 对话历史压缩策略(分级保真,存储永不压缩) |

另见 `docs/PLC_chat_突破性架构理解与演进方案.html`(工程评审与演进建议,PCEC 即其核心提议的落地)。
