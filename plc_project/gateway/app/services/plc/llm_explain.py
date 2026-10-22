"""LLM 深度解释：把块的规则引擎结构化分析作为脚手架，交由 OpenAI 兼容端点生成工程师向解释。

配置（环境变量，缺一即视为未配置，端点返回 LLM_NOT_CONFIGURED）：
- PLC_LLM_BASE_URL  兼容端点根地址，如 https://api.openai.com/v1 或本地 Ollama http://127.0.0.1:11434/v1
- PLC_LLM_API_KEY   API Key（本地推理服务可给任意非空串）
- PLC_LLM_MODEL     模型名，如 gpt-4o-mini / deepseek-chat / qwen-plus / glm-4-flash

DeepSeek 回退：未设 PLC_LLM_API_KEY 时沿用 DEEPSEEK_API_KEY（先读进程环境变量，
再读 Windows 持久环境变量——setx 写入的注册表 User/Machine 作用域），此时端点与
模型缺省为 https://api.deepseek.com/v1 + deepseek-chat；显式 PLC_LLM_* 永远优先。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

_DEEPSEEK_DEFAULT_BASE = "https://api.deepseek.com/v1"
# DeepSeek 现行低价型号（官方文档模型名；deepseek-chat 为旧别名仍可用）
_DEEPSEEK_DEFAULT_MODEL = "deepseek-flash"
# V4 系列 thinking 默认开启会额外产出 reasoning tokens；问答/解释/ops 类任务
# 不需要，显式关闭省钱（仅对 deepseek 端点发送，避免污染其他兼容端点）。
_THINKING_OFF = {"type": "disabled"}


class LlmNotConfigured(RuntimeError):
    """缺少 PLC_LLM_* 环境变量。"""


def _registry_env_value(name: str) -> str:
    """读 Windows 持久环境变量（setx 写入的 User/Machine 注册表作用域）。

    网关进程可能派生自设置密钥之前启动的 shell（环境快照里没有该变量），
    这里直接查注册表拿最新值；非 Windows 或未设置返回空串。
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:  # 无注册表的运行时（如 pyinstaller 精简环境）
        return ""
    for root, path in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ):
        try:
            with winreg.OpenKey(root, path) as key:
                value, _type = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _resolve_deepseek_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip() or _registry_env_value("DEEPSEEK_API_KEY")


def llm_settings() -> dict[str, str] | None:
    base = os.getenv("PLC_LLM_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("PLC_LLM_API_KEY", "").strip()
    model = os.getenv("PLC_LLM_MODEL", "").strip()

    if not key:
        deepseek_key = _resolve_deepseek_key()
        if deepseek_key:
            key = deepseek_key
            base = base or _DEEPSEEK_DEFAULT_BASE
            model = model or _DEEPSEEK_DEFAULT_MODEL

    if not (base and key and model):
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


def _is_deepseek_endpoint(settings: dict[str, str]) -> bool:
    base = (settings.get("base_url") or "").lower()
    model = (settings.get("model") or "").lower()
    return "deepseek.com" in base or model.startswith("deepseek")


def chat_completion_raw(
    messages: list[dict[str, str]],
    settings: dict[str, str],
    *,
    timeout_s: float = 60.0,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    """POST {base_url}/chat/completions（OpenAI 兼容），返回 (首个 choice 文本, usage)。

    成本控制（依据 DeepSeek 开发文档）：
    - max_tokens 限制输出长度；
    - deepseek 端点显式关闭 thinking（V4 系列默认开启，问答/解释/ops 类任务
      不需要，白烧 reasoning tokens）；
    - usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens 供上层展示缓存
      命中情况——稳定前缀放消息前部即可吃到磁盘缓存低价。
    """
    url = f"{settings['base_url']}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "temperature": 0.3,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if _is_deepseek_endpoint(settings):
        payload["thinking"] = _THINKING_OFF
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
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
        text = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LLM 响应格式异常：{json.dumps(body, ensure_ascii=False)[:300]}") from exc
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return text, usage


def call_chat_completions(
    messages: list[dict[str, str]],
    settings: dict[str, str],
    timeout_s: float = 60.0,
) -> str:
    """POST {base_url}/chat/completions（OpenAI 兼容），返回首个 choice 文本。"""
    text, _usage = chat_completion_raw(messages, settings, timeout_s=timeout_s)
    return text


def chat_completion_stream(
    messages: list[dict[str, str]],
    settings: dict[str, str],
    *,
    timeout_s: float = 90.0,
    max_tokens: int | None = None,
):
    """SSE 流式 POST {base_url}/chat/completions。

    yield (delta_text, None) 逐段输出；流结束 yield ("", usage_dict)。
    deepseek 端点带 stream_options.include_usage 拿缓存计费字段
    （其他兼容端点不发送该字段，避免不兼容服务报错，代价是拿不到 usage）。
    """
    url = f"{settings['base_url']}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "temperature": 0.3,
        "stream": True,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if _is_deepseek_endpoint(settings):
        payload["thinking"] = _THINKING_OFF
        payload["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_s)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LLM 端点返回 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 端点不可达：{exc.reason}") from exc

    usage: dict[str, Any] = {}
    try:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(obj.get("usage"), dict):
                usage = obj["usage"]
            choices = obj.get("choices") or []
            if choices:
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    yield delta, None
    finally:
        resp.close()
    yield "", usage


def deep_explain_block(block: dict[str, Any], scaffold: dict[str, Any]) -> str:
    """入口：未配置抛 LlmNotConfigured；其余异常以 RuntimeError 携带可读信息。"""
    settings = llm_settings()
    if settings is None:
        raise LlmNotConfigured(
            "未配置 LLM：请设置 PLC_LLM_BASE_URL / PLC_LLM_API_KEY / PLC_LLM_MODEL，"
            "或用 setx DEEPSEEK_API_KEY <key> 配置 DeepSeek 后重启网关。"
        )
    text, _usage = chat_completion_raw(
        build_explain_prompt(block, scaffold), settings, timeout_s=60.0, max_tokens=1536
    )
    return text
