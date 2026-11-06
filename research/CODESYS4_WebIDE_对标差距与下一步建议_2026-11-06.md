# CODESYS 4 Web IDE 对标研究：行业格局、PLC_chat 能力差距与下一步行动路线图

**日期**：2026-11-06
**版本**：v1.0（主理人汇编稿）
**委托**：PLC_chat 项目负责人 ——「深度研究下 codesys 退出的 webIDE 功能。我想做的就是这个类似产品！调研并给出当前项目的差距和下一步建议！」
**用户拍板口径**：5 章（含西门子 TIA 专章）／对标落点＝**形态 + 能力两者都要**／建议颗粒度＝**路线 + 验收 + 风险**

> **执行说明（如实披露）**：原计划的「逐章深度调研 → 独立审稿 → 修订」团队流程，在 Phase 3.1 因课题研究员网络中断（502 / ECONNRESET，运行 21 分 20 秒）而中止，**未产出任何章节草稿，也未经过同行审稿**。本报告由主理人基于以下三类真实材料直接汇编：① Phase 1 初调摘要与 18 条核实来源；② 对 `PLC_chat` 仓库的只读代码勘察；③ 2026-11-06 12:23 补充的 3 轮针对性检索（西门子 Eigen、TIA Openness 限制、SIOS 109817223 AF）。原始材料全文见同目录 `CODESYS4_WebIDE_调研成果存档_2026-11-06.md`。**凡属推断均显式标注，凡来源不足均如实写明，无编造 URL 与数据。**

---

## 目录

