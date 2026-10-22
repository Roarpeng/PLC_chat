# PLC_chat 工程约定

## 前后端启动 / 停止 —— 直接用 GraphFlow 宏,禁止重新推导命令

启动、停止、查看状态是高频固定操作,**必须**一步调用本地宏(0 LLM 推导),不要重新查脚本、拼命令:

```
gf_macro action:"run"  id:"launch_plc_stack"  rootDir:"<本仓库>/plc_project"   # 启动前后端 (gateway:8000 + web:5173)
gf_macro action:"run"  id:"stop_plc_stack"    rootDir:"<本仓库>/plc_project"   # 全部停止归零
gf_macro action:"run"  id:"status_plc_stack"  rootDir:"<本仓库>/plc_project"   # 查看服务状态
```

- 宏封装的是 `python tools/devctl.py up gateway / up web / down --all / status`(uv 兜底依赖,服务独立存活,日志在 `plc_project/.devctl/logs/`)。
- 图形化静默启动(含打开浏览器)等价物:`plc_project/启动项目.vbs` / `停止项目.vbs`。
- 宏定义存于 `plc_project/.graphflow/macros.json`;其余重复命令无需手写——宿主 Bash 的每次执行都会被记录并自动编译成新宏(重复 ≥2 次)。

## GraphFlow

- 本项目知识图谱存储在 `plc_project/.graphflow/`(不是仓库根)。调用 `gf_*` 工具时 `rootDir` 传 `<仓库>/plc_project`。
