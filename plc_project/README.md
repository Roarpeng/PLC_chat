# PLC_chat — 可验证的西门子 TIA / SimaticML 工业 PLC 智能工程系统

从自然语言对话到博图真实编译闭环的全栈工业 PLC 工程 workbench:**离线解析 → PLC-IR → 知识图谱 → 数字孪生画布 → NL 编辑 → 带证据的变更事务(PCEC)→ TIA Openness 1:1 回写与严格编译**。老项目 LAD 逆向转 SCL 在真实工程上等价性抽样 9/9;导入工程自动 AF 角色标注(物理冻结,字节级证明)。

---

## 架构

```
plc_project/
├── agents/plc/tia/     # 【解析核心】SimaticML 解析、IR、FlgNet 折叠、SCL 转换、知识图谱
├── plc_engine/
│   ├── canvas_model.py           # 数字孪生画布模型(PLC + HMI)与错误归因
│   ├── canvas_tia_transpiler.py  # 画布 1:1 SCL 转译、回写打包(最小破坏/draft-only)
│   ├── pcec.py                   # PCEC 变更事务:状态机/基线哈希/事务账本
│   ├── af/                       # AF 内核(隐形):mapper/generator/linter/planner/refactor
│   ├── standalone_api.py         # 100% 脱离博图的跨平台离线分析/翻译/审计 API
│   └── tia/                      # 【兼容占位】
├── gateway/app/        # 唯一 FastAPI 网关(端口 8000)
│   ├── routers/plc.py            # ingest/canvas/回写/编译/会话历史/变更账本/需求卡/AF
│   └── services/plc/             # session_store/compile_jobs/chat_ops/llm_explain/
│                                  # requirement_store/af_import/af_generate
├── frontend/           # React 19 + Vite + TS 工业工作台
│   └── src/           # 画布/全局图/SCL 面板/ChatDock(对话为唯一入口)/
│                       # ChangeLogDrawer(V0-V3)/RequirementCardDrawer(工艺需求卡)
├── industrial/tia_openness_cli/  # C# .NET Openness CLI
├── tests/              # 579+ 后端测试;frontend 151 项 vitest
└── docs/               # 编号文档 01-23(见下)
```

> 历史副本 `plc_gateway/` 已弃用,权威网关为 `gateway/app`。

## 核心能力

| 能力 | 说明 |
|---|---|
| **导入自动 SCL 化 + AF 角色标注** | 可读块自动转 SCL(等价性 9/9);每块自动标 AF 角色(Unit/EM/CM/Global/Safety);物理完全不动(DB 偏移/IO/OB 号/F 块,字节级测试证明);无法判定的诚实标注「待人工确认」;PCEC 事务留痕;加密块只提接口 |
| **需求驱动新建工程** | 对话输入工艺需求 → 需求卡(前置/序列/异常/约束/验收+三态来源)→ 确认工艺意图(≠批准修改)→ 一键创建标准工程+自动生成逻辑块;AF+IEC 61131 双门禁零违规;设备自动分类(电机/气缸/传感器→标准 CM) |
| **LAD→SCL 高保真逆向** | FlgNet 折叠为表达式 IR 再直译;`</>` 源码下钻(原始 XML/直译 SCL/归约追踪) |
| **NL 编辑与意图路由** | 简单/复杂问句直答,编辑走 ops;指代性指令(「按步骤全部修改」)依据分级压缩历史解析;不捏造变量;命名遵循 i_/o_/stat_ 惯例 |
| **双模式 LLM** | 简单直答(thinking 关),复杂深想;页脚标注「深度思考」 |
| **PCEC 变更事务** | change_id 贯穿 UI→编译→账本;基线门禁(工程变化→过期拒绝);V0-V3 分级验证;变更记录面板;四层审查(工艺/逻辑/源码/验证) |
| **真机回写闭环(存量 v3.0 链)** | 确认门禁→写前备份 fail-closed→外部源导入→严格编译→错误归因→一键自愈;此处的「TIA V19 真机验证全绿」是**存量 v3.0 回写链**的历史结论,不属于 Greenfield 新通道 |
| **跨浏览器会话** | 服务端账本+本地缓存;删除墓碑防复活 |
| **Chat UX** | 时间标签、复制、Markdown、流式打字机 |
| **Greenfield 新通道** | 独立路由 `/api/v1/plc/canvas/greenfield`;`/deliver-tia` 产出 XML 补充包 + 四层静态门禁 + PCEC 账本 + 结构化编译报告;本批次为离线可推进部分,真机全绿尚未达成(见下节) |

