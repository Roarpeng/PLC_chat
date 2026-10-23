# 15 · LAD→SCL 后端静默与源码工件契约(Rev.2 计划 · 第 0 步)

日期:2026-10-23 · 状态:已定稿,后端 / 前端 / 验证三线并行实现均以本文为唯一契约。

## 1. 原则

1. **LAD→SCL 转换后端静默**:在 ingest/导入阶段自动完成(`flgnet_fold` → `scl.py` 直译),Web 前端永远只看到 SCL。
2. **原始源码按需下钻**:FlgNet XML、1:1 直译 SCL(literal)、归约追踪(ast_trace)仅存服务端文件;仅当用户在块详情显式打开「查看原始源码」时才经 API 拉取。
3. **翻译模式**:默认 literal(1:1 布尔直译,100% 等价);semantic(`scl_rewrite` 语义重构)仅为后端开关,不对前端暴露模式切换。
4. 主界面零新增元素;对比抽屉是唯一新增 UI,默认不可见,打开才加载。

## 2. 服务端工件(job 内记录 + 磁盘文件)

- job record 新增字段 `source_artifacts: dict[str, dict[str, str]]`:
  - key = 块名(FB / OB / FC…)
  - value = `{"flgnet_xml": "<路径>", "literal_scl": "<路径>", "ast_trace": "<路径>"}` —— **只存路径,不内联内容**
- 落盘位置:job 导出目录下 `_source_artifacts/<块名安全化>/{flgnet.xml, literal.scl, ast_trace.txt}`;
  `openness_export_dir` 缺省时锚定到本次 ingest 实际使用的导出根目录。
- 写入时机:ingest 管线产出 `folded_logic` / `scl_sources` 的同一阶段。
- job detail 响应中 `source_xmls` 等字段若当前向客户端内联 XML 内容,改为路径化或移除 —— 以「前端只见 SCL」为验收线。

## 3. 按需取源 API

router 前缀 `/api/v1/plc`:

```
GET /api/v1/plc/jobs/{job_id}/blocks/{block_name}/source?kind=flgnet_xml|literal_scl|ast_trace
```

- `200` → `{"job_id": "...", "block_name": "...", "kind": "...", "content": "<纯文本>"}`
- `404` → job / 块 / 工件文件不存在
- `400` → kind 非法
- 文件按需读取,不进常规 job 响应。

## 4. ast_trace 格式(服务端调试 / 下钻用)

纯文本逐行,每个网络至少一行结论 + 关键归约步骤,示例:

```
[block] FB_Motor
[net 1] Coil #q_bMotorFwd := (#i_bStartFwd OR #q_bMotorFwd) AND NOT #i_bStop
  step: UId=23.in 汇入 2 条 Wire -> 并联 OR 归约
```

## 5. 前端行为契约

- SCL 主视图不变(零改动)。
- 块详情提供低显著度「查看原始源码」入口 → 懒加载抽屉:左 FlgNet XML / 右 当前 SCL(可切换 literal_scl、ast_trace)。
- API 未就绪 / 404 时回退开发 mock(电机启保停样例),不阻塞 UI、不报错弹窗。
