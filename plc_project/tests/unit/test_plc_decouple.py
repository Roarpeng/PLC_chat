"""Unit tests — decouple extract produces helper FC SCL + updated caller."""

from __future__ import annotations

from agents.plc.tia.changeset import write_import_bundle
from agents.plc.tia.decouple import propose_decouple
from agents.plc.tia.optimize import propose_optimization_changeset


def _god_job() -> dict:
    """FB with two disjoint networks (motor vs cooling) — extractable."""
    motor_scl = """FUNCTION_BLOCK \"FB_God\"
VAR_INPUT
    Start : Bool;
    Stop : Bool;
    TempHigh : Bool;
END_VAR
VAR_OUTPUT
    Running : Bool;
    FanOn : Bool;
END_VAR
BEGIN

    // ---------- 网络 1 ----------
    // 标题：motor
    #Running := #Start;

    // ---------- 网络 2 ----------
    // 标题：cooling
    #FanOn := #TempHigh;

END_FUNCTION_BLOCK
"""
    return {
        "project_name": "DecoupleDemo",
        "blocks": [
            {
                "name": "Main",
                "type": "OB",
                "body_available": True,
                "networks": 1,
            },
            {
                "name": "FB_God",
                "type": "FB",
                "body_available": True,
                "networks": 2,
                "inputs": ["#Start", "#Stop", "#TempHigh"],
                "outputs": ["#Running", "#FanOn"],
                "members": [
                    "Start : Bool",
                    "Stop : Bool",
                    "TempHigh : Bool",
                    "Running : Bool",
                    "FanOn : Bool",
                ],
            },
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::Main", "type": "Block", "props": {"name": "Main", "block_type": "OB"}},
                {"id": "Block::FB_God", "type": "Block", "props": {"name": "FB_God", "block_type": "FB"}},
                {"id": "Tag::Running", "type": "Tag", "props": {"name": "Running"}},
                {"id": "Tag::FanOn", "type": "Tag", "props": {"name": "FanOn"}},
                {"id": "Tag::Start", "type": "Tag", "props": {"name": "Start"}},
                {"id": "Tag::TempHigh", "type": "Tag", "props": {"name": "TempHigh"}},
                {"id": "Tag::W1", "type": "Tag", "props": {"name": "W1"}},
                {"id": "Tag::W2", "type": "Tag", "props": {"name": "W2"}},
                {"id": "Tag::W3", "type": "Tag", "props": {"name": "W3"}},
                {"id": "Tag::W4", "type": "Tag", "props": {"name": "W4"}},
            ],
            "edges": [
                {"source": "Block::Main", "target": "Block::FB_God", "type": "CALLS", "props": {}},
                {"source": "Block::FB_God", "target": "Tag::Running", "type": "WRITES", "props": {"network": "1"}},
                {"source": "Block::FB_God", "target": "Tag::FanOn", "type": "WRITES", "props": {"network": "2"}},
                {"source": "Block::FB_God", "target": "Tag::W1", "type": "WRITES", "props": {}},
                {"source": "Block::FB_God", "target": "Tag::W2", "type": "WRITES", "props": {}},
                {"source": "Block::FB_God", "target": "Tag::W3", "type": "WRITES", "props": {}},
                {"source": "Block::FB_God", "target": "Tag::W4", "type": "WRITES", "props": {}},
            ],
        },
        "folded_logic": {
            "FB_God": [
                {
                    "network_id": "1",
                    "title": "motor",
                    "statements": [
                        {
                            "kind": "coil",
                            "target": "#Running",
                            "value": {"type": "ref", "access": "#Start"},
                        }
                    ],
                },
                {
                    "network_id": "2",
                    "title": "cooling",
                    "statements": [
                        {
                            "kind": "coil",
                            "target": "#FanOn",
                            "value": {"type": "ref", "access": "#TempHigh"},
                        }
                    ],
                },
            ]
        },
        "scl_sources": {"FB_God": motor_scl},
        "source_xmls": [],
    }


def test_decouple_extract_helper_fc_and_caller_call():
    extracts = propose_decouple(_god_job())
    assert extracts, "expected at least one extract from mixed/god FB"
    ex = extracts[0]
    assert ex.caller == "FB_God"
    assert ex.helper_name.startswith("FC_FB_God_")
    assert 'FUNCTION "' + ex.helper_name + '"' in ex.helper_scl
    assert "END_FUNCTION" in ex.helper_scl
    # I/O only from IR interface — cooling network uses TempHigh / FanOn
    assert "FanOn" in ex.outputs or "TempHigh" in ex.inputs or "FanOn" in ex.helper_scl
    assert ex.helper_name in ex.caller_scl
    assert f'"{ex.helper_name}"(' in ex.caller_scl
    # Never invent names
    for name in ex.inputs + ex.outputs:
        assert name in {"Start", "Stop", "TempHigh", "Running", "FanOn"}


def test_decouple_skips_safety_caller():
    job = _god_job()
    job["blocks"][1]["is_safety"] = True
    assert propose_decouple(job) == []


def test_optimize_composes_decouple_and_scl_diff():
    job = _god_job()
    cs = propose_optimization_changeset(job)
    kinds = {o.kind for o in cs.ops}
    assert "stage_scl_source" in kinds
    assert "rewrite_scl" in kinds
    helper_ops = [
        o
        for o in cs.ops
        if o.kind == "stage_scl_source" and str(o.payload.get("block_name") or "").startswith("FC_")
    ]
    assert helper_ops
    helper = helper_ops[0].payload["block_name"]
    caller = next(o for o in cs.ops if o.kind == "rewrite_scl" and o.payload.get("block_name") == "FB_God")
    assert helper in caller.payload["scl_text"]
    plan = next(n for n in cs.notes if str(n).startswith("optimize_plan:"))
    assert "```diff" in plan
    assert job.get("scl_diffs")
    assert any(d.get("block") == helper or d.get("new_block") for d in job["scl_diffs"])


def test_write_import_bundle_stages_scl(tmp_path):
    from agents.plc.tia.changeset import PlcChangeOp, PlcChangeSet

    cs = PlcChangeSet(
        id="t",
        ops=[
            PlcChangeOp(
                kind="stage_scl_source",
                payload={
                    "block_name": "FC_Help",
                    "scl_text": 'FUNCTION "FC_Help" : Void\nBEGIN\nEND_FUNCTION\n',
                },
            )
        ],
        notes=["optimize_plan:# plan\n"],
    )
    write_import_bundle(tmp_path / "bundle", cs, [])
    scl = tmp_path / "bundle" / "external_sources" / "FC_Help.scl"
    assert scl.is_file()
    assert "FC_Help" in scl.read_text(encoding="utf-8")
    assert (tmp_path / "bundle" / "staged_scls.json").is_file()
