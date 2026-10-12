"""Evidence-gated PLC Analyst — deterministic findings from KG."""

from __future__ import annotations

from agents.plc.tia.analyst import (
    analyze_block,
    analyze_project,
    format_analysis_markdown,
)
from gateway.app.services.plc_jobs import answer_block_chat


def _job() -> dict:
    return {
        "project_name": "Demo",
        "summary": {"FB": 2, "OB": 1},
        "blocks": [
            {"name": "Main", "type": "OB", "number": 1, "language": "LAD", "networks": 1},
            {"name": "FB_A", "type": "FB", "number": 10, "language": "LAD", "networks": 1},
            {"name": "FB_orphan", "type": "FB", "number": 99, "language": "LAD", "networks": 0},
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::Main", "type": "Block", "props": {"name": "Main", "block_type": "OB"}},
                {"id": "Block::FB_A", "type": "Block", "props": {"name": "FB_A", "block_type": "FB"}},
                {
                    "id": "Block::FB_orphan",
                    "type": "Block",
                    "props": {"name": "FB_orphan", "block_type": "FB"},
                },
                {"id": "Tag::MotorRun", "type": "Tag", "props": {"name": "MotorRun"}},
            ],
            "edges": [
                {"source": "Block::Main", "target": "Block::FB_A", "type": "CALLS", "props": {"evidence": "xml_call"}},
                {"source": "Block::FB_A", "target": "Tag::MotorRun", "type": "WRITES"},
                {"source": "Block::FB_A", "target": "Tag::MotorRun", "type": "READS"},
            ],
        },
        "scl_sources": {"FB_A": "FB FB_A\nBEGIN\n    #MotorRun := TRUE;\nEND_FB"},
        "folded_logic": {},
    }


def test_analyze_project_finds_dead_block():
    result = analyze_project(_job())
    assert "FB_orphan" in result["dead_blocks"]
    assert "Main" in result["ob_entry_points"]
    codes = {f["code"] for f in result["findings"]}
    assert "DEAD_BLOCK" in codes
    dead = next(f for f in result["findings"] if f["code"] == "DEAD_BLOCK")
    assert dead["evidence"]


def test_analyze_block_call_graph_evidence():
    result = analyze_block(_job(), "FB_A")
    assert result["calls"]["callers"] == ["Main"]
    codes = {f["code"] for f in result["findings"]}
    assert "CALL_GRAPH" in codes
    call = next(f for f in result["findings"] if f["code"] == "CALL_GRAPH")
    assert any(e.get("edge_type") == "CALLS" for e in call["evidence"])


def test_format_analysis_markdown_chinese():
    md = format_analysis_markdown(analyze_project(_job()))
    assert "证据门控分析" in md
    assert "DEAD_BLOCK" in md or "未从 OB" in md


def test_answer_block_chat_appends_analysis():
    text = answer_block_chat(_job(), "FB_A 做什么？", "FB_A")
    assert "`FB_A`" in text
    assert "作用：" in text
    assert "输入：" in text
    assert "输出：" in text
    # Concise chat: no boilerplate / full evidence appendix
    assert "ResearchOS PLC Intelligence" not in text
    assert "针对你的问题" not in text
    assert "证据门控分析" not in text
    assert "SCL 预览" not in text


def test_node_card_has_engineering_logic_and_citations():
    job = _job()
    job["folded_logic"] = {
        "FB_A": [
            {
                "title": "**Start motor**",
                "statements": [
                    {
                        "target": "#MotorRun",
                        "kind": "coil",
                        "value": {"type": "ref", "access": "#StartCmd"},
                    },
                    {
                        "target": "#Timer(IN := #StartCmd, PT := T#2S)",
                        "kind": "call",
                        "value": {"type": "literal", "value": True},
                    },
                ],
                "unresolved_parts": [],
            }
        ]
    }

    text = answer_block_chat(job, "@FB_A 这个块干什么？", "FB_A")
    assert "工程逻辑解读（按网络）" in text
    assert "Start motor" in text
    assert "工程师检查点" in text
    assert job["_last_citations"]
    assert any(item["block"] == "FB_A" for item in job["_last_citations"])

def test_answer_resolves_at_mention_and_describes_function():
    text = answer_block_chat(_job(), "@ce 请描述功能", None)
    assert "未找到与" in text
    text2 = answer_block_chat(_job(), "@FB_A 请描述这个功能块的作用", None)
    assert "`FB_A`" in text2
    assert "理解：" in text2 or "作用：" in text2
    assert "MotorRun" in text2
    assert "被调用：Main" in text2
    # Click/describe must explain — not dump the whole SCL unit again
    assert "完整 SCL：" not in text2
    assert "FUNCTION_BLOCK" not in text2.upper() or "主要逻辑" in text2


