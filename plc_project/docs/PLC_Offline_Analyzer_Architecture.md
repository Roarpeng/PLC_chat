# PLC Offline Analyzer Architecture

Version: 0.1  
Status: Architecture Design

---

# 1. Overview

## Purpose

PLC Offline Analyzer is the offline analysis engine of ResearchOS PLC Intelligence.

The goal:

> Without TIA Portal Openness, analyze PLC project files, understand control logic, convert available programs into SCL, preserve protected blocks, and generate engineering documentation.

Main capability:

```
PLC Project

    |

Project Extractor

    |

Program Parser

    |

PLC-IR

    |

AI Understanding

    |

SCL Generator + Report

```

---

# 2. Design Principles

## 2.1 Do not depend on TIA Portal

ResearchOS should support:

- With TIA Openness
- Without TIA Openness

Architecture:

```
                 ResearchOS PLC Engine


                         |

                 PLC Import Layer


          +--------------+--------------+

          |                             |

   TIA Openness Connector       Offline Analyzer


          |                             |

      .apxx Project              Export Files


          |                             |

          +--------------+--------------+

                         |

                      PLC-IR

                         |

                 Knowledge Graph

                         |

                       Agent

```

---

# 3. Input Data Sources

## Supported Input

Priority order:

## Level 1: Exported Source

Recommended.

Example:

```
PLC_Source/

├── OB1.scl
├── FB1.scl
├── FC10.scl
├── DB1.db
└── Types.xml

```

Advantages:

- Stable
- Easy parsing
- Version independent


---

## Level 2: TIA XML Export


Example:

```
FB_Motor.xml

```

Contains:

- Network
- Contact
- Coil
- FB Call
- Parameter
- Data Access


Pipeline:

```
XML

 |

Parser

 |

AST

 |

PLC-IR

```

---

## Level 3: apxx Direct Analysis


Example:

```
Machine.ap19

```

Challenges:

- Version dependency
- Internal database format
- Encryption
- Compatibility


Recommendation:

Use only as future research.


---

# 4. System Architecture


```
                PLC Project

                    |

            File Classifier

                    |

        +-----------+------------+

        |                        |

    Parseable              Protected

        |                        |

 LAD/FBD/STL/SCL          Original Backup

        |

        |

    PLC Parser

        |

        |

    PLC AST

        |

        |

    PLC-IR

        |

        |

 Knowledge Graph

        |

        |

 AI Agent


```

---

# 5. File Classification


Every block receives a status.


Example:

```json
{
 "block":"FB100",

 "language":"LAD",

 "status":"protected",

 "convert":false

}

```


Status:


|Status|Meaning|
|-|-|
|parsed|Successfully analyzed|
|converted|Generated SCL|
|protected|Keep original|
|unknown|Need manual review|


---

# 6. PLC Parser Engine


Supported languages:


## LAD

Parse:

- Contact
- Coil
- Parallel branch
- Series logic
- SET
- RESET
- Edge detection
- Timer
- Counter


Example:


LAD:

```
Start

 |

Motor

```


PLC-IR:


```json
{
"type":"assignment",

"condition":"Start",

"output":"Motor"

}

```


Generated SCL:


```scl
Motor := Start;

```

---

## FBD

Parse:

- Function block
- Connector
- Signal flow


---

## STL

Parse:

- Load
- AND
- OR
- Jump
- Assignment


Example:

```
A Start
= Motor

```


Convert:


```scl
Motor := Start;

```

---

## SCL

Direct parsing:

```
SCL

 |

AST

 |

PLC-IR

```

---

# 7. PLC Intermediate Representation


All PLC languages are converted into:


```
Source Language

      |

    PLC-IR

      |

 Target Language

```


Example:


```json
{
"network":1,

"logic":
{
"type":"AND",

"inputs":
[
"Start",
"Safety_OK"
],

"output":
"Motor_Enable"

}

}

```


---

# 8. Protected Block Handling


Industrial PLC projects may contain:


- Know-how protection
- Password protection
- Encrypted FB
- Library blocks


Processing:


```
Protected Block

        |

Detection

        |

Keep Original

        |

Create Report

```


Example:


