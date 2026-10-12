"""Engineer-understanding interview loop: welcome, persist facts, grounded optimize."""

from __future__ import annotations

from gateway.app.services.chat_turns import _assistant_from_plc
from gateway.app.services.plc_jobs import answer_block_chat
from agents.plc.tia.optimize import propose_optimization_changeset
from agents.plc.tia.understanding import (
    format_welcome_interview,
    ingest_engineer_reply,
    is_understanding_thin,
)
from tests.unit.test_plc_nested_fb_type import _job_from_project, _nested_project
from tests.unit.test_plc_analyst import _job as _analyst_job


def test_welcome_asks_questions_instead_of_claiming_understanding():
    job = _analyst_job()
    text = format_welcome_interview(job)
    assert "我还没懂" in text
    assert "画布已更新" in text
    assert "需要你确认" in text
    assert "扫描调用链（顺序来自逻辑图 CALLS）" not in text
    assert "本工程整体结构" not in text
    # Evidence chips, not an architecture essay
    assert "`Main`" in text or "`FB_A`" in text
    assert "工艺主控" in text

    wrapped = _assistant_from_plc({**job, "status": "ready", "source_type": "upload"})
    assert "我还没懂" in wrapped
    assert "画布已更新" in wrapped or "程序块" in wrapped
    assert "扫描调用链（顺序来自逻辑图 CALLS）" not in wrapped


def test_engineer_replies_are_stored_and_reused():
    job = _analyst_job()
    stored = ingest_engineer_reply(job, "这条线是金刚石钻削产线，负责上下料和钻孔。", None)
    assert stored
    assert "金刚石" in str(job["engineer_understanding"]["process_narrative"])

    stored2 = ingest_engineer_reply(job, "工艺主控", "FB_A")
    assert stored2
    roles = job["engineer_understanding"]["roles"]
    assert roles["FB_A"]["role"] == "process_main"
    assert roles["FB_A"]["label"] == "工艺主控"

    ack = answer_block_chat(job, "@FB_orphan 不要动", "FB_orphan")
    assert "已记下" in ack
    assert "不要动" in ack
    assert "FB_orphan" in job["engineer_understanding"]["constraints"]["do_not_touch"]

    hints = answer_block_chat(job, "优化建议", None)
    assert "金刚石" in hints
    assert "工艺主控" in hints
    assert "不要动" in hints
    assert not is_understanding_thin(job)


def test_optimize_advice_without_facts_asks_with_facts_cites():
    job = _analyst_job()
    thin = answer_block_chat(job, "优化建议", None)
    assert "优化建议" in thin or "优化提示" in thin
    assert "确认还不够" in thin or "需要你确认" in thin
    assert "编造" in thin or "不是结论" in thin or "只提问" in thin
    assert "拍平" not in thin or "未确认" in thin or "必须" in thin

    ingest_engineer_reply(job, "工艺主控", "FB_A")
    ingest_engineer_reply(job, "不要动", "FB_orphan")
    rich = answer_block_chat(job, "@FB_A 优化建议", "FB_A")
    assert "你确认" in rich or "工程师确认" in rich
    assert "工艺主控" in rich
    assert "FB_A" in rich


def test_optimize_propose_skips_must_keep_and_do_not_touch():
    job = _analyst_job()
    ingest_engineer_reply(job, "不要动", "FB_orphan")
    cs = propose_optimization_changeset(job)
    orphan_writes = [
        o
        for o in cs.ops
        if o.payload.get("block_name") == "FB_orphan"
        and o.kind in {"rewrite_scl", "stage_scl_source", "stage_xml_import", "set_block_comment"}
    ]
    assert orphan_writes == []
    plan = next(n for n in cs.notes if str(n).startswith("optimize_plan:"))
    assert "不要动" in plan
    assert "FB_orphan" in plan

    nested = _job_from_project(_nested_project())
    ingest_engineer_reply(nested, "必须的多实例", "FB_A")
    assert "FB_A" in nested["engineer_understanding"]["constraints"]["must_keep_nested"]
    cs2 = propose_optimization_changeset(nested, focus_block="FB_A")
    flatten = [
        o
        for o in cs2.ops
        if o.payload.get("block_name") == "FB_A"
        and o.kind in {"rewrite_scl", "stage_scl_source", "stage_xml_import"}
    ]
    assert flatten == []
    plan2 = next(n for n in cs2.notes if str(n).startswith("optimize_plan:"))
    assert "必须" in plan2 and "多实例" in plan2
    assert "不拍平" in plan2 or "跳过" in plan2


