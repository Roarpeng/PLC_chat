"""Evidence-gated PLC optimization — compose analyze + decouple + SCL rewrite.

Does **not** decrypt Know-how / invent LAD networks / write Safety bodies.
Produces:
  - KG annotations + block comments for dead / risky / protected blocks
  - staged XML with header-comment patches when source XML is available
  - rewrite_scl / stage_scl_source for writable non-safety logic (importable SCL)
  - decouple extracts (helper FC SCL + updated caller CALL sites)
  - optimize_plan.md + reviewable SCL diffs for HITL before writeback→zap
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agents.plc.tia.changeset import PlcChangeOp, PlcChangeSet
from agents.plc.tia.scl_rewrite import refuse_body_write_reason


def _block_map(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }


def _is_writable_body(block: dict[str, Any] | None) -> bool:
    return refuse_body_write_reason(block) is None


def _skip_label(reason: str | None) -> str:
    return {
        "safety": "Safety/F-block，拒绝写程序体",
        "know_how": "Know-how / protected，拒绝写程序体",
        "interface_only": "interface-only，无程序体",
        "no_body": "无程序体",
        "untranslated": "仅 TODO / 未翻译，不静默丢逻辑",
    }.get(reason or "", reason or "跳过")


def propose_optimization_changeset(
    job: dict[str, Any],
    *,
    focus_block: str | None = None,
    max_dead: int = 24,
) -> PlcChangeSet:
    """Build a proposed changeset: dead + decouple + SCL rewrite (HITL)."""
    from agents.plc.tia.analyst import analyze_block, analyze_project
    from agents.plc.tia.decouple import nested_fb_coupling_notes, propose_decouple
    from agents.plc.tia.scl_rewrite import rewrite_job_to_importable_scl
    from agents.plc.tia.typed_as import format_chain
    from agents.plc.tia.understanding import (
        filter_optimize_ops,
        format_facts_for_llm,
        may_extract_block,
        must_keep_nested,
        must_not_touch,
        skip_write_reason,
    )
    from agents.plc.tia.xml_patch import match_xml_for_block

    blocks = _block_map(job)
    source_xmls = list(job.get("source_xmls") or [])
    ops: list[PlcChangeOp] = []
    notes: list[str] = []
    plan_lines: list[str] = [
        "# ResearchOS PLC 优化提案（HITL）",
        "",
        "范围：死块标注 + 解耦提取 + **可导入 SCL 改写**（证据门控）。",
        "不做：Know-how 解密、从零生成 LAD/FBD 网络、臆造 CALLS、写 Safety/F 块程序体、混用 F↔标准 CALL。",
        "",
        "反写路径（Windows HostGateway）：External Source `.scl` → "
        "`ExternalSourceGroup.ExternalSources.CreateFromFile` → "
        "`GenerateBlocksFromSource()` → `ICompilable.Compile()` → 仅编译成功才 Archive `.zap`。",
        "Linux Docker 可暂存 XML/SCL 包，不能执行 Openness 导入/编译。",
        "",
        "已核实（Siemens Openness 文档 *Generating blocks from source*）："
        "`PlcExternalSource.GenerateBlocksFromSource()` 会覆盖同名块；失败回滚工程。",
        "反射假定：`CreateFromFile(string, path)`、可选 `Find`/`Delete` 同名外部源、"
        "无参 `GenerateBlocksFromSource()`（若有重载则用 `GenerateBlockOption.None`）。",
        "",
    ]

    engineer_facts = format_facts_for_llm(job)
    if engineer_facts:
        plan_lines.append("## 工程师已确认（约束，优先于图谱假设）")
        plan_lines.append(engineer_facts)
        plan_lines.append("")

    project = analyze_project(job)
    # A focused request is a node consultation, not a whole-project audit.
    raw_dead = [] if (focus_block or "").strip() else list(project.get("dead_blocks") or [])
    dead = raw_dead[:max_dead]
    if dead:
        plan_lines.append("## 未从 OB 入口到达的块")
        for name in dead:
            if must_not_touch(job, name):
                plan_lines.append(f"- `{name}`：工程师确认不要动，跳过死块标注/写回")
                notes.append(f"optimize:skip_do_not_touch:{name}")
                continue
            b = blocks.get(name)
            btype = (b or {}).get("type") or "?"
            reason = refuse_body_write_reason(b)
            writable = reason is None
            msg = (
                f"[OPT] 未从 OB 入口到达（dead_block）。建议审查：删除/归档或补调用。"
                f" type={btype}"
            )
            ops.append(
                PlcChangeOp(
                    kind="annotate",
                    payload={"block_name": name, "text": msg},
                )
            )
            ops.append(
                PlcChangeOp(
                    kind="set_block_comment",
                    payload={"block_name": name, "comment": msg},
                )
            )
            xml = match_xml_for_block(name, source_xmls) if writable else None
            if xml is not None:
                ops.append(
                    PlcChangeOp(
                        kind="stage_xml_import",
                        payload={
                            "xml_path": str(xml),
                            "block_name": name,
                            "patch_comment": msg,
                        },
                    )
                )
                plan_lines.append(f"- `{name}`（{btype}）：标注 + 头注释写回 XML `{xml.name}`")
            elif reason:
                plan_lines.append(f"- `{name}`（{btype}）：仅图谱标注（{_skip_label(reason)}，不改 XML/SCL 体）")
            else:
                plan_lines.append(f"- `{name}`（{btype}）：图谱注释（未匹配到源 XML）")
            notes.append(f"optimize:dead_block:{name}")
        plan_lines.append("")

    focus = (focus_block or "").strip()
    if focus and focus in blocks:
        analysis = analyze_block(job, focus)
        plan_lines.append(f"## 焦点块 `{focus}`")
        b = blocks[focus]
        findings = analysis.get("findings") or []
        for f in findings:
            sev = f.get("severity") or "info"
            code = f.get("code") or ""
            message = str(f.get("message") or "").strip()
            if not message:
                continue
            plan_lines.append(f"- [{sev}] `{code}`：{message}")
            if sev in {"warn", "risk"}:
                text = f"[OPT:{code}] {message}"
                ops.append(
                    PlcChangeOp(
                        kind="annotate",
                        payload={"block_name": focus, "text": text},
                    )
                )
                notes.append(f"optimize:focus:{code}")
        if _is_writable_body(b) and any(
            (f.get("severity") in {"warn", "risk"}) for f in findings
        ):
            comment = (
                str(b.get("comment") or "").strip()
                or f"[OPT] 已审查焦点块 {focus}；详见图谱 annotations"
            )
            if not comment.startswith("[OPT"):
                comment = f"[OPT] {comment}"
            ops.append(
                PlcChangeOp(
                    kind="set_block_comment",
                    payload={"block_name": focus, "comment": comment},
                )
            )
            xml = match_xml_for_block(focus, source_xmls)
            if xml is not None:
                ops.append(
                    PlcChangeOp(
                        kind="stage_xml_import",
                        payload={
                            "xml_path": str(xml),
                            "block_name": focus,
                            "patch_comment": comment,
                        },
                    )
                )
        plan_lines.append("")

    nest_notes = nested_fb_coupling_notes(job, focus=focus or None)
    if nest_notes:
        plan_lines.append("## 多实例嵌套（TYPED_AS，非 CALLS / 非实例 DB INSTANCE_OF）")
        plan_lines.append(
            "Siemens 多实例：块内成员的 data_type 为另一个 FB/FC/UDT。"
            "不为此压平嵌套；无安全 SCL 改写时仍给出 HITL 计划。"
        )
        for note in nest_notes:
            name = str(note.get("block") or "")
            depth = int(note.get("depth") or 0)
            chains = note.get("chains") or []
            chain_s = format_chain(chains[0]) if chains else f"`{name}`"
            plan_lines.append(f"- `{name}` 深度 {depth}：{chain_s}")
            for mem in (note.get("members") or [])[:8]:
                plan_lines.append(
                    f"  - 成员 `{mem.get('member')}` : `{mem.get('type_block')}`"
                    f"（{mem.get('section') or 'Static'}）"
                )
            parent_skip = note.get("parent_skip")
            if parent_skip:
                plan_lines.append(f"  - 父块跳过写程序体：{_skip_label(str(parent_skip))}")
            for sk in note.get("skip") or []:
                plan_lines.append(
                    f"  - 嵌套 `{sk.get('block')}`：{_skip_label(str(sk.get('reason')))}，"
                    "不写其程序体；仅报告耦合"
                )
            if must_keep_nested(job, name) and not may_extract_block(job, name):
                plan_lines.append(
                    "  - 工程师确认这是必须的西门子多实例：**不拍平、不提取、不发明 I/O**"
                )
            elif may_extract_block(job, name):
                plan_lines.append(
                    "  - 工程师确认这是意外耦合：仅在 folded 网络已有 I/O 时可提取 helper，仍禁止发明 I/O"
                )
            elif note.get("writable_parent") and depth >= 2:
                plan_lines.append(
                    "  - 父块可写：若 folded 网络有既有 I/O，可提取 helper；"
                    "禁止发明 I/O 或 CALLS，禁止为改数字而扁平化多实例"
                    "（嵌套意图尚未由工程师确认）"
                )
            else:
                plan_lines.append("  - 本链无安全 XML/SCL 落地操作；本提案仅记录耦合与跳过原因")
            text = (
                f"[OPT:MULTI_INSTANCE_CHAIN] 多实例嵌套深度 {depth}：{chain_s}"
            )
            ops.append(
                PlcChangeOp(
                    kind="annotate",
                    payload={"block_name": name, "text": text},
                )
            )
            notes.append(f"optimize:nested_fb:{name}:depth={depth}")
        plan_lines.append("")

    extracts = propose_decouple(job)
    if focus:
        extracts = [item for item in extracts if item.caller == focus]
    extracts = [
        ex
        for ex in extracts
        if not skip_write_reason(job, ex.caller, kind="decouple")
        and not must_not_touch(job, ex.caller)
        and (
            may_extract_block(job, ex.caller)
            or not must_keep_nested(job, ex.caller)
        )
    ]
    extra_files: dict[str, str] = {}
    extra_evidence: dict[str, list[dict[str, Any]]] = {}
    if extracts:
        plan_lines.append("## 解耦（提取 helper FC）")
        for ex in extracts:
            extra_files[ex.helper_name] = ex.helper_scl
            extra_files[ex.caller] = ex.caller_scl
            extra_evidence[ex.helper_name] = list(ex.evidence)
            extra_evidence[ex.caller] = list(ex.evidence)
            ops.append(
                PlcChangeOp(
                    kind="stage_scl_source",
                    payload={
                        "block_name": ex.helper_name,
                        "scl_text": ex.helper_scl,
                        "new_block": True,
                        "evidence": ex.evidence,
                    },
                )
            )
            ops.append(
                PlcChangeOp(
                    kind="rewrite_scl",
                    payload={
                        "block_name": ex.caller,
                        "scl_text": ex.caller_scl,
                        "evidence": ex.evidence,
                    },
                )
            )
            ops.append(
                PlcChangeOp(
                    kind="add_edge",
                    payload={
                        "source": f"Block::{ex.caller}",
                        "target": f"Block::{ex.helper_name}",
                        "type": "CALLS",
                        "props": {"evidence": "decouple_extract", "network": ex.network_id},
                    },
                )
            )
            ops.append(
                PlcChangeOp(
                    kind="annotate",
                    payload={
                        "block_name": ex.caller,
                        "text": (
                            f"[OPT:DECOUPLE] 提取 `{ex.helper_name}` "
                            f"from network {ex.network_id} ({ex.reason})"
                        ),
                    },
                )
            )
            notes.append(f"optimize:decouple:{ex.caller}->{ex.helper_name}")
            plan_lines.append(
                f"- `{ex.caller}` 网络 `{ex.network_id}` {ex.network_title or ''}："
                f"提取 `{ex.helper_name}`（I/O 仅 IR 已有："
                f"in={', '.join(ex.inputs) or '-'} out={', '.join(ex.outputs) or '-'}）"
            )
            plan_lines.append(f"  - 证据：{ex.reason}")
        plan_lines.append("")

    rewrite = rewrite_job_to_importable_scl(
        job, extra_files=extra_files or None, extra_evidence=extra_evidence or None
    )
    job["scl_files"] = dict(rewrite.files)
    job["scl_diffs"] = [d.to_dict() for d in rewrite.diffs]
    job["scl_skipped"] = [s.to_dict() for s in rewrite.skipped]

    staged_scl_names = {
        str(o.payload.get("block_name") or "")
        for o in ops
        if o.kind in {"rewrite_scl", "stage_scl_source"}
    }
    rewrite_cap = 16
    added = 0
    for diff in rewrite.diffs:
        name = diff.block_name
        if focus and name != focus and name not in extra_files:
            continue
        if name in staged_scl_names:
            continue
        if name not in extra_files and added >= rewrite_cap:
            continue
        if name not in extra_files and not _is_writable_body(blocks.get(name)):
            continue
        skip_reason = skip_write_reason(job, name, kind="rewrite_scl")
        if skip_reason:
            notes.append(f"optimize:skip_engineer:{name}")
            continue
        kind = "stage_scl_source" if diff.new_block else "rewrite_scl"
        ops.append(
            PlcChangeOp(
                kind=kind,  # type: ignore[arg-type]
                payload={
                    "block_name": name,
                    "scl_text": diff.after,
                    "baseline_scl": diff.before,
                    "diff": diff.unified_diff,
                    "evidence": diff.evidence,
                    "new_block": diff.new_block,
                },
            )
        )
        staged_scl_names.add(name)
        if name not in extra_files:
            added += 1
            notes.append(f"optimize:rewrite_scl:{name}")

    skipped = rewrite.skipped
    if skipped:
        plan_lines.append("## 跳过（拒绝写程序体）")
        for s in skipped[:40]:
            plan_lines.append(f"- `{s.block_name}`：{_skip_label(s.reason)} — {s.detail}")
        plan_lines.append("")
        notes.append(f"optimize:skipped_count:{len(skipped)}")

    if rewrite.diffs:
        plan_lines.append("## SCL diff（HITL 审阅，不仅是 optimize_plan）")
        for diff in rewrite.diffs[:24]:
            label = "新建" if diff.new_block else "改写"
            plan_lines.append(f"### `{diff.block_name}`（{label}）")
            ev_bits = []
            for ev in diff.evidence[:4]:
                if ev.get("network"):
                    ev_bits.append(f"network={ev.get('network')}")
                if ev.get("tags"):
                    ev_bits.append("tags=" + ",".join(str(t) for t in ev["tags"][:8]))
                if ev.get("reason"):
                    ev_bits.append(str(ev["reason"]))
            if ev_bits:
                plan_lines.append("- 证据：" + "；".join(ev_bits))
            plan_lines.append("```diff")
            plan_lines.append((diff.unified_diff or "").rstrip() or "(unchanged importable SCL)")
            plan_lines.append("```")
            plan_lines.append("")

    iface_only = [
        n
        for n, b in blocks.items()
        if refuse_body_write_reason(b) in {"interface_only", "know_how", "no_body", "safety"}
    ][:40]
    if iface_only and not skipped:
        plan_lines.append("## 程序体不可写（跳过逻辑改写）")
        for name in iface_only:
            plan_lines.append(f"- `{name}`：{_skip_label(refuse_body_write_reason(blocks.get(name)))}")
        plan_lines.append("")
        notes.append(f"optimize:interface_only_count:{len(iface_only)}")

    ops, skipped_engineer = filter_optimize_ops(job, ops)
    if skipped_engineer:
        plan_lines.append("## 按工程师确认跳过")
        plan_lines.extend(skipped_engineer)
        plan_lines.append("")
        notes.append(f"optimize:engineer_skip_count:{len(skipped_engineer)}")

    if not ops:
        notes.append("optimize:no_ops")
        plan_lines.append("_当前图谱未产生可自动落地的安全写回操作；可先手动改 XML/SCL 再「导入」。_")
    else:
        plan_lines.extend(
            [
                "## 下一步",
                "1. 人工审阅本提案、**SCL diff** 与跳过列表",
                "2. 确认 writeback（Openness SCL GenerateBlocksFromSource 和/或 XML Import + Save）",
                "3. 编译门禁通过后才 Archive 下载新 `.zap`；编译失败则工程保持未归档",
                "",
            ]
        )

    cs = PlcChangeSet(
        id=uuid.uuid4().hex[:12],
        ops=ops,
        status="proposed",
        notes=notes,
    )
    cs.notes.append("optimize_plan:" + "\n".join(plan_lines))
    return cs


def write_optimize_plan(bundle_dir: str | Path, changeset: PlcChangeSet) -> Path | None:
    """Extract optimize_plan from changeset notes into ``optimize_plan.md``."""
    plan = ""
    for n in changeset.notes:
        if isinstance(n, str) and n.startswith("optimize_plan:"):
            plan = n[len("optimize_plan:") :]
            break
    if not plan.strip():
        return None
    path = Path(bundle_dir) / "optimize_plan.md"
    path.write_text(plan, encoding="utf-8")
    return path
