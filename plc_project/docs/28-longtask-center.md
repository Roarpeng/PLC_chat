# LongTaskCenter 统一长任务中心 · 对话体验线收尾记录

范围：2026-11-03 用户实测反馈驱动的六项前端修复/特性（`4791e99` → `f40cdcc`），
终态为 LongTaskCenter——长任务期间自由对话、页面级"进行中"指示、任务进度。
关联：`docs/26-v3_0-progress-audit.md`（审计）、`docs/25-gemini-refactor-contract.md`（P 线契约）。

## 0. 需求与决策点（用户确认）

1. 长任务（重构/逻辑分析/编译…）在当前对话运行时**可以接着对话**；
2. 页面必须有**"进行中、未完成"的明确表示**（任何布局可见）；
3. 有**任务进度**（阶段/计时）。

决策点：① 长任务跨会话继续跑、结果写回所属会话（不再切会话即中止）；② 编辑类指令
（改画布的 ops）全局串行，问答/分析/流水线并行。

## 1. 本线六次提交

| 提交 | 内容 | 真机验证要点 |
| --- | --- | --- |
| `4791e99` | **P 线接线 + 流水线进度卡**：App 里 createProject/fetchProjects 原是死接线 → 启动水合/导入新建即注册工程+首对话/侧栏选中水合/画布防抖回写（putProject+putConversation）；修复水合竞态（setSessions 异步后闭包 find 落空静默）；ChatDock 首版五阶段进度卡 | 导入 2 块工程 → 侧栏即现工程树+嵌套对话；「重构 不要编译」进度卡实时走完 |
| `783354c` | **编译/重构期间可提问**：isSubmitting 被长任务全程占住致"无法发送且无反应" → 重构分支后台化、回写摘锁（防重入独立 ref）、画布脏守卫×3（编译完成/fix-loop/流水线完成不自动覆盖期间新修改） | 流水线运行中 300ms 内连发提问：按钮未禁用、消息上屏、LLM 正常回答 |
| `fa4eed7` | **历史会话可进入 + 1970 时间修正**：P 线对话是空壳（消息从不回写）→ 启动即调 /canvas/projects/migrate（沿用原 session id，本地同 id 会话点开即命中）+ commitSession 防抖同步消息 + 注册即写首批消息；时间戳秒/毫秒混杂 → 读侧 tsMs 归一（工程/对话/消息 ts） | 刷新后侧栏现完整工程树（legacy 迁移入列）、无 1970、点对话 8 条历史消息上屏 |
| `f18e738` | **侧栏对话一键删除**：悬停垃圾桶+确认弹窗（复用工程删除交互）；服务端对话+映射本地会话+legacy 通道一起清；删活跃会话复位空白态；计数扣减 | 悬停出钮 → 弹窗带对话名 → 行数 5→4、服务端 conversation_count 真实下降 |
| `f40cdcc` | **LongTaskCenter**（见 §2） | 三场景：芯片+分析条+跨会话标注/跳回 |

## 2. LongTaskCenter 架构

```
顶栏（任何布局可见）  [● 重构流水线 2:41] [● AI 分析 0:01·其他会话] [+N]
                      点击 → 跳回所属会话 + 滚动到锚定消息(data-mid)
对话坞输入行上方       阶段卡(重构/编译共用)：·进行中/已结束/出错 + 阶段芯片 + detail
                      分析细条(llm_answer)：脉冲圆点 + "AI 分析中" + 计时
浏览器标签            ● 重构流水线进行中 — PLC Co-Pilot
```

- **契约层** `state/longTasks.ts`：`LongTask{ id,sessionId,kind:refactor_pipeline|compile|llm_answer,
  status:running|done|error, stages?,detail?,messageId?,errorText? }` + 纯函数
  （active/bySession/forOtherSessions/upsert/patch/finish/sweepFinished/topbarChips/
  overflowCount/formatElapsed），19 单测。
- **采集**：重构流水线（paintCard→patch stages）、编译（pollCompileJob 增 onProgress 回调刷
  detail）、AI 分析（问题分支登记，LLM 判编辑类即收 error 态转编辑链）。
- **handleSend 全后台化**：消息落账即释放输入锁，处理链 `runSendFlow` 后台跑——多条消息并行；
  编辑 ops 段 `opsBusyRef` 全局串行，占用时 settle 明确提示。`settle` 定义随迁。
- **跨会话语义**：`commitSessionFor(sessionId,…)` 写回任务所属会话（会话已删则静默）；切会话/
  新建不再 abort（abort 仅保留页面卸载）；删除会话时其运行中任务收 error"会话已删除"；
  编译结果消息/画布按会话感知落盘（脏守卫保持）。
- **生命周期**：终态保留 2.5s（绿色收尾）→ sweepFinished 清除；标签标题跟随首个运行中任务。

## 3. 验证凭据（E2E 走查记录）

- 芯片：重构中 `重构流水线 0:00` 计时跳动；双任务并存（CHIPS_COUNT=2）；收敛后消失
- 分析条：`AI 分析中 0:01`，回答落屏（"共 2 个逻辑块…"）
- 跨会话：切「新对话」→ 芯片带「其他会话」；点击跳回原工程（workbench-header 恢复 e2e_export）
- 门检：tsc 0 错；vitest 242（+19）；taste lint 0 FAIL（few-pictures 为"无照片线稿"用户豁免项）

## 4. 已知边界

- 后台任务完成写回非当前会话时只更新该会话消息与画布快照，不弹打扰性通知（顶栏绿色收尾即提示）。
- 编译任务的阶段视图目前为文本 detail（编译作业无独立 stages 结构），阶段卡以"启动中简化卡+detail"呈现。
- 删除工程（服务端级联删对话）不回收本地会话的运行中任务标记，依赖 2.5s sweep 自然清除。
- ops 串行锁为进程内单实例语义；多标签页并发编辑同一工程仍依赖 P 线服务端画布为权威合并点。
