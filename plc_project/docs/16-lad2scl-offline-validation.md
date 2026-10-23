# 16 · LAD→SCL 静默转换 · 真实导出数据离线验证报告

- 验证日期:2026-10-23
- 验证人:Agent C(验证线,只读验证,未改任何管线代码)
- 对象:`agents/plc/tia/pipeline.py::analyze_tia_exports`(SimaticML 提取 → flgnet_fold 折叠 → convert_project_to_scl)
- 结论速览:**管线能跑通全量真实数据(2.8 s / 89 块 / 410 网络),调用类与简单 OR 归约网络等价;但 LAD 逻辑网络的 SCL 输出存在 5 类系统性缺陷(语句错位丢失、伪环注释注入、TypedConstant 空字面量、引脚取反丢失、箱体 Q/.pre 驱动丢失),抽样等价率仅 2/9 完全等价,当前 SCL 不可直接回灌 TIA。**

---

## 1. 数据来源(实际路径与规模)

| 项 | 值 |
|---|---|
| 主数据集 | `C:\Users\vboxuser\Desktop\Project\Code\PLC_chat\PLC_Openness_data\hr001\export\`(真实 TIA Portal V19 Openness 导出,DocumentInfo 时间 2026-10-21,项目 HR001_PLC_20260509.zap19) |
| 块 XML | `export\plc\CPU_1200\blocks\` 共 **85 个**块导出文件 + 2 个 PLC 标签表 + HMI 标签/脚本 |
| 块语言分布 | **LAD 40 / SCL 15 / DB 30**(按 `<ProgrammingLanguage>` 逐文件统计;含 FlgNet 网络体的文件 29 个) |
| 备选目录 | `PLC_Openness_data\openness_e2e\`:只有 HMI 标签表导出(`hmi_unified_export/plc/PLC_1/tags/默认变量表.xml`),**无块 XML**,不适合本验证,未采用 |
| 本仓库缓存 | `plc_project\.researchos\plc_export_cache\<hash>\` 为 hr001 同一导出的缓存副本(块集相同),未重复使用 |
| 测试夹具 | `plc_project\tests\fixtures\tia_exports\Blocks`(FB_Motor/Main_OB1/DB_MotorInst,手工小样本)——任务要求真实导出,未采用 |
| HR002 | git 历史提及(72 块真实 TIA),**本机未找到 HR002 导出目录**,如实记为 pending |

## 2. 管线调用方式与整体结果

调用(CLI 入口 `agents/plc/cli.py`,离线 `--exports` 路径):

```
plc_project\.venv\Scripts\python.exe -m agents.plc.cli \
  --exports C:\...\PLC_Openness_data\hr001\export \
  --result-dir plc_project\tmp_validate\hr001_result --json-summary