def test_answer_node_click_explains_instead_of_dumping_scl():
    job = _job()
    job["scl_sources"]["FB_A"] = (
        "FUNCTION_BLOCK \"FB_A\"\n"
        "VAR_INPUT\n  en : Bool;\nEND_VAR\n"
        "VAR_OUTPUT\n  q : Bool;\nEND_VAR\n"
        "BEGIN\n"
        "  // NETWORK 1: 启动保持\n"
        "  #q := #en OR #q;\n"
        "END_FUNCTION_BLOCK\n"
    )
    job["folded_logic"] = {
        "FB_A": [
            {
                "title": "启动保持",
                "statements": [{"kind": "assign", "target": "#q", "value": "#en OR #q"}],
            }
        ]
    }
    job["blocks"][1]["inputs"] = ["#en"]
    job["blocks"][1]["outputs"] = ["#q"]
    text = answer_block_chat(
        job,
        "@FB_A 请简述该块作用、关键 IO 与调用关系；不要贴源码",
        "FB_A",
    )
    assert "理解：" in text
    assert "启动保持" in text
    assert "#en" in text and "#q" in text
    assert "被调用：Main" in text
    assert "完整 SCL：" not in text
    assert "FUNCTION_BLOCK" not in text
    assert "展开 SCL" in text
    # Concise card: stay scannable
    assert len([ln for ln in text.splitlines() if ln.strip()]) <= 12


def test_answer_expand_scl_returns_full_source():
    job = _job()
    job["scl_sources"]["FB_A"] = (
        "FUNCTION_BLOCK \"FB_A\"\n"
        "BEGIN\n  #q := TRUE;\nEND_FUNCTION_BLOCK\n"
    )
    text = answer_block_chat(job, "@FB_A 展开 SCL", "FB_A")
    assert "完整 SCL：" in text
    assert "FUNCTION_BLOCK" in text
    assert "#q := TRUE" in text
    after = text.split("完整 SCL：", 1)[1].strip()
    assert after
    assert "```scl" in text


def test_answer_expand_scl_missing_sources_dumps_folded_or_reason():
    job = _job()
    job["scl_sources"] = {}
    job["folded_logic"] = {
        "FB_A": [
            {
                "title": "启动保持",
                "statements": [{"kind": "assign", "target": "#q", "value": "TRUE"}],
            }
        ]
    }
    text = answer_block_chat(job, "@FB_A 展开 SCL", "FB_A")
    assert "完整 SCL：" in text
    after = text.split("完整 SCL：", 1)[1].strip()
    assert after
    assert "```scl" in text
    assert "#q" in text or "程序体不可用" in text

    empty = _job()
    empty["scl_sources"] = {}
    empty["folded_logic"] = {}
    empty["blocks"][1]["interface_only"] = True
    empty["blocks"][1]["body_available"] = False
    locked = answer_block_chat(empty, "@FB_A 展开 SCL", "FB_A")
    assert "完整 SCL：" in locked
    assert locked.split("完整 SCL：", 1)[1].strip()
    assert "程序体不可用" in locked
    assert "```scl" in locked


def test_answer_analyze_node_includes_runtime_logic_not_truncated():
    job = _job()
    job["blocks"][1]["comment"] = "用于电机自锁保持的功能块，注释足够长以免被 160 字截断路径当成唯一答案。" * 3
    job["scl_sources"]["FB_A"] = (
        "FUNCTION_BLOCK \"FB_A\"\n"
        "BEGIN\n"
        "  // NETWORK 1: 启动保持\n"
        "  #q := #en OR #q;\n"
        "END_FUNCTION_BLOCK\n"
    )
    job["folded_logic"] = {
        "FB_A": [
            {
                "title": "启动保持",
                "statements": [{"kind": "assign", "target": "#q", "value": "#en OR #q"}],
            }
        ]
    }
    job["blocks"][1]["inputs"] = ["#en"]
    job["blocks"][1]["outputs"] = ["#q"]
    for phrase in ("分析节点", "这个块干什么"):
        text = answer_block_chat(job, f"@FB_A {phrase}", "FB_A")
        assert "完整 SCL：" not in text
        assert "启动保持" in text
        assert "逻辑：" in text or "运行步骤：" in text or "主要逻辑" in text
        assert "```scl" in text
        assert "#q" in text
        # Must not be only a truncated 理解 line
        understanding = next((ln for ln in text.splitlines() if ln.startswith("理解：")), "")
        assert understanding
        assert not understanding.endswith("…") or "主要逻辑" in text
        assert "FUNCTION_BLOCK" not in text.upper() or "主要逻辑" in text


