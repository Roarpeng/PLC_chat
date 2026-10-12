"""Unit tests — PLC agent node, industrial planner steps, mcp-plc tools."""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from agents.planner import build_rule_based_plan
from agents.plc.node import run as plc_run
from agents.registry import get_agent_registry
from agents.supervisor import AGENT_TO_NODE, decide_route
from industrial.connectors.plc_docs import FakePlcDocsConnector, PlcDocEntry
from runtime.researchos_runtime.graph import WORKER_AGENTS, build_graph
from runtime.researchos_runtime.mcp_client import MCPClient
from runtime.researchos_runtime.settings import RuntimeSettings
from runtime.researchos_runtime.state import TaskStatus, initial_state
from tools.plc import server as plc_server

TIA_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"


def test_registry_contains_plc_agent():
    reg = get_agent_registry()
    assert "plc" in reg
    assert "plc" in WORKER_AGENTS
    assert AGENT_TO_NODE["plc"] == "plc"


def test_plc_node_happy_path():
    state = initial_state("tsk_plc", "Siemens S7 PROFINET commissioning")
    out = plc_run(state)
    assert out["evidence"], "expected manual evidence"
    assert all(e["meta"]["readonly"] is True for e in out["evidence"])
    blocks = out["analysis_results"]
    assert set(blocks) == {"plc_manuals", "plc_change_advice", "plc_safety"}
    assert not blocks["plc_manuals"]["gaps"]
    assert out["budgets"]["used_tool_calls"] == 1
    assert out["tool_traces"][0]["tool"] == "plc.manual.search"
    assert out["meta"]["plc_readonly"] is True
    assert out["route"] == "analysis"
    assert any(e["type"] == "plc.completed" for e in out["events"])


def test_plc_node_no_match_reports_gap():
    class EmptyConnector:
        def list_vendors(self) -> list[str]:
            return []

        def search(self, query: str, *, limit: int = 10) -> list[PlcDocEntry]:
            return []

        def get(self, doc_id: str) -> PlcDocEntry | None:
            return None

    state = initial_state("tsk_plc_empty", "unknown proprietary controller")
    out = plc_run(state, connector=EmptyConnector())
    assert out["evidence"] == []
    assert "no_plc_manual_matched" in out["analysis_results"]["plc_manuals"]["gaps"]
    assert (
        "missing_manual_reference_for_change_advice"
        in out["analysis_results"]["plc_change_advice"]["gaps"]
    )
    assert out["tool_traces"][0]["ok"] is False


def test_plc_node_safety_query_without_safety_reference():
    class UnsafeOnlyConnector(FakePlcDocsConnector):
        def search(self, query: str, *, limit: int = 10) -> list[PlcDocEntry]:
            hits = super().search(query, limit=limit)
            return [h for h in hits if "safety" not in h.tags] or super().search(
                "S7", limit=limit
            )

    state = initial_state("tsk_plc_safety", "safety interlock review for E-stop")
    out = plc_run(state, connector=UnsafeOnlyConnector())
    safety = out["analysis_results"]["plc_safety"]
    assert "safety_reference_missing" in safety["gaps"]


def test_plc_citations_resolve_through_citation_agent():
    from agents.citation.node import run as citation_run

    state = initial_state("tsk_plc_cite", "Siemens S7-1500 PROFINET")
    out = plc_run(state)
    merged = dict(state)
    merged["evidence"] = list(state.get("evidence") or []) + out["evidence"]
    merged["analysis_results"] = {**merged.get("analysis_results"), **out["analysis_results"]}
    cit_out = citation_run(merged)
    for block in cit_out["analysis_results"].values():
        for cid in block.get("citation_ids") or []:
            assert not str(cid).startswith("TMP:"), f"unresolved placeholder {cid}"


def test_planner_industrial_plan_contains_plc_step():
    industrial = build_rule_based_plan("alarm E2304 study", workflow="industrial")
    agents = [s["agent"] for s in industrial["steps"]]
    assert "plc" in agents
    assert agents.index("plc") < agents.index("analysis")
    default = build_rule_based_plan("same query")
    assert "plc" not in [s["agent"] for s in default["steps"]]


def test_supervisor_routes_plc_step():
    state = initial_state("tsk_route", "plc alarm study", workflow="industrial")
    state["plan"] = {
        "version": 1,
        "approved": True,
        "steps": [
            {"id": "S1", "title": "PLC", "agent": "plc", "status": "pending", "depends_on": []},
        ],
    }
    state["status"] = TaskStatus.RUNNING
    route, side = decide_route(state, auto_approve=True)
    assert route == "plc"
    assert side.get("agent") == "plc"


def test_mcp_plc_manual_tools_readonly():
    res = plc_server.plc_manual_search("siemens")
    assert res["ok"] and res["readonly"] and res["count"] >= 1
    assert res["results"][0]["readonly"] is True

    one = plc_server.plc_manual_get("plc_siemens_s7")
    assert one["ok"] and one["document"]["vendor"] == "Siemens"

    missing = plc_server.plc_manual_get("nope")
    assert missing["ok"] is False and missing["error"] == "not_found"

    vendors = plc_server.plc_vendors_list()
    assert "Siemens" in vendors["vendors"]


