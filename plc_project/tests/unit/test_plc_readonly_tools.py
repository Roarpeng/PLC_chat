"""Unit tests — read-only analysis tools added to mcp-plc (plc.st.parse /
plc.ld.summarize / plc.diff.routines / plc.opcua.read)."""

from __future__ import annotations

from pathlib import Path

from tools.plc import server as plc_server

TIA_EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
TIA_PARTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_parts"


# ---------------------------------------------------------------------------
# plc.st.parse
# ---------------------------------------------------------------------------

def test_st_parse_extracts_symbols_and_statements():
    res = plc_server.plc_st_parse("#Out := #In;\n#Out := #Out OR #In;")
    assert res["ok"] is True and res["readonly"] is True

    assert [s["kind"] for s in res["statements"]] == ["assignment", "assignment"]
    assert [s["text"] for s in res["statements"]] == ["#Out := #In", "#Out := #Out OR #In"]

    names = {s["name"] for s in res["symbols"]}
    assert names == {"#Out", "#In"}
    out_sym = next(s for s in res["symbols"] if s["name"] == "#Out")
    assert out_sym["kind"] == "local"
    assert out_sym["roles"] == ["write", "read"]
    assert out_sym["writes"] == 2
    in_sym = next(s for s in res["symbols"] if s["name"] == "#In")
    assert in_sym["roles"] == ["read"]

    assert res["diagnostics"] == []


def test_st_parse_classifies_global_and_absolute_and_call():
    res = plc_server.plc_st_parse('"HMI".StartCmd := %M0.5; FB_Motor(Start := #Go);')
    assert res["ok"] is True
    kinds = {s["name"]: s["kind"] for s in res["symbols"]}
    assert kinds['"HMI".StartCmd'] == "global"
    assert kinds["%M0.5"] == "absolute"
    assert kinds["#Go"] == "local"
    assert "call" in {s["kind"] for s in res["statements"]}


def test_st_parse_reports_syntax_diagnostics():
    res = plc_server.plc_st_parse("IF #a THEN #b := 1;")
    assert res["ok"] is True
    codes = {d["code"] for d in res["diagnostics"]}
    assert "unbalanced_if" in codes

    res = plc_server.plc_st_parse("#a := (1 + 2;")
    assert any(d["code"] == "unbalanced_parens" for d in res["diagnostics"])


def test_st_parse_empty_source_warns():
    res = plc_server.plc_st_parse("  (* nothing *)  ")
    assert res["ok"] is True
    assert res["statements"] == []
    assert any(d["code"] == "empty_source" for d in res["diagnostics"])


# ---------------------------------------------------------------------------
# plc.ld.summarize
# ---------------------------------------------------------------------------

def test_ld_summarize_single_block_from_dir():
    res = plc_server.plc_ld_summarize(str(TIA_EXPORTS), block="FB_Motor")
    assert res["ok"] is True and res["readonly"] is True
    assert res["block"] == "FB_Motor"
    assert len(res["networks"]) == 1
    net = res["networks"][0]
    assert net["title"] == "Self-holding motor start"
    assert net["statements"]
    assert any("#Running :=" in stmt and "#Start" in stmt for stmt in net["statements"])
    assert net["unresolved_parts"] == []


def test_ld_summarize_all_blocks_from_dir():
    res = plc_server.plc_ld_summarize(str(TIA_EXPORTS))
    assert res["ok"] is True
    names = {b["block"] for b in res["blocks"]}
    assert {"FB_Motor", "Main", "MotorInst"} <= names


def test_ld_summarize_single_xml_native_scl():
    res = plc_server.plc_ld_summarize(str(TIA_PARTS / "FC_NativeScl.xml"))
    assert res["ok"] is True
    assert res["block"] == "FC_NativeScl"
    assert res["networks"][0]["statements"] == ["#Out := #In;", "#Out := #Out OR #In;"]


def test_ld_summarize_missing_path_and_block():
    assert plc_server.plc_ld_summarize("does/not/exist")["error"] == "path_not_found"
    missing = plc_server.plc_ld_summarize(str(TIA_EXPORTS), block="Nope")
    assert missing["ok"] is False and missing["error"] == "block_not_found"


# ---------------------------------------------------------------------------
# plc.diff.routines
# ---------------------------------------------------------------------------

def test_diff_routines_added_removed_capped():
    res = plc_server.plc_diff_routines(str(TIA_EXPORTS), str(TIA_PARTS))
    assert res["ok"] is True and res["readonly"] is True
    assert res["added"], "expected added edges between differing projects"
    assert res["removed"], "expected removed edges between differing projects"
    assert len(res["added"]) <= 64
    assert len(res["removed"]) <= 64
    for edge in res["added"]:
        assert set(edge) == {"source", "target", "type"}
    assert res["added_total"] >= len(res["added"])
    assert res["removed_total"] >= len(res["removed"])


def test_diff_routines_identical_dirs_no_diff():
    res = plc_server.plc_diff_routines(str(TIA_EXPORTS), str(TIA_EXPORTS))
    assert res["ok"] is True
    assert res["added"] == []
    assert res["removed"] == []


def test_diff_routines_missing_dir():
    res = plc_server.plc_diff_routines("does/not/exist", str(TIA_PARTS))
    assert res["ok"] is False and res["error"] == "dir_a_not_found"


# ---------------------------------------------------------------------------
# plc.opcua.read
# ---------------------------------------------------------------------------

def test_opcua_read_disabled_by_default():
    res = plc_server.plc_opcua_read(node_id="ns=3;s=Temp")
    assert res["ok"] is False
    assert res["error"] == "opcua_read_disabled"
    assert res["code"] == "OPCUA_READ_DISABLED"
    assert "read-only" in res["message"] and "endpoint" in res["message"]
    assert res["node_id"] == "ns=3;s=Temp"

    res = plc_server.plc_opcua_read()
    assert res["ok"] is False and res["error"] == "opcua_read_disabled"
