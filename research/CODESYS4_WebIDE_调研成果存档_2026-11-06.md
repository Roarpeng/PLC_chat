# CODESYS 4 Web IDE 调研成果存档

**存档日期**：2026-11-06
**课题**：用户原话「深度研究下 codesys 退出的 webIDE 功能。我想做的就是这个类似产品！调研并给出当前项目的差距和下一步建议！」
**执行说明**：本文件是**原始调研成果的保真存档**，不含最终结论。完整团队深研（Phase 3 逐章草稿与审稿）因课题研究员网络中断（502 / ECONNRESET）未完成；本存档收录已真实产出的 Phase 1 初调、Phase 2 大纲、本地代码勘察事实清单，以及 2026-11-06 12:23 由主理人补充检索得到的一手证据。
**最终交付报告**：同目录 `CODESYS4_WebIDE_对标差距与下一步建议_2026-11-06.md`

---

## 一、歧义辨析结论（Phase 1 定稿口径）

**主判断（证据充分）**：「退出」是「推出」的笔误，所指为 2026 年 9 月 CODESYS 官方推出的 **CODESYS 4**（web-based IEC 61131-3 IDE，前称 CODESYS go!）。

- 官方命名链：官网「CODESYS®4 The web-based development environment」、官方 Webinar「the new web-based IDE for PLCs」、官方新闻稿「Web-based development environment for IEC 61131-3」。
- 时间吻合：用户 2026-11-06 提问，距 2026-09-23/24 发布约 6 周，恰是新推出舆情窗口；SPS 2026（11/24–26）展前预热同期。
- 中文侧同期报道《CODESYS 4 —— 新一代工业控制器开发平台正式发布》。

**次判断（有实据）**：若「退出」确有所指，最可能是「CODESYS go!」这一**名称**的退出（更名），而非产品退出。SPS 2026 官方展商文案逐字写明「CODESYS 4 (formerly "CODESYS go!")」。2025 全年官方 Roadmap（Q2/Q3/Q4）均用 go!，2026-02 官网新闻仍用 go!，2026-09 正式定名 CODESYS 4。**未检索到官方独立更名公告**——此为多份官方材料交叉推断，非官方声明体。

**可排除**：不存在「CODESYS WebIDE 产品下线/退出市场」的官方或媒体证据。官方停更清单（Last update 2026-10-06）逐条列出停产产品（V2.3、Profibus、UML、SVN、OPC DA Server、Qt4、CAA 库、V2.3 Converter 等），**无任何 WebIDE / go! / CODESYS 4 条目**；官方明确「There are no plans to discontinue it（V3）」。4 轮中英文检索未找到浏览器 IDE 退出原因分析报道。**「退出时间/官方说明/业界归因」维度来源不足，禁止补写或推测。**

**概念误用可能（推断，无直接证据）**：用户可能把 Automation Server 的 Web 端项目能力或 WebVisu 的浏览器画面记忆为「WebIDE」。二者均非浏览器内 PLC 编程 IDE，且均未退出。

---

## 二、Phase 1 研究摘要要点（初调产出）

### 定义与背景
CODESYS 是德国 CODESYS Group（原 3S-Smart Software Solutions，1994）推出的厂商无关 IEC 61131-3 自动化平台，由桌面 IDE「CODESYS Development System」与设备侧 Runtime 构成，支持 ST/LD/FBD/SFC/IL/CFC，编程工具免费、商业收入主要来自 Runtime 授权。CODESYS 4 是与 V3 并行的**第二套**编程系统，复用同一编译器、库与运行时。

### 易混淆产品辨析
| 产品 | 实质 | 是否编程 IDE |
|---|---|---|
| CODESYS 4 | web-based IEC 61131-3 开发环境 | 是 |
| CODESYS WebVisu / Visualization | HMI 画面以 HTML5 canvas 渲染到浏览器，工程仍在桌面 IDE 完成 | 否 |
| CODESYS Automation Server | 浏览器端设备/工程管理 SaaS（AWS 法兰克福）或 On-Premises；Engineering 依赖桌面 IDE 的 Connector Add-on 同步项目 | 否 |
| Virtual Control SL / Edge Gateway | 容器化虚拟 PLC / 安全网关 | 否 |

### 产品能力（首版 1.0.0.0）
- **有**：ST（语法高亮/补全/悬浮提示）+ LD（v0.1，仅基础离线）；目录化工程；c4-cli；下载后变量监视与 watchlist；Git 版本控制。
- **明确无**：Online Change、断点、变量强制/写入、梯形图在线能流、FBD/SFC/CFC/IL、EtherCAT 等现场总线、可视化/运动/安全、重构、交叉引用、全局撤销重做、静态分析、单元测试、PLC 通信 TLS/证书认证、内置多人实时协同。
- **仅放行两个生产场景**：ST/LD 库开发 + CI/CD 自动构建；Modbus TCP 小型设备项目。