```json
{
"name":"FB_Motion",

"status":"protected",

"conversion":"skip",

"reason":"Know-how protection"

}

```


---

# 9. AI Understanding Pipeline


```
PLC Files

    |

Structure Agent

    |

Logic Agent

    |

Process Agent

    |

Documentation Agent

    |

Engineering Report

```


Generated:


```
Machine_Control_Report.md

```

Includes:

- PLC architecture
- Program flow
- IO relationship
- Safety logic
- Motion sequence
- Risk points


---

# 10. SCL Generation


Conversion:


```
PLC-IR

 |

Template Engine

 |

SCL

```


Example:


Requirement:

```
Start AND Safety_OK controls Motor

```


Generate:


```scl
IF Start AND Safety_OK THEN

    Motor_Enable := TRUE;

END_IF;

```

---

# 11. Output Package


ResearchOS output:


```
ResearchOS_PLC_Result/


├── original/

│   └── protected_blocks/


├── converted_scl/

│   ├── OB1.scl

│   ├── FB1.scl


├── plc_ir/

│   └── project.json


├── knowledge_graph/

│   └── graph.json


├── reports/

│   ├── analysis.md

│   └── conversion_report.json


```

---

# 12. Conversion Report


Example:


```json
{

"total_blocks":120,

"converted":96,

"protected":18,

"failed":6

}

```

---

# 13. ResearchOS Module Design


Recommended structure:


```
plc_intelligence/


├── importer

│
├── offline_analyzer

│
├── tia_connector

│
├── parsers

│   ├── lad

│   ├── fbd

│   ├── stl

│   └── scl


├── plc_ir

│
├── converter

│
├── graph_builder

│
└── report_agent

```

---

# 14. Development Roadmap


## Phase 1

Input:

```
SCL/STL/XML

```

Output:

```
AI analysis report

```


---

## Phase 2

Implement:

- LAD parser
- PLC-IR
- Knowledge Graph


---

## Phase 3

Implement:

- SCL generation
- Conversion report


---

## Phase 4

Add:

- TIA Openness Connector
- Automatic project update


---

# 15. Final Goal


ResearchOS becomes:


```
Industrial AI Engineer


PLC Understanding

+

Program Migration

+

Logic Review

+

Automatic Documentation

+

Engineering Assistant

```


Core asset:

```
PLC Semantic Model

not

simple code conversion

```

# 16. Implementation Status (ResearchOS)

Aligned entry point for the user contract **「提供 .apxx → 解析 → 逻辑理解 → SCL」**:

```
researchos-tia-cli --project Machine.ap19 --result-dir .\ResearchOS_PLC_Result
```

| Layer | Status |
|-------|--------|
| Level 1/2 export folder offline parse | **Implemented** (`agents/plc/tia`) |
| Level 3 `.apxx` via Openness auto-export | **Implemented** (`importer` + `ExportProject.ps1`) |
| Level 3 pure binary `.apxx` without TIA | Not supported (encrypted internal DB) |
| PLC-IR + Knowledge Graph + SCL | **Implemented** |
| `ResearchOS_PLC_Result` package | **Implemented** (`package.py`) — includes `reports/coverage.json` |
| Block status parsed/converted/protected/interface_only/unknown | **Implemented** |
| LAD Part coverage (TON/CTU/Move/Set-Reset/compare/jump/Call ENO) | **Implemented** (leftovers named `TODO[Part]`) |
| Native SCL passthrough / STL A-AN-O-ON-=-S-R-CU-TON / GRAPH steps | **Implemented** (GRAPH is commented sequence, not executable) |
| Safety F-block flag | **Implemented** (`Block.is_safety`, never mixed into standard OB scan) |
| Chat evidence citations | **Implemented** (`chat_retrieve.answer_query_pack`) |
| HITL writeback | **Implemented** (optimize → confirm → Openness archive `.zap`) |
| Full STL rare ops / executable GRAPH / complete hardware | Remaining TODOs |

Chat cites KG edges (`CALLS`/`READS`/`WRITES`) plus SCL snippets; it does not invent CALLs.

MCP: `plc.project.analyze` (one-shot), `plc.tia.analyze` (export folder only).

---

END