## Greenfield 通道状态(批次 1 / P0-C,现状描述)

> 本节与 `gateway/app/routers/greenfield.py` 实际注册端点一致,为**现状描述**,不是规划清单。

**当前端点**(统一前缀 `/api/v1/plc/canvas/greenfield`、`ApiResponse` 信封):
`GET /state` `/whitelist` `/views` `/export/mermaid` `/specs/{version}` `/download-package`;
`POST /upload` `/receipt/confirm` `/draft` `/draft/export` `/draft/import` `/load-reference` `/links` `/validate` `/hardware` `/chat` `/begin-edit` `/confirm` `/generate` `/engineering-summary` `/deliver-tia`。
契约 §3 约定的 `/patch` `/diff` `/confirm-diff` 由 Agent A 并行开发,集成收口前以路由实际注册为准,不预先宣称上线。

**P0-A 编译判定口径**:`POST /deliver-tia` 回执新增 `compile_diagnostics`(error 数 / warning 单列清单 / 块清单 / 耗时 / TIA 版本 / 项目路径 / 静态门禁 / `compile_ok`);`compile_ok = (error_count == 0 and static_gate_passed)`,warning 单列、禁止并入成功;`tia_unavailable` 显式失败(非 HTTP 200、`ok=false`、明确 error code),与「真机未跑」`pending_real_machine` 显式区分。`xml_package_unverified` 保持 `true`。

**「真机全绿」归属与状态**:`真机全绿 = L1 ∧ L2 ∧ L3 ∧ L4`,归属 **WP-10 全量验收 / M4 发布门禁**;**尚未达成**。上表「TIA V19 真机验证全绿」仅指存量 v3.0 回写链的历史结论,不迁移到 Greenfield 新通道(N9:`fidelity_ok` 与 `compile_ok` 是独立层)。

**本批次口径**:本批次为**离线可推进部分**(WP-01 的 P0-A 编译判定 + P0-C 文档口径),不含真机验收;L2 / L4 相关验收项一律标 `pending_real_machine`,**M4 发布门禁在这些 pending 清零前保持未通过**。禁止以离线单测宣称 L2 通过或「编译零错误」。

**AF 档位(P0-D)**:结论**待 G0 真机实测后拍板**;结论前映射层维持「**档位无关**」,禁止据推断定型。

**证据路径**:P0-A → `tests/unit/test_greenfield_tia_delivery.py`(UC-02 / UC-03 / 静态门禁负例)与 `tia_delivery.json` 的 `compile_diagnostics`;P0-B(K1 探针)→ `xml_supplement/manifest.json` 的 `xml_package_unverified` / `pending_real_machine`,真机项 `pending_real_machine`。

## 快速启动

```bash
cd plc_project
python tools/devctl.py up gateway   # 网关 :8000
python tools/devctl.py up web       # 前端 :5173
```

> 启动屏两入口:导入工程 / 新建工程。新建工程从工艺需求开始(对话输入→需求卡确认→创建)。

## 测试

```bash
python -m pytest tests/unit -q      # 后端 579 项
cd frontend && npm run test         # 前端 151 项
```

## 文档索引(docs/)

| 编号 | 主题 |
|---|---|
| 01-13 | 架构基础:Windows Openness Worker、PLC 离线分析器、数字孪生画布、微服务化等 |
| 14 | Chat2PLC V2.5 蓝图存档 |
| 15-16 | LAD→SCL 契约与验证报告(等价性 9/9) |
| 17-18 | Siemens Automation Framework 调研与集成行动计划 |
| 19 | PCEC 契约(变更事务/状态机/V0-V3) |
| 20 | 对话历史压缩策略 |
| 21 | 工作台规范差距分析 |
| 22 | 工作台 P0 契约(需求卡/变更审查/批量删除护栏) |
| 23 | AF 内置化契约(两入口/导入自动 AF/需求驱动生成) |
