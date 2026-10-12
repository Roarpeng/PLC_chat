# PLC Knowledge Graph Model

Version: 0.1

## 1. Purpose

PLC Knowledge Graph converts PLC code into industrial semantic knowledge.

Goal:

```
PLC Code
   |
Semantic Extraction
   |
Knowledge Graph
   |
AI Reasoning
```

---

# 2. Graph Database

Recommended:

- Neo4j
- Graphiti

---

# 3. Entity Model

## PLC

Attributes:

```
name
vendor
version
cpu
```

## Block

```
FB
FC
DB
OB
```

## Variable

```
name
type
address
data_source
```

## Device

```
Sensor
Motor
Servo
Robot
Valve
Cylinder
AGV
```

---

# 4. Relationships

```
PLC
 |
contains
 |
Block
 |
uses
 |
Variable
 |
controls
 |
Device
```

---

# 5. Example

```
Door_Sensor
      |
      detects
      |
Safety_FB
      |
      enables
      |
Motor_Start
```

AI reasoning:

Question:

"Why motor cannot start?"

Graph traversal:

```
Motor_Start=false

-> Safety_FB=false

-> Door_Sensor=false

-> Door not closed
```

---

# 6. Knowledge Types

## Structural Knowledge

Project hierarchy.

## Logic Knowledge

Control relationships.

## Process Knowledge

Machine operation sequence.

## Diagnostic Knowledge

Fault propagation path.

---

# 7. Agent Usage

PLC Analyst Agent:

```
Graph Query
      |
LLM Reasoning
      |
Engineering Explanation
```

PLC Review Agent:

Find:

- Missing safety condition
- Dead logic
- Unused variables
- Dangerous bypass

---

# 8. Future

The graph becomes the industrial memory layer of ResearchOS.
