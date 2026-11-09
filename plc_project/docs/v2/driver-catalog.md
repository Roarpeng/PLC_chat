# WP-02 · DriverCatalog 与四类标准元件（离线内核）

> 证据等级：**offline**。本文所有结论来自纯函数/契约测试，不涉及 TIA Portal 真机。
> 实现位置：`plc_engine/components/`，模板 `plc_engine/components/templates/*.json`。

## 1. 设计边界

- `ComponentDefinition`：`id` 稳定不可变、`name` 可改展示名；`io_bindings` 默认 `null`（unbound）。
- `DriverSpec`：强类型 typed ports、参数、状态机、超时、故障策略、编译模式、SafetyPermit。
- **绝不编造物理地址**：Greenfield 下任何 `%I/%Q` 都只有在 `source=imported` 时才合法；`DriverSpec.assert_no_fictional_address()` 与 `validate_driver_spec()` 双重 fail-closed。
- 正式 LBC 与 self-contained 编译模式通过 `compile_mode` 显式区分：`official_lbc` 只引用官方库块（不生成实现体），`self_contained` 生成本地 FB 接口与 SCL 存根。

## 2. 四类模板

| component_type | driver_template | LBC | 默认 compile_mode | 关键端口 |
|---|---|---|---|---|
| `double_acting_cylinder` | 双作用气缸 | `LBC_TwoWayActuator` | `official_lbc` | CmdExtend / CmdRetract / SafetyPermit / SensorOut / SensorIn / Reset / Q_Extend / Q_Retract / Busy / Error / ErrorID |
| `single_acting_actuator` | 单作用执行器（弹簧复位） | `LBC_OneWayActuator` | `official_lbc` | CmdExtend / SafetyPermit / SensorOut / SensorIn / Reset / Q_Extend / Busy / Error |
| `di_do` | DI/DO 数字量 | `LBC_DigitalSignal` | `self_contained` | DI_Value / DO_Command / Q_Value / Error / Reset |
| `motor_starter` | 电机启停 | `LBC_MotorStarter` | `official_lbc` | CmdStart / CmdStop / SafetyPermit / FeedbackRunning / Reset / Q_Contactor / Busy / Error / ErrorID |

未命中的设备类型返回 `custom_pending`，进入问题队列，绝不猜测型号。

## 3. Driver FSM

```
IDLE --CmdExtend & SafetyPermit--> EXTENDING --SensorOut--> EXTENDED
EXTENDED --CmdRetract--> RETRACTING --SensorIn--> RETRACTED
EXTENDING / RETRACTING --timeout--> FAULT
EXTENDING / RETRACTING --SafetyPermit lost--> FAULT
FAULT --Reset--> IDLE
```

- 扫描周期由 `contracts.SCAN_CYCLE_MS = 10ms` 固定。
- `SafetyPermit` **仅为软件联锁**，不冒充安全完整性等级/急停回路（PRD 7.3）。
- 手/自动命令经唯一仲裁器 `arbitrate_mode()`，反向输出互斥（同时置位 → 双双强制为 FALSE + 告警）。
- 所有物理输出与符号映射遵守单写者；`typed_ports[].writer` 必填。

## 4. NL → 候选变更（US-1）

`gateway/app/services/plc/intent_service_v2.py`：

1. 规则表先识别实体（`气缸 / 单作用 / 电机 / 传感器 / DI-DO`）。
2. 槽位：`move_timeout_ms`（正则提取「3 秒」→ 3000）、反馈信号、元件类型。
3. 缺槽位 → `questions[]`，**不生成可执行候选、不猜测**。
4. 候选仅含结构化 `ChangeOp`（`add_component` / `add_step` / `add_transition` / `add_exception`），**不返回自由 SCL、不写 IR、不写 TIA**。
5. 字段来源标注 `user_explicit / inferred / imported / library_default`。

验收示例：「一只双作用气缸、伸出/缩回限位、3 秒超时」→ `component_type=double_acting_cylinder`，`move_timeout_ms=3000`，`io_bindings=null`，typed ports 齐全，无 `%I/%Q`。

## 5. 负例清单（实际执行结果见 T03 evidence）

双线圈同时使能 · 缺超时 · 缺反馈 · 虚构 `%Q0.0` · 端口类型不一致 · 命令/反馈混用 · 单写者冲突 · 未知元件类型 · 同一模板复用于两套工艺 · SafetyPermit 丢失时命令全抑制。

## 6. 复用与不重复

- 只读复用 `plc_engine/af/*`：通过 `plc_engine/process/af_adapter_v2.py` 包装，`driver_compiler.py` 仅产出 AF 声明数据，不改 `af_generator.py` 主体。
- `DriverCatalog` 的模板是声明式 JSON（数据，不是可执行代码），`catalog_sha256()` 参与确定性留痕。
