# PLC Agent Tool API Design

Version: 0.1

## 1. Purpose

Define interfaces between ResearchOS Agents and PLC Intelligence Engine.

Architecture:

```
Agent
 |
Tool API
 |
PLC Intelligence Engine
 |
TIA Project
```

---

# 2. Tool Categories

## Project Tools

### plc.load_project

Load TIA project.

Input:

```json
{
 "path":"project.ap19"
}
```

Output:

```json
{
 "project_id":"PLC001"
}
```

---

## Analysis Tools

### plc.analyze_block

Analyze PLC block.

Input:

```json
{
 "block":"FB_Motor"
}
```

Output:

- logic summary
- IO relation
- risk analysis

---

## Knowledge Tools

### plc.query_graph

Query PLC knowledge graph.

Example:

```
Find all conditions preventing Motor_Enable
```

---

## Generation Tools

### plc.generate_scl

Generate SCL from PLC-IR.

Input:

```json
{
 "ir":"network.json"
}
```

Output:

```scl
IF Start AND Safety_OK THEN
 Motor_Enable:=TRUE;
END_IF;
```

---

## Review Tools

### plc.review_program

Checks:

- safety
- reliability
- maintainability
- coding standard

---

# 3. Agent Workflow

```
User Requirement
      |
Planning Agent
      |
PLC Design Agent
      |
PLC-IR Generator
      |
SCL Generator
      |
Review Agent
      |
TIA Import
```

---

# 4. MCP Compatibility

Recommended exposure:

```
ResearchOS MCP Server
        |
PLC Tools
        |
TIA Connector
```

Allows:

- Claude
- ChatGPT
- Local LLM
- Cursor

calling PLC engineering functions.

---

# 5. Security Rules

Before writing PLC:

1. Generate diff.
2. Validate logic.
3. Require approval.
4. Export backup.
5. Compile test.

---

# 6. Future Extensions

- Automatic PLC testing
- Simulation integration
- Digital twin connection
- Robot/AGV coordination
