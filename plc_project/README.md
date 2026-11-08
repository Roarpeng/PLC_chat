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
│   ├── routers/greenfield.py     # Greenfield 新通道(/state /confirm /generate /deliver-tia …)
│   └── services/plc/             # session_store/compile_jobs/chat_ops/greenfield_*/
├── frontend/           # React 19 + Vite + TS 工业工作台(默认落地 4 步主链)
│   ├── src/shell/steps/          # StepDescribe/StepLink/StepConfirm/StepDeliver + stepMachine.ts
│   ├── src/shell/                # GreenfieldWizard(主链容器)/EngineeringDrawer(工程视角)
│   └── src/state/greenfield.ts   # 唯一后端出入口(Facade,导出签名冻结)
├── industrial/tia_openness_cli/  # C# .NET Openness CLI
├── tests/              # 后端 1341 项 pytest;frontend 393 项 vitest
├── evidence/           # WP-10 全量验收证据链(rtm.json / pending 台账 / 真机报告)
└── docs/               # 编号文档 01-28 + greenfield/ + frontend-redesign/(见下)
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
| **Greenfield 新通道** | 独立路由 `/api/v1/plc/canvas/greenfield`;批次 4 已闭合 UC-04 全量 AF 包与 UC-16 增量链(RTM pass=19/19);`xml_package_unverified` 仍为 `true`、**M4 仍未通过**,详见下节 |
| **4 步可体验主链(2026-11-08)** | 自然语言描述 → ReactFlow 拖线 → 业务语言确认 → 导出工程包完成页;全部契约/审计信息收进默认折叠的「工程视角」抽屉;主链首屏零内部术语;不依赖 TIA 真机即可到达完成态;按 `frontend-design` 规范实现「工业蓝图 / 制图室」美学,零新增依赖 |

## 前端交互壳(2026-11-08)

前端默认落地页为 **4 步主链**(见 `docs/frontend-redesign/01-prd.md`);存量工作台不隐藏,顶栏保留「返回工作台」入口。

| 步 | 主操作 | 完成态 |
|---|---|---|
| 1 描述 | 全流程唯一工艺描述输入框;显式提交后走真实 `/chat` 生成草图 | 草图出现 + 工位节点 1 点亮 |
| 2 连线 | 全幅 `@xyflow/react` 画布,从 8px 连接桩拖出新增、选中删除(走 `applyLinkPatch add_edge/remove_edge`) | 连线数 >0 且校验通过 |
| 3 确认 | 三段业务摘要 + 唯一主按钮;进入时先 `fetchEngineeringSummary`,再 `confirmSpec(explicit=true)` | FROZEN + 工程包生成 |
| 4 完成 | 「工程包已就绪」+ 盖章 + fidelity 中文如实转述 + 下载工程包 | 用户可见终点,不依赖真机 / A·B·C / 差异清单 |

- **工程视角**:默认折叠的右侧 420px 抽屉,6 组原样保留 D7/D10/D11/N9、`fidelity_ok`、`spec_hash`、`step_order`、PCEC、`compile_diagnostics`、`pending_real_machine`、A·B·C、差异清单、SCL 只读预览。折叠是纯前端视图状态,不触发/不跳过/不替代任何后端调用与写入门禁。
- **隐藏硬门禁**:`/confirm` 要求 `engineering_summary_shown === true`,该标志只能由 `POST /engineering-summary` 置位;步 3 漏调必返 `GF_GATE_NOT_CONFIRMED`。`/generate` 的后端门禁只有 `FROZEN` + `specs` 非空,故完成态合法可达、不构成绕过。
- **美学**:工业蓝图 / 制图室,纸随 `data-step` 四步换底 + 完成盖章;方角、无阴影、无渐变、纯 CSS 动效 + `prefers-reduced-motion` 降级;沿用自托管 Albert Sans,零新增依赖。
- **边界**:后端、`state/greenfield.ts`、`greenfield.css`、既有 20 个测试文件、构建配置零改动;`App.tsx` 仅 1 行改动(默认 channel)。浏览器端到端点击与真实 HTTP 跨域联调尚未验证。

## Greenfield 通道状态(批次 4 + 前端交互壳,现状描述)

> 本节与 `gateway/app/routers/greenfield.py` 实际注册端点一致,为**现状描述**,不是规划清单。

**当前端点**(统一前缀 `/api/v1/plc/canvas/greenfield`、`ApiResponse` 信封):
`GET /state` `/whitelist` `/views` `/export/mermaid` `/specs/{version}` `/download-package`;
`POST /upload` `/receipt/confirm` `/draft` `/draft/export` `/draft/import` `/load-reference` `/links` `/validate` `/hardware` `/chat` `/begin-edit` `/confirm` `/generate` `/engineering-summary` `/deliver-tia`。
契约 §3 的 `/patch` `/diff` `/confirm-diff` 已接入前端 `state/greenfield.ts`(`applyCanvasPatch` / `fetchSpecDiff` / `confirmDiff`);端点一律以路由实际注册为准。

