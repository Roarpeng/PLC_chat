# PLC Intermediate Representation

## Purpose

建立统一 PLC 逻辑中间层。

支持：

- Siemens LAD
- Codesys FBD
- Rockwell Ladder

转换到统一语义模型。

## Example

Ladder:

```
Start AND Safety -> Motor
```

PLC-IR:

```json
{
  "type": "LogicBlock",
  "operation": "AND",
  "inputs": ["Start", "Safety"],
  "output": "Motor"
}
```

## Node Categories

### Logic

- AND
- OR
- NOT

### Motion

- MOVE
- HOME
- STOP

### Timer

- TON
- TOF

### Compare

- GT
- LT
- EQ
