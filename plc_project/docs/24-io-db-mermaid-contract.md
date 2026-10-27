# 24 · IO 表/DB/Mermaid 时序图四线契约

## 数据格式(用户实测样本)

**IO 表(PLCTags.xlsx)**: 列 = Name, Path, Data Type, Logical Address(%I2.0), Comment
**DB SCL 文本**: `DATA_BLOCK "DB1900_..." { S7_Optimized_Access } STRUCT ... END_STRUCT BEGIN 赋值 END_DATA_BLOCK`

## A 线:IO 表导入(xlsx→canvas 标签)

`gateway/app/services/plc/io_import.py`:
- `parse_plctags_xlsx(path) -> list[dict]`(openpyxl 读;列名映射 Name/Logical Address/Data Type/Comment)
- `parse_plctags_csv(path) -> list[dict]`(同列名 CSV)
- `io_entries_to_canvas_tags(entries) -> dict[str, CanvasTag]`(name→CanvasTag(name,data_type,logical_address,comment,status="draft"))
- API: `POST /api/v1/plc/canvas/io/import`(body {file_path 或 file_content(csv文本), project_name}) → {tags_created, canvas}
- 写入 canvas.tags(不动 blocks)

## B 线:DB SCL 文本导入(→canvas DB 块)

`gateway/app/services/plc/db_import.py`:
- `parse_db_scl(text) -> dict`(SCL DATA_BLOCK 文本→{name, interface: [{name,data_type,comment,initial_value,section:"VAR"}], initial_assignments: {路径:值}});解析 STRUCT/END_STRUCT(嵌套→点路径如 Send.Heart)、Array[0..21] of Byte、注释 //
- `db_to_canvas_block(parsed) -> CanvasBlock`(block_type="DB", language="DB", interface, scl_body=原始文本, status="draft")
- API: `POST /api/v1/plc/canvas/db/import`(body {db_text 或 file_path, project_name}) → {blocks_created, canvas}
- 多个 DB 可多次调用

## C 线:Mermaid 时序图生成(对话→Mermaid→前端渲染)

后端 `gateway/app/services/plc/mermaid_gen.py`:
- `generate_mermaid_sequence(prompt, canvas) -> {mermaid, description}`:LLM 生成 Mermaid sequenceDiagram 文本(参与方=设备/CM,消息=动作/条件,alt/opt=异常分支);系统提示写清 Mermaid 语法
- API: `POST /api/v1/plc/canvas/mermaid/generate`(body {prompt, canvas}) → {mermaid}
前端:
- ChatDock 中 Mermaid 代码块(```mermaid)检测→渲染(引入 mermaid npm 包,~40KB,CDN 不引入,本地打包)
- 渲染结果可复制(导出 .md)

## D 线:Mermaid→AF 步序解析(Mermaid→AfProject 步骤)

`plc_engine/af/mermaid_parser.py`:
- `parse_mermaid_sequence(mermaid_text) -> {participants: [设备名], steps: [{seq, actor, action, condition, note}], alt_branches: [{condition, steps}]}`
- `mermaid_to_af_steps(parsed, cms) -> list[AfSequenceStep]`(参与者→CM 映射;消息→action;alt→异常分支;note→注释)
- 接入 planner:`plan_from_mermaid(mermaid_text, project_name) -> AfProject`(复用 _classify_cm_type + _build_default_steps_for_cms 兜底)
- API: `POST /api/v1/plc/canvas/generate-from-mermaid`(body {mermaid, project_name}) → {canvas, blocks_created}