def test_nested_fb_questions_distinguish_required_vs_accidental():
    job = _job_from_project(_nested_project())
    welcome = format_welcome_interview(job)
    assert "必须的西门子多实例" in welcome
    assert "意外耦合" in welcome
    assert "FB_A" in welcome and "FB_B" in welcome
    assert "拍平" in welcome

    ask = answer_block_chat(job, "@FB_A 这个块干什么", "FB_A")
    assert "必须的西门子多实例" in ask or "意外耦合" in ask

    ack = answer_block_chat(job, "@FB_A 必须的多实例", "FB_A")
    assert "已记下" in ack
    nest = job["engineer_understanding"]["nested"]["FB_A"]
    assert nest["kind"] == "required_multi_instance"

    advice = answer_block_chat(job, "@FB_A 优化建议", "FB_A")
    assert "不建议拍平" in advice or "必须" in advice
    assert "FB_B" in advice and "FB_C" in advice

    other = _job_from_project(_nested_project())
    ingest_engineer_reply(other, "意外耦合", "FB_A")
    acc = answer_block_chat(other, "@FB_A 优化建议", "FB_A")
    assert "意外耦合" in acc
    assert "拍平" in acc or "提取" in acc


def test_understand_logic_asks_and_recaps_without_claiming_architecture():
    job = _job_from_project(_nested_project())
    text = answer_block_chat(job, "@FB_A 理解逻辑", "FB_A")
    assert "**理解逻辑" in text
    assert "待确认假设" in text or "请确认" in text
    assert "不是「程序就是 X」" in text or "待确认假设" in text
    assert "扫描调用链（顺序来自逻辑图 CALLS）" not in text
    assert "本工程整体结构" not in text
    assert "完整 SCL：" not in text
    assert "？" in text
    assert "必须的西门子多实例" in text or "意外耦合" in text or "工艺主控" in text

    ingest_engineer_reply(job, "工艺主控", "FB_A")
    recap = answer_block_chat(job, "@FB_A 理解这块", "FB_A")
    assert "工艺主控" in recap
    assert "已确认" in recap or "工程师确认" in recap
    # nested still unknown — ask next, do not restart as if nothing is known
    assert "多实例" in recap or "意外耦合" in recap

    ack = answer_block_chat(job, "@FB_A 必须的多实例", "FB_A")
    assert "已记下" in ack
    ready = answer_block_chat(job, "@FB_A 确认逻辑", "FB_A")
    assert "够用来优化" in ready
    assert "优化逻辑" in ready and "优化SCL" in ready


def test_optimize_logic_asks_when_thin_cites_when_confirmed():
    job = _analyst_job()
    thin = answer_block_chat(job, "@FB_A 优化逻辑", "FB_A")
    assert "**优化逻辑" in thin
    assert "确认还不够" in thin or "需要你确认" in thin
    assert "编造" in thin or "只提问" in thin
    assert "```diff" not in thin
    assert "```scl" not in thin

    ingest_engineer_reply(job, "工艺主控", "FB_A")
    ingest_engineer_reply(job, "不要动", "FB_orphan")
    rich = answer_block_chat(job, "@FB_A 优化逻辑", "FB_A")
    assert "工艺主控" in rich
    assert "你确认" in rich or "工程师确认" in rich
    assert "不要动" in rich or "跳过" in rich
    assert "优化SCL" in rich
    assert "不是 SCL 文件" in rich or "逻辑上拟改" in rich

    nested = _job_from_project(_nested_project())
    ingest_engineer_reply(nested, "工艺主控", "FB_A")
    ingest_engineer_reply(nested, "必须的多实例", "FB_A")
    plan = answer_block_chat(nested, "@FB_A 优化建议", "FB_A")
    assert "必须" in plan and "多实例" in plan
    assert "不建议拍平" in plan or "不拍平" in plan
    assert "优化SCL" in plan


def test_optimize_scl_returns_plan_and_diff_or_skip_never_empty():
    job = _job_from_project(_nested_project())
    text = answer_block_chat(job, "@FB_A 优化SCL", "FB_A")
    assert "**优化SCL" in text
    body = text.split("**优化SCL", 1)[1].strip()
    assert body
    assert "先不编造改写" not in text
    assert "确认还不够，先不编造改写" not in text
    assert job.get("changeset")
    assert job.get("optimize_plan") or "焦点块" in text or "多实例" in text
    has_fence = "```diff" in text or "```scl" in text
    has_skip = any(
        k in text
        for k in (
            "跳过",
            "interface-only",
            "无程序体",
            "不要动",
            "必须保留",
            "无可写",
            "Know-how",
            "安全",
        )
    )
    assert has_fence or has_skip
    assert "确认反写" in text

    # Must not take the warn-only hints path
    alias = answer_block_chat(job, "@FB_A 改写 SCL", "FB_A")
    assert "**优化SCL" in alias
    assert "```diff" in alias or "```scl" in alias or "跳过" in alias or "无可写" in alias