- [0. 一页结论（先看这个）](#0-一页结论先看这个)
- [1. 研究标的辨析：不是「退出」，是「推出」](#1-研究标的辨析不是退出是推出)
- [2. CODESYS 4 产品解剖：能力边界与架构标尺](#2-codesys-4-产品解剖能力边界与架构标尺)
- [3. 西门子 TIA 工程链专章：真正同构、也真正有威胁的对标](#3-西门子-tia-工程链专章真正同构也真正有威胁的对标)
- [4. 行业路线与落地阻力：哪些该抄，哪些别碰](#4-行业路线与落地阻力哪些该抄哪些别碰)
- [5. PLC_chat 差距判定：形态 × 能力双维四类归位](#5-plc_chat-差距判定形态--能力双维四类归位)
- [6. 下一步路线图：P0/P1/P2 编号行动项](#6-下一步路线图p0p1p2-编号行动项)
- [7. 「不建议做」清单与既定口径兼容边界](#7-不建议做清单与既定口径兼容边界)
- [8. 来源、证据强度与待完善事项](#8-来源证据强度与待完善事项)

---

## 0. 一页结论（先看这个）

**1）标的纠偏**：你说的「CODESYS **退出**的 WebIDE」，证据指向「**推出**」笔误 —— 官方实体是 **CODESYS 4**，2026 年 9 月 23–24 日发布的 web-based IEC 61131-3 IDE，前称 CODESYS go!。官方停更清单（2026-10-06 更新）无任何相关条目，V3 明确无停产计划，**不存在该产品退市**。若「退出」确有所指，唯一有实据的是「go! 这个名称被替换」，且未见官方独立更名公告。([官方产品页](https://www.codesys.com/products/engineering/codesys-4)、[官方停更清单](https://www.codesys.com/eco-system/up-to-date/release-lifecycle/discontinuations/)、[SPS 2026 展商页](https://sps.mesago.com/nuernberg/en/exhibitor-search.detail.html/codesys-gmbh-a-member-of-the-codesys-group/mf_6_0050331023_5263067_10000128202601.html))

**2）但最重要的发现不是 CODESYS 4，是西门子自己**。**Eigen Engineering Agent** 已于 2026 年 4 月汉诺威工博会发布并 **GA**，19 国 100+ 企业部署；2026 年 6 月 VivaTech 新增「符合行业规范的项目自动生成」：工程师用**自然语言描述机器（工位、设备、行为），几分钟内生成遵循 Siemens Automation Framework 的完整标准项目，可直接在 TIA Portal 打开**；它还能生成 SCL/LAD、生成测试逻辑、**数秒内修复编译或语法错误**、在交付前自我验证并迭代到达标。([西门子官方新闻稿 PDF](https://assets.new.siemens.com/siemens/assets/api/uuid:7c20b450-d7b7-4e8b-9a02-cb4bde2c520c/HQCOPR202604187387EN.pdf)、[西门子中国新闻稿](https://w1.siemens.com.cn/press/NewsDetail.aspx?ColumnId=2&ArticleId=21970)、[官方产品页](https://www.siemens.com/de-de/products/tia-portal/eigen-engineering-agent/)、[西门子全球博客](https://blog.siemens.com/en/2026/06/the-new-ai-agent-doesnt-just-make-suggestions-it-gets-the-job-done))

> 换句话说：**你想做的东西，TIA 的厂商自己已经在卖，而且是订阅制、绑定 TIA V19/V20/V21 许可、已有百家企业客户。** 这改变了本项目的战略定位 —— 不建议把目标定成「做一个类似 CODESYS 4 的 Web IDE」，而应定成「在西门子 AF 生态里做**厂商不会做、也不能做**的那一层」。

**3）你手里真正稀缺的资产不是形态，是流程**：人工连线确认硬门禁（确认前 `ops/disk_writes/writebacks/generations` 恒 0）、规格冻结 vN（`spec_hash` + `ir_snapshot`）、双维强类型 IR 与边白名单、四层静态门禁、PCEC 变更账本、单机离线可控。CODESYS 官方明确「不走纯浏览器聊天机器人路线」「Engineering remains responsible」；Eigen 虽自主执行，官方仍强调「目标不是取代工程师」、结果需 review。([SPS 2026 AI 专题页](https://www.codesys.com/codesys-ai-supported-engineering-at-the-sps-2026/)、[西门子全球博客](https://blog.siemens.com/en/2026/06/the-new-ai-agent-doesnt-just-make-suggestions-it-gets-the-job-done)) **人在回路 + 可复现证据链，是你能站住的位置。**

**4）最该立刻做的不是补前端，是把验收链做实**。当前 `compile_ok` 判定含 `"warning" in state.lower()`、TIA 不可用时返回 HTTP 200 + `tia_unavailable`、自产 OB/文件夹 XML 自标 `xml_package_unverified: True`、README 的「真机全绿」其实属于存量 HR001 重构链 —— **「Greenfield 生成链在 V19 编译零错误」这一终态口径，目前没有闭环证据**。这是 P0。

**5）一个必须优先核实的方向性风险：AF 档位**。Eigen 官方称生成「遵循 Siemens Automation Framework」的标准项目，而 SIOS 109817223 官方 AF 手册的标准实现方式是「每个 Unit / EM 各有独立 **Software Unit**」；你的 PRD 明确选「**AF Basic 文件夹版 + 命名空间前缀、不采用 AF V3 软件单元**」。两者是否同一档位、生成物能否互操作，**目前无直接证据，属推断，必须实测拍板**（P0-4）。([AF v2.2 官方手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_AutomationFramework_DOC_V2_2_3_en.pdf)、[西门子新闻稿](https://w1.siemens.com.cn/news_en/news_articles_en/21971.aspx))

---

## 1. 研究标的辨析：不是「退出」，是「推出」

用一段锁定口径，避免后续所有判断建在错的对象上：

- **实体**：CODESYS 4 v1.0.0.0，官网自称 "The web-based development environment"，副标题 "The future-proof IEC 61131-3 IDE for you, your team, and your CI/CD pipeline"；官方 Webinar 直言 "the new web-based IDE for PLCs"。([官方产品页](https://www.codesys.com/products/engineering/codesys-4)、[Releases & Updates](https://us.codesys.com/ecosystem/up-to-date/release-lifecycle/releases-updates/))
- **不是退市**：官方停更清单（2026-10-06 更新）逐条列出 V2.3、Profibus、UML、SVN、OPC DA、Qt4、CAA 库等停产项，无 WebIDE / go! / CODESYS 4；官方明确 V3 无停产计划（30 万+ 用户、20+ 年现场验证）。「WebIDE 退出原因」维度**来源不足，不补写、不推测**。
- **若「退出」另有所指**：SPS 2026 展商文案写明 "CODESYS 4 (formerly CODESYS go!)"，2025 全年 Roadmap 与 2026-02 官网新闻均用 go!，2026-09 定名 CODESYS 4 —— 是**名称退出**；但**未检索到官方独立更名公告**，属多份官方材料交叉推断。
- **易混淆、需排除**：WebVisu 是 HMI 运行时 HTML5 可视化（工程仍在桌面 IDE 完成）；Automation Server 是浏览器端设备/工程管理 SaaS / On-Prem，其 Engineering 依赖桌面 IDE 的 Connector Add-on 同步项目，浏览器侧不做 PLC 编程；Virtual Control SL / Edge Gateway 均非 IDE。三者都不是你要对标的东西，也都没有退出。([Visualization 产品页](https://www.codesys.com/products/visualization/)、[Automation Server Datasheet](https://api-de.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Datasheets/codesys_automation_server_en.pdf))

---

## 2. CODESYS 4 产品解剖：能力边界与架构标尺

### 2.1 一句话架构

**不造新编译器、不造新运行时，只把工程变成「目录化文本 + 浏览器 UI + 后台编译进程 + 命令行」**。CODESYS 4 与 V3 并行，复用同一编译器、库与运行时；官方在 SPS 2026 材料中明说这是为 CI/CD 与「AI agents working directly on the project files」准备。([官方发布新闻稿](https://www.codesys.com/company/news-center/latest-news/codesys-4-version-1000-is-available/)、[SPS 2026 展商页](https://sps.mesago.com/nuernberg/en/exhibitor-search.detail.html/codesys-gmbh-a-member-of-the-codesys-group/mf_6_0050331023_5263067_10000128202601.html))

### 2.2 首版能力边界（**刻意的窄**）

| 维度 | 首版 1.0.0.0 实况 |
|---|---|
| 编辑器 | ST（高亮/补全/悬浮提示）+ LD v0.1（仅基础离线）；**无** FBD/SFC/CFC/IL |
| 编译位置 | **后台进程**编译、工程管理、控制器通信；浏览器只做 UI；Windows 下自开窗口无需单独浏览器 |
| 命令行 | c4-cli：save-compiled / pack / bootapp compile / install / restore / resolve / check |
| 工程格式 | 目录化 JSON/XML/纯文本（.fbslib/.fbsdev/.fbsws）；Git 可 diff/merge；Libraries.lock.json 含 SHA384 |
| 在线/调试 | **无** Online Change、断点、强制、在线能流、在线仿真；下载后可监视变量与 watchlist |
| 下装链路 | 经 CODESYS Gateway 3.5+；首版仅自家 Control SL 运行时获准；TLS/证书认证尚不支持 |
| 部署 | 本地单用户（Win/Linux x64/ARM64）、团队共享 Linux 服务器（每会话独立进程、需外部反向代理）、控制器上；**非云服务、不需互联网、非订阅** |
| 协作/权限 | Git + 服务器进程隔离 + Linux 用户权限 + 防 CSRF + TLS；**无内置多人实时协同** |
| 静态分析/测试 | 首版**无**静态分析、单元测试、重构、交叉引用、全局撤销重做 |
| 商业 | 免费至 2028 底，无需 License；2029 起拟并入 Professional Developer Edition；6–8 周一个完整版本，不设 SP/补丁 |

**首版只放行两个生产场景**：ST/LD 库开发 + CI/CD 自动构建；Modbus TCP 小型设备项目。第三方评测据此判断「现场调试仍须回 V3」，是「sensible first release rather than a flashy one」([AdoptAutomation](https://adoptautomation.com/blog/plc/codesys-4)，行业观点)。

### 2.3 「形态 × 能力」双维标尺（CODESYS 4 首版状态）

> 用户拍板要求形态 + 能力两者都对照。下表是标尺，第 5 章用同一张表给 PLC_chat 归位。

| # | 维度 | 项目 | CODESYS 4 首版 |
|---|---|---|---|
| S1 | 形态 | 浏览器 / 桌面形态 | Web UI + 本地后台进程（非纯浏览器） |
| S2 | 形态 | 代码编辑器内核 | **有**（ST 完整、LD v0.1） |
| S3 | 形态 | 工程树 / 项目浏览 | **有**（目录化工程） |
| S4 | 形态 | 编译执行位置 | 后台进程 + c4-cli，复用既有编译器 |
| S5 | 形态 | 工程文本化 / Git diff / 依赖锁 | **有**（JSON/XML + lock 文件 + Git） |
| S6 | 形态 | 部署 / 离线 | 本地 / 服务器 / 控制器，明确离线性 |
| S7 | 形态 | 协作 / 账号 | **弱**（Git + 进程隔离 + Linux 权限，无实时协同、无产品化账号） |
| S8 | 形态 | 在线调试 / 下装调试 | **无**（交回 V3）；仅变量监视 |
| A1 | 能力 | 自然语言入口 | **无**（AI 能力在 V3 侧 MCP Server） |
| A2 | 能力 | 人工确认硬门禁 / 规格冻结 | **无此概念**（靠 Git 版本控制） |
| A3 | 能力 | 生成物可被既有编译器消费 | **有**（复用同编译器/库/运行时） |
| A4 | 能力 | 编译器错误回喂闭环 | **部分**（V3 侧 MCP `check_for_errors`，C4 本身无自愈） |
| A5 | 能力 | 静态门禁 / 变更账本 | **无**（静态分析与单元测试首版缺失） |
| A6 | 能力 | 统一「编译零错误」终态口径 | **无**（未见统一验收口径） |
| A7 | 能力 | AI 工程责任归属 | **明确人负责**（Engineering remains responsible） |

---

## 3. 西门子 TIA 工程链专章：真正同构、也真正有威胁的对标

> 这是用户点名要的专章，也是对「TIA V19 编译零错误」终态支撑最强的一章。本节事实主要来自 2026-11-06 补充检索到的西门子官方一手材料（证据强度高）。

### 3.1 Eigen Engineering Agent：厂商已经下场做了你要做的事

| 能力 | 官方事实 | 来源 |
|---|---|---|
| 发布与状态 | 2026-04 汉诺威工博会发布，**已 generally available**；19 国 100+ 企业部署（ANDRITZ Metals、中科摩通 CASMT、Prism Systems） | [新闻稿 PDF](https://assets.new.siemens.com/siemens/assets/api/uuid:7c20b450-d7b7-4e8b-9a02-cb4bde2c520c/HQCOPR202604187387EN.pdf) |
| 端到端执行 | 多步推理 + 自我纠错，规划/执行/验证自动化工程任务；理解项目数据结构、块、参数与组件关系；**交付前验证所有输出并迭代至达标** | 同上、[西门子全球博客](https://blog.siemens.com/en/2026/06/the-new-ai-agent-doesnt-just-make-suggestions-it-gets-the-job-done) |
| **自然语言 → 标准项目** | 2026-06 VivaTech 新增：工程师用简单自然语言描述机器（工位、设备、行为），**几分钟内生成遵循 Siemens Automation Framework 的完整标准项目，直接在 TIA Portal 打开** | [西门子中国](https://w1.siemens.com.cn/press/NewsDetail.aspx?ColumnId=2&ArticleId=21970)、[英文新闻稿](https://w1.siemens.com.cn/news_en/news_articles_en/21971.aspx) |
| ECAD 集成 | 读 XML/AML 电气设计文件，检测并解决不一致，按实际硬件拓扑生成 PLC tags | 同上 |
| **代码与编译闭环** | 支持 SCL 与 LAD 生成/改写、生成测试逻辑、**数秒内修复编译或语法错误**、Style-Guide 检查、批量属性修改、自动项目文档 | [官方产品页](https://www.siemens.com/de-de/products/tia-portal/eigen-engineering-agent/) |
| 交付条件 | 需 TIA Portal **V19/V20/V21 有效许可** + Industry Organization Account；订阅制，1 个月免费试用；属 Xcelerator 组合 | 同上 |
| 官方口径的效率 | 执行 2–5 倍、工程效率 +50%、方案质量 +80% | [西门子中国](https://w1.siemens.com.cn/press/NewsDetail.aspx?ColumnId=2&ArticleId=21970)（**厂商营销数据，未见第三方复核，按宣传口径采信**） |
| 责任边界 | 官方明确「目标不是取代工程师」，让专家聚焦系统级决策；结果供工程师 review | [西门子全球博客](https://blog.siemens.com/en/2026/06/the-new-ai-agent-doesnt-just-make-suggestions-it-gets-the-job-done) |

**反方 / 局限（观点均衡）**：订阅制 + 绑定商业 TIA 许可、需联网账号体系，与离线/空气隔离现场存在张力；「100+ 企业」「+50% 效率」均为厂商自述，缺乏独立验证与失败案例披露；官方虽称端到端执行，仍把最终判断交回工程师，说明**自主执行 ≠ 免验证**。Engineering Copilot TIA 早期形态为 beta、以托管服务交付、集成 V19/V20（[SPS 2025 新闻稿](https://assets.new.siemens.com/siemens/assets/api/uuid:7c447a50-fb36-40fc-b438-19eba5d3f839/HQDIPR202511217291EN.pdf)），说明这条产品线仍在快速演进，不宜把单期能力当稳态。

### 3.2 同构映射：谁和 PLC_chat 最像

| PLC_chat 主链环节 | Eigen Engineering Agent | CODESYS 4 | 判定 |
|---|---|---|---|
| 自然语言描述 | **有**（描述机器工位/设备/行为） | 无（V3 侧 MCP 才有） | Eigen 同构 |
| 生成 Mermaid + 人工连线 | 无（直接生成项目） | 无 | **PLC_chat 特有** |
| 用户显式点击确认（硬门禁） | 无（Agent 自主执行，事后 review） | 无 | **PLC_chat 特有，且是差异化核心** |
| 规格冻结 vN / spec_hash / IR 快照 | 未见公开说明 | Git + Libraries.lock.json | **PLC_chat 更细** |
| 生成 Siemens AF 标准工程 | **有**（遵循 Siemens Automation Framework） | 不适用（CODESYS 生态） | Eigen 同构且由厂商定义标准 |
| 生成物可被既有编译器消费 | **有**（直接在 TIA Portal 打开） | **有**（同编译器/库/运行时） | 三方同构 |
| 编译错误回喂 / 自动修复 | **有**（数秒修复编译或语法错误） | 部分（V3 MCP check_for_errors） | **Eigen 领先** |
| 静态门禁 / PCEC 账本 | 未见公开说明 | 首版无静态分析/单元测试 | **PLC_chat 更细** |
| 终态「TIA V19 编译零错误」 | 自验证至预设质量标准（口径不同） | 无统一口径 | **PLC_chat 口径更硬，但尚未闭环** |

**结论**：形态上 CODESYS 4 是「Web IDE」的参照系；**能力闭环上 Eigen 才是直接竞品**。而 PLC_chat 独有的「人在回路确认 + 可复现证据链」在两家官方产品里都找不到等价物 —— 这既是差异化，也意味着没有现成路径可抄，需要自己把验收做实。

### 3.3 TIA Openness 的能力边界（解释你项目里那几处 `unverified`）

补充检索到的 Openness 事实，与 `plc_project/gateway/app/services/plc/tia_delivery.py` 的现状高度吻合：

- 外部源只支持 `.awl/.scl/.db/.udt`，`GenerateBlocksFromSource()` 生成块；**SCL 是唯一可纯文本从头生成的语言**；LAD/FBD/GRAPH 无文本源，只能走「SimaticML XML 导出 → 改参 → 覆盖导入」的模板法。([导入指南](https://github.com/renanlido/tia-openness/blob/main/docs/guides/import-lad-fbd-scl-blocks.md))
- SimaticML 导入的硬约束：**缺失实例 DB 不会自动创建**、无块编号则自动分配、**导入后数据可能不一致必须编译**、单文件根对象须同类、XML 必须 well-formed，`ImportOptions.Override` 先删后建。（同上）
- **导入时无原生参数指定 OB 编号**，按导入顺序算法分配；要精确控制需预创建空 OB 预留号或用 Openness Scripter；西门子官方更推荐 Global Libraries 而非源文件。([Industrial Monitor Direct](https://industrialmonitordirect.com/blogs/knowledgebase/s7-1200-ob-number-assignment-during-tia-portal-source-import)，行业来源强度中等)
- V18 起软件单元支持 `NamespacePreset`、PLC 块支持 `Namespace`；V16 起 `IgnoreUnitAttribute` 可把块从 unit 导入到 non-unit composition。([SIOS V18 中文 Readme](https://support.industry.siemens.com/cs/attachments/109815199/TIAPortalOpeness_zhCN_zh-CHS.pdf)、[英文 Readme](https://support.industry.siemens.com/cs/attachments/109773802/TIAPortalOpenness_en-US.pdf))

**这解释了三件事**（主理人分析，基于代码勘察 + 上述资料的交叉推断）：
1. `tia_delivery.py` 里「External Source 无法创建软件单元/文件夹；OB 不能由外部源生成，走 SimaticML XML 导入」的判断方向是对的；
2. 自产 OB XML 标 `xml_package_unverified: True`（K1 探针项）不是保守，而是必需 —— 因为 OB 编号不可控 + 实例 DB 不自动创建 + 导入后必须编译；
3. `greenfield_upload.py` 中 `ob_entries` 留空「未虚构条目」的原则正确，但**AF 有强制 OB 编号规则**（见下），这个缺口不能一直空着。

### 3.4 AF 档位风险（**本节最需要你拍板**）

- SIOS **109817223 就是 Siemens Automation Framework**：基于 ISA-88（CM/EM/Unit）+ 默认 OMAC PackML 状态机，使用 LGF / LPML / LUC / LAF 等全局库；官方手册明确**标准实现方式是「每个 Unit 与每个 EM 各有独立 Software Unit」**。([AF V1.2 中文手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_Automation_Framework_DOC_V1_2_CN.pdf)、[AF v2.2 英文手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_AutomationFramework_DOC_V2_2_3_en.pdf))
- AF 还有**强制 OB 编号规则 ueet**（u＝单元号、ee＝EM 号、t＝OB 类型 0 Startup / 1 Main / 2 ProDiag，例 OB2001＝Unit2 Main），用于保证执行时序确定性。([AF 深度解析](https://bbs.plcjs.com/thread-652457-1-2.html)，社区来源强度中等，需以官方手册复核)
- Eigen 官方称生成「遵循 Siemens Automation Framework」的标准项目。([英文新闻稿](https://w1.siemens.com.cn/news_en/news_articles_en/21971.aspx))
- **而 PLC_chat PRD 明确**：AF Basic **文件夹版** + 命名空间前缀，**不采用 AF V3 软件单元**；`greenfield_upload.py` 的 `ob_entries` 留空。

> ⚠️ **推断（非结论，必须实测）**：如果 Eigen 生成的 AF 项目走官方标准的软件单元版，而 PLC_chat 生成的是文件夹版，两套生成物在 TIA 里可能不兼容，且「OB 编号无法原生指定」与「AF 强制 ueet 规则」会叠加放大风险。**建议在投入 P1 之前，先用一个最小样例实测并拍板档位**（P0-4）。目前没有直接证据能证明这两者是同一档位或必然冲突，不能当结论写死。

### 3.5 另外两条西门子线（简述）

- **SIMATIC AX**：VS Code + Git + 包管理 + 单元测试的 IT 化工程路线，与 TIA Portal 双轨；2025-03 官方确认 Linux/macOS 本地支持尚未到位。([Liam Bee](https://liambee.me/general/simatic-ax-explained-what-it-is-how-it-differs-from-tia-portal-and-how-to-prepare-without-a-licence)，行业来源；[西门子博客](https://blog.siemens.com/?p=71316)) 它验证了「工程文本化 + Git」的方向，但也提示双轨迁移成本。
- **TIA Portal Cloud**：云端托管 TIA Portal（免安装、项目存云、共享），**不是浏览器原生 IDE**。([TIA Portal 官方 FAQ](https://www.siemens.com/zh-cn/products/tia-portal/)) 与本项目本机离线形态不同，不构成必须跟进的理由。

---

## 4. 行业路线与落地阻力：哪些该抄，哪些别碰

### 4.1 三条路线

| 路线 | 代表 | 可借鉴点 |
|---|---|---|
| MCP 化「generate → check → correct」 | CODESYS Development System MCP Server 1.0.0.0（2026-04-28）：`browse_project_tree` / `get_structured_text_content` / `check_for_errors`，支持云 AI 与本地 LLM | **把编译器错误回喂给生成器**，而不是让 AI 一次成型；官方同时强调版本控制/测试/静态分析不可让渡 ([官方 AI 页](https://www.codesys.com/products/engineering/ai-supported-engineering/)、[SPS 2026 AI 专题](https://www.codesys.com/codesys-ai-supported-engineering-at-the-sps-2026/)) |
| 国产 B/S 云原生 IDE | 宝信「天行 IDE」：B/S 架构、云原生、适配国产 OS，集成 DeepSeek 做代码生成/补全/解释/修复，2025 CIIF 大奖；MIR 称国内唯一量产上市 B/S PLC 编程环境 | 证明中文语境下 B/S + 代码生成有市场；**但一手技术文档来源不足**，白皮书为付费摘要页，来源强度中等 ([控制工程网](https://www.cechina.cn/Company/227040_136551/ProductDetail.aspx)、[凤凰网专访](https://v.ifeng.com/c/8mxjawHaVrU)) |
| IDEaaS | 德国 SDA：浏览器中多供应商多版本 IDE、一次性 IDE 副本 + 许可证共享 + MQTT/WireGuard | 说明「许可证与远程访问」是 Web 化真正的工程难点 ([搜狐译文](https://www.sohu.com/a/860845959_313848)，二手来源) |
| 开源 | OpenPLC / Beremiz | **均为桌面本地工具，不是浏览器 IDE**，不构成对标 ([腾讯新闻](https://news.qq.com/rain/a/20220913A02Z5600)) |

### 4.2 落地阻力：正反两面都要看

**反面（支持「不做云、不做实时协同」）**：离线/空气隔离与数据主权要求；per-seat 许可与厂商锁定；浏览器画布/AI 生成逻辑容易忽略扫描周期、竞争条件、看门狗、E-Stop 硬件优先级（[TrueSight 行业评论](https://tsight.io/articles/20320025)）；Web 化三段式架构（Web 控制平面 + 工具链 + 容器）带来默认免认证、命令拼接、特权容器逃逸等攻击面（[ZONE.CI 安全研究](https://zone.ci/secarticles/wx/570008.html)）；学界亦指出工控工具长期 local-first、商业工具与自有 RTE 紧耦合造成 lock-in（[波尔图大学论文](https://repositorio-aberto.up.pt/bitstream/10216/175663/2/786577.pdf)）。

**正面/对冲（支持「补文本工程与编译回喂」）**：官方 On-Premises 明确支持 isolated networks / offline operation，说明 Web 化与离线并不必然冲突（[Automation Server 部署形态](https://www.codesys.com/products/automation-server/product-variants/)）；文本工程 + CI/CD 带来可 diff、可测、可回滚；学术侧 LLM4PLC 用语法检查器 + 模型检查器把生成成功率 47%→72%（[Eurokommerz 转述](https://eurokommerz.at/blog/local-ai-for-plc-programming-iec-61131-3)，二手，建议回查原论文），Adnyana & Schwung（MLwA 2026）在 25 个真实用例、21 种提示技术、跨 TIA Portal 与 TwinCAT 上得出「**提示结构对确定性与正确性的影响大于 LLM 选型**」（[ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2666827025001872)）。

> **对本项目的含义（推断）**：资源应投在「规格冻结 + 提示/契约结构 + 编译器反馈回喂」，而不是换更大模型或造 IDE。这与你既有的硬门禁、静态门禁、PCEC 账本完全同向。

---

## 5. PLC_chat 差距判定：形态 × 能力双维四类归位

> 判定依据：第 2.3 节同一张标尺 + 第 3 章同构映射 + 本地代码勘察。四类：**【已有且更强】/【已有但需补强】/【完全缺失】/【刻意不做·应坚持】**。

### 5.1 形态维度

| # | 项目 | CODESYS 4 | PLC_chat 实况 | 归位 |
|---|---|---|---|---|
| S1 | 浏览器/桌面形态 | Web UI + 本地后台进程 | React19/Vite 前端 + FastAPI 网关，本机 127.0.0.1 双进程 | **已有且相当** —— 都是「浏览器 UI + 本地后台」，别误以为自己不是 Web 形态 |
| S2 | 代码编辑器内核 | ST 完整 + LD v0.1 | **无** Monaco/CodeMirror；`SclPane.tsx` 仅 textarea + `sclHighlight.tsx` 关键字高亮；Mermaid 源码只读 `<pre>` | **完全缺失（但只需补「只读审阅」，见 P1-3）** |
| S3 | 工程树 / 项目浏览 | 目录化工程树 | 存量工作台有 `ProjectSidebar.tsx`；**Greenfield 三栏通道无工程树** | **已有但需补强** —— 把已有工程树能力复用到 Greenfield |
| S4 | 编译执行位置 | 后台进程 + c4-cli，复用既有编译器 | TIA Openness C# CLI 一次性 spawn + TIA V19 编译 | **已有且更强** —— 你的终裁是真实 TIA 编译器，比 c4-cli 口径更硬 |
| S5 | 工程文本化 / Git diff / 依赖锁 | JSON/XML + Libraries.lock.json(SHA384) + Git | 生成 SCL/XML 文本包 + manifest + 规格 vN 冻结 + PCEC 账本；**但 Greenfield 会话纯内存、服务重启即清空，无产品内 Git/分支/回滚** | **已有但需补强（最高优先级）** —— 这是 CODESYS 4 最核心的资产，你只差「持久化 + 幂等」 |
| S6 | 部署 / 离线 | 本地/服务器/控制器，明确非云、不需互联网 | 本机 devctl 双进程；docs 明确 "not a shared public service"，无生产部署 | **已有且同构，应坚持** —— 与工控离线约束一致 |
| S7 | 协作 / 账号 | Git + 进程隔离 + Linux 权限，无实时协同 | 仅 dev stub（`usr_dev/ws_dev`、JWT 验签 TODO），无 WebSocket | **刻意不做·应坚持** —— 对标物首版同样没有，投入产出比低 |
| S8 | 在线调试 / 下装调试 | 首版**无**，交回 V3；仅变量监视 | CLI README 列 hard refuse；memory 记为「永拒桩」 | **刻意不做·应坚持** —— 与「HMI 后置」一致，且 CODESYS 4 首版同样后置 |

### 5.2 能力维度

| # | 项目 | CODESYS 4 / Eigen | PLC_chat 实况 | 归位 |
|---|---|---|---|---|
| A1 | 自然语言入口 | C4 无；Eigen **有** | 已实现（Mermaid 生成 + 对话上传 + 四视图） | **已有（领先于 C4，与 Eigen 同构）** |
| A2 | 人工确认硬门禁 / 规格冻结 | C4 无此概念；Eigen 自主执行、事后 review | `confirm_and_freeze`：explicit 校验 + 确认前零副作用计数器 + `assert_no_side_effects()` + `specs/vN.json`；`greenfield_session.py` 明确「不得代劳或超时自动推进」 | **已有且更强（核心差异化资产）** |
| A3 | 生成物可被既有编译器消费 | C4 同编译器/库/运行时；Eigen 直接在 TIA 打开 | SCL 源包 + XML 补充包 → TIA Openness 导入 | **同构，方向正确** |
| A4 | 编译器错误回喂闭环 | V3 MCP `check_for_errors`；Eigen 数秒修复编译/语法错误 | 存量链有 `compile_jobs.py` + `writeback_heal.py`（3 次自愈 + 熔断）；**Greenfield 链 `/deliver-tia` 未与之接通**，PCEC 关系待定 | **已有但需补强（P1-2）** |
| A5 | 静态门禁 / 变更账本 | C4 首版无静态分析/单元测试 | 四层静态门禁 fail-closed + PCEC V0–V3 账本 | **已有且更强** |
| A6 | 统一「编译零错误」终态口径 | C4 无；Eigen 自验证至预设质量标准 | 口径明确（TIA V19 零错误），但**实现有偏差**：`compile_ok` 含 warning 判定；TIA 不可用返回 HTTP 200 + `tia_unavailable`；`xml_package_unverified: True` | **口径领先、闭环缺失（P0 核心）** |
| A7 | AI 工程责任归属 | 双方官方均强调人负责、工程责任不可让渡 | 硬门禁 + 人工连线确认 | **已有且更强，应坚持** |

### 5.3 四项必须先处理的风险（代码勘察实证）

| 风险 | 事实 | 影响 |
|---|---|---|
| **R1 文档—代码越界** | `docs/greenfield/01-greenfield-prd.md:39,60`、`02-architecture.md:4` 写「Phase 2 只设计、不实现」；但 `greenfield.py:258-298` 已有 `/generate`、`/deliver-tia`、`/download-package`，`greenfield_delivery.py:54` 已有实现体，前端 `GreenfieldGateBar.tsx:146-164` 已有「写入博途（真机）」按钮 | 决策依据失真；验收范围无法界定 |
| **R2 编译口径偏差与验收归属错位** | `tia_delivery.py:647` `compile_ok` 含 `"warning" in state.lower()`；`:806-883` TIA 不可用时 HTTP 仍 200；README「TIA V19 真机验证全绿」实为**存量 HR001 重构链**（见 memory 2026-11-02） | 「Greenfield 生成链编译零错误」目前**没有闭环证据** |
| **R3 OB/文件夹 XML 未验证** | `tia_delivery.py:15-19,335,490-494` 自标 `xml_package_unverified: True`（K1 探针项）；ProDiag 类 OB 因 `SecondaryType` 未确证被跳过；文件夹 XML 可导入性未确证 | 与第 3.3 节 Openness 硬约束叠加：OB 编号不可控、实例 DB 不自动创建、导入后必须编译 |
| **R4 工程资产易失** | `greenfield_session.py:1-5,241-260` 纯内存草稿、重启即清空，靠用户主动导出/导入 JSON；`greenfield_upload.py` 的 `ob_entries` 留空，而 AF 有强制 OB 编号规则 | 无法复现、无法 diff、无法审计；OB 契约缺口 |

---

## 6. 下一步路线图：P0/P1/P2 编号行动项

> 每项按你拍板的「**目标 — 验收口径 — 风险**」三件套给出，可逐条拍板。**本报告未改动任何代码，以下均为待确认项。**

### P0 —— 先把终态验收做实（方向性问题优先于补功能）

**P0-1　修正「编译零错误」判定口径**
- 目标：把 `tia_delivery.py` 的 `compile_ok` 改为基于 TIA 编译结果的结构化诊断（error count == 0 且四层静态门禁无拦截），warning 单列不并入成功判定；TIA 不可用/`tia_unavailable` 改为显式非成功状态，禁止 HTTP 200 静默通过。
- 验收：在 V19 真机跑通一次 Greenfield 生成链，产出可复现的结构化编译报告（error 数、warning 清单、块清单、耗时、TIA 版本、报告路径落盘）。
- 风险：改动会暴露此前被 warning 合并掉的真实失败，短期内「通过率」会下降；需同步更新前端门禁条与 `CompileDrawer` 的状态文案。

**P0-2　打通 K1 探针：OB/文件夹 XML 真机导入验证**
- 目标：对自产 `xml_supplement/ob/*.xml` 与 `folders.json` 在 V19 真机做导入验证，消掉 `xml_package_unverified: True`。
- 验收：一个最小样例（1 Unit + 2 EM）从自然语言 → 冻结规格 → 生成工程包 → Openness 导入 → 编译零错误，全程留痕（PCEC 账本 + 编译报告 + `.zap19` 归档）。
- 风险：Openness 导入时 OB 编号按算法分配、实例 DB 不自动创建、导入后必须编译（第 3.3 节）；可能需预创建空 OB 或改走 SimaticML 模板法。ProDiag 类 OB 的 `SecondaryType` 仍需确证。

**P0-3　统一文档与代码口径**
- 目标：把 `01-greenfield-prd.md` / `02-architecture.md` 的「Phase 2 不实现」改为现状描述；README 从 v3.0 存量口径更新并明确「真机全绿」归属哪条链；补一份 Greenfield 交付链的能力/边界清单。
- 验收：文档中的路由与能力清单与 `greenfield.py` 一致，且能指向 P0-1/P0-2 产出的验收证据路径。
- 风险：低（纯文档），但会改变后续所有决策的基线，建议与 P0-1 同步。

**P0-4　AF 档位对齐核实（**战略性，建议先于任何 P1 投入**）**
- 目标：实测并拍板「AF Basic 文件夹版」与官方 AF / Eigen 生成项目（疑似软件单元版）的兼容性；确认 Openness 能否稳定产出符合 AF 强制 OB 编号规则（ueet）的文件夹版工程。
- 验收：一份档位对照表 + 一个最小样例在 V19 的导入编译结果 + 明确的「坚持文件夹版 / 切软件单元版」拍板结论与依据。
- 风险：**这是推断驱动的方向性风险，不是已证实结论**。若两者不兼容，P0/P1 的成果可能与西门子官方 AF 生态无法互操作；若选错档位，返工成本高。注意你的 PRD 已明确「不采用 AF V3 软件单元」，此项是**核实并请重新拍板**，不是默认要改口径。

### P1 —— 补齐 CODESYS 4 最核心的那块资产：文本工程 + 编译闭环

**P1-1　Greenfield 会话持久化 + 产物可 diff / 幂等**
- 目标：把纯内存草稿改为按 `spec_version` 落盘（已有 `write_spec` 雏形），产物包纳入 Git 可 diff，`manifest.json` 带内容哈希；复用存量 `ProjectSidebar` 工程树到 Greenfield 通道。
- 验收：服务重启后能恢复到 FROZEN vN；同一份冻结规格两次生成的产物哈希一致（幂等）。
- 风险：**落盘只允许发生在 FROZEN 之后**，绝不能破坏「确认前四个副作用计数器恒 0」的硬门禁（R4）。

**P1-2　编译器错误回喂闭环接通 Greenfield**
- 目标：把存量链 `compile_jobs.py` / `writeback_heal.py` 的结构化诊断与自愈能力挂到 `/deliver-tia` 之后，形成 generate → compile → 结构化诊断 → 修正 → 复编译，并全程写入 PCEC 账本；对齐 CODESYS MCP `check_for_errors` 与 Eigen「数秒修复编译错误」的范式。
- 验收：故意注入 1 个 SCL 语法错误，系统能定位并自动修复，复编译 error=0，账本可追溯到每一次修正。
- 风险：自愈范围限定在生成物，**不得修改已冻结规格、不得越过人工确认节点**；熔断次数与超时沿用存量链既有护栏。

**P1-3　引入轻量 SCL 只读审阅器（**不是自制 IDE**）**
- 目标：Monaco/CodeMirror **只读**模式，支持语法高亮、查找、点击编译错误跳行、与上一版 `spec` 做 diff。
- 验收：能在浏览器审阅生成的 SCL 与差异，且不提供任何写回 TIA 的编辑入口。
- 风险：形态补齐应服务于「可审阅、可追责」，一旦滑向在线编辑就会与 TIA 主编译器双主，违背第 2 章「不造编译器」的行业共识（N1）。

**P1-4　补齐 OB 编号 / 调用顺序的契约输入**
- 目标：为 `greenfield_upload.py` 目前留空的 `ob_entries` 提供**由用户或模板给出**（不是 AI 猜）的确定输入，覆盖 AF 的 ueet 编号规则与执行顺序。
- 验收：生成的 manifest 能给出确定的 OB 编号与执行顺序，且 V19 真机导入后与预期一致。
- 风险：与现有「未虚构条目」原则一致，必须由外部输入；若用户无法提供，需明确降级路径（预创建空 OB 或模板法），不得静默近似。`safety_entries` 同理。

### P2 —— 差异化与护城河（视 P0 结论再投）

**P2-1　把「人在回路」做成可对外讲的方法论资产**
- 目标：形成一份规格 → 工程的可复现映射说明 + 每次生成的 evidence bundle（冻结规格、IR 快照、连线清单、静态门禁结果、编译报告、账本）。
- 验收：第三方（或未来的你）仅凭 evidence bundle 能复现同一工程并解释每一处生成决策。
- 风险：避免写成营销材料；必须与 P0-1/P0-2 的真实证据绑定，否则反而放大 R2。

**P2-2　选择性引入 MCP 化工具接口（可选）**
- 目标：参照 CODESYS MCP Server 暴露 `browse_project_tree` / `get_structured_text_content` / `check_for_errors` 一类只读 + 校验工具，支持本地 LLM。
- 验收：本地模型能通过工具读取工程、触发编译校验并拿到结构化错误，且所有写操作仍走硬门禁。
- 风险：CODESYS 官方明确「不走纯浏览器聊天机器人路线」；引入 MCP 不得把「确认」降级为对话建议（N3）。

---

## 7. 「不建议做」清单与既定口径兼容边界

### 7.1 明确不建议做（每条给理由）

| # | 不做 | 理由 |
|---|---|---|
| **N1** | 自制编译器 / 运行时 / 全语言 IDE | CODESYS 4 复用同编译器/库/运行时，首版仅 ST+LD；在线调试仍交回 V3。你的 TIA V19 就是编译器，重造即失去终裁权威 ([官方产品页](https://www.codesys.com/products/engineering/codesys-4)) |
| **N2** | 在线调试 / 仿真 / 下载到 PLC | CODESYS 4 首版明确不做；Eigen 也不替代现场验证；你的 CLI 已列 hard refuse，HMI 后置 |
| **N3** | 纯浏览器聊天机器人 / 取消硬门禁 | CODESYS 官方明确拒绝纯 browser chatbot、强调 Engineering remains responsible；Eigen 虽自主执行仍强调「不取代工程师」、结果需 review ([SPS 2026 AI 专题](https://www.codesys.com/codesys-ai-supported-engineering-at-the-sps-2026/)) |
| **N4** | 云 SaaS / 多租户 / 订阅制 | CODESYS 4 正式产品页明确非云服务、不需互联网、非订阅；工控离线/空气隔离与数据主权是硬约束，Web 化还带来认证/注入/容器逃逸攻击面 ([官方产品页](https://www.codesys.com/products/engineering/codesys-4)、[ZONE.CI](https://zone.ci/secarticles/wx/570008.html)) |
| **N5** | 多人实时协同 / 完整账号体系 | CODESYS 4 首版也无内置实时协同，只有 Git + Linux 权限 + 进程隔离；与单机工程站定位不符，投入产出比低 |
| **N6** | 靠换更大模型提升正确率 | 学术侧显示提示结构、语法/模型检查、编译器反馈的收益大于模型选型（Adnyana 2026；LLM4PLC 47%→72%），资源应投在规格冻结与编译回喂 ([ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2666827025001872)) |
| **N7** | 现在就追 Eigen 的能力广度（HMI/驱动/网络配置/ECAD） | 与「HMI 后置、存量冻结」既定口径冲突；且对手是平台厂商，广度竞争无胜算 |

### 7.2 五条既定决策口径的兼容边界

| 既定口径 | 本路线图的兼容情况 |
|---|---|
| **TIA V19 编译零错误** | P0-1 / P0-2 直接服务；P1-2 强化。任何 Web 能力引入都不得放宽此判定 |
| **HMI 后置** | N2 / N7 一致。Eigen 已含 HMI 不构成你必须跟进的理由 |
| **存量重构链冻结** | 所有 P 项**只作用于 Greenfield 通道**；`compile_jobs` / `writeback_heal` 仅作为能力来源被复用，不回改存量链 |
| **硬门禁不可降级** | P1-1 落盘只在 FROZEN 之后；P1-2 自愈不改冻结规格；P2-2 MCP 写操作仍走确认。Eigen 的自主执行是对照物，不是模板 |
| **DB 编号 / IO 表由前端对话上传** | 保持。但 P1-4 需补 OB 编号与调用顺序的输入来源，且必须由用户/模板提供，不虚构 |

---

## 8. 来源、证据强度与待完善事项

### 8.1 关键来源（完整 18 条 + 备选池 + 补搜 15 条见存档文件第五节）

**CODESYS 官方（强度高）**：[CODESYS 4 产品页](https://www.codesys.com/products/engineering/codesys-4)、[v1.0.0.0 发布新闻稿](https://www.codesys.com/company/news-center/latest-news/codesys-4-version-1000-is-available/)、[Store 页](https://us.store.codesys.com/codesys-4.html)、[Releases & Updates](https://us.codesys.com/ecosystem/up-to-date/release-lifecycle/releases-updates/)、[官方停更清单](https://www.codesys.com/eco-system/up-to-date/release-lifecycle/discontinuations/)、[SPS 2026 AI 专题](https://www.codesys.com/codesys-ai-supported-engineering-at-the-sps-2026/)、[AI-supported Engineering](https://www.codesys.com/products/engineering/ai-supported-engineering/)、[Automation Server Datasheet](https://api-de.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Datasheets/codesys_automation_server_en.pdf)。

**西门子官方（强度高）**：[Eigen 发布新闻稿 PDF](https://assets.new.siemens.com/siemens/assets/api/uuid:7c20b450-d7b7-4e8b-9a02-cb4bde2c520c/HQCOPR202604187387EN.pdf)、[Eigen 官方产品页](https://www.siemens.com/de-de/products/tia-portal/eigen-engineering-agent/)、[西门子全球博客](https://blog.siemens.com/en/2026/06/the-new-ai-agent-doesnt-just-make-suggestions-it-gets-the-job-done)、[西门子中国两项新功能](https://w1.siemens.com.cn/press/NewsDetail.aspx?ColumnId=2&ArticleId=21970)、[英文新闻稿（AF 表述）](https://w1.siemens.com.cn/news_en/news_articles_en/21971.aspx)、[SPS 2025 Copilot TIA 新闻稿](https://assets.new.siemens.com/siemens/assets/api/uuid:7c447a50-fb36-40fc-b438-19eba5d3f839/HQDIPR202511217291EN.pdf)、[AF V1.2 中文手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_Automation_Framework_DOC_V1_2_CN.pdf)、[AF v2.2 英文手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_AutomationFramework_DOC_V2_2_3_en.pdf)、[Openness V18 中文 Readme](https://support.industry.siemens.com/cs/attachments/109815199/TIAPortalOpeness_zhCN_zh-CHS.pdf)。

**学术 / 行业 / 安全（强度中，仅作辅助）**：[Adnyana & Schwung, MLwA 2026](https://www.sciencedirect.com/science/article/pii/S2666827025001872)、[波尔图大学 Web-based IDE 论文](https://repositorio-aberto.up.pt/bitstream/10216/175663/2/786577.pdf)、[ZONE.CI 安全分析](https://zone.ci/secarticles/wx/570008.html)、[ControlByte](https://controlbyte.tech/?p=20262)、[AdoptAutomation](https://adoptautomation.com/blog/plc/codesys-4)、[tia-openness 导入指南](https://github.com/renanlido/tia-openness/blob/main/docs/guides/import-lad-fbd-scl-blocks.md)、[Industrial Monitor Direct OB 编号](https://industrialmonitordirect.com/blogs/knowledgebase/s7-1200-ob-number-assignment-during-tia-portal-source-import)、[plcjs AF 深度解析](https://bbs.plcjs.com/thread-652457-1-2.html)。

### 8.2 必须保留的证据标注

1. **三处官方口径差异，全报告已统一**：① 发布日统一写「2026 年 9 月 23–24 日」（产品页 9/24、SPS 新闻稿 9/23、官方发布稿自身前后并存）；② 最低 Runtime 以产品页 SP19 为准（新闻稿写 SP18）；③ 「是否云服务」以正式产品页「not a cloud service / An Internet connection is not required」为准（SPS 预热稿 "in the cloud" 属发布前宣传）。
2. **营销数据**：Eigen 的「2–5 倍 / +50% / +80% / 100+ 企业」均为西门子自述，未见第三方复核，不作为本项目目标值。
3. **推断清单**（非事实，已在正文标注）：AF 档位可能与 Eigen 生成物不兼容（3.4）；OB 编号规则与 Openness 限制叠加放大 R3（3.3）；资源应投规格冻结与编译回喂（4.2）。
4. **来源不足（未补位）**：CODESYS 4 的 OEM 采用案例/用户数/营收；「WebIDE 退出原因」的官方说明与业界分析；国产天行 IDE 一手技术文档；Eigen 生成项目所用 AF 的**具体版本与档位**；LLM4PLC 原始论文（本报告引用的是二手转述）。

### 8.3 待完善事项（流程降级的影响）

| 项 | 状态 | 建议 |
|---|---|---|
| 第 1–3 章逐章深度调研草稿与独立审稿 | **未完成**（课题研究员网络中断，零草稿回传） | 本报告以初调 + 补搜材料替代，**未经 6 维审稿**；如需对外发布，建议补一轮独立事实核查，重点核 A5 的 AF 表述与 C2 的软件单元口径 |
| SIMATIC AX / Portal Cloud 深挖 | 仅初调级（行业来源为主） | 若要据此做技术选型，需补西门子官方手册与许可条款 |
| 国产 B/S IDE、IDEaaS 一手资料 | 来源强度中等 | 不影响本报告主要结论；若要对标国内市场需单独补研 |
| P0-4 AF 档位 | **待真机实测** | 这是全报告唯一可能改变技术路线的未决项，建议优先于 P1 全部投入 |
| 文档与代码口径 | 待 P0-3 修正 | 不改变代码行为，但影响后续所有验收判定 |

---

> **免责声明**：本报告由 AI 汇编，团队逐章审稿流程因网络故障未完成。所有外部来源请在重要决策场景下二次核验时效性与真实性；涉及 TIA Openness、AF 档位、OB 编号的技术结论**必须以你本机 V19 真机实测为准**。文中「下一步路线图」为待确认建议，未对 `PLC_chat` 仓库做任何代码改动。