def test_mcp_plc_alarm_explain_requires_citation():
    res = plc_server.plc_alarm_explain("E2304")
    assert res["ok"] is True
    assert res["candidate_causes"]
    assert res["citation"] and res["citation"]["id"] == "plc_siemens_s7"

    unknown = plc_server.plc_alarm_explain("X9999")
    assert unknown["ok"] is False and unknown["error"] == "unknown_alarm_code"


def test_mcp_plc_program_download_forbidden_by_default(monkeypatch):
    monkeypatch.delenv("RESEARCHOS_PLC_ALLOW_DOWNLOAD", raising=False)
    res = plc_server.plc_program_download()
    assert res["ok"] is False
    assert res["code"] == "PLC_DOWNLOAD_DISABLED"

    # Even with the flag, device writes stay unimplemented
    monkeypatch.setenv("RESEARCHOS_PLC_ALLOW_DOWNLOAD", "true")
    res = plc_server.plc_program_download()
    assert res["ok"] is False
    assert res["code"] == "PLC_DOWNLOAD_NOT_IMPLEMENTED"


def test_mcp_plc_tia_analyze():
    res = plc_server.plc_tia_analyze(str(TIA_FIXTURES), project_name="MotorDemo")
    assert res["ok"] and res["readonly"]
    assert res["summary"]["FB"] == 1
    assert "#Running := ((#Start OR #Running)" in res["scl_sources"]["FB_Motor"]
    kg_ids = {n["id"] for n in res["knowledge_graph"]["nodes"]}
    assert "Block::FB_Motor" in kg_ids

    missing = plc_server.plc_tia_analyze("does/not/exist")
    assert missing["ok"] is False and missing["error"] == "export_dir_not_found"


def test_mcp_plc_project_analyze_export_dir(tmp_path):
    res = plc_server.plc_project_analyze(
        str(TIA_FIXTURES),
        result_dir=str(tmp_path / "pkg"),
        project_name="MotorDemo",
    )
    assert res["ok"] and res["readonly"]
    assert res["conversion_report"]["total_blocks"] >= 3
    assert (tmp_path / "pkg" / "converted_scl" / "FB_Motor.scl").exists()


def test_mcp_client_dispatches_tia_analyze():
    client = MCPClient(RuntimeSettings())
    result = client.call_tool(
        "plc.tia.analyze", {"export_dir": str(TIA_FIXTURES)}, task_id="t1"
    )
    assert result["ok"] is True
    assert result["result"]["readonly"] is True
    assert result["result"]["summary"]["Networks"] == 2


def test_plc_node_with_tia_exports():
    state = initial_state(
        "tsk_plc_tia",
        "convert Siemens TIA project to SCL",
        tia_export_dir=str(TIA_FIXTURES),
    )
    assert state["meta"]["plc_tia_export_dir"] == str(TIA_FIXTURES)
    assert state["goal"]["tia_export_dir"] == str(TIA_FIXTURES)
    out = plc_run(state)
    assert "plc_tia_analysis" in out["analysis_results"]
    block = out["analysis_results"]["plc_tia_analysis"]
    assert "#Running := ((#Start OR #Running)" in block["scl_sources"]["FB_Motor"]
    assert block["conversion_report"]["converted"] >= 1
    assert any(t["tool"] == "plc.tia.ingest" for t in out["tool_traces"])
    assert out["budgets"]["used_tool_calls"] == 2
    assert out["meta"]["plc_tia_analyzed"] is True


def test_mcp_client_dispatches_plc_tools():
    client = MCPClient(RuntimeSettings())
    result = client.call_tool("plc.manual.search", {"query": "compactlogix"}, task_id="t1")
    assert result["ok"] is True
    assert result["result"]["count"] >= 1

    blocked = client.call_tool("plc.program.download", {}, task_id="t1")
    assert blocked["ok"] is True  # transport ok...
    assert blocked["result"]["ok"] is False  # ...but tool refuses
    assert blocked["result"]["code"] == "PLC_DOWNLOAD_DISABLED"


def test_graph_industrial_pipeline_end_to_end(monkeypatch):
    monkeypatch.setenv("DEV_AUTO_APPROVE", "true")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    graph = build_graph(checkpointer=MemorySaver())
    state = initial_state(
        "tsk_ind", "包装线报警 E2304 排查与 Siemens 手册对照", workflow="industrial"
    )
    state["status"] = TaskStatus.RUNNING
    config = {"configurable": {"thread_id": "tsk_ind"}}
    result = graph.invoke(state, config)

    assert result.get("status") == TaskStatus.COMPLETED
    agents_ran = {
        e.get("payload", {}).get("agent")
        for e in result.get("events") or []
        if e.get("type") == "node_start"
    }
    assert "plc" in agents_ran
    assert "plc_manuals" in (result.get("analysis_results") or {})
    assert any(t.get("tool") == "plc.manual.search" for t in result.get("tool_traces") or [])
    assert result.get("result")