def test_answer_optimize_and_signal_trace_shortcuts():
    text = answer_block_chat(_job(), "@FB_A 优化建议", "FB_A")
    assert "优化提示" in text
    text2 = answer_block_chat(_job(), "@FB_A 谁读写这些信号", "FB_A")
    assert "信号追踪" in text2
    assert "MotorRun" in text2


def test_answer_axis_process_logic_horizontal_and_vertical():
    job = _job()
    job["blocks"].extend(
        [
            {
                "name": "FB1060_AutoStep",
                "type": "FB",
                "number": 1060,
                "networks": 3,
                "comment": "自动循环控制",
            },
            {
                "name": "FB1062_HorDrillAutoStep",
                "type": "FB",
                "number": 1062,
                "networks": 4,
                "comment": "Added Visual Chiseling Mode",
            },
            {
                "name": "FB1063_DownDrillAutoStep",
                "type": "FB",
                "number": 1063,
                "networks": 3,
                "comment": "PosNo is ToolNo",
            },
        ]
    )
    job["folded_logic"] = {
        "FB1062_HorDrillAutoStep": [
            {"title": "水平钻孔Start", "statements": [{"kind": "coil", "target": "#HorDrillStep.StepStart"}]},
            {"title": "速度分时", "statements": [{"kind": "coil", "target": "#HorDrillStep.S20"}]},
            {"title": "结束", "statements": [{"kind": "coil", "target": "#HorDrillStep.TaskDone"}]},
        ],
        "FB1063_DownDrillAutoStep": [
            {"title": "垂直向下钻孔Start", "statements": [{"kind": "coil", "target": "#DownDrillStep.StepStart"}]},
            {"title": "开启凿削模式", "statements": [{"kind": "coil", "target": "#DownDrillStep.S1"}]},
            {"title": "结束", "statements": [{"kind": "coil", "target": "#DownDrillStep.TaskDone"}]},
        ],
        "FB1060_AutoStep": [
            {"title": "HorDrillAutoStep", "statements": [{"kind": "call", "target": "#HorDrillAutoStep();"}]},
            {"title": "DownDrillAutoStep", "statements": [{"kind": "call", "target": "#DownDrillAutoStep();"}]},
        ],
    }
    job["knowledge_graph"]["nodes"].extend(
        [
            {"id": "Block::FB1060_AutoStep", "type": "Block", "props": {"name": "FB1060_AutoStep", "block_type": "FB"}},
            {
                "id": "Block::FB1062_HorDrillAutoStep",
                "type": "Block",
                "props": {"name": "FB1062_HorDrillAutoStep", "block_type": "FB"},
            },
            {
                "id": "Block::FB1063_DownDrillAutoStep",
                "type": "Block",
                "props": {"name": "FB1063_DownDrillAutoStep", "block_type": "FB"},
            },
        ]
    )
    text = answer_block_chat(job, "给出水平作业和垂直向上，向下作业的逻辑", None)
    assert "FB1062_HorDrillAutoStep" in text or "水平钻孔" in text
    assert "问题" in text or "检索" in text or "水平" in text
    assert "扫描调用链（顺序来自逻辑图 CALLS）" not in text
    assert "不依赖 LLM" not in text


def test_answer_project_overview_uses_call_architecture():
    job = _job()
    job["logic_graph"] = {
        "nodes": [],
        "edges": [
            {
                "source": "Block::Main",
                "target": "Block::FB_A",
                "type": "CALLS",
                "seq": 1,
                "evidence": "xml_call",
            }
        ],
    }
    text = answer_block_chat(job, "根据图谱深入理解整个项目", None)
    assert "块：DB1000" not in text
    assert "Main" in text or "FB_A" in text


def test_answer_resolves_spaced_at_mention_and_network_title():
    job = _job()
    job["blocks"].append(
        {
            "name": "FB_CoolingFan",
            "type": "FB",
            "number": 42,
            "language": "LAD",
            "networks": 2,
            "comment": "A Station CoolingFan",
        }
    )
    job["scl_sources"]["FB_CoolingFan"] = (
        'FUNCTION_BLOCK "FB_CoolingFan"\n'
        "BEGIN\n"
        "    // NETWORK 1: A Station CoolingFan\n"
        "    #Run := TRUE;\n"
        "END_FUNCTION_BLOCK\n"
    )
    job["knowledge_graph"]["nodes"].append(
        {
            "id": "Block::FB_CoolingFan",
            "type": "Block",
            "props": {"name": "FB_CoolingFan", "block_type": "FB"},
        }
    )
    text = answer_block_chat(
        job,
        "@A Station CoolingFan 这个功能具体是有什么作用？",
        None,
    )
    assert "`FB_CoolingFan`" in text
    assert "作用：" in text
    assert "未找到与" not in text


