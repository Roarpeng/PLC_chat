# 08 — TIA Openness MCP（工业 Milestone 1）

## 定位

`tools/industrial-mcp/tia-openness` 是 ResearchOS **TIA Openness MCP Foundation**：把 Siemens TIA Portal Openness 暴露为 stdio MCP。导出走 chapter-6 walker；写回（Import / GenerateBlocksFromSource / Retrieve / Archive）在 **Windows HostGateway** 上运行，见包内 README 的 implemented vs out-of-scope 表。

```text
ResearchOS Agent
        |
       MCP
        |
TIA Openness Server
        |
TIA Portal V19
```

Milestone 1 **之后**再接到已有离线管线：

```text
XML → PLC Parser → PLC-IR → Neo4j → PLC Agent
```

## Server

| 项 | 值 |
|----|-----|
| 路径 | `tools/industrial-mcp/tia-openness/` |
| 进程名 | `researchos-tia-openness` |
| Transport | stdio |
| 默认 Portal | V19（`TIA_VERSION` / `TIA_PORTAL_ROOT` 可覆盖） |

## 工具

| 工具 | side_effect | 说明 |
|------|-------------|------|
| `tia.get_status` | none | 检测 Portal 进程与 Openness DLL |
| `tia.open_project` | none* | 打开 `.ap19`（亦支持 `.ap17`+） |
| `tia.list_blocks` | none | 列出 OB / FB / FC / DB |
| `tia.export_block` | export | 导出 SimaticML XML |
| `tia.export_project` | export | 批量导出全部块到目录 |
| `tia.import_block` | write | `Blocks.Import`；拒绝 F-block XML |
| `tia.import_xml` | write | UDT/标签表/监视强制表等，**仅当**该 composition 有 `Import` |
| `tia.generate_from_source` | write | `CreateFromFile` + `GenerateBlocksFromSource` |
| `tia.generate_source_from_block` | export | `PlcBlock.GenerateSourceFromBlocks`（5.11.3.18） |
| `tia.compile_plc` | none* | `ICompilable.Compile`；失败不得 Archive |
| `tia.save_project` | write | `Project.Save()` |
| `tia.archive_project` | export | `Project.Archive(..., Compressed)` → `.zap*` |
| `tia.retrieve_project` | write | `Projects.Retrieve(FileInfo, DirectoryInfo)` |
| `tia.create_project` | write | `Projects.Create`（API 缺失则失败关闭） |
| `tia.close_project` | none | `Project.Close()` |

\*打开工程会附着或拉起 Openness 会话，但不写 PLC、不改工程内容。

**许可证：** Export / Import / Archive 需要有效的 STEP 7 / TIA 许可证（常见报错：`Necessary license 'STEP 7 Basic' is missing`）。先在 Automation License Manager 激活，再跑闭环。

## 与 `mcp-plc` / `tia_adapter` 的关系

| 组件 | 角色 |
|------|------|
| `tools/plc` (`mcp-plc`) | 手册 / 报警 / 已有导出目录的离线分析 |
| `industrial/tia_adapter` | PowerShell 整工程批量导出 |
| **`tia-openness` MCP** | Agent 交互式 Openness：状态 / 打开 / 列块 / 单块导出 |

## 安全

- 禁止程序下载到 PLC（`plc.program.download` / Online download 明确 out of scope）
- F-block 写回拒绝（`XmlLooksLikeSafety`）
- 运行账户须在 **Siemens TIA Portal Openness** 组
- 运行账户须在 **Siemens TIA Portal Openness** 组
- 审计由 Runtime `tool_traces` 记录工具名与参数摘要

## Downstream bridge (Milestone 1 follow-on)

```text
tia.export_block / tia.export_project / .apxx
        |
   SimaticML XML
        |
plc.tia.ingest   (Parser → PLC-IR → KG → optional Neo4j)
        |
   PLC Agent
```

| Tool | Role |
|------|------|
| `tia.export_project` | Bulk export all blocks (MCP or `--cli export-project`) |
| `plc.tia.analyze` | Offline folder → IR/KG/SCL (`publish_graph` optional) |
| `plc.tia.ingest` | XML / .apxx / folder → full bridge incl. Neo4j publish |

C# CLI (for Python importer, no MCP session):

```powershell
dotnet run --project tools/industrial-mcp/tia-openness/src/TiaOpenness.Server -c Release -- --cli status
dotnet run --project tools/industrial-mcp/tia-openness/src/TiaOpenness.Server -c Release -- `
  --cli export-project --project C:\Proj\Line.ap19 --export-dir C:\Export\Line
dotnet run --project tools/industrial-mcp/tia-openness/src/TiaOpenness.Server -c Release -- `
  --cli archive-project --project C:\Proj\Line.ap19 --out-dir C:\Out --name Line.zap19
```

Env:

- `RESEARCHOS_TIA_OPENNESS=auto|cli|ps1` — prefer C# CLI (default auto) then PowerShell
- `RESEARCHOS_PLC_PUBLISH_GRAPH=1` — PLC Agent publishes KG on analyze
- `NEO4J_URI` / `NEO4J_PASSWORD` — real Neo4j; else in-memory graph

## 实现说明

- 宿主目标框架：**`net481`**（Siemens.Engineering 依赖 .NET Framework Remoting；不可在 net8+ 进程内直接加载）
- Openness DLL 以**反射 + 临时目录 staging**加载（对齐 `ExportProject.ps1`）
- 加入 Openness 组后必须**重新登录**，否则 `opennessGroupInToken=false`，`tia.open_project` 会返回 `openness_group_token_missing`

详见包内 [`tools/industrial-mcp/tia-openness/README.md`](../../tools/industrial-mcp/tia-openness/README.md)。
