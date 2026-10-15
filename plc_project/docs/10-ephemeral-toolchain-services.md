# 10 · 工具链微服务化调研：按需起停的语言服务架构

> 调研目标：不为本机安装每一种语言的 SDK；编辑哪种语言，就按需拉起对应的服务/工具进程，用完即退、不占资源。
> 结论先行：**本项目已经天然接近这个模型**——Openness 桥就是"按调用起、干完退"的样板；Python 侧用 uv 免装依赖；net481 运行时 Windows 自带。缺的只是一个统一的生命周期入口（建议做 `devctl`）与空闲自动退出策略。Docker 建议作为 CI/跨机一致性的可选后端，而非日常路径。

## 1. 现状盘点（2026-10 实测）

### 1.1 本机运行时

| 运行时 | 版本 | 状态 | 项目用途 |
|---|---|---|---|
| Python | 3.14.6 | ✅ 系统 | 网关 / agents / plc_engine（常驻服务 + 分析任务） |
| uv | 0.9.17 | ✅ | 临时依赖环境（`uv run --with fastapi ...`），全程未污染全局 |
| Node | 24.12.0 | ✅ 系统 | 前端 dev/build（仅编辑前端时需要） |
| dotnet SDK | 8.0.423 | ✅ | 仅构建 TiaOpenness.Server 用；**net481 运行时 = Windows 内置 .NET Framework，跑起来不需要 SDK** |
| Docker | CLI 29.6.2 | ⚠️ 已装、**守护进程未启动**（Docker Desktop 默认不常驻） | 可选容器后端 |
| podman / nix | — | ❌ 未装 | 备选 |

### 1.2 项目的语言-服务矩阵与生命周期属性

| 服务 | 语言 | 理想生命周期 | 可否容器化 |
|---|---|---|---|
| **Openness 桥**（TiaOpenness.Server.exe） | C# net481 | **按调用 spawn，干完退出**（现状即如此：网关每次操作拉起 `--cli`，结束进程消亡） | ❌ **永远不行**——Siemens.Engineering 走 .NET Remoting/COM，许可证绑定宿主机器，TIA Portal 必须装在宿主。这是工业软件的硬约束 |
| **网关**（FastAPI :8000） | Python | 开发时常驻、空闲可停；测试时一次性（pytest 即用即弃） | ✅ 可（Linux 容器） |
| **前端**（Vite :5173） | Node | 仅编辑前端时常驻；`npm run build` 是一次性任务 | ✅ 可（node:20 镜像 + 卷挂载） |
| **构建任务**（dotnet build / tsc / pytest） | 各语言 | 纯一次性 | ✅ `docker run --rm` 或语言原生临时环境 |

### 1.3 已经在用的"零安装"模式（值得显式承认）

- `uv run --no-project --with fastapi --with pytest ...`：每次运行临时组装环境，用缓存秒级启动，全局 Python 零污染。网关、全部后端测试都是这么跑的——**这就是"免装 SDK 的微服务"在 Python 上的实现**。
- Openness `--cli` 模式：进程级 serverless。本次实测冷启动 ≈ 数秒（attach 失败后新起无界面 TIA 实例除外——那是 TIA 本身的启动成本，任何方案都省不掉）。

## 2. 候选方案对比

### 方案 A：Docker/Podman 容器化（每语言一镜像）

`docker compose --profile web up` / `docker run --rm -v .:/app node:20 npm run build`

- 优点：环境彻底隔离、镜像可版本化、与 CI 天然一致、跨机器可复制。
- 缺点：
  1. **Docker Desktop 守护进程常驻 1–2GB 内存**——与"不占资源"目标直接冲突（本机 daemon 现在就是关的）；
  2. Windows 卷挂载 I/O 慢（前端 dev server 热更新会明显迟滞）；
  3. **Openness/TIA 无法进容器**（见 1.2），方案永远覆盖不了最关键的工业链路；
  4. 冷启动 = 拉镜像 + 起容器，比进程级慢一个量级。
- 定位：**CI / 交付一致性**用，不当日常开发路径。

### 方案 B：语言原生临时环境（uv / npx / dotnet tool）

- Python：`uv run --with ...`（现状）。Node：`npx` 一次性执行 + 局部 `node_modules`。C#：一次性构建，产物直接跑（net481 运行时系统自带）。
- 优点：零守护进程、零常驻内存、缓存秒级、**本机现状已是 90%**。
- 缺点：每语言一个心智模型；"服务"概念缺失（谁在跑、何时退，无统一视图）。

### 方案 C：轻量监督器（devctl）——推荐

一个百行级的入口脚本（Python 或 PowerShell），把"工具即进程"登记成清单：

```yaml
# services.yaml（示意）
services:
  gateway:
    start: uv run --no-project --with fastapi --with uvicorn --with pydantic-settings --with python-multipart --with httpx -- python -m uvicorn gateway.app.main:app --port 8000
    health: http://127.0.0.1:8000/health
    cwd: plc_project
    idle_timeout: 1800        # 无请求 30 分钟自动退出
  web:
    start: npm run dev
    cwd: plc_project/frontend
    idle_signal: tcp:5173     # 端口无人连接且 TTL 到期 → 退出
  openness-e2e:               # 一次性任务型
    start: TiaOpenness.Server.exe --cli ...
    once: true
```