def test_optimize_scl_skips_do_not_touch_and_keep_nested():
    job = _analyst_job()
    ingest_engineer_reply(job, "不要动", "FB_A")
    text = answer_block_chat(job, "@FB_A 优化SCL", "FB_A")
    assert "不要动" in text
    assert "```diff" in text or "跳过" in text or "无可写" in text
    cs = job.get("changeset") or {}
    writes = [
        o
        for o in (cs.get("ops") or [])
        if (o.get("payload") or {}).get("block_name") == "FB_A"
        and o.get("kind") in {"rewrite_scl", "stage_scl_source", "stage_xml_import"}
    ]
    assert writes == []

    nested = _job_from_project(_nested_project())
    ingest_engineer_reply(nested, "必须的多实例", "FB_A")
    kept = answer_block_chat(nested, "@FB_A 优化SCL", "FB_A")
    assert "多实例" in kept
    assert "不拍平" in kept or "跳过" in kept or "必须保留" in kept
    flatten = [
        o
        for o in (nested.get("changeset") or {}).get("ops") or []
        if (o.get("payload") or {}).get("block_name") == "FB_A"
        and o.get("kind") in {"rewrite_scl", "stage_scl_source", "stage_xml_import"}
    ]
    assert flatten == []


def test_confirm_intent_vs_propose_and_optimize_scl_never_auto_writes(monkeypatch):
    from gateway.app.services.plc_jobs import (
        _wants_confirm_writeback,
        _wants_optimize_scl,
        propose_job_changeset,
    )

    assert _wants_confirm_writeback("确认反写")
    assert _wants_confirm_writeback("@FB_A 确认反写.zap")
    assert _wants_confirm_writeback("执行反写")
    assert not _wants_confirm_writeback("优化SCL")
    assert not _wants_confirm_writeback("@FB_A 优化 SCL")
    assert not _wants_confirm_writeback("优化工程逻辑并准备反写")
    assert _wants_optimize_scl("优化SCL")
    assert not _wants_confirm_writeback("优化SCL 并确认反写")  # 优化SCL wins; never auto-confirm

    job = _analyst_job()
    job["changeset"] = {
        "id": "keep-me",
        "ops": [
            {
                "kind": "rewrite_scl",
                "payload": {
                    "block_name": "FB_A",
                    "scl_text": 'FUNCTION_BLOCK "FB_A"\nEND_FUNCTION_BLOCK\n',
                },
            }
        ],
        "status": "proposed",
        "notes": [],
    }
    out = propose_job_changeset(job, "确认反写", "FB_A")
    assert out["id"] == "keep-me"
    propose_job_changeset(job, "@FB_A 执行反写", "FB_A")
    assert job["changeset"]["id"] == "keep-me"

    def boom_confirm(*_a, **_k):
        raise AssertionError("优化SCL must not auto-confirm writeback")

    from gateway.app.services import plc_jobs as plc

    monkeypatch.setattr(plc, "confirm_job_writeback", boom_confirm)
    text = answer_block_chat(job, "@FB_A 优化SCL", "FB_A")
    assert "**优化SCL" in text
    assert "只预览" in text or "确认反写" in text


def test_confirm_writeback_chat_recap_and_skip_reason(monkeypatch):
    job = _analyst_job()
    ingest_engineer_reply(job, "不要动", "FB_A")
    job["changeset"] = {
        "id": "cs-skip",
        "ops": [
            {"kind": "annotate", "payload": {"block_name": "FB_A", "text": "[OPT] skip"}},
            {
                "kind": "rewrite_scl",
                "payload": {
                    "block_name": "FB_orphan",
                    "scl_text": 'FUNCTION_BLOCK "FB_orphan"\nEND_FUNCTION_BLOCK\n',
                },
            },
        ],
        "status": "proposed",
        "notes": ["optimize:dead_block:FB_orphan"],
    }
    opened = {"n": 0}

    def boom_exec(*_a, **_k):
        opened["n"] += 1
        raise AssertionError("skip-write must not execute Openness")

    monkeypatch.setattr("agents.plc.tia.writeback.execute_writeback", boom_exec)
    text = answer_block_chat(job, "@FB_A 确认反写", "FB_A")
    assert "**确认反写" in text
    assert "跳过" in text or "不要动" in text
    assert "Openness" in text or "不调用" in text or "未导入" in text
    assert opened["n"] == 0
    wb = job.get("writeback") or {}
    assert wb.get("skipped") or (wb.get("openness") or {}).get("skipped")

    job2 = _analyst_job()
    job2["changeset"] = dict(job["changeset"])
    recap = answer_block_chat(job2, "确认反写.zap", None)
    assert "**确认反写" in recap
    assert "整工程" in recap or "跳过" in recap or "变更集" in recap

