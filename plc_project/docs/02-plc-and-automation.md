# PLC 与自动化

本文描述 ResearchOS 对 PLC / 工控自动化场景的辅助定位：解读、对照、建议与知识沉淀，**而不是**无人值守的控制器刷写系统。

## 问题域

- 根据报警代码与手册定位可能原因（知识检索 + 推理）
- 对比两版结构化文本 / 梯形图逻辑差异（人工贴入或从受控仓库读取）
- 将设备手册、IO 表、联锁说明入库，供维护团队检索
- 生成变更方案与测试清单，供工程师审核

## 架构位置

```
Agent
  ├── mcp-plc          （解析、静态分析建议、厂商手册检索封装）
  ├── knowledge.*      （IO 表、联锁矩阵、历史工单）
  └── interrupt gate   （任何下发类工具）
```

现场协议（Modbus、OPC UA、厂商 SDK）若启用，必须运行在 **工控 DMZ 侧车**，由 MCP 暴露最小只读面。

## MCP：`tia-openness`（Milestone 1 Foundation — 已落地）

路径：`tools/industrial-mcp/tia-openness/`（C# stdio MCP → TIA Portal V19 Openness）

| 工具 | 状态 | 说明 |
|------|------|------|
| `tia.get_status` | **已实现** | 检测 TIA Portal 进程 + Openness PublicAPI |
| `tia.open_project` | **已实现** | 打开 `.ap19`（亦支持 `.ap17`+） |
| `tia.list_blocks` | **已实现** | 列出 OB / FB / FC / DB |
| `tia.export_block` | **已实现** | 单块导出 SimaticML XML |
| `tia.export_project` | **已实现** | 整工程块导出到目录 |
| `plc.tia.ingest` | **已实现** | XML/.apxx/目录 → Parser → PLC-IR → KG → Neo4j(可选) |

契约见 [`docs/mcp/08-tia-openness-mcp.md`](../mcp/08-tia-openness-mcp.md)。下游已接：`XML → plc.tia.ingest (PLC Parser / PLC-IR / KG / Neo4j) → PLC Agent`。

## ResearchOS 子功能：PLC Workspace（Gateway + Frontend）

- 前端：主控制台旁 **PLC** 页（与 Research 并列）
- API：`/api/v1/plc/jobs`（path / upload）→ chat → **changes / writeback** → export ZIP
- 写回：HITL 确认后 Openness `Import(Override)` + `Save`（见 [`docs/deployment/06-plc-feature.md`](../deployment/06-plc-feature.md)）
- 部署：混合拓扑（Docker 数据面 + Windows Openness 侧车）

## MCP：`mcp-plc`（已实现 vs 目标）

| 工具 | 默认 | 状态 | 说明 |
|------|------|------|------|
| `plc.manual.search` / `get` / `vendors.list` | 开 | **已实现** | 手册目录检索（当前为 fake catalog stub） |
| `plc.alarm.explain` | 开 | **已实现** | 报警码 → 候选原因（必须带手册引用） |
| `plc.tia.analyze` | 开 | **已实现** | Openness SimaticML 导出 → IR / KG / SCL（只读） |
| `plc.st.parse` | 开 | 目标 | 解析 Structured Text 片段 |
| `plc.ld.summarize` | 开 | 目标 | 梯形图摘要 |
| `plc.diff.routines` | 开 | 目标 | 两版本逻辑差异 |
| `plc.opcua.read` | 关 | 目标 | 读节点值 |
| `plc.program.download` | 关 | **已实现为永拒** | 高危；默认禁用且无写设备实现 |
| `plc.program.upload_suggest` | 关 | stub | 需显式 flag；当前未生成产物 |

### 自测：用你自己的 TIA 工程

**一键（推荐）**：你提供 `.apxx`，系统自动 Openness 导出 → 解析 → 逻辑理解 → SCL 结果包：

```powershell
researchos-tia-cli --project <项目.ap19> --result-dir .\ResearchOS_PLC_Result --json-summary
```

说明：`.apxx` 内部库不能纯离线拆包（见 Offline Analyzer 文档 Level 3）；本机需安装 TIA + Openness。若已有 SimaticML 导出目录，用 `--exports` 即可完全离线。

详见 `docs/agents/PLC Offline Analyzer Architecture.md`、`industrial/tia_adapter/README.md`。


## 安全与责任边界

1. ResearchOS 输出 = **建议**；生产变更走企业原有变更管理（MOC）
2. 禁止在未审核情况下修改运行中的 PLC 应用程序
3. 联锁、安全继电器、安全 PLC（Safety PLC）相关结论必须引用厂商安全手册；模型不得「优化掉」安全条件
4. 所有 OPC UA / 现场读取写入审计，并绑定 `task_id`、`user_id`
5. 默认工作空间关闭现场连接；仅「运维只读」空间可开 `opcua.read`

## 知识建模

实体示例：

- `PLC`（型号、固件）
- `IOPoint`（地址、信号名、电气注释）
- `AlarmCode`
- `Interlock`
- `Routine`

关系：`HAS_IO`、`RAISES_ALARM`、`GUARDS`、`CALLS_ROUTINE`。

入库优先结构化 IO 表（CSV/Excel）与 PDF 手册；工单文本做脱敏。

## 典型研究流

**查询**：包装线频繁出现报警 E2304，对比近三个月工单与手册，给出检查清单。

流程：

1. 检索 AlarmCode 与手册章节
2. 关联历史工单实体
3. 若有只读 OPC，采样相关 IO（需批准）
4. 生成分步检查清单 + 引用
5. Reviewer 门禁：无引用则打回

## 人工中断

| 动作 | 中断 |
|------|------|
| 纯文档研究 | 审阅门 |
| OPC 只读采样 | 每次会话首次批准 |
| 生成可导入程序包 | 强制批准 + 显示 diff 摘要 |
| 下载到 PLC | 产品默认不提供 |

## 与 n8n

可用 n8n 做「每班报警摘要通知」：定时调用 Gateway 创建 quick 任务或推送已生成报告链接。分析逻辑仍在 Runtime。

## 验收切片

1. 对样本报警码返回带手册页引用的解释
2. ST 片段符号表解析正确率基线测试
3. 确认 `program.download` 在默认配置下不可注册或调用失败码稳定
4. 审计日志含工具名与操作者

## 非目标

- 替代 TIA Portal / GX Works / Studio 5000 等 IDE
- 自动生成并通过安全认证的完整安全逻辑
- 跨厂商「万能」在线调试
