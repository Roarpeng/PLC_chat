# TIA Openness MCP Server Design

## Purpose

连接 ResearchOS 与 Siemens TIA Portal。

架构：

```
ResearchOS Agent
 |
 MCP
 |
TIA Openness MCP Server
 |
Siemens.Engineering.dll
 |
TIA Portal V19
```

## Runtime

Language:

C#

Framework:

.NET Framework 4.8

## MCP Tools

### tia.open_project

打开 TIA 项目。

### tia.list_blocks

返回：

```
OB1
FB10
DB20
```

### tia.export_block

输入：

```
FB20
```

输出：

```
FB20.xml
```

### tia.get_hardware

返回：

- CPU
- IO
- Network

## Security

要求：

- Windows 用户加入 Siemens TIA Openness Group
- 操作授权
- 审计日志