### 技术架构
浏览器只做 UI，编译/工程管理/控制器通信在**后台进程**；Windows 下自开窗口无需单独浏览器。c4-cli 无界面编译（save-compiled / pack / bootapp compile / install / restore / resolve / check）。工程为目录化 JSON/XML/纯文本（.fbslib/.fbsdev/.fbsws），Git 可 diff/merge，Libraries.lock.json 含 SHA384 与语义化版本。三种部署：本地单用户（Win/Linux x64、Linux ARM64）、团队共享 Linux 服务器（每会话独立进程、需外部反向代理）、控制器上。**非云服务、不需互联网、非订阅**。经 CODESYS Gateway 3.5+ 下装，首版仅自家 CODESYS Control SL 运行时获准。6–8 周一个完整版本，不设 SP/补丁。

### 商业与生态
免费至 2028 年底，无需 License；最早 2029 年纳入 Professional Developer Edition 收费；V3 继续免费；CI/CD 构建机首版不需单独许可。V3 有 30 万+ 用户、20+ 年现场验证，官方明确不替代、无停产计划。研发始于 2020，2023-05-10 Technology Day 首次公开（当时名 go!）。**CODESYS 4 的 OEM 采用案例/用户数/营收：来源不足。**

### 官方 AI 立场
CODESYS Development System MCP Server 1.0.0.0（2026-04-28）提供 browse_project_tree / get_structured_text_content / check_for_errors，形成 generate → check（编译器错误回喂）→ correct 闭环。SPS 2026 AI 专题明确「CODESYS does not take a purely "browser-based chatbot" approach」「Engineering remains responsible」，强调版本控制、测试、静态分析仍是不可让渡的准绳。SPS 2026 展商文案写明 CODESYS 4 为 CI/CD 与「AI agents working directly on the project files」准备。

### 落地阻力（正反两面）
- 反面：离线/空气隔离与数据主权；per-seat 许可与厂商锁定；浏览器仿真与物理扫描周期语义断层；Web 化新增攻击面（默认免认证本地端口、命令拼接、特权容器逃逸）。
- 正面/对冲：官方 On-Premises 明确支持 isolated networks / offline operation；CI/CD 文本工程带来可测可回滚收益；学术侧 LLM4PLC（ICSE-SEIP 2024）用语法检查器+模型检查器把生成成功率 47%→72%，Adnyana & Schwung（MLwA 2026）在 25 个真实用例、21 种提示技术、跨 TIA Portal 与 TwinCAT 上得出「提示结构对确定性与正确性的影响大于 LLM 选型」。

### 竞品全景（初调）
西门子 SIMATIC AX（VS Code + Git + 包管理 + 单元测试）、TIA Portal Cloud（云端托管 TIA，非浏览器原生 IDE）、Engineering Copilot TIA（生成式 AI，beta 集成 TIA V19/V20）；倍福 TwinCAT CoAgent；国产宝信「天行 IDE」（B/S + 云原生 + DeepSeek，2025 CIIF 大奖，MIR 称国内唯一量产 B/S，来源强度中等）；德国 SDA 的 IDEaaS；开源 OpenPLC / Beremiz（均桌面本地，非浏览器 IDE）。

---

## 三、已收集来源池（18 条，Phase 1 真实检索所得）

