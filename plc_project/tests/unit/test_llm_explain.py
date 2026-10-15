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
    for var in ("PLC_LLM_BASE_URL", "PLC_LLM_API_KEY", "PLC_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
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

    for var in ("PLC_LLM_BASE_URL", "PLC_LLM_API_KEY", "PLC_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(LlmNotConfigured):
        deep_explain_block(_block(), _scaffold())


# ---------------------------------------------------------------- mock 端点全路径

def test_deep_explain_via_mock_openai_endpoint(monkeypatch):
    from gateway.app.services.plc.llm_explain import deep_explain_block

    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
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
