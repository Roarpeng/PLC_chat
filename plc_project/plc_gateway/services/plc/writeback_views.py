"""Engineer-facing writeback and optimization previews."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("researchos.gateway.plc")

def _excerpt_optimize_plan(plan: str, *, limit: int = 40) -> str:
    """Keep engineer facts / focus / skip / next-step; drop Openness preamble and SCL dump."""
    text = (plan or "").strip()
    if not text:
        return ""
    keep_prefixes = (
        "## 工程师已确认",
        "## 焦点块",
        "## 多实例嵌套",
        "## 未从 OB",
        "## 解耦",
        "## 跳过",
        "## 按工程师确认跳过",
        "## 程序体不可写",
        "## 下一步",
    )
    collected: list[str] = []
    capturing = False
    for ln in text.splitlines():
        if ln.startswith("# ") and not ln.startswith("## "):
            collected.append(ln)
            continue
        if ln.startswith("## "):
            capturing = any(ln.startswith(p) for p in keep_prefixes) and not ln.startswith(
                "## SCL diff"
            )
            if capturing:
                collected.append(ln)
            continue
        if capturing:
            collected.append(ln)
    body = collected if any(ln.startswith("## ") for ln in collected) else text.splitlines()[:limit]
    out = body[:limit]
    return "\n".join(out).strip()


def _openness_skip_reason(
    job: dict[str, Any],
    cs: Any,
    *,
    focus: str | None,
    extra_skips: list[str] | None = None,
) -> str | None:
    """Human skip reason when Openness must not run. None = may import if files exist."""
    from agents.plc.tia.changeset import changeset_has_importable_writes
    from agents.plc.tia.scl_rewrite import refuse_body_write_reason
    from agents.plc.tia.understanding import skip_write_reason

    if changeset_has_importable_writes(cs):
        return None
    if extra_skips:
        return extra_skips[0].lstrip("- ").strip()
    name = (focus or "").strip()
    if name:
        eng = skip_write_reason(job, name, kind="rewrite_scl")
        if eng:
            return f"`{name}`：{eng}，不调用 Openness。"
        meta = next(
            (
                b
                for b in (job.get("blocks") or [])
                if isinstance(b, dict) and b.get("name") == name
            ),
            None,
        )
        body = refuse_body_write_reason(meta)
        if body:
            label = {
                "safety": "Safety/F-block，拒绝写程序体",
                "know_how": "Know-how / protected，拒绝写程序体",
                "interface_only": "interface-only，无程序体",
                "no_body": "无程序体",
                "untranslated": "仅 TODO / 未翻译，不静默丢逻辑",
            }.get(body, body)
            return f"`{name}`：{label}，不调用 Openness。"
        for s in job.get("scl_skipped") or []:
            if isinstance(s, dict) and str(s.get("block") or "") == name:
                reason = str(s.get("reason") or "").strip()
                detail = str(s.get("detail") or "").strip()
                bit = " — ".join(p for p in (reason, detail) if p) or "跳过"
                return f"`{name}`：{bit}，无可写 SCL，不调用 Openness。"
        return f"`{name}` 没有可落地的 XML/SCL 写回（空程序体或仅注释），不调用 Openness。"
    skipped = [s for s in (job.get("scl_skipped") or []) if isinstance(s, dict)]
    if skipped:
        bits = []
        for s in skipped[:4]:
            bits.append(f"`{s.get('block') or '?'}` {s.get('reason') or '跳过'}")
        return "当前变更集没有可导入的 XML/SCL（" + "；".join(bits) + "），不调用 Openness。"
    return (
        "当前变更集没有可导入的 XML/SCL"
        "（Know-how / F 块 / interface-only / 不要动 / 必须保留嵌套），不调用 Openness。"
    )


def _format_writeback_recap(
    result: dict[str, Any],
    *,
    focus: str | None = None,
) -> str:
    """Engineer-facing recap after HITL confirm — never a silent empty card."""
    lines = ["**确认反写**"]
    scope = str(result.get("scope") or ("block:" + focus if focus else "project"))
    helpers = [str(h) for h in (result.get("helper_blocks") or []) if h]
    if scope.startswith("block:"):
        block = scope.split(":", 1)[-1] or (focus or "?")
        extra = f"（含 helper {', '.join(f'`{h}`' for h in helpers)}）" if helpers else ""
        lines.append(f"范围：焦点块 `{block}`{extra}。未应用工程级死块删除/无关块写回。")
    else:
        lines.append("范围：**整工程变更集**（含死块标注等全部 ops）。")

    skip = str(result.get("skip_reason") or "").strip()
    openness = result.get("openness") if isinstance(result.get("openness"), dict) else {}
    compile_payload = result.get("compile")
    if compile_payload is None and isinstance(openness, dict):
        compile_payload = openness.get("compile")
    zap = result.get("zap_path") or (
        (result.get("zap_archive") or {}).get("path")
        if isinstance(result.get("zap_archive"), dict)
        else None
    )
    zap_archive = result.get("zap_archive") if isinstance(result.get("zap_archive"), dict) else {}

    if result.get("skipped"):
        lines.append("")
        lines.append(f"**跳过 Openness**：{skip or (openness.get('reason') if isinstance(openness, dict) else '') or '无可写操作'}")
        lines.append("未导入、未编译、未归档 .zap。")
        return "\n".join(lines)

    import_ok = None
    if isinstance(openness, dict):
        if "import_ok" in openness:
            import_ok = bool(openness.get("import_ok"))
        elif "ok" in openness and not openness.get("skipped"):
            import_ok = bool(openness.get("ok"))
    if isinstance(openness, dict) and openness.get("skipped"):
        lines.append(
            f"导入：跳过（{openness.get('note') or openness.get('reason') or '未请求 Openness'}）"
        )
    elif import_ok is True:
        lines.append("导入：**成功**")
    elif import_ok is False:
        err = ""
        if isinstance(openness, dict):
            err = str(openness.get("error") or openness.get("reason") or "").strip()
        lines.append("导入：**失败**" + (f"（{err}）" if err else ""))
    else:
        lines.append("导入：未执行")

    inconsistent: list[str] = []
    compile_obj = compile_payload
    if isinstance(compile_payload, dict) and isinstance(compile_payload.get("compile"), dict):
        compile_obj = compile_payload.get("compile")
    if isinstance(compile_obj, dict):
        if compile_obj.get("skipped"):
            cmsg = str(compile_obj.get("message") or compile_obj.get("reason") or "").strip()
            lines.append("编译门控：跳过" + (f"（{cmsg}）" if cmsg else ""))
        else:
            compile_ok = bool(compile_obj.get("ok"))
            if isinstance(compile_payload, dict) and compile_payload.get("ok") is False:
                compile_ok = False
            if isinstance(openness, dict) and openness.get("compiled_ok") is False:
                compile_ok = False
            if isinstance(openness, dict) and openness.get("compiled_ok") is True:
                compile_ok = True
            raw_inc = compile_obj.get("inconsistentBlocks") or []
            if isinstance(raw_inc, list):
                inconsistent = [str(x) for x in raw_inc if x]
            if compile_ok:
                lines.append("编译门控：**通过**")
            else:
                bits = "、".join(f"`{b}`" for b in inconsistent[:8]) or "见 compile 详情"
                lines.append(f"编译门控：**未通过**（不一致块：{bits}）")
                lines.append("编译失败时**不会**归档 .zap。")
    elif isinstance(openness, dict) and openness.get("ok") is False and not openness.get("skipped"):
        lines.append("编译门控：**未通过**（导入或编译失败）")
        lines.append("编译失败时**不会**归档 .zap。")

    if zap:
        lines.append(f"归档 .zap：`{zap}`")
    elif isinstance(zap_archive, dict) and zap_archive.get("skipped"):
        reason = str(zap_archive.get("reason") or skip or "").strip()
        lines.append("归档 .zap：**跳过**" + (f"（{reason}）" if reason else ""))
    elif isinstance(zap_archive, dict) and zap_archive.get("ok") is False:
        err = str(zap_archive.get("error") or zap_archive.get("reason") or "").strip()
        lines.append("归档 .zap：**失败**" + (f"（{err}）" if err else ""))
    elif isinstance(openness, dict) and openness.get("ok") and not zap:
        lines.append("归档 .zap：未生成")

    if not any(ln.startswith(("导入", "**跳过")) for ln in lines):
        lines.append("无反写结果（空卡已避免）。")
    return "\n".join(lines)


def _format_confirm_writeback_chat(
    job: dict[str, Any],
    block_name: str | None,
    *,
    message: str = "",
    confirm_writeback: Callable[..., dict[str, Any]],
) -> str:
    """HITL confirm from chat — never auto-runs from 「优化SCL」."""
    _ = message
    focus = (block_name or "").strip() or None
    raw = job.get("changeset")
    if not isinstance(raw, dict) or not raw:
        return (
            "**确认反写**\n"
            "还没有可确认的变更集。请先点「优化SCL」或画布「优化提案」生成 HITL 预览"
            "（不会自动导入或归档）。"
        )

    try:
        result = confirm_writeback(
            job,
            project_path=str(job.get("project_path") or "") or None,
            block_name=focus,
            accept_changeset=True,
            execute_openness_import=True,
            archive_zap=True,
        )
    except ValueError as exc:
        msg = str(exc)
        if "project_path" in msg or "Write-back target" in msg:
            return (
                "**确认反写**\n"
                "已有变更集，但缺少 TIA 工程路径（`.ap19`/`.apxx`）。"
                "请用画布「确认反写.zap」填写路径，或从 `.zap`/`.apxx` 解析后再确认。"
                "尚未调用 Openness，也不会自动导入。"
            )
        return f"**确认反写**\n无法执行：{exc}\n未调用 Openness。"
    except Exception as exc:  # noqa: BLE001
        logger.warning("confirm writeback chat failed: %s", exc)
        return f"**确认反写**\n反写失败：{exc}\n未归档 .zap。"
    recap = _format_writeback_recap(result, focus=focus)
    if recap.strip():
        return recap
    return "**确认反写**\n已处理确认请求，但没有可展示的导入/编译/归档结果。"


def _format_optimize_scl_chat(
    job: dict[str, Any],
    block_name: str | None,
    *,
    message: str = "",
    propose_optimize: Callable[..., dict[str, Any]],
) -> str:
    """HITL SCL rewrite preview for the focused block — never a silent empty card."""
    from agents.plc.tia.understanding import (
        is_block_understanding_thin,
        is_understanding_thin,
        must_keep_nested,
        must_not_touch,
        skip_write_reason,
    )

    focus = (block_name or "").strip() or None
    title = "**优化SCL**" + (f"（`{focus}`）" if focus else "（工程）")
    lines = [title]

    thin = (
        is_block_understanding_thin(job, focus)
        if focus
        else is_understanding_thin(job)
    )
    if thin:
        lines.append(
            "理解尚未由工程师确认：以下是 HITL **预览**，不是已批准改写。"
            "可用「理解逻辑」补确认；Know-how / F 块体仍不写。"
        )
    else:
        lines.append("已按你确认的事实约束生成预览；确认反写.zap 前请审阅 diff。不会自动导入或归档。")

    if focus and must_not_touch(job, focus):
        lines.append(f"`{focus}` 你确认**不要动**，跳过该块写回操作。")

    try:
        propose_optimize(job, block_name=focus, message=message or "优化SCL")
    except Exception as exc:  # noqa: BLE001
        logger.warning("optimize SCL chat failed: %s", exc)
        lines.append(f"优化引擎暂不可用：{exc}")
        lines.append("请稍后重试，或改用画布「优化提案」。")
        return "\n".join(lines)

    plan = str(job.get("optimize_plan") or "").strip()
    excerpt = _excerpt_optimize_plan(plan)
    if excerpt:
        lines.append("")
        lines.append(excerpt)

    diffs = list(job.get("scl_diffs") or [])
    files = dict(job.get("scl_files") or {})
    skipped = list(job.get("scl_skipped") or [])
    from agents.plc.tia.changeset import (
        PlcChangeSet,
        filter_scl_diffs_for_focus,
        helper_block_names_for_focus,
    )

    raw_cs = job.get("changeset")
    parsed_cs = None
    if isinstance(raw_cs, dict) and (raw_cs.get("ops") or raw_cs.get("id")):
        parsed_cs = PlcChangeSet.from_dict(raw_cs)
    diffs_f = filter_scl_diffs_for_focus(diffs, parsed_cs, focus, limit=8)
    if focus:
        helpers = helper_block_names_for_focus(parsed_cs, focus) if parsed_cs else set()
        allowed = {focus} | helpers
        skipped_f = [
            s for s in skipped if isinstance(s, dict) and str(s.get("block") or "") in allowed
        ]
        file_text = files.get(focus)
    else:
        skipped_f = [s for s in skipped if isinstance(s, dict)][:12]
        file_text = None

    skip_reason = skip_write_reason(job, focus, kind="rewrite_scl") if focus else None
    if focus and must_keep_nested(job, focus) and skip_reason:
        lines.append(f"`{focus}`：{skip_reason}，不拍平该多实例。")

    if skipped_f:
        lines.append("")
        lines.append("**跳过写程序体**")
        for s in skipped_f[:12]:
            reason = str(s.get("reason") or "").strip()
            detail = str(s.get("detail") or "").strip()
            bit = reason
            if detail and detail not in bit:
                bit = f"{reason} — {detail}" if reason else detail
            lines.append(f"- `{s.get('block') or '?'}`：{bit or '跳过'}")
    elif skip_reason:
        lines.append("")
        lines.append(f"**跳过写程序体**：`{focus}` — {skip_reason}")

    shown = False
    for d in diffs_f[:4]:
        name = str(d.get("block") or focus or "?")
        diff = str(d.get("diff") or "").strip()
        after = str(d.get("after") or files.get(name) or "").strip()
        if diff:
            lines.append("")
            lines.append(f"**SCL diff（`{name}`）**")
            lines.append("```diff")
            lines.append(diff)
            lines.append("```")
            shown = True
        elif after:
            lines.append("")
            lines.append(f"**SCL（`{name}`）**")
            lines.append("```scl")
            lines.append(after)
            lines.append("```")
            shown = True
    if not shown and file_text:
        lines.append("")
        lines.append(f"**SCL（`{focus}`）**")
        lines.append("```scl")
        lines.append(str(file_text))
        lines.append("```")
        shown = True

    if not shown:
        why = skip_reason or (
            "该块没有可落地的 SCL 改写（Know-how / 安全块 / interface-only / 不要动 / 必须保留嵌套）"
            if focus
            else "当前工程没有可落地的 SCL 改写"
        )
        lines.append("")
        lines.append(f"无可写 SCL diff：{why}。上方仍是优化计划，不会静默空卡。")

    lines.append("")
    lines.append("审阅后点节点「确认反写」或画布「确认反写.zap」才会导入/归档；本步只预览。")
    return "\n".join(lines)
