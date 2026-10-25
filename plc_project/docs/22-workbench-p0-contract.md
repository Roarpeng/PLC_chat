# 22 · 工作台 P0 三线并行契约(Phase1+2+3)

依据:docs/PLC_chat.html(工作台规范)+ docs/21(差距与计划)。三方(F1 前端主域/F2 前端组件域/B 后端域)唯一依据;**App.tsx 仅 F1 可改**。

## 1. ProcessRequirement 对象(B 交付存储,F2/F1 消费)

```json
{
  "requirement_id": "req-<hex12>",
  "project_name": "HR001_PLC_20260509",
  "created_at": 1790000000.0, "updated_at": 1790000000.0,
  "confirmation_status": "proposed|confirmed|rejected",
  "intent_summary": "一句话工艺意图",
  "items": [
    {"id":"it-1","kind":"precondition|sequence|exception|constraint|acceptance",
     "text":"工件到位、自动模式有效","source":"engineering|user|inferred","source_ref":"FB5002 NW1"}
  ],
  "open_questions": ["夹紧超时时间取多少?(必须工程师确认)"],
  "linked_blocks": ["FB5002_SafetyDoorV1"], "linked_signals": [],
  "task_kind": "understand|diagnose|improve|refactor",
  "origin_prompt": "用户原始输入"
}
```

- `items` 统一七字段拆解(kind 五类 + open_questions);`source` 三态:engineering(带 source_ref)/user/inferred。
- **铁律**:confirmation_status=confirmed 仅表示工艺意图确认,**绝不触发任何 ops/写回**(前后端都不允许)。

## 2. 后端 API(B 交付,风格同 /canvas/sessions)

- `GET  /api/v1/plc/canvas/requirements` → meta 列表(id/summary/status/updated_at/task_kind)
- `GET  /api/v1/plc/canvas/requirements/{id}` → 完整对象(404 code=PLC_REQUIREMENT_NOT_FOUND)
- `PUT  /api/v1/plc/canvas/requirements/{id}` → 整对象 upsert(校验 id 正则、items 结构)
- `DELETE /api/v1/plc/canvas/requirements/{id}` → 删除
- `POST /api/v1/plc/canvas/requirements/draft` → **LLM 生成需求卡**:body `{prompt, canvas, task_kind?}`;返回按 §1 结构的**草稿**(confirmation_status=proposed,来源尽量标 engineering+块内证据,不确定一律 inferred/open_questions;超时参数等未知值**不得填数值**,进 open_questions)。LLM 未配置→400 code=LLM_NOT_CONFIGURED。
- 存储:`PLC_WORK_DIR/requirements/<id>/requirement.json`+`meta.json`(temp+rename,同 session_store 模式;10MB 上限)。

### PCEC 弱关联(B 交付,兼容优先)

- `plc_engine/pcec.py` 的 intent 增可选字段 `requirement_id`(new_change 增可选参 requirement_id="",写入 intent;缺省行为零变化);
- confirm-writeback 请求体可选 `requirement_id`,透传进事务 intent;响应不变(不强制)。

## 3. 前端组件(F2 交付,props 固定;不碰 App.tsx)

### TaskQuickBar
```tsx
export type TaskKind = "understand" | "diagnose" | "improve" | "refactor";
props: { active: TaskKind | null; onTask: (t: TaskKind) => void; }
```
四个入口按钮(理解工程/诊断问题/完善工艺逻辑/重构程序),含一句话说明 tooltip;低显著度贴顶栏下沿,学现有 tab 风格。

