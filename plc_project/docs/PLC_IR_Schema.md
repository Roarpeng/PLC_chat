# PLC Intermediate Representation (PLC-IR) Schema

Version: 0.1

## 1. Purpose

PLC-IR is the semantic intermediate layer between PLC languages and AI reasoning.

Supported conversion:

```
LAD / FBD / STL / SCL
          |
       PLC-IR
          |
 SCL / LAD / Documentation / Test
```

PLC-IR is not source code. It describes control intent.

---

# 2. Core Object Model

```json
{
 "project":{},
 "blocks":[],
 "signals":[],
 "networks":[],
 "sequences":[],
 "devices":[]
}
```

---

# 3. Block Schema

```json
{
 "id":"FB_Motor_Control",
 "type":"FB",
 "language":"LAD",
 "purpose":"Motor sequence control",
 "inputs":[],
 "outputs":[],
 "logic":[]
}
```

---

# 4. Logic Node

Universal logic representation:

```json
{
 "node":"AND",
 "inputs":[
  "Start",
  "Safety_OK"
 ],
 "output":"Motor_Enable"
}
```

Supported operators:

- AND
- OR
- NOT
- XOR
- SET
- RESET
- MOVE
- COMPARE
- TIMER
- COUNTER
- FB_CALL

---

# 5. Motion Object

For Siemens Motion Control:

```json
{
 "function":"MC_MoveAbsolute",
 "axis":"Axis_X",
 "position":100,
 "velocity":50,
 "execute":"Move_Request"
}
```

---

# 6. Sequence Model

Industrial state machine:

```json
{
 "name":"Axis_Homing",
 "states":[
  "Start",
  "SearchSensor",
  "Retract",
  "SetZero",
  "Done"
 ]
}
```

---

# 7. Design Rules

1. Preserve original PLC behavior.
2. Separate logic and implementation.
3. Make every signal traceable.
4. Support AI reasoning.
5. Support code generation.

---

# 8. Future Extension

PLC-IR will become the foundation for:

- Automatic PLC refactoring
- Digital twin generation
- Simulation test generation
- Industrial Copilot
