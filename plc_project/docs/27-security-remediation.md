# Mimosa 深扫修复记录（Security Remediation Record）

对象：Mimosa 深度安全扫描（deep，静态证据边界 `static_only_no_runtime_execution`）的 21 项 finding
方式：三泳道并行修复（XML / 网络出口 / 本地工具与脚本）+ 整合期 agents 层补防线
提交：`23b87f3`（2026-11-03，已推送）
前置审计：`docs/26-v3_0-progress-audit.md`

## 0. 扫描凭据

| 轮次 | scanId | seal | finding |
| --- | --- | --- | --- |
| 基线 | `scan-2026-11-03T01-40-25.219Z-eb58b5beeac3` | `sha256:68f480bd…68630cfa` | 21（高 18 / 低 3） |
| 中检 | `scan-2026-11-03T02-28-34.240Z-425f3102e6f3` | `sha256:12e77dcd…92cc16c` | 13 |
| 终扫（=提交树） | `scan-2026-11-03T02-34-36.586Z-ddc59b57dcdf` | `sha256:e72399aa…d046636c` | 12（高 11 / 低 1） |

依赖：337 包，已知漏洞库 0 命中（三轮一致）。

## 1. 已修复（9 项）

### 1.1 XXE / 实体扩展（CWE-776，高危）×1 —— 消除

`ingest.py` 解析导入 XML 处双保险：`plc_engine/xml_guard.py::assert_no_dtd`（零依赖文本守卫，
`<!DOCTYPE`/`<!ENTITY` 大小写与空白变体全拒）+ 换 `defusedxml.ElementTree.fromstring`（仓库既有依赖，
禁 DTD 的标准实现）。守卫另接入 `array_evidence.py`、`hmi_writeback.py`。

**整合期补防线**：泳道范围外的 agents 层才是上传 .xml/.zip 的真实解析落点——新建
`agents/plc/tia/xml_safe.py::parse_xml_tree_no_dtd`（`ET.parse` 的 DTD 拒绝版 drop-in，返回
ElementTree 保留 `.getroot()/.write()` 语义，agents 层自包含不跨层 import），接线 9 处：
`simaticml.py::parse_block_xml/parse_tag_table_xml`（canvas_import 处理上传的实际入口）、
`hardware.py`、`surface.py`、`hmi_screens.py` ×3、`xml_patch.py` ×2。新增单测 16 例
（`test_xml_guard.py` + `test_xml_safe_agents.py`）。

### 1.2 SSRF（CWE-918，高危）×3 —— 消除

- `llm_explain.py`：调查确认 `base_url` 仅来自环境变量 `PLC_LLM_BASE_URL`（无 HTTP 注入面）；
  新增 `_validated_base_url`（scheme ∈ http/https 且 netloc 非空），在 `llm_settings()` 构建点单一收口。
  **取舍**：不封私网/回环——本地 Ollama `http://127.0.0.1:11434/v1` 是模块头文档支持的合法用法。
- `openness_session.py`：`_validated_worker_url`——默认基址必须回环；非回环仅当
  `RESEARCHOS_TIA_SESSION_URL` 显式配置时放行（局域网 worker 是合法拓扑）。非法配置走既定
  一次性 CLI 回退，不炸调用方。
- `devctl.py::probe_health` + `quiet_start.py`：探活 URL 回环断言（`LOOPBACK_HOSTS` 白名单）。

### 1.3 不安全随机（CWE-330，低危）×2 —— 消除

`llm_settings.py:716` 实为 DNS 查询 txid（`_dns_udp_a_record`）：可预测将使离路径攻击者可伪造
DNS 应答、把 `_resolve_ipv4` 引向攻击者 IP——**定性为敏感**，改 `secrets.randbelow(65536)`
（取值域与原 `random.randint(0, 65535)` 一致）。弃用镜像 `plc_gateway/services/llm_settings.py`
同步最小改动。

### 1.4 命令注入（CWE-78）×1 + 路径穿越（CWE-22）×2 —— 消除

