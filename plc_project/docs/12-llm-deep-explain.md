# 12 · LLM 深度解释（配置即用）

解释卡的「深度解释」按钮把块的规则引擎结构化分析作为脚手架，交由 **OpenAI 兼容端点**生成工程师向中文解释（工艺用途、控制策略、信号语义、协作关系、风险与建议）。未配置时按钮可用，点击显示一次性配置指引，不报错。

## 启用（网关进程环境变量，三者缺一不可）

```
PLC_LLM_BASE_URL = https://api.openai.com/v1        # 或任意兼容端点：
                                                    #   DeepSeek https://api.deepseek.com/v1
                                                    #   通义千问 DashScope 兼容模式 /v1
                                                    #   智谱 https://open.bigmodel.cn/api/paas/v4
                                                    #   本地 Ollama http://127.0.0.1:11434/v1（key 任意非空）
PLC_LLM_API_KEY  = sk-...
PLC_LLM_MODEL    = gpt-4o-mini                      # deepseek-chat / qwen-plus / glm-4-flash / llama3 ...
```

配置后重启网关：`python tools/devctl.py 重新 up gateway`（或改 services.toml 的 gateway.env 后重启）。

## 链路

- 端点：`POST /api/v1/plc/canvas/explain-block`，body `{block, scaffold}`（scaffold = 前端规则引擎预分析）
- 服务：`gateway/app/services/plc/llm_explain.py`（提示词构造 + chat/completions 调用，60s 超时）
- 未配置 → 400 `LLM_NOT_CONFIGURED`（含指引）；端点失败 → 502 `LLM_CALL_FAILED`
- 测试：`tests/unit/test_llm_explain.py`（5 例：提示词结构 / 未配置分支 / **本地 mock OpenAI 端点全路径** / 端点错误码 ×2）
