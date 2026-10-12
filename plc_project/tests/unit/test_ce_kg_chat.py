"""CE demo: Main CALLS ce + USES ceD; chat SCL Markdown fence."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.flgnet_fold import attach_folded, fold_project
from agents.plc.tia.kg import build_knowledge_graph
from agents.plc.tia.simaticml import extract_project
from gateway.app.services.plc_jobs import _block_list, _logic_graph_from_kg, answer_block_chat

CE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_ce"


def test_ce_kg_main_calls_fc_and_uses_db() -> None:
    project = attach_folded(extract_project(CE, project_name="CeDemo"))
    kg = build_knowledge_graph(project)

    assert set(project.blocks) >= {"Main", "ce", "ceD"}
    assert kg.callees_of("Main") == ["ce"]
    assert kg.callers_of("ce") == ["Main"]
    assert "ceD" in kg.uses_of("Main")
    assert "IEC_Counter_0_DB" in kg.uses_of("ce")

    lg = _logic_graph_from_kg(kg.to_json())
    edges = {(e["type"], e["source"].split("::")[-1], e["target"].split("::")[-1]) for e in lg["edges"]}
    assert ("CALLS", "Main", "ce") in edges
    # Internal deps belong on knowledge canvas, not scan-cycle logic graph
    assert ("USES", "Main", "ceD") not in edges
    assert ("USES", "ce", "IEC_Counter_0_DB") not in edges

    from gateway.app.services.knowledge_extract import edges_from_plc_logic, nodes_from_plc_job

    job_seed = {
        "id": "plc_ce",
        "project_name": "CeDemo",
        "blocks": _block_list(project),
        "knowledge_graph": kg.to_json(),
    }
    plc_nodes = nodes_from_plc_job(job_seed, task_id="t", turn_id="u")
    k_edges = edges_from_plc_logic(job_seed, plc_nodes)
    by_id = {n["id"]: n["label"] for n in plc_nodes}
    k_pairs = {(e["label"], by_id.get(e["source"]), by_id.get(e["target"])) for e in k_edges}
    assert ("CALLS", "Main", "ce") in k_pairs
    assert ("USES", "Main", "ceD") in k_pairs
    assert ("USES", "ce", "IEC_Counter_0_DB") in k_pairs


def test_ce_chat_scl_markdown_fence() -> None:
    from agents.plc.tia.scl import convert_project_to_scl, translate_block_to_scl

    project = attach_folded(extract_project(CE, project_name="CeDemo"))
    kg = build_knowledge_graph(project)
    scl_sources = convert_project_to_scl(project)
    job = {
        "project_name": "CeDemo",
        "summary": {},
        "blocks": _block_list(project),
        "knowledge_graph": kg.to_json(),
        "folded_logic": fold_project(project),
        "scl_sources": scl_sources,
    }
    ce_scl = translate_block_to_scl(project.blocks["ce"])
    assert "VAR_INPUT" in ce_scl and "VAR_OUTPUT" in ce_scl and "END_VAR" in ce_scl
    assert 'FUNCTION "ce"' in ce_scl
    assert "END_FUNCTION" in ce_scl
    assert "// 含义：当 #in1 为 TRUE 时置位 #out1" in ce_scl
    assert "// 含义：调用计数器实例" in ce_scl

    text = answer_block_chat(job, "@ce 描述", "ce")
    assert "被调用：Main" in text
    assert "使用：IEC_Counter_0_DB" in text or "IEC_Counter_0_DB" in text

    scl_chat = answer_block_chat(job, "@ce 展开 SCL", "ce")
    assert "```scl" in scl_chat
    assert "VAR_INPUT" in scl_chat
    assert "END_VAR" in scl_chat
    assert '"IEC_Counter_0_DB"(CU := #in5, PV := 1, CV => #out3);' in scl_chat

    main = answer_block_chat(job, "@Main", "Main")
    assert "调用：ce" in main
    assert "使用：ceD" in main
