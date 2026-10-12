"""Siemens multi-instance nesting: TYPED_AS chains, analyst, chat, optimize."""

from __future__ import annotations

from agents.plc.tia.analyst import analyze_block, analyze_project
from agents.plc.tia.ir import (
    Block,
    BlockType,
    InterfaceSection,
    Network,
    PlcProject,
    Variable,
)
from agents.plc.tia.kg import build_knowledge_graph
from agents.plc.tia.optimize import propose_optimization_changeset
from agents.plc.tia.typed_as import nest_depth_of, strip_type_name, typed_as_chains
from gateway.app.services.plc_jobs import (
    _annotate_block_nest_depth,
    _block_list,
    _describe_block_function,
    answer_block_chat,
)


def _nested_project(*, interface_only_leaf: bool = True) -> PlcProject:
    """FB_A.STAT : FB_B ; FB_B.STAT : FB_C. Shallow instance-DB INSTANCE_OF on the side."""
    project = PlcProject(name="NestDemo")
    project.add_block(
        Block(
            name="FB_A",
            number=10,
            block_type=BlockType.FB,
            programming_language="SCL",
            header_comment="component",
            interface=[
                Variable(name="Enable", section=InterfaceSection.INPUT, data_type="Bool"),
                Variable(name="Child", section=InterfaceSection.STATIC, data_type='"FB_B"'),
            ],
            networks=[Network(id="1", title="hold")],
            source_text='FUNCTION_BLOCK "FB_A"\nBEGIN\nEND_FUNCTION_BLOCK\n',
        )
    )
    project.add_block(
        Block(
            name="FB_B",
            number=20,
            block_type=BlockType.FB,
            programming_language="SCL",
            interface=[
                Variable(name="Grand", section=InterfaceSection.STATIC, data_type='"FB_C"'),
                Variable(name="Timers", section=InterfaceSection.STATIC, data_type='Array[0..1] of "FB_C"'),
            ],
            networks=[Network(id="1", title="inner")],
            source_text='FUNCTION_BLOCK "FB_B"\nBEGIN\nEND_FUNCTION_BLOCK\n',
        )
    )
    leaf_nets = [] if interface_only_leaf else [Network(id="1", title="leaf")]
    leaf_src = "" if interface_only_leaf else 'FUNCTION_BLOCK "FB_C"\nBEGIN\nEND_FUNCTION_BLOCK\n'
    project.add_block(
        Block(
            name="FB_C",
            number=30,
            block_type=BlockType.FB,
            programming_language="SCL",
            interface=[
                Variable(name="Q", section=InterfaceSection.OUTPUT, data_type="Bool"),
            ],
            networks=leaf_nets,
            source_text=leaf_src,
        )
    )
    project.add_block(
        Block(
            name="DB_A",
            block_type=BlockType.DB,
            attributes={"InstanceOfName": "FB_A"},
        )
    )
    return project


def _job_from_project(project: PlcProject) -> dict:
    kg = build_knowledge_graph(project)
    job = {
        "project_name": project.name,
        "blocks": _block_list(project),
        "knowledge_graph": kg.to_json(),
        "scl_sources": {
            name: (block.source_text or "")
            for name, block in project.blocks.items()
            if block.source_text
        },
        "folded_logic": {},
        "source_xmls": [],
    }
    _annotate_block_nest_depth(job)
    return job


def test_strip_type_name_quotes_and_array():
    assert strip_type_name('"FB_B"') == "FB_B"
    assert strip_type_name('Array[0..1] of "FB_C"') == "FB_C"
    assert strip_type_name("Bool") == "Bool"


