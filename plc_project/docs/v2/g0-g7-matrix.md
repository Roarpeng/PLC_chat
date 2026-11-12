# G0–G7 闸门矩阵（Q-01 冻结口径）

> 与 `03-验收矩阵.md` §2 一致；本表为逐闸门签发视图。
> **G5 单独列为 Greenfield-only 真实 `.zap19` 归档链，当前 `pending_real_machine`，未通过、不可签署。**

| Gate | 定义 | 本期适用性 | 完成判据 | 证据等级 | 签发状态 |
|---|---|---|---|---|---|
| G0 | 版本 / TiaCapabilityManifest / CPU 模板 / AFProfile | ✅ 全量 | Schema + 真实 `status` 探测回执 + AF 档位锁定 | `V19_real`（仅探测）/ `offline` | ⚠️ 有条件：探测回执取得，CPU 选型 `selected_by_lead` 且 `verification_required=true` |
| G1 | 完整序列化 / Patch 原子性 / Canvas 不反向覆写 | ✅ 全量 | 100 次随机 Patch、409/422、v1 零丢失、layout 排除 | `offline` | ✅ PASS |
| G2 | 必需端口 / 超时 / 反向互斥 / 单写者 | ✅ 全量 | 4 类元件属性 + 正反例 | `offline` | ✅ PASS |
| G3 | 可达性 / 异常转移 / 优先级 / 无未实现并行语义 | ✅ 全量 | GuardAST + 图算法 + 5 场景 Trace + 负例 | `offline` | ✅ PASS |
| G4 | 确定性产物 + SourceMap + 依赖排序 + 静态检查 | ✅ 全量 | golden + 二次生成 hash 一致 | `offline` | ✅ PASS |
| **G5** | **真实 V19 导入 / 编译 / Save / Archive / reopen（Greenfield-only）** | ✅ **单独列** | **Windows V19 单机集成测试，不是 mock** | **`pending_real_machine`** | ❌ **NOT PASSED / 不可签署** |
| G6 | 原件不动 / 只改批准对象 / 删除无悬空引用 | ⚠️ 仅接口与 Schema | 接口 + Schema + 4+ 类负例 + mocked 编排 + 留痕 + 可回归 | `mocked` / `offline` | ✅ 按降级判据完成（AC-02 实机验收范围外） |
| G7 | 超时 / 编译失败 / 重复请求 / worker 崩溃 / 基线漂移不写错项目 | ✅ 全量 | 15 类故障注入，100% 失败任务不发布 `NATIVE_ARCHIVED` | `offline` / `mocked` | ✅ PASS |

## 签发规则

1. `compile_ok = error_count == 0 ∧ static_gate_passed ∧ 存在真实回执`；`warning_count` 单列。
2. `NATIVE_ARCHIVED` 只在 `Retrieve/reopen` 强制通过 + 精确 `archivePath` + sha256 校验 + V19 real 全链回执后由后端 Job 置位（Q-06）。
3. 无 V19 real 全链证据时，整体验收一律 `pending_real_machine`，**绝不显示「交付完成」**。
4. 历史结论 `xml_package_unverified=true` / M4 未通过 / 端到端未闭环，在取得新的 V19 real 全链证据前不得改口径。
5. README 的 1341 / 393 为未复跑声明值；本期 vitest 393 基线 + 20 项新增 = **413 项实跑通过**、v2 pytest **212 passed**、QA 独立验收 **36 passed**、dotnet test 110 passed；pytest 3 个 pre-existing 失败已隔离标记。