1. [CODESYS 4 – The web-based development environment](https://www.codesys.com/products/engineering/codesys-4) — 官方 2026 — 定义、v1.0.0.0 自 2026-09-24 可用、同编译器/库/运行时、首版仅 ST+LD、后台进程编译、非云服务、免费至 2028 底、不替代 V3。
2. [CODESYS 4 Version 1.0.0.0 is available](https://www.codesys.com/company/news-center/latest-news/codesys-4-version-1000-is-available/) — 官方 2026 — c4-cli、目录化工程、Libraries.lock.json、两种生产场景、SP18/Gateway 3.5 要求。
3. [CODESYS 4（Store 产品页）](https://us.store.codesys.com/codesys-4.html) — 官方 2026 — 商品号 2101000024、三平台分发、.NET 8 / 3GB RAM、No license is required、TLS/证书认证不支持、多用户服务器需外部反向代理。
4. [Interview with Kevin Ketterle about CODESYS 4](https://www.codesys.com/company/news-center/interviews/interview-with-kevin-ketterle-about-codesys-4/) — 官方 2026 — Head of Web Based Platforms：2023-05 宣布、定位 V3 补充、技术工人短缺动机、EtherCAT/可视化/Soft Motion 优先级。
5. [CODESYS Releases & Updates](https://us.codesys.com/ecosystem/up-to-date/release-lifecycle/releases-updates/) — 官方 2026 — 更新日志；Webinar 标题「new web-based IDE for PLCs」；MCP Server 1.0.0.0（2026-04-28）。
6. [SPS 2026 CODESYS 4 新闻稿 PDF](https://api-it.codesys.com/fileadmin/user_upload/CODESYS_Group/Unternehmen/News-Center/Pressezentrum/SPS-2026/CODESYS-Presse-SPS-2026-CODESYS-4-EN.pdf) — 官方 2026 — 9/23 可用、c4-cli 无界面编译、文本工程 + Git、EtherCAT alpha 计划 2027。
7. [Roadmap 2025 Q2 PDF](https://api-us.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Roadmap_2025_Q2.pdf) — 官方 2025 — go! 完整规划：2020 启动、2023-05-10 首秀、四种部署、ST+LD、V1.0.0 计划 2025 年底。
8. [Roadmap 2025 Q4 PDF](https://api-us.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Roadmap_2025_Q4.pdf) — 官方 2025 — 首版改 2026-04、仅复用 V3 编译器、聚焦简单应用与库 CI/CD、2028 后收费。
9. [Roadmap 2025 Q3 PDF](https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Roadmap_2025_Q3.pdf) — 官方 2025 — AI 路线图：Help Chatbot、ST 补全（微调 LLM）、MCP、Raw ST parser。
10. [Press releases on SPS 2025](http://us.codesys.com/company/news-center/press-releases/press-releases-sps-2025?trk=public_post_comment-text) — 官方 2025 — 「showcasing CODESYS go! as a web-based development interface ahead of its planned release in April 2026」。
11. [Platform-independent programming, productive manufacturing](https://us.codesys.com/company/news-center/interviews/platform-independent-programmingproductive-manufacturing/) — 官方 2026 — V3 是纯 Windows 工具（Linux 仅 VM），go! 后端 Win/Linux、前端浏览器、可装在控制器上。
12. [SPS 2026 官方展商页](https://sps.mesago.com/nuernberg/en/exhibitor-search.detail.html/codesys-gmbh-a-member-of-the-codesys-group/mf_6_0050331023_5263067_10000128202601.html) — 展商提交（归类待复核）2026 — **决定性证据**「CODESYS 4 (formerly CODESYS go!)」；基于开源 .NET；为 CI/CD 与 AI agents 直接操作项目文件准备。
13. [Discontinuations 官方停更清单](https://www.codesys.com/eco-system/up-to-date/release-lifecycle/discontinuations/) — 官方 2026-10-06 — **反证核心**：无任何 WebIDE/go!/CODESYS 4 条目。
14. [CODESYS Automation Server 官方 Datasheet PDF](https://api-de.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Datasheets/codesys_automation_server_en.pdf) — 官方 — Engineering 实为桌面 IDE Connector 同步项目 + 简单 merge，浏览器侧不做编程。
15. [CODESYS Visualization / WebVisu 产品页](https://www.codesys.com/products/visualization/) — 官方 — HTML5 canvas 运行时 HMI 显示，非编程 IDE。另见 [WebVisu SL 数据手册](https://store.codesys.com/media/n98_media_assets/files/2304000004-F/4/CODESYS%20WebVisu%20SL_en.pdf)。
16. [AI in CODESYS: work even more efficiently](https://www.codesys.com/products/engineering/ai-supported-engineering/) — 官方 2026 — MCP Server 获 2026 年度产品、自动纠错、支持云 AI 与本地 LLM。
17. [CODESYS AI-supported Engineering at SPS 2026](https://www.codesys.com/codesys-ai-supported-engineering-at-the-sps-2026/) — 官方 2026 — **关键立场**：不走纯浏览器 chatbot、generate-check-correct 闭环、Engineering remains responsible。另见 [MCP Server Datasheet](https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Datasheets/CODESYS_Development_System_MCP_Server_en.pdf)。
18. [Siemens SPS 2025 新闻稿 PDF：Engineering Copilot TIA](https://assets.new.siemens.com/siemens/assets/api/uuid:7c447a50-fb36-40fc-b438-19eba5d3f839/HQDIPR202511217291EN.pdf) — 官方 2025 — 生成式 AI、自然语言自动生成/修改工程元素、beta 集成 TIA V19/V20、托管服务交付、试点客户 F. Zimmermann。

### 备选来源池
[AdoptAutomation: CODESYS 4 Is Out](https://adoptautomation.com/blog/plc/codesys-4)｜[ControlByte: CODESYS 4 Web-Based IDE](https://controlbyte.tech/?p=20262)｜[搜狐：CODESYS 4 正式发布](https://www.sohu.com/a/1092834518_313848)｜[西门子中国 SPS 2025 新闻稿](https://w1.siemens.com.cn/news/news_articles/21916.aspx)｜[TIA Portal 官方 FAQ](https://www.siemens.com/zh-cn/products/tia-portal/)｜[西门子博客 Industrial Operations X](https://blog.siemens.com/?p=71316)｜[Liam Bee: SIMATIC AX Explained](https://liambee.me/general/simatic-ax-explained-what-it-is-how-it-differs-from-tia-portal-and-how-to-prepare-without-a-licence)｜[Adnyana & Schwung, MLwA 2026](https://www.sciencedirect.com/science/article/pii/S2666827025001872)｜[Tran et al., ETFA 2024](http://puma.ub.uni-stuttgart.de/bibtex/1d38130fe0f3d60d45b83021b15b58178/isw-bibliothek)｜[Haag et al., LLM4Code 2025](https://scholar.google.dk/citations?citation_for_view=UdGRM5IAAAAJ%3AzYLM7Y9cAGgC&hl=en&view_op=view_citation)｜[波尔图大学 IEC 61499 Web-based IDE 论文](https://repositorio-aberto.up.pt/bitstream/10216/175663/2/786577.pdf)｜[ZONE.CI 新型 PLC 编程软件架构演进、安全风险分析](https://zone.ci/secarticles/wx/570008.html)｜[TrueSight 在线绘制的幻象](https://tsight.io/articles/20320025)｜[控制工程网：宝信天行 IDE](https://www.cechina.cn/Company/227040_136551/ProductDetail.aspx)｜[凤凰网专访宝信肖硌](https://v.ifeng.com/c/8mxjawHaVrU)｜[搜狐：工业 DevOps / SDA IDEaaS](https://www.sohu.com/a/860845959_313848)｜[腾讯新闻：15 个开源工业软件](https://news.qq.com/rain/a/20220913A02Z5600)｜[Automation Server Product variants](https://www.codesys.com/products/automation-server/product-variants/)｜[MeloAuto SPS 2025 综述](https://www.meloautotech.com/sps-2025-how-siemens-beckhoff-rockwell-abb-and-industry-leaders-are-shaping-the-future-of-industrial-automation)｜[Industrial Monitor Direct 浏览器 IDE 评估指南](https://industrialmonitordirect.com/it/blogs/knowledgebase/evaluating-browser-based-iec-61131-3-plc-programming-environments)｜[MIR 白皮书摘要](https://bg.sgpjbg.com/labels/zhongguodaxingplczizhukekongbaipishu/1/6906691.html)｜[Eurokommerz LLM4PLC 转述](https://eurokommerz.at/blog/local-ai-for-plc-programming-iec-61131-3)

---

## 四、口径差异与来源不足（全报告须遵守）

1. **发布日 9/23 vs 9/24**：官方产品页、Store、AdoptAutomation 写 2026-09-24；SPS 2026 新闻稿与展商议程写 09-23；官方发布新闻稿自身前后同时出现两者。统一表述「2026 年 9 月 23–24 日」并加注。
2. **最低 Runtime SP18 vs SP19**：官方发布新闻稿写 SP18，产品页/ControlByte/AdoptAutomation 写 SP19。以产品页 SP19 为准并标注差异。
3. **是否云服务**：正式产品页明确「not a cloud service and not offered as subscription software」「An Internet connection is not required」；SPS 2026 展商预热稿写「either on the controller, a local server, or in the cloud」。以后者为发布前宣传稿、以正式产品页为准。

**来源不足项（禁止编造补位）**：CODESYS 4 的 OEM 采用案例/用户数/营收；「WebIDE 退出原因」的官方说明与业界分析；Automation Server 浏览器端编辑能力细节；国产天行 IDE 一手技术文档。

**来源强度提示**：Industrial Monitor Direct、Eurokommerz、MIR 白皮书摘要页、搜狐译文属二手/行业转述，仅作辅助；SPS Mesago 展商页文案由 CODESYS GmbH 提交，按官方计但归类待复核。

---

## 五、补搜新增一手证据（2026-11-06 12:23，主理人执行）

> 这四轮检索补齐了 Phase 3 未能完成的「西门子专章」关键材料，其中若干事实直接改变差距判断，单列存档。

### A. Eigen Engineering Agent（西门子官方，证据强度高）

| # | 来源 | 关键事实 |
|---|---|---|
| A1 | [西门子中国：Eigen 工程智能体两项全新功能](https://w1.siemens.com.cn/press/NewsDetail.aspx?ColumnId=2&ArticleId=21970) | 2026-04 汉诺威工博会发布；VivaTech 2026 新增 ECAD 集成 + 符合行业规范的项目自动生成；**自然语言描述设备需求 → 自动生成可直接使用且符合行业规范的项目**；19 国 100+ 企业部署（ANDRITZ Metals、中科摩通 CASMT、Prism Systems）；执行效率 2–5 倍、工程效率 +50%、方案质量 +80%（官方营销口径）；两项新功能含在标准订阅内 |
| A2 | [Siemens Blog: The new AI agent doesn't just make suggestions—it gets the job done](https://blog.siemens.com/en/2026/06/the-new-ai-agent-doesnt-just-make-suggestions-it-gets-the-job-done) | 直接集成 TIA Portal；写 PLC 代码、生成 HMI 可视化、配置设备；**独立检查自己的工作并反复修正直至达到预设质量标准**；ECAD 读 XML/AML 生成 PLC tags；工程师用简单自然语言描述机器（工位、设备、行为），几分钟内生成完整标准项目，可直接在 TIA Portal 打开；明确「目标不是取代工程师」 |
| A3 | [Siemens 官方产品页：Eigen Engineering Agent](https://www.siemens.com/de-de/products/tia-portal/eigen-engineering-agent/) | 生成式 AI 助手，与 TIA Portal 连接；**支持 SCL 与 LAD 生成、生成测试逻辑、数秒内修复编译或语法错误**、Style-Guide 检查、批量属性修改、自动项目文档；HMI WinCC Unified JavaScript、驱动/硬件/PROFINET 配置；**需 TIA Portal V19/V20/V21 有效许可 + Industry Organization Account**；订阅制、1 个月免费试用 |
| A4 | [Siemens 新闻稿 PDF：Hannover Messe 2026 发布](https://assets.new.siemens.com/siemens/assets/api/uuid:7c20b450-d7b7-4e8b-9a02-cb4bde2c520c/HQCOPR202604187387EN.pdf) | **已 generally available（GA）**；多步推理 + 自我纠错，端到端执行并在交付前验证所有输出；对 100+ 客户试点；Prism Systems 用其创建/修改/导入 SCL 代码「缩短到数秒」 |
| A5 | [Siemens China 英文新闻稿：两项新能力](https://w1.siemens.com.cn/news_en/news_articles_en/21971.aspx) | 明确「生成的项目遵循 **Siemens Automation Framework**，西门子对 TIA Portal 项目结构的最佳实践参考」；ECAD 集成读 XML/AML、自动解决不一致、按实际硬件拓扑生成 PLC tags |

### B. TIA Openness 能力边界（与本项目 `tia_delivery.py` 直接相关）

| # | 来源 | 关键事实 |
|---|---|---|
| B1 | [GitHub: tia-openness 导入 LAD/FBD/SCL 指南](https://github.com/renanlido/tia-openness/blob/main/docs/guides/import-lad-fbd-scl-blocks.md) | 外部源只支持 `.awl/.scl/.db/.udt`，`GenerateBlocksFromSource()` 生成块；SCL 是可纯文本从头生成的唯一语言；LAD/FBD/GRAPH 无文本源，只能走 SimaticML 模板法。SimaticML 导入注意：**缺失实例 DB 不自动创建**、无块编号则自动分配、**导入后数据可能不一致必须编译**、单文件根对象须同类、XML 必须 well-formed；`ImportOptions.Override` 会先删后建 |
| B2 | [SIEMENS 官方：TIA Portal Openness Readme V18 中文](https://support.industry.siemens.com/cs/attachments/109815199/TIAPortalOpeness_zhCN_zh-CHS.pdf) | V18 起软件单元支持 `NamespacePreset`、PLC 块支持 `Namespace`；交叉引用信息可读；导入时实例特定属性（如起始值）可能丢失 |
| B3 | [SIEMENS 官方：TIA Portal Openness Readme 英文](https://support.industry.siemens.com/cs/attachments/109773802/TIAPortalOpenness_en-US.pdf) | 在线设备不支持写属性；V16 起 `IgnoreUnitAttribute` 可把块从 unit 导入到 non-unit composition |
| B4 | [Industrial Monitor Direct：源文件导入时 OB 编号分配](https://industrialmonitordirect.com/blogs/knowledgebase/s7-1200-ob-number-assignment-during-tia-portal-source-import) | **TIA Portal 无原生参数指定 OB 编号**，按导入顺序算法分配；要精确控制需预创建空 OB 预留号或用 Openness Scripter；西门子官方推荐 Global Libraries 而非源文件（行业来源，强度中等） |
| B5 | [PLC技术网：TIA Portal Openness 概述](https://bbs.plcjs.com/forum.php?mod=viewthread&tid=650511) | Openness 不能逐行编辑块内程序逻辑，生成走「外部源文件」或「SimaticML XML 导出→修改→覆盖导入」两条路线；SimaticML 不宜作长期存档格式（社区来源，强度中等） |

### C. Siemens Automation Framework（SIOS 109817223，与本项目口径直接相关）

| # | 来源 | 关键事实 |
|---|---|---|
| C1 | [SIOS 官方：Automation Framework V1.2 中文手册 PDF](https://support.industry.siemens.com/cs/attachments/109817223/109817223_Automation_Framework_DOC_V1_2_CN.pdf) | 交付含 TIA Portal 项目 `.zap`；使用 LGF / LPML(OMAC PackML) / LUC / LAF 等全局库；基于 ISA-88；要求 TIA Portal V19 Up3、S7-1500、WinCC Unified Panel、ProDiag/OPC UA |
| C2 | [SIOS 官方：Automation Framework v2.2 英文手册 PDF](https://support.industry.siemens.com/cs/attachments/109817223/109817223_AutomationFramework_DOC_V2_2_3_en.pdf) | **AF 架构遵循 ISA-88（CM/EM/Unit），默认 OMAC PackML 状态机**；标准实现方式是「每个 Unit 与每个 EM 各有独立 Software Unit」；软件单元建议按功能而非位置命名以便复用 |
| C3 | [PLC技术网：博途自动化框架正式发布](https://bbs.plcjs.com/forum.php?mod=viewthread&tid=652548) | SIOS 109817223 下载；涵盖 Unit 到 CM 级物理模型；**「PLC 结构的解决方案以软件单元为基础」**；LPMLV2022 模式状态管理器、OPC UA、ProDiag（社区来源，与 C2 官方手册互相印证） |
| C4 | [PLC技术网：AF 框架深度解析 V2.2.2](https://bbs.plcjs.com/thread-652457-1-2.html) | 六大固定软件单元（CentralFunctions/Global/Motion/ObjectsOfProjectLibraryUsed/Safety/用户应用层）；**AF 强制 OB 编号规则 ueet**（u=单元号、ee=EM 号、t=OB 类型：0 Startup / 1 Main / 2 ProDiag），例 OB2001＝Unit2 Main；AF 是参考模板不是开箱即用产品（社区深度解析，强度中等，但 OB 规则与官方手册可交叉核对） |
| C5 | [西门子「西有技术」：AF 十大亮点（微信公众号）](http://mp.weixin.qq.com/s?__biz=Mzg3NzYyOTU1Ng==&mid=2247518706&idx=2&sn=5cac74b2013d937b82b2f7ad644bf4cb&chksm=cee8b34cf2159cec9c5feb8bd0729aa6d44e0394ecb734b4f0725023baaffc199c12bfd7fcf7#rd) | AF 核心是预组态 TIA Portal 项目中的库、应用示例、硬件配置与编程最佳实践集合；强调软件单元带来可重用性、并行编程、易加单元测试与模拟；提供 SCL/LAD/Graph 多语言模板 |

**主理人标注（推断，非事实）**：
- A5 明确 Eigen 生成的标准项目「遵循 Siemens Automation Framework」；C2/C3 显示官方 AF 以软件单元为标准组织方式。而 PLC_chat PRD 明确选「AF Basic 文件夹版、不采用 AF V3 软件单元」。**两者是否同一档位、生成物能否互操作，目前无直接证据，属必须实测核实的方向性风险。**
- A3 显示 Eigen 需 TIA V19/V20/V21 许可且为订阅制；PLC_chat 走本地 Openness CLI，形态不同但终态同为 V19 编译零错误。
- B4 的「OB 编号无法原生指定」与 C4 的「AF 强制 ueet 编号规则」共同解释了本项目 `greenfield_upload.py` 中 `ob_entries` 留空、`tia_delivery.py` 中 `xml_package_unverified: True` 的技术根因。

---

## 六、Phase 2 报告大纲（5 章，用户已确认）

**标题**：《CODESYS 4 Web IDE 对标研究：行业格局、PLC_chat 能力差距与下一步行动路线图》

1. 「退出」实为「推出」的歧义定稿：CODESYS 4 Web IDE 能力边界、后台编译架构及形态/能力双维对照清单
2. 西门子 TIA 工程链与 PLC_chat「TIA V19 编译零错误」终态的同构映射：Copilot TIA / Eigen Agent / TIA Openness / SIMATIC AX 文本化工程 / Portal Cloud
3. 浏览器/云端工控 IDE 的行业路线与落地阻力：MCP 错误回喂闭环、天行 B/S 与 IDEaaS 方案，及离线/授权/扫描周期/攻击面对「坚持不做」的支撑
4. PLC_chat 工程形态与「自然语言→文本工程→编译零错误」双维逐项差距判定：四类归位及文档—代码越界、编译口径与「真机全绿」归属错位风险
5. 可逐条拍板的 PLC_chat 路线图：P0/P1/P2 编号项的「目标—验收口径—风险」三件套、「不建议做」理由与五条既定决策口径的兼容边界

**用户三项拍板**：① 5 章（含西门子 TIA 专章）；② 对标落点＝形态 + 能力两者都要；③ 建议颗粒度＝路线 + 验收 + 风险。

---

## 七、PLC_chat 本地现状勘察事实清单（只读，2026-11-06）

> 勘察范围 `C:/Users/vboxuser/Desktop/Project/Code/PLC_chat`，结论标签：已实现 / 部分实现·原型 / 仅有设想 / 未发现。

### 1. 架构
- **已实现** 主工程 `plc_project/`；gateway(8000) = Python 3.11+ / FastAPI + uvicorn，入口 `gateway/app/main.py`；web(5173) = React 19 + Vite 6 + TS 5.7，入口 `frontend/src/main.tsx`。
- **已实现** 两个 APIRouter：`plc.py` → `/api/v1/plc`（约 80 条 API）；`greenfield.py` → `/api/v1/plc/canvas/greenfield`（22 条 API）。
- **已实现** 子系统：`plc_engine/`、`industrial/tia_openness_cli/`（C# .NET 4.8.1 Openness CLI）、`agents/`、`knowledge/`、`runtime/`、`tests/`。
- **已实现** 起停走 `gf_macro` 的 launch/stop/status_plc_stack（AGENTS.md 强制）；`plc_gateway/` 已被 README 明确弃用。

### 2. 浏览器内 IDE 形态能力
| 能力 | 判定 | 证据 |
|---|---|---|
| Monaco / CodeMirror | **未发现** | `frontend/package.json` 无相关依赖，全量检索零命中 |
| 轻量 SCL 文本输入 | 部分实现 | `frontend/src/shell/SclPane.tsx:609-655` textarea；`canvas/sclHighlight.tsx` 仅关键字高亮 |
| Mermaid 渲染 | 已实现 | `shell/GreenfieldPanel.tsx:171-189` 懒加载 mermaid + render → SVG |
| React Flow 手动连线画布 | 已实现 | `GreenfieldPanel.tsx:8-16, 410-426`；`@xyflow/react ^12.12.0` + `elkjs` |
| 工程树 | 已实现（仅存量工作台） | `ProjectSidebar.tsx` / `WorkspacePanel.tsx`；Greenfield 三栏通道无工程树 |
| 编译按钮/进度 | 已实现 | `CompileDrawer.tsx`；Greenfield `GreenfieldGateBar.tsx:146-164` 有「生成标准 AF 博途工程」「写入博途（真机）」 |
| 在线调试/仿真/下载 PLC | **未发现（明确排除）** | `industrial/tia_openness_cli/README.md:59-60` 列 hard refuse；memory 2026-10-20 记录「零实现、永拒桩」 |
| 多用户协作 / WebSocket | **未发现（明确排除）** | CLI README:66 列 VCI/Multiuser/UMAC out of scope；`main.py` 无 WebSocket 端点 |

**整体判定**：对话驱动的工程工作台 + 画布，**不是浏览器内 IDE**。

### 3. Mermaid 生成与人工连线确认
- **已实现** 生成链：`services/plc/mermaid_gen.py`、`plc_engine/af/mermaid_parser.py`、`greenfield_draft_llm.py`、`greenfield_views.py`；四线契约见 `docs/24-io-db-mermaid-contract.md`。
- **已实现** 四 Tab：`GreenfieldPanel.tsx:47-54`（step_flow / flow / seq / state）。
- **已实现** 状态机：`plc_engine/af/greenfield_ports.py:21-29`（DRAFT/LINKABLE/VALIDATING/FROZEN/LOCKED）+ `greenfield_session.py:27-37` 合法迁移表；四个副作用计数器（ops/disk_writes/writebacks/generations，确认前恒 0）。
- **已实现** 硬门禁确认：前端 `GreenfieldGateBar.tsx:165-211`「确认图中架构与功能」；后端 `POST /confirm` → `greenfield_service.py:318-372` `confirm_and_freeze`（校验 explicit、report.ok、回执已确认、工程摘要已展示、`assert_no_side_effects()`，写盘 `specs/vN.json` 后迁 FROZEN）；`greenfield_session.py:118-140` 明确「确认必须由用户显式点击产生，系统不得代劳或超时自动推进」。
- **已实现** 连线数据模型：`plc_engine/af/greenfield_ir.py:1-9` 扁平注册表 + 全局 ID 引用 + `edges[]`；`greenfield_edges.py` 13 个 EdgeKind、12 组 LEGAL_EDGE_GROUPS、ALLOWED_EDGES 矩阵、10 类 ILLEGAL_EDGE_CATALOG 拦截码。
- **事实·文档与代码不一致**：`docs/greenfield/01-greenfield-prd.md:39,60` 与 `02-architecture.md:4` 声明「Phase 2 本轮不实现 / 只设计、不实现」；但 `greenfield.py:258-298` 已实现 `/generate`、`/deliver-tia`、`/download-package`，`greenfield_delivery.py:54` 已有 `AfGreenfieldDelivery` 实现体。**代码实况已越过文档声明的 Phase 1 边界。**

### 4. 工程生成与回写
- **已实现** 产物（`greenfield_delivery.py:5-8, 119-175`）：`blocks/<folder>/*.scl`（UDT、LAF/LBC 自举标准库块、Unit/EM0/EM 逻辑块、冻结标准访问 DB720/DB1900、FC_Compat_*、FC_IoMap_ReadWrite）、`PLCTags_Frozen.csv/.xml`、`io_retention_matrix.csv`、`af_verification_report.json`、`architecture_spec.md`、`manifest.json`。
- **部分实现·原型** XML 补充包（`tia_delivery.py:248-336`）：OB SimaticML XML、folders.json、README、manifest；**`:15-19 / :335 / :490-494` 自标 `xml_package_unverified: True`，「自产 XML 尚未在真机验证导入（K1 探针项）」**；ProDiag 类 OB 因 SecondaryType 未确证被跳过；文件夹 XML 可导入性未确证。
- **已实现** 回写方式 = TIA Openness C# CLI 一次性 spawn（非 MCP、非直接写 .zap19）；六步见 `tia_delivery.py:573-655`。`.zap19` 是输入/归档格式。
- **部分实现·原型** 编译校验：四层静态门禁 fail-closed（`tia_delivery.py:367-435`）；PCEC 事务/V0–V3（`:733-804`）；存量链 `compile_jobs.py` + `writeback_heal.py`（3 次自愈 + 熔断）；**边界**：`:806-883` TIA 不可用 → `status="tia_unavailable"` + 人工导入指引（HTTP 仍 200）；`:647` `compile_ok` 判定含 `"warning" in state.lower()`，与「编译零错误」口径不完全一致；README「TIA V19 真机验证全绿」指存量 HR001 重构链，不是 Greenfield 生成链。

### 5. DB 编号 / IO 表上传
- **已实现** 前端对话内上传：`GreenfieldChatFeed.tsx:6,38,131-141`（PDF/XLSX/CSV/SCL/TXT/DB，最多 5 个）、`GreenfieldLinkPanel.tsx:154-236`（上传 + 解析回执 + 「确认解析结果并锁定资料」）。
- **事实** 上传的是 DB 的 SCL 文本/文件与 IO 表，不是独立「DB 编号」字段；编号来自 `DATA_BLOCK "DB1900_..."` 名称本身（`db_import.py:5,37`）。`greenfield_upload.py:759-760` 明确「上传格式不含 OB 编号与调用顺序、F/安全块来源，未虚构条目，`ob_entries` / `safety_entries` 留空」；而 `greenfield_contract.py:30,44,144` 中 `ObEntry.number` 属契约六类物理不可变之一。
- **已实现** 解析：`io_import.py`（中英文表头别名）、`db_import.py`（STRUCT 嵌套、Array、BEGIN 初值）、`pdf_import.py`；`greenfield_upload.py:30-47, 664-796` 整批原子拒绝 + 明细回执 + 唯一性校验 + `contract_draft_hash`；`:517-520` 明确 DB offset 按声明顺序派生「无法证明与 TIA 实际字节偏移等价，绝不静默近似」。

### 6. 云端 / 账号 / 持久化 / 部署
- **未发现** 云端/多租户，且明确排除：`docs/07-openness-worker.md:93-97`「not a shared public service … rather than a multi-tenant server」；`config.py:21-22` DATABASE_URL/REDIS_URL 默认 None；`store.py:1` in-memory Phase 1 stubs。
- **部分实现·原型** 账号仅 dev stub：`deps.py:27-77` 匿名放行 `usr_dev/ws_dev`、`ros_ak_` 前缀直过、`:64` 注释「validate signature later」；`config.py:24-37` jwt_secret 默认 `dev-insecure-change-me-32chars!!`。
- **部分实现·原型** 持久化：存量链 `session_store.py` 落盘到 temp dir；**Greenfield 通道明确纯内存、服务重启即清空**（`greenfield_session.py:1-5, 241-260`），靠用户主动导出/导入草稿 JSON 防丢失。
- **部分实现·原型** 版本管理：产品规格 vN（`FrozenSpec`: spec_version/spec_hash/frozen_at/frozen_by/ir_snapshot），`specs/vN.json` 可复现；产品内无 Git 分支/合并/回滚。
- **未发现** 生产发布部署：`docker-compose.ci.yml` 仅 CI 容器；`services.toml` 是本机 127.0.0.1 devctl；`docs/07-openness-worker.md` 的 Docker Gateway + nginx + Windows Worker 是设计拓扑非实装。

### 7. CODESYS / WebIDE 相关既有痕迹
- **仅有设想** 唯一「Web IDE」字样：`docs/plc_chat_v3_0.html:621`「前端交互与编排网关 (Web IDE / VS Code Plugin)」——V3.0 目标态蓝图非现状，memory 2026-11-02 明确记录。
- **仅有设想** `docs/03-PLC-IR-Schema.md:10` 列「Codesys FBD」为计划支持输入格式，未发现解析器。
- **仅有设想/排除性备注** `docs/26-v3_0-progress-audit.md:110-113` 博世 OpCon 基于 CoDeSys 2.2、与 TIA/S7/Openness 不同生态；`01-greenfield-prd.md:61` 明确不做。
- **未发现** 以 Automation Server / WebIDE / 浏览器内 IDE 为主题的既有调研、TODO 或设计稿（多处目录检索零命中）。

### 8. 文档与决策口径
- `README.md:3` 仍是 v3.0 存量口径（离线解析 → PLC-IR → 知识图谱 → 数字孪生画布 → NL 编辑 → PCEC → TIA Openness 1:1 回写）；未包含 Greenfield 新通道。
- `docs/greenfield/01-greenfield-prd.md:19-26` 原始需求六条：AF = 西门子 AF SIOS 109817223 的 ISA-88 Unit/EM/CM + PackML；**AF Basic 文件夹版 + 命名空间前缀、不采用 AF V3 软件单元**；DB/IO 由对话上传；HMI 后置；存量重构链冻结。`:174-184` BR-1~BR-9（确认硬门禁、只读冻结契约、全 SCL + OB/文件夹 XML、强类型 IR、AF 档位统一、AF 隐形、复用优先+存量冻结、验收=回写 V19 编译零错误、PCEC 留痕）。
- `.workbuddy/memory/2026-11-05.md:3-13` Greenfield 方向提案与 6 项待拍板；`2026-11-02.md:8-13,87-99` V3.0 蓝图 vs 现状「离线文件管道与在线 Openness 管道尚未合流」、真机 V19 四轮验收、无头链路必须 `do_compile=false`。
- `AGENTS.md` 起停必须用 GraphFlow 宏；知识图谱在 `plc_project/.graphflow/`。

### 勘察边界
未展开断言：`02-architecture.md` 全文（102KB，仅检索关键段落）、`App.tsx` 全文（3349 行，仅检索挂载点）、docs 下 PDF/ZIP 二进制资料包、`.mimosa/hook-state` 源码快照。第 2 节「在线调试/协作」、第 6 节「云端/生产部署」结论均为「未发现证据」且在文档中明确 out of scope，非凭目录名推断。

---

## 八、执行中断记录

- Phase 1 初始调研：完成（500–1000 字摘要 + 歧义辨析 + 18 条来源池），耗时约 11 分 52 秒。
- Phase 2 大纲：完成（4 章 v2 → 用户拍板改 5 章 → v3 已确认）。
- Phase 3.1 第 1–3 章深研：**课题研究员运行 21 分 20 秒后因 `502 网络连接被中断（read ECONNRESET，target: https://wb.tencentbuddy.com）` 失败，零草稿回传**。不得以任何形式代为补写或暗示其已完成。
- 后续处理：用户于 2026-11-06 12:22 拍板「方案 1」—— 先落盘保存已有成果，再由主理人直接接手撰写差距与建议；专家团队工作流随即停止。
- 主理人补搜：2026-11-06 12:23 执行 3 轮检索（Eigen Engineering Agent、TIA Openness 限制、SIOS 109817223 AF），结果见第五节。