def test_kg_typed_as_chain_not_instance_of():
    kg = build_knowledge_graph(_nested_project())
    typed = [
        (e.source, e.target, e.props.get("kind"), e.props.get("member"))
        for e in kg.edges
        if e.type == "TYPED_AS"
    ]
    assert (
        "Variable::FB_A::Static::Child",
        "Block::FB_B",
        "multi_instance",
        "Child",
    ) in typed
    assert ("Block::FB_A", "Block::FB_B", "TYPED_AS") in {
        (e.source, e.target, e.type) for e in kg.edges
    }
    assert ("Block::FB_B", "Block::FB_C", "TYPED_AS") in {
        (e.source, e.target, e.type) for e in kg.edges
    }
    instance = [(e.source, e.target) for e in kg.edges if e.type == "INSTANCE_OF"]
    assert ("Block::DB_A", "Block::FB_A") in instance
    # INSTANCE_OF is not reused for member-type nesting
    assert ("Block::FB_A", "Block::FB_B") not in instance
    payload = kg.to_json()
    assert nest_depth_of(payload, "FB_A") == 2
    assert nest_depth_of(payload, "FB_B") == 1
    assert nest_depth_of(payload, "FB_C") == 0
    assert nest_depth_of(payload, "DB_A") == 0
    chains = typed_as_chains(payload, "FB_A")
    assert ["FB_A", "FB_B", "FB_C"] in chains
    assert kg.nodes["Block::FB_A"].props.get("nest_depth") == 2
    # Do not invent types absent from IR
    unknown = [
        e
        for e in kg.edges
        if e.type == "TYPED_AS" and "FB_Missing" in (e.target or "")
    ]
    assert unknown == []


def test_analyst_nested_chain_warn_risk_not_shallow_instance_db():
    job = _job_from_project(_nested_project())
    a = analyze_block(job, "FB_A")
    codes = {f["code"]: f for f in a["findings"]}
    assert "NESTED_FB_TYPE" in codes
    assert codes["NESTED_FB_TYPE"]["severity"] == "warn"
    assert "FB_B" in codes["NESTED_FB_TYPE"]["message"]
    assert "MULTI_INSTANCE_CHAIN" in codes
    assert codes["MULTI_INSTANCE_CHAIN"]["severity"] == "risk"
    assert "FB_A" in codes["MULTI_INSTANCE_CHAIN"]["message"]
    assert "FB_B" in codes["MULTI_INSTANCE_CHAIN"]["message"]
    assert "FB_C" in codes["MULTI_INSTANCE_CHAIN"]["message"]
    assert any(e.get("edge_type") == "TYPED_AS" for e in codes["NESTED_FB_TYPE"]["evidence"])

    db = analyze_block(job, "DB_A")
    db_codes = {f["code"] for f in db["findings"]}
    assert "NESTED_FB_TYPE" not in db_codes
    assert "MULTI_INSTANCE_CHAIN" not in db_codes

    leaf = analyze_block(job, "FB_C")
    leaf_codes = {f["code"] for f in leaf["findings"]}
    assert "MULTI_INSTANCE_CHAIN" not in leaf_codes

    project = analyze_project(job)
    assert any(f["code"] == "MULTI_INSTANCE_CHAIN" for f in project["findings"])


def test_chat_optimize_and_node_card_mention_chain():
    job = _job_from_project(_nested_project())
    hints = answer_block_chat(job, "@FB_A 优化建议", "FB_A")
    assert "优化提示" in hints
    assert "未发现" not in hints
    assert "FB_B" in hints and "FB_C" in hints
    assert "NESTED_FB_TYPE" in hints or "多实例" in hints or "嵌套" in hints

    fb_a = next(b for b in job["blocks"] if b["name"] == "FB_A")
    card = "\n".join(_describe_block_function(job, "FB_A", fb_a))
    assert "嵌套 FB 类型" in card
    assert "Child : FB_B" in card
    assert "FB_C" in card
    assert fb_a.get("nest_depth") == 2


def test_analyze_and_nest_chip_show_full_typed_as_chain():
    job = _job_from_project(_nested_project())
    for phrase in ("分析节点", "这个块干什么"):
        text = answer_block_chat(job, f"@FB_A {phrase}", "FB_A")
        assert "FB_A" in text and "FB_B" in text and "FB_C" in text
        assert "→" in text
        assert "FB_A" in text.split("→")[0] or "`FB_A`" in text
    nest = answer_block_chat(job, "@FB_A 嵌套链", "FB_A")
    assert "FB-as-type" in nest or "嵌套" in nest
    assert "`FB_A`" in nest and "`FB_B`" in nest and "`FB_C`" in nest
    assert "→" in nest
    assert "Child" in nest
    leaf = answer_block_chat(job, "@FB_C 嵌套链", "FB_C")
    assert "无 FB-as-type 嵌套" in leaf
    member = answer_block_chat(job, "@Child 嵌套链", "Child")
    assert "未找到与" not in member
    assert "FB_A" in member and "FB_B" in member and "FB_C" in member
    assert "Child" in member