def test_answer_multi_instance_from_kg_evidence():
    """Canvas/@ for multi-instance names (Analog_Out_1) must use KG edges, not 未找到."""
    job = _job()
    job["blocks"].append(
        {
            "name": "FB1080_Component",
            "type": "FB",
            "number": 1080,
            "language": "SCL",
            "networks": 2,
            "comment": "Component",
            "statics": ['#Analog_Out_1 : "FB5009_AnalOut"'],
            "members": ['Analog_Out_1 : "FB5009_AnalOut"'],
            "inputs": ["#ManMode"],
            "outputs": [],
        }
    )
    job["blocks"].append(
        {
            "name": "FB5009_AnalOut",
            "type": "FB",
            "number": 5009,
            "language": "LAD",
            "networks": 4,
            "comment": "",
            "inputs": [],
            "outputs": [],
            "members": ["IW : Int", "OUT_Offset : Real", "OUT_Gain : Real"],
        }
    )
    job["knowledge_graph"]["nodes"].extend(
        [
            {
                "id": "Block::FB1080_Component",
                "type": "Block",
                "props": {"name": "FB1080_Component", "block_type": "FB"},
            },
            {
                "id": "Block::FB5009_AnalOut",
                "type": "Block",
                "props": {"name": "FB5009_AnalOut", "block_type": "FB"},
            },
            {
                "id": "Block::Analog_Out_1",
                "type": "Block",
                "props": {"name": "Analog_Out_1", "block_type": "DB", "external": True},
            },
            {
                "id": "Variable::FB1080_Component::Static::Analog_Out_1",
                "type": "Variable",
                "props": {
                    "name": "Analog_Out_1",
                    "section": "Static",
                    "data_type": '"FB5009_AnalOut"',
                },
            },
        ]
    )
    job["knowledge_graph"]["edges"].extend(
        [
            {
                "source": "Block::FB1080_Component",
                "target": "Variable::FB1080_Component::Static::Analog_Out_1",
                "type": "HAS_INTERFACE",
                "props": {"section": "Static"},
            },
            {
                "source": "Block::FB1080_Component",
                "target": "Block::Analog_Out_1",
                "type": "USES",
                "props": {
                    "evidence": "xml_call_instance",
                    "network": "Network::FB1080_Component::1",
                },
            },
            {
                "source": "Block::Analog_Out_1",
                "target": "Block::FB5009_AnalOut",
                "type": "INSTANCE_OF",
                "props": {},
            },
        ]
    )
    text = answer_block_chat(
        job,
        "@Analog_Out_1 请描述这个功能块的作用、输入输出与主要逻辑",
        "Analog_Out_1",
    )
    assert "未找到与" not in text
    assert "多实例" in text or "实例数据" in text
    assert "FB5009_AnalOut" in text
    assert "INSTANCE_OF" in text
    assert "FB1080_Component" in text
    assert "USES" in text
    assert "xml_call_instance" in text or "Network::FB1080_Component" in text
    assert "扫描调用链" not in text


def test_answer_interface_only_block_describes_io_and_calls_not_body():
    job = _job()
    job["blocks"].append(
        {
            "name": "FB_Locked",
            "type": "FB",
            "number": 1000,
            "language": "LAD",
            "networks": 0,
            "inputs": ["#Enable"],
            "outputs": ["#Done"],
            "inouts": [],
            "interface_only": True,
            "body_available": False,
            "protected": False,
            "comment": "标准信号",
        }
    )
    job["knowledge_graph"]["nodes"].append(
        {
            "id": "Block::FB_Locked",
            "type": "Block",
            "props": {
                "name": "FB_Locked",
                "block_type": "FB",
                "interface_only": True,
                "body_available": False,
            },
        }
    )
    job["knowledge_graph"]["edges"].append(
        {
            "source": "Block::Main",
            "target": "Block::FB_Locked",
            "type": "CALLS",
            "props": {"evidence": "xml_call"},
        }
    )
    text = answer_block_chat(job, "@FB_Locked 请描述功能", "FB_Locked")
    assert "接口开放" in text
    assert "程序体不可用" in text or "程序体：不可用" in text
    assert "#Enable" in text
    assert "#Done" in text
    assert "被调用" in text and "Main" in text
    assert "```scl" not in text.lower()
