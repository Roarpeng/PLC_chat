"""T-E2E · 三份参考 PDF → 硬件拓扑 + 变量目录 + 步序流程图联动 → 对话增量修改 → 确认 → 生成标准 AF V1.2 博途工程包全链路回归。"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc import greenfield_chat as gfchat

PDF_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "greenfield" / "legacy_pdf"
PREFIX = "/api/v1/plc/canvas/greenfield"


def _b64_pdf(name: str) -> dict[str, str]:
    raw = (PDF_DIR / name).read_bytes()
    return {
        "filename": name,
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }


def test_full_pipeline_three_pdfs_to_af_tia_zip_package(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)

    # 1. 初始化会话
    st0 = client.get(f"{PREFIX}/state").json()
    assert st0["ok"] is True
    sid = st0["data"]["session_id"]

    # 2. 上传 3 份参考 PDF (PLC_IO.pdf + KUKA_DATA.pdf + PC_DATA.pdf)
    up = client.post(
        f"{PREFIX}/upload",
        json={
            "session_id": sid,
            "items": [
                _b64_pdf("PLC_IO.pdf"),
                _b64_pdf("KUKA_DATA.pdf"),
                _b64_pdf("PC_DATA.pdf"),
            ],
        },
    )
    assert up.status_code == 200
    receipt = up.json()["data"]["receipt"]
    assert receipt["status"] == "parsed"

    # 3. 确认回执并冻结兼容契约
    rc = client.post(f"{PREFIX}/receipt/confirm", json={"session_id": sid})
    assert rc.status_code == 200
    contract = rc.json()["data"]["contract"]
    assert contract["immutable"] is True
    assert len(contract["io_entries"]) == 113
    assert len(contract["db_structs"]) == 2

    # 4. 对话生成首版规格 (包含上料、钻孔/KUKA、压装/PC 工序)
    dr = client.post(
        f"{PREFIX}/draft",
        json={
            "session_id": sid,
            "project_name": "KukaDrillingCell",
            "prompt": "A工位与B工位旋转压紧上料，KUKA机器人换爪与水平垂直钻孔，上位机PC力位移曲线监控",
        },
    )
    assert dr.status_code == 200
    state = dr.json()["data"]
    hw = state["hardware"]
    hw_ids = {n["id"] for n in hw["nodes"]}
    assert "HW_CPU" in hw_ids
    assert "HW_KUKA" in hw_ids
    assert "HW_PC" in hw_ids
    assert any(h.startswith("HW_DI_") for h in hw_ids)
    assert any(h.startswith("HW_DO_") for h in hw_ids)
    assert hw["variable_catalog"]["counts"]["external_io"] == 113
    assert hw["variable_catalog"]["counts"]["external_db"] == 453
    assert hw["variable_catalog"]["counts"]["internal_vars"] > 0

    # 4.5 对话增量修改：LLM 产出 IRPatch → 白名单校验 → IR 生效并回流消息流
    first_step = state["ir"]["steps"][0]
    monkeypatch.setattr(
        gfchat,
        "llm_settings",
        lambda: {"base_url": "http://test.local", "api_key": "k", "model": "m"},
    )
    monkeypatch.setattr(
        gfchat,
        "chat_completion_raw",
        lambda messages, settings, **kwargs: (
            json.dumps(
                {
                    "intent": "edit",
                    "reply": "已把首步超时改为 8000ms",
                    "patches": [
                        {
                            "op": "set_ir_only_field",
                            "field_path": f"steps.{first_step['id']}.timeout_ms",
                            "value": 8000,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            {},
        ),
    )
    chat_res = client.post(
        f"{PREFIX}/chat",
        json={"session_id": sid, "message": "把首步超时改成 8000 毫秒"},
    )
    assert chat_res.status_code == 200
    chat_state = chat_res.json()["data"]["state"]
    steps_by_id = {s["id"]: s for s in chat_state["ir"]["steps"]}
    assert steps_by_id[first_step["id"]]["timeout_ms"] == 8000
    assert any(m["role"] == "assistant" and m["kind"] == "edit" for m in chat_state["messages"])

    # 5. 画布交互：绑定外部 DB720 变量到首步转换条件，验证步序流程图 Mermaid 实时同步
    first_step_id = state["ir"]["steps"][0]["id"]
    first_cm_id = state["ir"]["cms"][0]["id"]
    hw_patch = client.post(
        f"{PREFIX}/hardware",
        json={
            "session_id": sid,
            "op": "mount_cm",
            "cm_id": first_cm_id,
            "hw_node_id": "HW_KUKA",
        },
    )
    assert hw_patch.status_code == 200

    bind_res = client.post(
        f"{PREFIX}/hardware",
        json={
            "session_id": sid,
            "op": "bind_var",
            "var_key": "DB:DB720_KuKa_MainCtrl.CmdOut.di_ChgGrp_Ack",
            "target_id": first_step_id,
            "role": "condition",
        },
    )
    assert bind_res.status_code == 200
    step_flow = bind_res.json()["data"]["views"]["step_flow"]
    assert "DB720_KuKa_MainCtrl.CmdOut.di_ChgGrp_Ack" in step_flow["mermaid"]

    # 6. 确认前调用 /generate 必须被门禁 409 拒绝
    pre_gen = client.post(f"{PREFIX}/generate", json={"session_id": sid})
    assert pre_gen.status_code == 409

    # 7. 校验 → 工程视角摘要 → 显式确认冻结
    assert client.post(f"{PREFIX}/validate", json={"session_id": sid}).status_code == 200
    assert client.post(f"{PREFIX}/engineering-summary", json={"session_id": sid}).status_code == 200
    cf = client.post(
        f"{PREFIX}/confirm",
        json={"session_id": sid, "explicit": True, "frozen_by": "chief_engineer"},
    )
    assert cf.status_code == 200

    # 8. 冻结后生成标准 AF V1.2 博途工程包并下载 ZIP
    gen = client.post(f"{PREFIX}/generate", json={"session_id": sid})
    assert gen.status_code == 200
    delivery = gen.json()["data"]["delivery"]
    assert delivery["ok"] is True
    assert delivery["verification"]["linter_error_count"] == 0
    assert delivery["verification"]["single_writer_audit"]["ok"] is True
    assert delivery["verification"]["single_writer_audit"]["total_q_tags"] == 49
    assert delivery["verification"]["single_writer_audit"]["mapped_q_tags"] == 49
    assert delivery["verification"]["compat_integrity"]["ok"] is True

    dl = client.get(f"{PREFIX}/download-package?session_id={sid}")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(dl.content), "r") as zf:
        names = set(zf.namelist())
        assert "blocks/90_Compat_Frozen_Boundary/DB720_KuKa_MainCtrl.scl" in names
        assert "blocks/90_Compat_Frozen_Boundary/DB1900_Communication_PC.scl" in names
        assert "blocks/90_Compat_Frozen_Boundary/FC_Compat_DB720_KuKa_MainCtrl.scl" in names
        assert "blocks/90_Compat_Frozen_Boundary/FC_Compat_DB1900_Communication_PC.scl" in names
        assert "blocks/90_Compat_Frozen_Boundary/FC_IoMap_ReadWrite.scl" in names
        assert "plc_tags/PLCTags_Frozen.csv" in names
        assert "plc_tags/PLCTags_Frozen.xml" in names
        assert "audit/io_retention_matrix.csv" in names
        assert "audit/af_verification_report.json" in names
        assert "docs/architecture_spec.md" in names
        kuka_scl = zf.read("blocks/90_Compat_Frozen_Boundary/DB720_KuKa_MainCtrl.scl").decode("utf-8")
        assert "S7_Optimized_Access := 'FALSE'" in kuka_scl


def test_one_click_load_reference_fixture() -> None:
    client = TestClient(app)
    sid = client.get(f"{PREFIX}/state").json()["data"]["session_id"]
    resp = client.post(f"{PREFIX}/load-reference", json={"session_id": sid, "prompt": ""})
    assert resp.status_code == 200
    st = resp.json()["data"]
    assert st["has_ir"] is True
    assert st["has_contract"] is True
    assert st["counters"] == {"ops": 0, "disk_writes": 0, "writebacks": 0, "generations": 0}
    cat = st["hardware"]["variable_catalog"]
    assert cat["counts"]["external_io"] == 113
    assert cat["counts"]["external_db"] == 453