- `devctl.py:157`：`spec["start"]` 字符串经 shlex 拆分 + `shutil.which` 解析完整可执行路径
  （Windows CreateProcess 不做 PATHEXT 搜索），`Popen` 列表参数、去 `shell=True`。
  真机回归：`up web` 启动成功、`status` 正常、`down --all` 归零。
- `baseline.py:87`：**真风险是 zip slip**——zip 成员名 `rel` 拼进 `project_folder / rel` 可 `../` 逃逸。
  修为 `resolve()` + `is_relative_to(project_folder.resolve())` 断言，逃逸即抛 ValueError。
- `devctl.py:242/244`：pathlib 化（原为 `os.devnull` 字面量，静态误报）。

## 2. 剩余 12 项的豁免依据（逐项，非忽略）

| finding | 位置 | 豁免依据 |
| --- | --- | --- |
| SSRF ×2 | `llm_explain.py:181/243` | `_validated_base_url` 在 settings 构建点收口（§1.2），27 个单测 + 7 种畸形值实测拒绝；静态分析无法穿透函数边界证明 |
| SSRF ×1 | `quiet_start.py:57` | 字面量常量 `http://127.0.0.1:5173` + `_assert_loopback` 断言在位 |
| 路径穿越 ×6 | 根目录 5 个攻坚脚本 + `baseline.py:94` | 脚本已 `__file__` 锚定（无 CWD 依赖）；baseline 已有 zip-slip 断言——均为 join 模式被模式匹配，无不可信输入进入 |
| 路径穿越 ×1 | `tmp_validate/af_research/extract_pdf.py:9` | `.gitignore` 内的一次性复现材料（docs/16），非产品代码 |
| SSTI ×1 | `baseline.py:4` | **词义误报**：docstring 中 "Startup Template" 指 TIA 工程模板 zip 资产；全模块无 string.Template/.format 模板渲染，已加 triage 注释 |
| 命令注入 ×1（低） | `compile_jobs.py:12` | 唯一执行点 `_kill_process_tree` 已是列表参数；外部值 pid 加正整数白名单校验 |

## 3. 过程中发现并修复的缺陷（非 finding）

**`test_pcec_gateway` 测试隔离缺陷**：`plc_engine.pcec` 缺席时 `/changes` 回落读
`<PLC_WORK_DIR>/changes` 真盘；PLC_WORK_DIR 未设时落到 `%TEMP%/researchos_plc/changes`，
实测累积 84 条跨运行残留，连续第二次全量跑必击穿 `== []` 断言（本仓库一度复现）。
修：autouse 夹具将 `PLC_WORK_DIR` 指向每用例独立 `tmp_path`（保全测试意图，非放松断言），
并清理历史残留。连续两轮全量 975 passed 验证稳定。

## 4. 待决策事项（不擅自改 API 行为）

`gateway/app/services/llm_settings.py` 存在**尚未挂载任何路由**的运行时写接口：
`update_llm_settings(LlmSettingsUpdate)`（可写各 slot `base_url`/`api_key` 并落盘、回写
`os.environ` 与 litellm yaml）及 `test_llm_slot`（对用户提供的 base_url 发起连通性测试）。
当前无暴露面；**一旦未来接入 POST/PUT 路由，用户可控 base_url 即成 SSRF 入口**——
接路由前必须补：目标白名单或 scheme/host/解析 IP 边界校验，并对 api_key 落盘做权限收紧。

## 5. 验证

- 后端全量：`pytest tests/unit -q` → **975 passed**（连续两轮稳定；= 957 基线 + 16 新增守卫单测 + 既有增量）
- ruff：新增/触碰文件中，本次新增代码零告警（触碰文件内 15 条既有风格债未动，遵循"不做无关格式化"）
- 真机回归：`devctl up web` / `status` / `down --all` 链路完好
- 前端本轮未触碰（vitest 219 绿维持）

## 6. 纪律声明

本文记录静态扫描数字与缓解依据；`verdictEffect: none`，**不构成"项目安全"的结论**。
运行时行为（真实 DNS 路径、网络边界、真机暴露面）不在本轮证据边界内。