```text
devctl up gateway        # 按需起（uv 免装依赖）
devctl up web            # 编辑前端时才起
devctl status            # 看谁在跑、空闲多久
devctl down --all        # 一键全退，资源归零
```

- 优点：统一入口与可见性；空闲 TTL 自动退（贴合"编辑完成就退出"）；Python/Node 零全局安装；**Openness 的 spawn-per-call 模式自然融入**（它甚至不需要 devctl 管理，网关自己就是它的监督者）。
- 成本：百行脚本 + 一份清单；无任何新基础设施。
- 本质：**方案 B 加一层生命周期壳**，而不是引入容器平台。

### 方案 D：DevContainer / Nix devenv

VS Code DevContainer（依赖 Docker）或 nix flakes（Windows 需 WSL2）。可复现性最强，但引入重基建（WSL/Docker 常驻），与"不占资源"矛盾，且同样解决不了 TIA 宿主绑定。**不推荐**。

## 3. 推荐架构

```text
┌─────────────────────────── Windows 宿主 ───────────────────────────┐
│                                                                    │
│  devctl（轻量监督器，按需/TTL）                                      │
│   ├─ gateway   [uv 临时环境]  ── 常驻(开发时段)，空闲30min自退        │
│   ├─ web       [node_modules] ── 仅前端编辑时存在                    │
│   └─ (一次性任务) dotnet build / npm build / pytest                  │
│                                                                    │
│  网关内部（无需 devctl）：每次 Openness 操作                          │
│   └─ spawn TiaOpenness.Server.exe --cli …  → 退出                   │
│        └─ 按需新起/附着 TIA Portal 实例（宿主绑定，不可容器化）        │
│                                                                    │
│  可选：Docker Desktop（默认关）→ CI/跨机一致性后端                    │
└────────────────────────────────────────────────────────────────────┘
```

要点：
1. **常驻面最小化**：开发时段只有网关（+编辑前端时的 vite）；其余全部事件驱动或一次性。
2. **"不装 SDK"的真相**：Python 依赖用 uv 免装；net481 运行时 Windows 自带（dotnet SDK 只在改 C# 代码重新构建时需要，构建完即可不再想它）；Node 已装但仅前端时使用。真正"每语言装全家桶"的场景不存在。
3. **Openness 是特例也是样板**：它证明了"宿主进程 + 按调用生命周期"在工业软件上是最优解；任何容器化方案都必须给它留宿主通道。
4. 资源对比（估）：全常驻（现状 debug 用）≈ 网关 200MB + vite 150MB + TIA 700MB×N；devctl 化后，闲置态 ≈ 0（TIA 是用户自开的除外）。

## 4. 落地清单（已实施 ✅ / 待办 ○）

1. ✅ `tools/devctl.py`：up / down / status / prune 四命令 + 空闲 TTL（纯标准库，tomllib 读 services.toml；中文 Windows 的 tasklist/taskkill GBK 输出已容错处理）；
2. ✅ `services.toml`：gateway（uv 免装环境 + CORS + Openness exe 环境变量）与 web（vite）两条服务定义 + gateway_test 一次性任务样例；
3. ✅ `docker-compose.ci.yml`：CI 用容器后端（gateway_test / web_build 两个一次性服务）；
4. ○ 网关空闲自退：devctl prune 按存活时长回收已可用；如需"无流量感知"的精细空闲判定，后续在网关加请求时间戳端点；
5. ✅ Openness 孤儿实例防护（实测）：spawn-per-call 模式下 CLI 退出即回收自有 TIA 实例，全程无残留；
6. ✅ 长操作防阻塞：`/canvas/confirm-writeback` 已改 `asyncio.to_thread`（Openness 分钟级操作不再冻结事件循环）。

## 5. 本次实测记录

- `TiaOpenness.Server.exe --cli status` → `opennessAvailable: true, opennessGroupInToken: true`（用户已在 Openness 组，无需提权）；
- `create-project`（博途关闭后一次成功）→ 真实 `CanvasE2E.ap19`；`create-device`（S7-1500 6ES7 511-1AK01-0AB0/V2.5，设备名 PLC_1）→ 成功保存；注意本机硬件目录无测试所用 S7-1200 型号，S7-1500 一次通过；
- **全链路回写实测通过**：画布 → 网关 `/canvas/confirm-writeback` → SCL 外部源 `GenerateBlocksFromSource` → **真实编译 0 Error / 0 Warning**。首跑暴露并修复了外部源方言四处偏差（END_VAR 结束符、VAR_STAT→VAR、声明区行内注释、块头注释），已同步修复后端 `get_full_scl` 与前端 SCL 预览，保持 1:1 一致；
- `create-device` 的 C# 侧鸡生蛋缺陷（open 在无 PLC 空工程上硬失败）与异常透传缺失已修复并重新构建；
- 博途 GUI 占用时：新起无界面实例会在 TIA 内部阻塞（疑似许可证/首跑对话框），**推荐工作方式：先关博途 GUI，或以 `/OpennessAccess` 参数启动以便 attach**；
- Docker daemon 未启动时 `docker ps` 直接失败——印证"容器常驻 = 资常驻"。
