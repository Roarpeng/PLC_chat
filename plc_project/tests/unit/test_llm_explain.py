"""LLM 深度解释：提示词构造 + 未配置分支 + 本地 mock 端点全路径。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
    monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(tmp_path))
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    _scrub_llm_env(monkeypatch)
    from fastapi.testclient import TestClient

    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app
    from gateway.app.services import store as mem

    mem.store.plc_jobs.clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
    mem.store.plc_jobs.clear()


def _scrub_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离本机 LLM 配置：显式变量与 DeepSeek 回退（env + 注册表）全部清零。"""
    for var in (
        "PLC_LLM_BASE_URL",
        "PLC_LLM_API_KEY",
        "PLC_LLM_MODEL",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    from gateway.app.services.plc import llm_explain

    monkeypatch.setattr(llm_explain, "_registry_env_value", lambda _name: "")


def _block() -> dict:
    return {
        "name": "MotorCtrl",
        "block_type": "FB",
        "language": "SCL",
        "comment": "电机控制",
        "interface": [{"name": "Start", "data_type": "Bool", "section": "VAR_INPUT"}],
        "networks": [
            {"id": 1, "title": "hold", "language": "SCL", "scl_text": "IF #Start THEN\n    #Run := TRUE;\nEND_IF;", "status": "synced"}
        ],
        "status": "synced",
    }


def _scaffold() -> dict:
    return {"headline": "电机控制：自锁", "keywords": ["自锁"], "networks": [{"id": 1, "summary": "自锁逻辑"}]}


# ---------------------------------------------------------------- 提示词

def test_build_explain_prompt_structure():
    from gateway.app.services.plc.llm_explain import build_explain_prompt

    msgs = build_explain_prompt(_block(), _scaffold())
    assert msgs[0]["role"] == "system"
    assert "工业自动化工程师" in msgs[0]["content"]
    user = json.loads(msgs[1]["content"])
    assert user["block"]["name"] == "MotorCtrl"
    assert user["block"]["networks"][0]["scl"].startswith("IF #Start")
    assert "自锁" in json.dumps(user, ensure_ascii=False)


# ---------------------------------------------------------------- 未配置分支

def test_deep_explain_not_configured(monkeypatch):
    from gateway.app.services.plc.llm_explain import LlmNotConfigured, deep_explain_block

    _scrub_llm_env(monkeypatch)
    with pytest.raises(LlmNotConfigured):
        deep_explain_block(_block(), _scaffold())


# ---------------------------------------------------------------- DeepSeek 回退

def test_deepseek_env_key_fills_defaults(monkeypatch):
    from gateway.app.services.plc import llm_explain

    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-fallback")
    settings = llm_explain.llm_settings()
    assert settings == {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-env-fallback",
        "model": "deepseek-flash",
    }


def test_deepseek_registry_key_fills_defaults(monkeypatch):
    """setx 写注册表：网关派生自旧 shell（env 无此变量）时仍能取到。"""
    from gateway.app.services.plc import llm_explain

    _scrub_llm_env(monkeypatch)
    monkeypatch.setattr(llm_explain, "_registry_env_value", lambda name: "sk-reg" if name == "DEEPSEEK_API_KEY" else "")
    settings = llm_explain.llm_settings()
    assert settings is not None
    assert settings["api_key"] == "sk-reg"
    assert settings["model"] == "deepseek-flash"


def test_explicit_plc_llm_overrides_deepseek(monkeypatch):
    from gateway.app.services.plc import llm_explain

    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-fallback")
    monkeypatch.setenv("PLC_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("PLC_LLM_API_KEY", "explicit-key")
    monkeypatch.setenv("PLC_LLM_MODEL", "my-model")
    settings = llm_explain.llm_settings()
    assert settings == {
        "base_url": "http://127.0.0.1:9/v1",
        "api_key": "explicit-key",
        "model": "my-model",
    }


# ---------------------------------------------------------------- mock 端点全路径

def _mock_llm_server(captured: dict, content: str, usage: dict | None = None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(length))
            out = json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    **({"usage": usage} if usage else {}),
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):  # 静默
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _mock_sse_server(captured: dict, chunks: list[str], usage: dict | None = None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured["body"] = json.loads(self.rfile.read(length))
            lines = ["data: " + json.dumps(c, ensure_ascii=False) for c in chunks]
            if usage:
                lines.append("data: " + json.dumps({"choices": [], "usage": usage}))
            lines.append("data: [DONE]")
            out = ("\n\n".join(lines) + "\n\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):  # 静默
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_chat_completion_stream_deltas_and_usage(monkeypatch):
    """SSE 流式：逐段 delta + 末尾 usage；非 deepseek 端点不带 stream_options/thinking。"""
    from gateway.app.services.plc.llm_explain import chat_completion_stream

    captured: dict = {}
    chunks = [
        {"choices": [{"delta": {"content": "电机"}}]},
        {"choices": [{"delta": {"content": "自锁"}}]},
        {"choices": [{"delta": {}}]},
    ]
    usage = {"prompt_tokens": 20, "prompt_cache_hit_tokens": 8, "completion_tokens": 4}
    server = _mock_sse_server(captured, chunks, usage)
    try:
        port = server.server_address[1]
        _scrub_llm_env(monkeypatch)
        monkeypatch.setenv("PLC_LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setenv("PLC_LLM_API_KEY", "test-key")
        monkeypatch.setenv("PLC_LLM_MODEL", "mock-model")

        deltas: list[str] = []
        final_usage = {}
        for delta, u in chat_completion_stream(
            [{"role": "user", "content": "q"}],
            {
                "base_url": f"http://127.0.0.1:{port}/v1",
                "api_key": "test-key",
                "model": "mock-model",
            },
            max_tokens=3072,
        ):
            if delta:
                deltas.append(delta)
            elif u:
                final_usage = u
        assert "".join(deltas) == "电机自锁"
        assert final_usage["prompt_cache_hit_tokens"] == 8
        # 成本参数：流式 + 限输出；非 deepseek 端点不注入 stream_options/thinking
        assert captured["body"]["stream"] is True
        assert captured["body"]["max_tokens"] == 3072
        assert "stream_options" not in captured["body"]
        assert "thinking" not in captured["body"]
    finally:
        server.shutdown()


def test_chat_answer_stream_endpoint(client):
    """SSE 端点：未配置 → error 事件 + DONE（HTTP 200，状态码在首字节前已提交）。"""
    with client.stream(
        "POST", "/api/v1/plc/canvas/chat-answer/stream", json={"prompt": "q", "canvas": {}}
    ) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        text = "".join(res.iter_text())
    assert '"code": "LLM_NOT_CONFIGURED"' in text or '"code":"LLM_NOT_CONFIGURED"' in text
    assert text.rstrip().endswith("data: [DONE]")


def test_chat_answer_via_mock_llm(monkeypatch):
    """chat-answer 服务路径：骨架+相关块进 prompt、问题在末尾、usage 透传。"""
    from gateway.app.services.plc.chat_ops import answer_project_question, build_question_messages
    from plc_engine.canvas_model import create_empty_canvas

    captured: dict = {}
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_cache_hit_tokens": 40,
        "prompt_cache_miss_tokens": 60,
    }
    server = _mock_llm_server(captured, "这是项目分析回答。", usage)
    try:
        port = server.server_address[1]
        _scrub_llm_env(monkeypatch)
        monkeypatch.setenv("PLC_LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setenv("PLC_LLM_API_KEY", "test-key")
        monkeypatch.setenv("PLC_LLM_MODEL", "mock-model")

        canvas = create_empty_canvas("Demo")
        msgs = build_question_messages("该项目的运行逻辑", canvas, {"selected_block": "MotorCtrl"})
        assert msgs[0]["role"] == "system"
        payload = json.loads(msgs[1]["content"])
        # 稳定骨架在前（排序），相关块详情居中，问题在最后（前缀缓存友好）
        assert [b["name"] for b in payload["blocks"]] == ["MainDB", "MotorCtrl"]
        assert payload["relevant_blocks"], "选中块应进相关块详情"
        focus_row = next(b for b in payload["relevant_blocks"] if b["name"] == "MotorCtrl")
        assert "scl_preview" in focus_row
        assert list(payload)[-1] == "question"
        assert payload["question"] == "该项目的运行逻辑"

        result = answer_project_question("该项目的运行逻辑", canvas, {"selected_block": "MotorCtrl"})
        assert result["answer"] == "这是项目分析回答。"
        assert result["usage"]["prompt_tokens"] == 100
        assert result["usage"]["prompt_cache_hit_tokens"] == 40
        assert captured["path"] == "/v1/chat/completions"
        # 成本参数：限输出；非 deepseek 端点不注入 thinking
        sent_payload = captured["body"]
        assert sent_payload["max_tokens"] == 3072
        assert "thinking" not in sent_payload
    finally:
        server.shutdown()


def test_chat_answer_prefix_stable_across_questions(monkeypatch):
    """同一画布不同问题：question 之前的内容字节一致（DeepSeek 前缀缓存前提）。"""
    from gateway.app.services.plc.chat_ops import build_question_messages
    from plc_engine.canvas_model import create_empty_canvas

    canvas = create_empty_canvas("Demo")
    m1 = build_question_messages("该项目的运行逻辑", canvas, {}) or []
    m2 = build_question_messages("电机为什么不启动", canvas, {})
    u1 = json.loads(m1[1]["content"])
    u2 = json.loads(m2[1]["content"])
    assert u1["question"] != u2["question"]
    for key in ("project", "blocks", "hmi_widgets"):
        assert u1[key] == u2[key], f"前缀字段 {key} 应跨问题稳定"


def test_select_relevant_blocks_scoring():
    from gateway.app.services.plc.chat_ops import select_relevant_blocks
    from plc_engine.canvas_model import create_empty_canvas

    canvas = create_empty_canvas("Demo")
    # 默认 MotorCtrl 不跨块引用；补一条 "MainDB". 引用以验证邻居带出
    canvas.blocks["MotorCtrl"].networks[0].scl_text += '\n"MainDB".StartCmd := TRUE;'
    # 名字命中优先
    assert "MotorCtrl" in select_relevant_blocks("MotorCtrl 怎么不自锁", canvas)
    # 变量名命中（StartCmd 属于 MainDB）
    assert "MainDB" in select_relevant_blocks("StartCmd 是干什么的", canvas)
    # 选中块必进，且带出 SCL 引用邻居（MotorCtrl 引用 "MainDB".）
    picked = select_relevant_blocks("随便看看", canvas, focus_block="MotorCtrl")
    assert "MotorCtrl" in picked and "MainDB" in picked
    # k 上限
    assert len(select_relevant_blocks("块 块", canvas, k=2)) <= 2


def test_chat_answer_endpoint_not_configured(client):
    res = client.post(
        "/api/v1/plc/canvas/chat-answer",
        json={"prompt": "该项目的运行逻辑", "canvas": {}},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "LLM_NOT_CONFIGURED"


def test_chat_answer_endpoint_prompt_required(client):
    res = client.post("/api/v1/plc/canvas/chat-answer", json={"canvas": {}})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "PROMPT_REQUIRED"


def test_deep_explain_via_mock_openai_endpoint(monkeypatch):
    from gateway.app.services.plc.llm_explain import deep_explain_block

    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured["path"] = self.path
            captured["auth"] = self.headers.get("Authorization", "")
            captured["body"] = json.loads(self.rfile.read(length))
            out = json.dumps(
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": "这是深度解释正文。"}}
                    ]
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):  # 静默
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("PLC_LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setenv("PLC_LLM_API_KEY", "test-key")
        monkeypatch.setenv("PLC_LLM_MODEL", "mock-model")

        text = deep_explain_block(_block(), _scaffold())
        assert text == "这是深度解释正文。"
        assert captured["path"] == "/v1/chat/completions"
        assert captured["auth"] == "Bearer test-key"
        assert captured["body"]["model"] == "mock-model"
        assert captured["body"]["messages"][0]["role"] == "system"
        assert not captured["body"]["stream"]
    finally:
        server.shutdown()


# ---------------------------------------------------------------- 网关端点（TestClient）

def test_endpoint_not_configured_code(client):
    res = client.post(
        "/api/v1/plc/canvas/explain-block",
        json={"block": _block(), "scaffold": _scaffold()},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "LLM_NOT_CONFIGURED"
    assert "PLC_LLM_BASE_URL" in detail["message"]


def test_endpoint_block_required(client):
    res = client.post("/api/v1/plc/canvas/explain-block", json={})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "BLOCK_REQUIRED"