def test_optimize_plan_documents_chain_skips_interface_only_body():
    job = _job_from_project(_nested_project(interface_only_leaf=True))
    fb_c = next(b for b in job["blocks"] if b["name"] == "FB_C")
    assert fb_c.get("interface_only") is True
    cs = propose_optimization_changeset(job, focus_block="FB_A")
    plan = next(n for n in cs.notes if str(n).startswith("optimize_plan:"))
    assert "多实例嵌套" in plan
    assert "FB_A" in plan and "FB_B" in plan and "FB_C" in plan
    assert "interface-only" in plan or "无程序体" in plan
    assert "不为此压平" in plan or "扁平化" in plan
    body_ops = [
        o
        for o in cs.ops
        if o.kind in {"rewrite_scl", "stage_scl_source", "stage_xml_import"}
        and o.payload.get("block_name") == "FB_C"
    ]
    assert body_ops == []
    assert any(o.kind == "annotate" and o.payload.get("block_name") == "FB_A" for o in cs.ops)


def test_fallback_variable_data_type_without_typed_as_edges():
    """Jobs parsed before TYPED_AS still surface the chain from Variable.data_type."""
    job = {
        "project_name": "Legacy",
        "blocks": [
            {"name": "FB_A", "type": "FB", "body_available": True},
            {"name": "FB_B", "type": "FB", "body_available": True},
            {"name": "FB_C", "type": "FB", "interface_only": True, "body_available": False},
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::FB_A", "type": "Block", "props": {"name": "FB_A", "block_type": "FB"}},
                {"id": "Block::FB_B", "type": "Block", "props": {"name": "FB_B", "block_type": "FB"}},
                {
                    "id": "Block::FB_C",
                    "type": "Block",
                    "props": {"name": "FB_C", "block_type": "FB", "interface_only": True},
                },
                {
                    "id": "Variable::FB_A::Static::Child",
                    "type": "Variable",
                    "props": {"name": "Child", "section": "Static", "data_type": '"FB_B"'},
                },
                {
                    "id": "Variable::FB_B::Static::Grand",
                    "type": "Variable",
                    "props": {"name": "Grand", "section": "Static", "data_type": '"FB_C"'},
                },
            ],
            "edges": [
                {
                    "source": "Block::FB_A",
                    "target": "Variable::FB_A::Static::Child",
                    "type": "HAS_INTERFACE",
                    "props": {"section": "Static"},
                },
                {
                    "source": "Block::FB_B",
                    "target": "Variable::FB_B::Static::Grand",
                    "type": "HAS_INTERFACE",
                    "props": {"section": "Static"},
                },
            ],
        },
        "scl_sources": {},
        "folded_logic": {},
        "source_xmls": [],
    }
    result = analyze_block(job, "FB_A")
    codes = {f["code"] for f in result["findings"]}
    assert "NESTED_FB_TYPE" in codes
    assert "MULTI_INSTANCE_CHAIN" in codes
    text = answer_block_chat(job, "优化", "FB_A")
    assert "未发现" not in text
    assert "FB_B" in text and "FB_C" in text


def test_optimize_scl_on_nested_fixture_never_empty_after_title():
    job = _job_from_project(_nested_project())
    text = answer_block_chat(job, "@FB_A 优化SCL", "FB_A")
    assert text.strip().startswith("**优化SCL")
    after = text.split("\n", 1)[1].strip() if "\n" in text else ""
    assert after
    assert "先不编造改写" not in text
    writable = "```diff" in text or "```scl" in text
    skipped = any(
        k in text
        for k in ("跳过", "interface-only", "无程序体", "无可写", "不要动", "必须保留")
    )
    assert writable or skipped
    # 分析逻辑 still dumps IR; 理解逻辑 does not steal it
    analyze = answer_block_chat(job, "@FB_A 分析逻辑", "FB_A")
    assert "FB_A" in analyze and "FB_B" in analyze
    understand = answer_block_chat(job, "@FB_A 理解逻辑", "FB_A")
    assert "待确认假设" in understand or "请确认" in understand
    assert "完整 SCL：" not in understand