### RequirementCardDrawer(需求卡抽屉,核心交互)
```tsx
props: {
  open: boolean;
  requirement: Requirement | null;      // state/requirements.ts 的类型
  loading?: boolean;
  onEdit: (r: Requirement) => void;     // 工程师编辑(items/open_questions/summary)
  onConfirmIntent: (r: Requirement) => void;  // 仅确认工艺意图(按钮文案:确认工艺意图;副文案:不产生任何修改)
  onClose: () => void;
}
```
- 渲染:intent_summary(可编辑)、items 按 kind 分组(前置/序列/异常/约束/验收),每条**来源徽章**:engineering=绿·证据(可点 source_ref→onFocusRef?本层不接,仅展示 ref 文本)/user=蓝/inferred=琥珀·AI 推断;open_questions 红色待确认区;
- 底部主按钮「确认工艺意图」+ 明确副文案「确认仅表示意图已确认,不会修改工程」;confirmed 后徽章化展示状态。
- state/requirements.ts:类型定义 + fetchRequirements/fetchRequirement/putRequirement/deleteRequirement/requestDraft(prompt, canvas, task_kind)(走 requestPlc;404/网络错→内置示例卡 mock,标「示例」)+ vitest。

### ChangeReviewDrawer(四层变更审查)
```tsx
props: {
  open: boolean; changeId: string | null;
  requirement?: Requirement | null;     // change.intent.requirement_id 命中时由 F1 传入
  onFocusTarget: (t: { blockName?: string; varName?: string }) => void;  // 证据定位回调
  onClose: () => void;
}
```
- 数据:GET /canvas/changes/{changeId}(复用 state/pcec.ts,可扩展 fetchChange 已有)+ requirement;
- 四 Tab:①工艺差异(requirement.items 摘要+确认状态;无关联显示「未关联需求」)②逻辑差异(change.impact.blocks/signals/hmi_widgets 清单,点击行→onFocusTarget)③源码差异(复用 SclDiffPreview 或最简 pre 对照:literal_scl via /blocks/{name}/source?kind=literal_scl,右栏 change 后 scl——取不到显示占位说明)④验证差异(复用 pcec.ts V 工具渲染四态+detail.diagnostics)。
- 全部 mock-first:changes/requirements API 不可用时显示内置示例并标注。

## 4. F1(App.tsx 主域)

- **启动态**:无活跃会话(canvas.blocks 空)且历史为空时,主区呈现 ProjectLaunchScreen(新组件,F1 自建):「继续最近项目(最近 3 个会话卡片,点击=选中会话)/ 导入工程(触发现有导入)/ 从工艺需求开始(打开需求卡抽屉的草稿态)」;有历史时保持现有空白画布+引导。
- **工程概览头**(WorkbenchHeader,F1 自建):活跃项目时顶栏下沿常驻一条:项目名 · CPU/PLC 名(canvas.source.plc_name 或 —) · TIA 版本 · 基线指纹(调 GET /canvas/changes 最新?开销大——改为:有 source 时调 workspace 元信息?**简化**:显示 project_path 存在性+块/变量/标签计数(由 canvas 即时统计)+最近会话更新时间;基线指纹复用确认弹窗逻辑不动)。
- **挂载 F2 组件**:TaskQuickBar(active 状态存 App)、RequirementCardDrawer(open/requirement/loading,接 requirements state;onConfirmIntent→PUT confirmed)、ChangeReviewDrawer(从变更记录抽屉条目点「审查」打开,onFocusTarget→setSelectedBlockName+focus)。
- **任务流接线**:onTask("improve")→聚焦输入框并预填任务前缀提示(不改后端);ChatDock 输入保持自由文本;"从工艺需求开始/完善逻辑任务"→打开需求卡草稿流:调 requestDraft(当前输入或空)。
- **需求卡与变更关联**:confirm-writeback 请求体带当前已确认需求的 requirement_id(若有)。

## 5. 验收与测试义务

- B:store CRUD/校验/坏文件、draft 端点(mock LLM:来源标注结构、未知值进 open_questions、未配置 400)、PCEC requirement_id 兼容(缺省不变)。
- F2:组件渲染/三态徽章/确认按钮不产生 ops 调用(mock 断言)、mock 回退、四 Tab 数据映射。
- F1:启动态三入口、概览头统计、挂载后不破坏现有(全量前端测试)。
- 收口(我):全量 514+100、浏览器手动链路(导入→任务→需求卡→确认→回写→变更记录→审查四层)、提交。

## 6. 边界

复用优先:不新建平行状态源;requirements/changes 均后端权威;App.tsx 仅 F1;F2/B 不碰彼此;禁 git;禁服务重启(收口统一);禁 PLC 下载/自动写回(规范红线)。
