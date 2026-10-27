# 25 · Gemini 式前端重构契约(工程=容器,对话在其中,画布滑入)

## 0. 产品原则

- 默认态:纯对话全屏(Gemini 式)
- 工程是一等实体:画布/需求卡/变更账本挂在工程下,多个对话共享
- 画布按需滑入:对话触发→右侧面板展示→可全屏→ESC 返回
- 智能标签路由:对话内容自动切换画布标签
- 左侧工程栏:Gemini 式窄条,工程分组+对话列表

## 1. 数据模型(P 线)

### 服务端

```
Project(新):
  project_id: "prj-<hex12>"
  project_name: str
  canvas: dict          # 唯一权威画布(CanvasState.to_dict())
  created_at / updated_at: float
  # 不存消息

Conversation(改造 Session):
  conversation_id: "cv-<hex12>"
  project_id: str        # FK → Project
  title: str
  messages: list[ChatMessage]  # 只存消息,不存画布
  created_at / updated_at: float
```

### API

- `GET/POST /api/v1/plc/canvas/projects` → 列表(meta)/新建(含 canvas)
- `GET/PUT/DELETE /api/v1/plc/canvas/projects/{id}` → 完整/更新/删除
- `GET/POST /api/v1/plc/canvas/projects/{pid}/conversations` → 对话列表/新建
- `GET/PUT/DELETE /api/v1/plc/canvas/conversations/{cid}` → 完整/更新/删除
- 兼容:旧 `/canvas/sessions` 保留(读旧数据用,新代码不走)

### 存储结构

```
PLC_WORK_DIR/
├── projects/
│   └── <project_id>/
│       ├── meta.json       # id/name/updated_at/conversation_count
│       └── project.json    # 完整(含 canvas)
├── conversations/
│   └── <conversation_id>/
│       ├── meta.json       # id/project_id/title/updated_at
│       └── conversation.json
└── sessions/               # 旧,迁移源
```

### 前端迁移

- 启动时:检测旧 localStorage `plc-copilot.sessions.v1` → 提取画布建 Project + 消息建 Conversation → 写入新 key `plc-copilot.projects.v1` → 标记已迁移
- 服务端迁移:读旧 sessions → 建 projects/conversations → 写完成标记

## 2. 布局架构(L 线)

### 状态机

```
"chat"          → 纯对话全屏(默认)
"split"         → 对话(左) + 画布(右),可拖比例
"fullscreen"    → 画布全屏,底部薄条对话输入
```

### 画布面板

- 右侧滑入,300ms spring 动画
- 左边缘竖向图标标签栏(工业感):
  ```
  [▣] 全局图    (PlcInteractiveCanvas)
  [▤] SCL      (SclPane,含块解释/源码下钻)
  [⚡] HMI     (HMI 仿真面板)
  [⊞] 变量     (变量交叉引用)
  [⏱] 时序图   (Mermaid 渲染,对话生成的图自动流入)
  [📋] 需求卡   (RequirementCard,只读视图)
  [📋] 变更审查 (ChangeReviewDrawer 内容)
  ```
- 标签栏窄(~48px),图标+悬停 tooltip
- 内容区占满剩余宽度,组件复用(不重写)
- 可拖分隔线(chat ↔ canvas),最小 20%
- 最大化按钮 → fullscreen 态;ESC → 返回 split

### 智能标签路由规则

| 触发 | 切换到 | 附加动作 |
|---|---|---|
| AI 回答含块名引用 | SCL | setSelectedBlock(第一个引用块) |
| Mermaid 生成完成 | 时序图 | 渲染最新 Mermaid |
| 逻辑块生成/修改 | 全局图 | 高亮 draft 块 |
| 用户问变量/交叉引用 | 变量 | 无 |
| HMI 控件创建 | HMI | 无 |
| 回写确认弹窗 | 变更审查 | 打开最新事务 |
| Canvas 未打开时 | 自动滑入(300ms) | — |

### 对话区(不变的能力)

- ChatDock 全部现有功能保留(Markdown/Mermaid 内联/时间标签/复制/需求卡抽屉)
- 需求卡抽屉仍从对话内弹出(不进画布标签,因为它是模态交互)
- 变更记录抽屉仍从对话内弹出

## 3. 左侧工程栏(S 线)

### 结构

```
┌─────────────┐
│ PLC Co-Pilot│  ← 顶部 logo/标题
│ [新建工程]   │  ← 主按钮(引导:导入/对话新建)
│─────────────│
│ ▾ HR001     │  ← 工程名(展开态)
│   对话 1     │     点击切换对话
│   对话 2 ●   │     ● 当前
│   [+ 新对话] │
│─────────────│
│ ▸ 夹紧工站   │  ← 折叠态工程
│─────────────│
│ (底部)       │
│ [⇤ 折叠栏]   │  ← 折叠成图标条(~48px)
└─────────────┘
```

### 交互

- 默认宽 ~240px,可折叠成图标条(只显示工程首字/图标)
- 工程项:名称+块数 badge;悬停显示删除按钮
- 点击工程名 → 展开/折叠对话列表 + 切换活跃工程
- 「+ 新对话」→ 在当前工程下建新对话
- 「新建工程」→ 弹出引导(导入 IO/DB/项目文件 or 对话描述工艺)
- 删除工程 → 确认弹窗(警告:所有对话和画布将删除)

### 引导屏(新建工程)

无工程时主区中央显示(取代启动屏):
```
┌─────────────────────────────────┐
│      开始你的工程               │
│                                 │
│  ┌──────────┐  ┌──────────┐   │
│  │ 📥 导入   │  │ ✨ 新建   │   │
│  │ 上传 IO表 │  │ 描述工艺  │   │
│  │ DB定义    │  │ 需求      │   │
│  │ 项目文件  │  │ → 生成    │   │
│  └──────────┘  └──────────┘   │
└─────────────────────────────────┘
```

## 4. 文件归属

### P 线(数据模型)
- 新: gateway/app/services/plc/project_store.py
- 改: gateway/app/routers/plc.py(追加 projects/conversations 路由)
- 新: tests/unit/test_project_store.py
- 新: frontend/src/state/projects.ts(前端 Project/Conversation 类型+API)
- 新: frontend/src/state/projects.test.ts
- 新: frontend/src/state/migration.ts(旧→新迁移)
- 新: frontend/src/state/migration.test.ts

### L 线(布局+画布+路由)
- 改: frontend/src/App.tsx(核心:布局状态机+画布挂载)
- 新: frontend/src/shell/WorkspacePanel.tsx(画布面板+标签栏)
- 新: frontend/src/shell/WorkspacePanel.css
- 新: frontend/src/shell/smartRoute.ts(智能标签路由规则)
- 新: frontend/src/shell/smartRoute.test.ts

### S 线(工程栏+引导)
- 新: frontend/src/shell/ProjectSidebar.tsx(左侧工程栏)
- 新: frontend/src/shell/ProjectSidebar.css
- 新: frontend/src/shell/OnboardingScreen.tsx(引导屏)
- 新: frontend/src/shell/OnboardingScreen.css

### 三线都不碰的
- ChatDock.tsx(P 线可改类型引用,L 线不改)
- 现有画布/SCL/HMI/变量组件(只 import,不修改)
- 后端 services 除 project_store 外
