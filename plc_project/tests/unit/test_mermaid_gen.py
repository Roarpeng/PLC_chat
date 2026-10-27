"""Mermaid 时序图生成（docs/24 C 线）：提示词 + 清洗 + mock LLM 端点全路径。

mock 端点模式沿用 test_llm_explain：本地 HTTPServer 伪装 OpenAI 兼容端点，
不打真实 LLM。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_MERMAID_SAMPLE = """sequenceDiagram
    participant OPR as 操作员
    participant CV as 输送带
    participant RN as 机器人
    OPR->>CV: 启动请求
    CV-->>OPR: 运行反馈
    alt 工件到位
        CV->>RN: 到位信号=true
        RN->>RN: 抓取
        note over RN: 节拍 12s
    else 超时
        CV-->>OPR: 超时报警
    end"""


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


def _mock_llm_server(captured: dict, content: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(length))
            out = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": content}}]}
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


def _point_mock_llm(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("PLC_LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("PLC_LLM_API_KEY", "test-key")
    monkeypatch.setenv("PLC_LLM_MODEL", "mock-model")


# ---------------------------------------------------------------- 提示词

def test_build_mermaid_messages_structure():
    from gateway.app.services.plc.mermaid_gen import build_mermaid_messages
    from plc_engine.canvas_model import create_empty_canvas

    canvas = create_empty_canvas("Demo")
    msgs = build_mermaid_messages("画一条输送带时序", canvas)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "工艺时序图专家" in msgs[0]["content"]
    assert "sequenceDiagram" in msgs[0]["content"]
    assert "```" not in msgs[0]["content"].split("不要 markdown 代码围栏")[0]
    payload = json.loads(msgs[1]["content"])
    # 参与方线索：画布块名进 prompt；工艺描述在末尾（前缀缓存友好）
    assert any(b["name"] == "MotorCtrl" for b in payload["canvas"]["blocks"])
    assert list(payload)[-1] == "工艺描述"
    assert payload["工艺描述"] == "画一条输送带时序"


def test_build_mermaid_messages_accepts_raw_dict():
    from gateway.app.services.plc.mermaid_gen import build_mermaid_messages

    msgs = build_mermaid_messages("空画布", {"project_name": "P", "blocks": {}})
    payload = json.loads(msgs[1]["content"])
    assert payload["canvas"]["blocks"] == []


# ---------------------------------------------------------------- 清洗/校验

def test_sanitize_strips_markdown_fences():
    from gateway.app.services.plc.mermaid_gen import sanitize_mermaid_sequence

    fenced = f"```mermaid\n{_MERMAID_SAMPLE}\n```"
    assert sanitize_mermaid_sequence(fenced) == _MERMAID_SAMPLE
    # 裸代码原样通过
    assert sanitize_mermaid_sequence(_MERMAID_SAMPLE) == _MERMAID_SAMPLE


def test_sanitize_rejects_non_sequence_diagram():
    from gateway.app.services.plc.mermaid_gen import sanitize_mermaid_sequence

    with pytest.raises(RuntimeError):
        sanitize_mermaid_sequence("graph TD; A-->B")
    with pytest.raises(RuntimeError):
        sanitize_mermaid_sequence("   \n")


def test_participants_and_description():
    from gateway.app.services.plc.mermaid_gen import describe_mermaid, mermaid_participants

    names = mermaid_participants(_MERMAID_SAMPLE)
    assert names == ["OPR", "CV", "RN"]
    desc = describe_mermaid(_MERMAID_SAMPLE, "随便")
    assert "3 个参与方" in desc and "OPR" in desc
    # 无 participant 声明时回退到 prompt 摘要
    assert "时序图" in describe_mermaid("sequenceDiagram\nA->>B: x", "异常复位流程")


# ---------------------------------------------------------------- 服务层

def test_generate_not_configured(monkeypatch):
    from gateway.app.services.plc.llm_explain import LlmNotConfigured
    from gateway.app.services.plc.mermaid_gen import generate_mermaid_sequence

    _scrub_llm_env(monkeypatch)
    with pytest.raises(LlmNotConfigured):
        generate_mermaid_sequence("输送带启动时序", {})


def test_generate_via_mock_llm_strips_fences(monkeypatch):
    from gateway.app.services.plc.mermaid_gen import generate_mermaid_sequence
    from plc_engine.canvas_model import create_empty_canvas

    captured: dict = {}
    server = _mock_llm_server(captured, f"```mermaid\n{_MERMAID_SAMPLE}\n```")
    try:
        _point_mock_llm(monkeypatch, server.server_address[1])
        result = generate_mermaid_sequence("输送带启动时序", create_empty_canvas("Demo"))
        assert result["mermaid"] == _MERMAID_SAMPLE
        assert "3 个参与方" in result["description"]
        # 提示词进入 chat/completions，模型名/auth 正确，输出限长
        assert captured["path"] == "/v1/chat/completions"
        assert captured["body"]["model"] == "mock-model"
        assert captured["body"]["max_tokens"] == 2048
        assert captured["body"]["messages"][0]["role"] == "system"
    finally:
        server.shutdown()


def test_generate_invalid_output_raises(monkeypatch):
    from gateway.app.services.plc.mermaid_gen import generate_mermaid_sequence

    captured: dict = {}
    server = _mock_llm_server(captured, "这是一段解释文字，不是图。")
    try:
        _point_mock_llm(monkeypatch, server.server_address[1])
        with pytest.raises(RuntimeError):
            generate_mermaid_sequence("输送带启动时序", {})
    finally:
        server.shutdown()


# ---------------------------------------------------------------- 网关端点

def test_endpoint_not_configured(client):
    res = client.post(
        "/api/v1/plc/canvas/mermaid/generate",
        json={"prompt": "输送带启动时序", "canvas": {}},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "LLM_NOT_CONFIGURED"
    assert "PLC_LLM_BASE_URL" in detail["message"]


def test_endpoint_prompt_required(client):
    res = client.post(
        "/api/v1/plc/canvas/mermaid/generate", json={"prompt": "   ", "canvas": {}}
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "PROMPT_REQUIRED"


def test_endpoint_ok_via_mock_llm(client, monkeypatch):
    captured: dict = {}
    server = _mock_llm_server(captured, _MERMAID_SAMPLE)
    try:
        _point_mock_llm(monkeypatch, server.server_address[1])
        res = client.post(
            "/api/v1/plc/canvas/mermaid/generate",
            json={"prompt": "输送带启动时序", "canvas": {"project_name": "Demo"}},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["data"]["mermaid"].startswith("sequenceDiagram")
        assert "alt" in body["data"]["mermaid"]
        assert body["data"]["description"]
        # 参与方提示约束确实下发给了 LLM
        system = captured["body"]["messages"][0]["content"]
        assert "工艺时序图专家" in system
        assert "participant" in system
    finally:
        server.shutdown()


def test_endpoint_invalid_llm_output_is_502(client, monkeypatch):
    captured: dict = {}
    server = _mock_llm_server(captured, "抱歉，我无法生成。")
    try:
        _point_mock_llm(monkeypatch, server.server_address[1])
        res = client.post(
            "/api/v1/plc/canvas/mermaid/generate",
            json={"prompt": "输送带启动时序", "canvas": {}},
        )
        assert res.status_code == 502
        assert res.json()["detail"]["code"] == "LLM_CALL_FAILED"
    finally:
        server.shutdown()
