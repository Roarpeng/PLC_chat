# PLC Handover Q1 — Device/Sensor Cards & Brief

工程师交接第一问：每块硬件 / 每个传感器做什么。本契约给 **M2 Brief** 与工作台「传感器」页使用。

日路径：Gateway PLC jobs + Knowledge Canvas。**不是** LangGraph Research TaskState。

权威决策：[ADR-0009](../adr/0009-plc-device-sensor-cards.md)。

## Card schema `researchos.device_sensor_card.v1`

```json
{
  "schema": "researchos.device_sensor_card.v1",
  "id": "tag:StartCmd",
  "kind": "tag",
  "symbol_name": "StartCmd",
  "address": "%I0.0",
  "comment": "HMI start pushbutton",
  "io_type": "DI",
  "data_type": "Bool",
  "tag_table": "HMI",
  "meaning_status": "cited",
  "meaning_text": "HMI start pushbutton",
  "meaning_source": "tag_comment",
  "hmi_texts": [{"device": "HMI_1", "screen": "Screen_Main", "text": ""}],
  "used_by": [
    {
      "block": "FB_Motor",
      "access": "READS",
      "network_id": "",
      "network_title": "Self-holding motor start",
      "part": ""
    }
  ],
  "hardware": null,
  "annotation": null,
  "citations": []
}
```

`kind`：`tag` | `device`。`id` = `{kind}:{symbol_name}`。

`meaning_status`：

| 值 | 何时 |
|----|------|
| `annotated` | 工程师批注非空（最高优先级） |
| `cited` | 标签注释或非空 HMI 文本 |
| `meaning_unconfirmed` | 都没有 — **`meaning_text` 必须为空**，禁止用符号名冒充含义 |

`meaning_source`：`engineer_annotation` | `tag_comment` | `hmi_text` | `none`。

`io_type`：由地址形态分类（`%I0.0`→DI，`%IW`→AI），不是工艺猜测。

## Endpoints

Base：`/api/v1/plc/jobs/{job_id}`。作业须 `status=ready`。

| Method | Path | 说明 |
|--------|------|------|
| GET | `/device-cards` | 列表。Query：`q`, `io_type`, `meaning_status`, `kind`, `limit` |
| GET | `/device-cards/{kind}/{name}` | 单卡。`name` 需 URL-encode（`#` / 空格） |
| PUT | `/device-cards/{kind}/{name}/annotation` | `{ "text", "author?" }` — 覆盖引用注释 |
| DELETE | `/device-cards/{kind}/{name}/annotation` | 清除批注，回到 cited / unconfirmed |
| GET | `/brief` | Project Brief。**必须**含下面这一段 |

## Brief section `researchos.brief.device_sensor_summary.v1`

M2 只依赖 `data.sections.device_sensor_summary`，不要扫整张 `knowledge_graph`。

```json
{
  "schema": "researchos.project_brief.v1",
  "job_id": "plc_…",
  "project_name": "MotorDemo",
  "status": "ready",
  "sections": {
    "device_sensor_summary": {
      "schema": "researchos.brief.device_sensor_summary.v1",
      "owned_by": "Q1",
      "total_cards": 4,
      "cited": 3,
      "annotated": 0,
      "meaning_unconfirmed": 1,
      "io_type_counts": {"DI": 3, "UNKNOWN": 1},
      "cards": [
        {
          "id": "tag:StartCmd",
          "kind": "tag",
          "symbol_name": "StartCmd",
          "address": "%I0.0",
          "io_type": "DI",
          "meaning_status": "cited",
          "meaning_text": "HMI start pushbutton",
          "meaning_source": "tag_comment",
          "used_by_count": 1,
          "tag_table": "HMI"
        }
      ],
      "unconfirmed_ids": ["tag:Mystery"],
      "gaps": [
        "meaning_unconfirmed: 1 cards have no cited comment, HMI text, or engineer annotation — do not invent process meaning"
      ]
    }
  },
  "notes": [
    "Q1: device/sensor cards are cited-field only; meaning_unconfirmed is explicit.",
    "Q2 run-logic and Q3 impact/SCL write-back are out of scope for this Brief."
  ],
  "card_count": 4
}
```

Q2/Q3 若要加 Brief 段：请 **additive** 增加 `sections.run_logic` / `sections.hitl`，不要改本段字段名。

## Annotation persistence

存在 `job.device_card_annotations[card_id]`。与现有 PLC job 一样是内存态；重启丢失。接口已稳定，后续可换 store。

## Out of scope (do not expect here)

- M1 export-status
- Q2 运行逻辑叙事
- Q3 影响分析 / SCL 回写
- Research graph / LangGraph TaskState