```

- 环境:Python 3.14.2(venv),退出码 0,**耗时 2.79 s**
- 结果包:`plc_project\tmp_validate\hr001_result\`(converted_scl/ 54 个 .scl、plc_ir/project.json、knowledge_graph/graph.json、reports/*)

整体数字(reports/conversion_report.json):

| 指标 | 值 | 说明 |
|---|---|---|
| 识别块总数 | **89** | 85 XML + 4 UDT(嵌入解析)|
| converted | 30 | SCL 生成且无 TODO(含 13 个 DB、4 个 UDT、9 个 LAD、4 个原生 SCL)|
| parsed | 24 | SCL 生成但含 TODO(**全部为 LAD 块**)|
| interface_only | 18 | 体未导出(库/知识保护),只解析接口 |
| failed(unknown) | 17 | 全部为实例 DB(`_is_instance_db` 按设计跳过,不回灌重建)|
| 网络总数 | 410 | |
| TODO 标记 | 581(todo_rate 10.45%)| **其中约 368 处为纯噪声(见 §4-9)** |
| KG | 3774 节点 / 5129 边 | |
| 报错/跳过清单 | 无运行时异常 | 跳过=17 实例 DB + 18 接口-only(原因字段逐块记录在 conversion_report.json)|

LAD 40 块明细:9 converted + 24 parsed + 7 interface_only。**37 个 LAD 衍生 SCL 文件中,仅 12 个不含本报告追踪的缺陷模式**,且这 12 个多为单网络 OB / 纯调用块。

## 3. 等价性抽样(核心)

方法:从 FlgNet 的 Parts/Wires 手工推导期望布尔表达式/SCL 语句,与结果包 `converted_scl/*.scl` 及内部 folded_logic 逐条比对。抽样 6 块 9 个判定点,覆盖任务要求的三类模式。

### 3.1 判定总表

| 块 | 网络 | 模式 | 手工推导(期望) | 生成的 SCL 语句(实际) | 判定 |
|---|---|---|---|---|---|
| FB1040_HomePos | 12 | 并联 OR 归约 | `#MainStep.End := #MainStep.S17 OR #MainStep.ErrEnd;` | 同左(外加一行无害 `(* TODO[O] *)` 噪声注释) | **✓** |
| OB1Main | 1–15 | FB 调用+参数 | 实例 DB 调用,如 `"DB1010_Parameter"(IMaxProgNo := 300);` | 同左,15 个网络调用/参数全部正确 | **✓** |
| FB5002_SafetyDoorV1 | 4 | 比较器 Ne | `#AtDoorUnLock <> 0` 驱动双线圈 | `IF (#AtDoorUnLock <> 0) THEN … := TRUE; ELSE … := FALSE; END_IF;` 比较器本体正确;但同网 `"TRUE"` 被渲染为引号标识符 | **部分** |
| FB1060_AutoStep | 1 | 比较器 Eq+MOVE | `IF PosNoClear OR ClearHoleNoReq OR (gi_ToolTypeNo=2 AND ChangeTool) THEN #Aux.HoleNo := 0;`(Eq93 还应 AND ClearHoleNoReq) | Eq86 本体 `(gi_ToolTypeNo = 2)` ✓;但 Eq93 的 `.pre` 前置 RLO(ClearHoleNoReq)丢失 → 比较变无条件 | **部分** |
| FB2009_CoolingFanFunction | 1 | SR 自锁+互锁+CoilTON | ①`#Timer_StationToolOn.TON(IN:=Auto AND T1 AND T2, PT:=T#2s);` ②`#SR_StationTool.SR(S:=Ton.Q, R1:= NOT(T1) OR NOT(T2) OR Fan.Q OR Man OR Emm);` ③`ToolAtPos := SR.Q` ④`#Timer_StationCoolingFan.TON(IN:=SR.Q, PT:=#CoolingTime);` | `TODO[CoilTON]×2` + `#Timer_StationToolOn.TON(IN:=…, PT := );`(PT 空,语法非法)+ `Sr();`(SR 参数与实例全丢)——**coil ③ 与 TON ④ 整条丢失** | **✗** |
| FB5002_SafetyDoorV1 | 1 | 启保停(OR 自锁)+取反触点 | `start := i_DoorOverRide AND NOT(EMMode) AND NOT(i_AutoRunning) AND i_OpenDoorPmt;` `Aux.DT2 := start AND (PS10 OR Aux.DT2) AND Aux.DT1;` | 取反全部丢失(EMMode/i_AutoRunning 变正逻辑,**极性反转**);共享支路被 `(* loop guard *)` 替换(**语法非法+条件丢失**) | **✗** |
| FB1040_HomePos | 7 | CoilTON×3 + Gt 比较 + MOVE | 3 条 TON 调用(PT=T#常量)+ 若干 Set 线圈 + `ProgNo:=255`(EN=SCoil 输出 RLO) | TON 的 IN 折叠正确(含 `Current_2 > CurrentMaxLimit` 比较器 ✓)但 `PT := )` 空;**4 条语句静默丢失**(EdgeDetc.JUMP 置位、ProgStart、BitStuckErr_HighCurrent、MainStep.S6 自锁);`ProgNo := 255` 变无条件(EN 丢失) | **✗** |
| FB1060_AutoStep | 1 | IEC TON box | `"Timer_RecvEmmMode".TON? (IN:=TRUE AND EmmMode, PT:=T#…); IF Timer.Q THEN Send.PowerOff:=TRUE` | `"Timer_RecvEmmMode"(IN := …, PT := );`(PT 空)+ `"Send.PowerOff" := TRUE;` **无条件置位(TON.Q 驱动丢失,上电即常置位)** | **✗** |
| FC2300 Time Calculation | 5 | Mul/Add 数学框 | `IF #High THEN #Temp_PLC_Minute := MINUTE*64; END_IF;` `TimeWord2 := Temp_PLC_Minute + SECOND;` | 整个网络只剩 `(* TODO[Mul] *)`、`(* TODO[Add] *)` 两条注释——**fold 已算对但 translate 全部丢弃,计算逻辑整体丢失** | **✗** |

**抽样通过率:✓ 2 / 部分 2 / ✗ 5(9 个判定点;完全等价 22%)。**

### 3.2 逐块补充说明

**FB2009 网络 1(最典型的复合样例)** —— FlgNet 实测:Contact35→36→37 串联驱动 CoilTON38(Timer_StationToolOn, T#2s),其 out 驱动 Sr45 的 s 脚;NegContact39/40+Contact41/42/43 五支路进 O44(Card=5)驱动 r1;Sr45.q 同时驱动 Coil46(ToolAtPos)与 CoilTON47。fold() 的 folded_logic 里 TON38 调用语句是**正确**的(IN 链与实例都对,唯 PT 空),但 translate() 输出时:CoilTON38/47 不在消费分支→只发 TODO;Sr45(BOX)分支 `next()` 拿到的是 TON38 的语句→错位发出;Coil46 拿到的是 Sr45 的 `Sr();`(空参数,因 `_fold_box_call` 不读 operand 脚引脚、s/r1 小写脚不匹配);CoilTON47 的语句无人消费→丢弃。

**FB1040 网络 7 错位账目**:fold 23 条 → translate 实际发出 20 条:3 条 TON 语句被后续 SCoil 错位"借用"、Move105/106 消费到 kind!=move 的语句将其**静默丢弃**后走 `_emit_move` 兜底(凑巧恢复了 2 条)、**净丢失 4 条**(EdgeDetc.JUMP、ProgStart、BitStuckErr_HighCurrent、MainStep.S6 自锁保持——后者是步序链状态机的保持条件,丢失即步进逻辑断裂)。

**FB5002 网络 1 手工推导依据**:Wire59 把 Contact38.out 扇出到 5 个下游,Sr 式自锁 = `(start AND PS10) OR (start AND Aux.DT2)` 再 AND Aux.DT1;生成式第二支路变成 `((* loop guard *) AND #i_OpenDoorPmt) AND #Aux.DT2`——`_visited` 在评估第一支路时已标记 Contact38.in,第二支路复用同一链即被判"环"。

## 4. 问题清单(按严重度)

**S1(严重)translate() 折叠语句迭代器错位 → 语句丢失/张冠李戴**
`scl.py::NetworkTranslator.translate()` 用 `iter(network.folded.statements)` 顺序消费,但 fold() 产出语句的部件种类(CoilTON、SYS_TIME、T_CONV、全部数学框)不在 translate 的消费分支里:这些部件只发 TODO、不消费;后续 COIL/MOVE 消费者就拿到别人的语句,或把 kind 不符的语句**静默丢弃**。全量统计:TODO[CoilTON] 44、数学框 TODO 约 127(Add37/Swap32/Calc22/Sub18/Mul13/Div5/Mod5/Abs1)、SYS_TIME 3、T_CONV 2 处,涉及 11–16 个文件。实证:FB1040 net7 丢 4 条、FB2009 net1 丢 2 条、FC2300 net5 整网丢失。

**S2(严重)伪环守卫把 DAG 共享支路注释掉 → 语法非法 + 条件丢失**
`flgnet_fold._visited` 只加不删(非调用栈),同一触点链扇出到同一门的多个输入时,第二支路被替换为 `Lit("(* loop guard *)")` 并**嵌入表达式内部**。`(* … *)` 是 SCL 注释,出现在操作数位置直接语法错误。**17 个 SCL 文件**含此模式;FB1060 net1 甚至出现 `((* loop guard *) OR (* loop guard *))` 整支路报废。启保停/互锁电路(共享链+自锁)是重灾区。

**S3(严重)TypedConstant 作用域未映射 → `PT := )` 空字面量**
`simaticml.parse_access` 只认 `Scope="Constant"/"LiteralConstant"`,TIA V19 导出的定时器 PT 常量用的是 `Scope="TypedConstant"` → scope=UNKNOWN、as_scl()="" → 所有 CoilTON/TON 的 `PT := ` 为空。**12 个文件**。FB1040 net7 三条 TON 全中。同因:`"TRUE"` 常量触点(GlobalVariable 名叫 TRUE 的 Symbol)被渲染为引号标识符 `"TRUE"`(19 文件)。

**S4(严重)FlgNet 引脚级取反 `<Negated Name="operand"/>` 未解析 → 极性反转**
解析器只处理 `Attribute Name="Negated"`(带文本 true),而 FlgNet 的取反是**子元素** `<Negated Name="operand"/>`,`part.negated` 恒 False → NOT 丢失。FB5002 net1 实证:NOT(EMMode)、NOT(i_AutoRunning) 均变正逻辑。

**S5(高)箱体输出脚(Q/ET/CV)与 S/R 线圈输出不算 RLO 驱动 → 下游条件丢失**
`_wire_driver_exprs` 只认 namecon `pin=="out"` 且部件在 RLO_OUTPUT_PARTS(触点/比较器)。TON.Q→SCoil、RCoil.out→RCoil、SCoil.out→Move.en 这三类链路全部丢条件。实证:FB1060 net1 `Send.PowerOff := TRUE;` 无条件(应 TON.Q 门控,上电常置位);FB1040 net7 `ProgNo := 255;` 无条件。

**S6(高)比较器 `.pre` 脚(前置 RLO)被忽略**
FB1060 net1:Eq93.pre ← Contact92(ClearHoleNoReq)、Eq98.pre ← O97(DrillDirection1 OR DrillDirection3)均未折叠,比较变无条件执行。

**S7(高)Convert/Mux 框 EN 丢失**
`_fold_convert` 无 EN 逻辑。FB5009 net2:`IF Cmd.Read1 THEN TP_ActualAI_1 := IW`(Int→Real)被生成为无条件 `#Ctrl_IN.TP_ActualAI_1 := #IW;`。

**S8(中)TODO 噪声夸大失败统计**
O 门(297)、PBox/NBox 沿触点(56)、Not(15)在 fold() 已正确折进下游表达式,translate() 却仍输出 `(* TODO[O] *)` 等注释(其部件分支没有像 fold() 那样 `continue`)。581 个 TODO 中约 368(63%)是噪声,直接扭曲 converted/parsed 状态划分与 coverage 指标。

**S9(中)folded_logic 中 SCL 源码网络被逐行补分号**
SCL 原文网络走 fold 的 source_text 分支时每行补 `;` → `IF #Confirm;`、`THEN;`。`.scl` 文件不受影响(translate 走原文透传),但所有消费 folded_logic 的下游(chat/图谱)拿到的是坏文本。

**S10(中)`_fold_box_call` 不读 operand 引脚 + 脚名大小写不匹配**
SR/RS/CTU 等以 `operand` 脚接实例(而非 CallInfo instance),且 s/r1/q 为小写脚名,与代码里的 "S"/"S1"/"Q" 大写白名单不匹配 → `Sr();` 空调用。

**S11(低)合理 TODO(真正未支持部件,如实保留)**
MOVE_BLK_VARIANT(9)、InRange/OutRange(7)、Shr(3)、JmpList(1)、S_Move(1)、MB_SERVER(1)——fold 与 translate 均未支持,TODO 是正确行为。

**S12(低)输出噪声**
`("TRUE" AND X)` 前缀、推断注入的 `PT/ET/IN/Q` 静态变量声明(FB2009)、`IF "TRUE" THEN` 包裹等,不影响语义但降低可读性。

**literal 直译 vs 语义化重构差异点(记录)**:简单线圈被重构为 `IF cond THEN t := TRUE; ELSE t := FALSE; END_IF;`(语义等价,工程师友好 ✓);Set/Reset 线圈重构为条件置位/复位 ✓;MOVE+EN 重构为 `IF en THEN dst := src; END_IF;`(EN 识别正确时 ✓)。这些重构本身没问题——问题都出在上游表达式/对齐层。

## 5. pending 项

1. **真实 TIA 回灌编译验证**(External Source 导入 → GenerateBlocksFromSource → ICompilable.Compile):本轮按纪律未启动 TIA Portal / Openness / devctl。修复 S1–S3 后此项才有意义(当前 17+12 个文件语法非法,必挂)。
2. **HR002(72 块)真实导出**:本机未找到,获取后复跑同一验证脚本(`tmp_validate/dump_network.py` + 本报告 §2 命令)。
3. **修复后回归重点**:CoilTON/数学框语句错位、伪环守卫、TypedConstant、Negated 元素、Q/.pre/SCoil-out 驱动、Convert EN;并复查 TODO 噪声清理后的 converted/parsed 重新分层。
4. openness_e2e 目录目前无块导出,若后续补充 CanvasE2E 块 XML 可作为第二个数据源。

## 6. 复现材料

- 运行结果包:`plc_project\tmp_validate\hr001_result\`(manifest.json / reports/conversion_report.json / converted_scl/*.scl)
- 网络级 diff 工具(一次性,未入正式目录):`plc_project\tmp_validate\dump_network.py`(块名 + 网络号 → FlgNet 结构 / fold 语句 / translate 语句三栏对照)
- CLI 原始输出:`plc_project\tmp_validate\cli_hr001_out.txt`、`cli_hr001_err.txt`

## 7. 修复后回归(2026-10-23 修复波)

三线并行修复(S1–S10)+ 收口期两个新发现修复后,同一 hr001 数据复跑验证:

### 7.1 指标前后对比

| 指标 | 修复前(§2/§4) | 修复后 | 说明 |
|---|---|---|---|
| TODO 标记 | 581(约 63% 噪声) | **23** | 剩余全部为 S11 合理 TODO(MOVE_BLK_VARIANT 9、InRange 6、Shr 3 等)+ 1 个 Word 字逻辑 Or 门(双方未支持,建议归一到 *Word 算子) |
| converted / parsed | 30 / 24 | **46 / 8** | 噪声 TODO 清零后的真实分层 |
| `(* loop guard *)` | 17 文件 | **0 文件** | S2:记忆化复用替代伪环守卫 |
| `PT := )` 空字面量 | 12 文件 | **0 文件** | S3:TypedConstant 映射 |
| `"TRUE"` 引号标识符 | 19 文件 | **0 文件** | S3:布尔常量触点 → TRUE/FALSE 字面量 |
| 取反触点解析 | 0 / 570 | **570 / 570** | S4:`<Negated>` 子元素 100% 捕获(24 文件) |
| 裸 `();` 空调用 | 2(FB5715) | **0** | 新发现:CallInfo Instance 名被 walk 吞掉 |
| SCL 原文空操作数 | 存在(FB5715) | **0** | 新发现:LocalConstant → `#名` 引用(VAR CONSTANT 已声明) |
| FB1040 net7 语句 | 23→20(丢 4) | **23→23 零丢失** | S1:按身份消费 |

### 7.2 §3.1 九个判定点复核(全部通过)

- FB1040 net12:OR 归约正确,TODO[O] 噪声消失 ✓
- OB1Main 1–15:FB 调用/参数无回归 ✓
- FB5002 net4:Ne 比较器正确,`"TRUE"` 渲染修复 ✓
- FB1060 net1(Eq+MOVE):Eq93/Eq98 的 `.pre` 前置 RLO 折入(`ClearHoleNoReq AND (#Aux.HoleNo = 0)`)✓
- FB2009 net1:四条语句完整(`#Timer_StationToolOn.TON(IN:=…, PT:=T#2s)`、`#SR_StationTool.SR(S:=…, R1:=…)`、`IF #SR_StationTool.Q THEN #ToolAtPos…`、`#Timer_StationCoolingFan.TON(IN:=#SR_StationTool.Q, PT:=#CoolingTime)`)✓
- FB5002 net1:`((#i_DoorOverRide AND NOT (#EMMode)) AND NOT (#i_AutoRunning)) AND #i_OpenDoorPmt`——极性恢复、无 loop guard ✓
- FB1040 net7:三条 TON PT 值正确(T#5S/T#100mS/T#5S);`ProgNo := 255` 恢复 S2/NOT S6/NOT DrillMemory 门控;`#MainStep.S6` 自锁保持恢复 ✓
- FB1060 net1(IEC TON):`IF "Timer_RecvEmmMode".Q THEN …Send.PowerOff := TRUE; END_IF;`——TON.Q 门控恢复 ✓
- FC2300 net5:`IF #High THEN #Temp_PLC_Minute := (…"PLC Time.MINUTE" * 64); END_IF;` 数学链恢复 ✓

**完全等价 9/9(修复前 2/9)。**

### 7.3 修复实现落点

- 解析层 `simaticml.py`/`ir.py`:S3(TypedConstant/TRUE 字面量)、S4(Negated 子元素 + negated_pins 字段)、LocalConstant 映射、CallInfo Instance 渲染
- 折叠层 `flgnet_fold.py`:S2(栈式真环检测 + 记忆化)、S5/S6/S7(箱体 Q 直通/.pre/EN)、S9(原文透传)、S10(operand 实例 + 小写脚名);`FoldStmt` 增 `part_uuid/part_name` 溯源字段(ast_trace 契约不变)
- 翻译层 `scl.py`:S1(按身份消费 + 全种类发射分支,禁止静默丢弃)、S2 字符串版、S5–S7 字符串版、S8(噪声 TODO 跳过)
- 测试:`test_tia_parse_fixes.py`(12)、`test_tia_fold_fixes.py`(13)、`test_tia_translate_fixes.py`(12);全量 `tests/unit` **463 passed**;快照基线已按改善后输出刷新

### 7.4 残留(不阻塞,记录待办)

1. S12 可读性噪声:`(TRUE AND X)` 前缀未做布尔化简(语义正确,建议后续小任务)。
2. Word 字逻辑 `Or` 门(SrcType=Word)1 处:fold/translate 均未支持,建议归一到 `*Word` 算子族。
3. 真实 TIA 回灌编译验证(§5-1):语法非法文件已清零,具备开跑条件。
4. `Move.eno → Move.en` 链(ENO≈EN 近似)未折,维持无条件。