**P0-A 编译判定口径**:`POST /deliver-tia` 回执新增 `compile_diagnostics`(error 数 / warning 单列清单 / 块清单 / 耗时 / TIA 版本 / 项目路径 / 静态门禁 / `compile_ok`);`compile_ok = (error_count == 0 and static_gate_passed)`,warning 单列、禁止并入成功;`tia_unavailable` 显式失败(非 HTTP 200、`ok=false`、明确 error code),与「真机未跑」`pending_real_machine` 显式区分。

**AF 档位(P0-D)**:已于 2026-11-06 由用户拍板 **坚持 AF Basic 文件夹版、暂不切软件单元版**(`docs/greenfield/11-p0d-decision.md`);Gate-0 由 `conditional-go` 升 `go`,映射层已按文件夹版定型。`go` ≠ `L1∧L2∧L3∧L4` 全绿 ≠ M4 可签署。

**批次 4 真机结论**(提交 `b4eac2d`,详见 `docs/greenfield/14-18` 与 `evidence/`):完整 AF 包补齐 FB / 全局实例 DB 后,两轮独立干净副本各 **10/10 imports + compile errorCount=0 / warningCount=0**;UC-16 增量链 `/open=1`、句柄复用、PCEC 3 条、4× 编译 0/0、八步 `fidelity_ok=true`。RTM 由 `pass=17 / pending=2` 变为 **`pass=19 / fail=0 / pending=0 / not_run=0`**。

**「真机全绿」归属与状态**:`真机全绿 = L1 ∧ L2 ∧ L3 ∧ L4`,归属 **WP-10 全量验收 / M4 发布门禁**。批次 4 已闭合 UC-04 / UC-16 的真机证据,但提交口径仍明确保留:`xml_package_unverified = True`(ProDiag OB、`deliver_tia` 自动端到端链、组归属、可复现性与 culture 边界未验证)、**L1–L4 未全绿**、`evidence/pending_real_machine.json` 的 `cleared=false` 且 10 条历史 items 未删、**M4 未通过 / 不可签署**(签署栏留给用户)。上表「TIA V19 真机验证全绿」仅指存量 v3.0 回写链的历史结论,不迁移到 Greenfield 新通道(N9:`fidelity_ok` 与 `compile_ok` 是独立层)。

**本批次口径**:禁止以离线单测宣称 L2 通过或「编译零错误」;pending 台账清零只能由主 agent 逐条核验后执行。前端 4 步主链的「完成态」是**产品体验口径**(导出工程包 + fidelity 报告),不等于、也不改变上述终态验收口径。

**证据路径**:P0-A → `tests/unit/test_greenfield_tia_delivery.py` 与 `tia_delivery.json` 的 `compile_diagnostics`;批次 4 → `evidence/uc04_product_package_real.json`、`evidence/uc16_incremental_closed_real.json`、`evidence/rtm.json`、`evidence/pending_real_machine.json`;前端交互壳 → `docs/frontend-redesign/03-qa-report.md`(构建 / 393 项回归 / 真实后端门禁反证)。

## 快速启动

```bash
cd plc_project
python tools/devctl.py up gateway   # 网关 :8000
python tools/devctl.py up web       # 前端 :5173
```

> 也可使用仓库根的 GraphFlow 宏 `launch_plc_stack` / `stop_plc_stack` / `status_plc_stack`(见 `AGENTS.md`),或图形化静默启动 `启动项目.vbs` / `停止项目.vbs`。
> 打开 `:5173` 默认进入 4 步主链:描述 → 拖线 → 确认 → 下载工程包;右上角「工程视角」默认折叠;顶栏「返回工作台」可回到存量工作台(导入工程 / 历史会话 / 新建向导)。

## 测试

```bash
python -m pytest tests/unit -q                    # 后端 1341 passed / 1 xfailed(排除既有基线失败)
cd frontend && npm run test -- --pool=threads    # 前端 23 files / 393 passed / 0 failed / 0 skip
cd frontend && npm run build                     # tsc -b && vite build
```

> 前端 vitest 默认 `forks` 池在本机偶发 worker 启动超时(无断言失败),用 `--pool=threads` 稳定;不得为消 flake 改测试或加 skip。

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
| 24-28 | IO/DB/Mermaid 四线契约、Gemini 重构契约、v3.0 进度审计、安全整改、长任务中心 |
| `greenfield/` | Greenfield 通道 PRD / 架构 / Gate-0 / P0-D 拍板 / 批次 3-4 真机验收 / M4 评审(01-18 + 两张 Mermaid 图) |
| `frontend-redesign/` | 2026-11-08 前端交互壳重构:`01-prd.md`(增量 PRD) / `02-architecture.md`(架构与任务分解) / `03-qa-report.md`(独立 QA 报告) |
