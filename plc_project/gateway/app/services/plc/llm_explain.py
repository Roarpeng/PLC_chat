"""LLM 深度解释：把块的规则引擎结构化分析作为脚手架，交由 OpenAI 兼容端点生成工程师向解释。

配置（环境变量，缺一即视为未配置，端点返回 LLM_NOT_CONFIGURED）：
- PLC_LLM_BASE_URL  兼容端点根地址，如 https://api.openai.com/v1 或本地 Ollama http://127.0.0.1:11434/v1
- PLC_LLM_API_KEY   API Key（本地推理服务可给任意非空串）
- PLC_LLM_MODEL     模型名，如 gpt-4o-mini / deepseek-chat / qwen-plus / glm-4-flash
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class LlmNotConfigured(RuntimeError):
    """缺少 PLC_LLM_* 环境变量。"""


def llm_settings() -> dict[str, str] | None:
    base = os.getenv("PLC_LLM_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("PLC_LLM_API_KEY", "").strip()
    model = os.getenv("PLC_LLM_MODEL", "").strip()
    if not base or not key or not model:
        return None
    return {"base_url": base, "api_key": key, "model": model}


def build_explain_prompt(block: dict[str, Any], scaffold: dict[str, Any]) -> list[dict[str, str]]:
    """结构化提示词：系统角色 + 块数据 + 规则引擎预分析（脚手架）。"""
    system = (
        "你是一位资深西门子 PLC 工业自动化工程师。根据给定的块数据与初步分析，"
        "用中文写一段面向同行的深度解释：该块的工艺用途、控制策略（自锁/互锁/时序等）、"
        "信号语义、与其他块的协作关系、潜在风险或改进建议。"
        "直接输出正文（可分 3-5 个短段，可用「」强调信号名），不要开场白、不要复述数据。"
    )
    user = json.dumps(
        {
            "block": {
                "name": block.get("name"),
                "type": block.get("block_type"),
                "language": block.get("language"),
                "comment": block.get("comment", ""),
                "interface": block.get("interface", []),
                "networks": [
                    {"id": n.get("id"), "title": n.get("title", ""), "scl": n.get("scl_text", "")}
                    for n in block.get("networks", [])
                ],
            },
            "初步分析（规则引擎，供参考）：": scaffold,
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_chat_completions(
    messages: list[dict[str, str]],
    settings: dict[str, str],
    timeout_s: float = 60.0,
) -> str:
    """POST {base_url}/chat/completions（OpenAI 兼容），返回首个 choice 文本。"""
    url = f"{settings['base_url']}/chat/completions"
    payload = json.dumps(
        {
            "model": settings["model"],
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LLM 端点返回 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 端点不可达：{exc.reason}") from exc

    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LLM 响应格式异常：{json.dumps(body, ensure_ascii=False)[:300]}") from exc


def deep_explain_block(block: dict[str, Any], scaffold: dict[str, Any]) -> str:
    """入口：未配置抛 LlmNotConfigured；其余异常以 RuntimeError 携带可读信息。"""
    settings = llm_settings()
    if settings is None:
        raise LlmNotConfigured(
            "未配置 LLM：请在网关进程设置 PLC_LLM_BASE_URL / PLC_LLM_API_KEY / PLC_LLM_MODEL 后重启。"
        )
    return call_chat_completions(build_explain_prompt(block, scaffold), settings)
