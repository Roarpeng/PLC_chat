"""M2 layered Project Brief — structure-first, not blocked on full SCL translate."""

from __future__ import annotations

from typing import Any

from gateway.app.services.plc.citations import (
    NOT_EXPORTED,
    resolve_export_status,
)
from gateway.app.services.plc.handover import handover_prompts

INGEST_PHASES = (
    "queued",
    "skeleton",
    "structure",
    "bodies_queued",
    "ready",
    "failed",
)

# Target UX: Brief readable 1–3 min after open on mid-size projects.
TIMING_ASSUMPTIONS = {
    "mid_project_blocks": "约 200–800 块",
    "skeleton_target": "结构清单（块名/类型/注释/接口/硬件）在 Openness list 或已有 XML 后尽快可用",
    "brief_target_minutes": "1–3 分钟（最佳努力；取决于 Openness list_blocks / 已导出 XML，不包含全文 LAD→SCL）",
    "full_translate": "全文翻译与程序体下载进入 body_pull_queue，不阻塞首份 Brief",
}


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for key in (
        "name",
        "device_type",
        "address",
        "slot",
        "comment",
        "failsafe",
        "rack",
        "modules",
        "subnets",
        "network_interfaces",
        "source_file",
    ):
        if hasattr(obj, key):
            out[key] = getattr(obj, key)
    return out


def hardware_rows(job: dict[str, Any], project: Any | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    sources = list(job.get("hardware") or [])
    if project is not None:
        sources = list(getattr(project, "hardware", None) or []) + sources
    cards = job.get("device_cards") or job.get("m1_device_cards") or []
    if isinstance(cards, list):
        sources = list(cards) + sources
    for raw in sources:
        row = _as_dict(raw) if not isinstance(raw, dict) else dict(raw)
        name = str(row.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(
            {
                "name": name,
                "device_type": str(row.get("device_type") or row.get("type") or ""),
                "address": str(row.get("address") or ""),
                "slot": str(row.get("slot") or ""),
                "comment": str(row.get("comment") or "")[:160],
                "failsafe": bool(row.get("failsafe")),
                "rack": str(row.get("rack") or ""),
            }
        )
    return rows[:40]


def _sensor_like(name: str, address: str, comment: str, dtype: str = "") -> bool:
    blob = " ".join([name, address, comment, dtype]).lower()
    if any(
        k in blob
        for k in (
            "传感",
            "sensor",
            "encoder",
            "编码器",
            "温度",
            "压力",
            "接近",
            "光电",
            "analog",
            "模拟量",
            "piw",
            "iw",
        )
    ):
        return True
    addr = address.upper()
    return addr.startswith("%I") or addr.startswith("I") or addr.startswith("%PIW")


def sensor_candidates(job: dict[str, Any], project: Any | None = None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, address: str = "", comment: str = "", source: str = "") -> None:
        name = name.strip()
        if not name or name in seen:
            return
        if not _sensor_like(name, address, comment):
            return
        seen.add(name)
        found.append(
            {
                "name": name,
                "address": address,
                "comment": comment[:120],
                "source": source,
            }
        )

    for table in job.get("tag_tables") or []:
        if not isinstance(table, dict):
            continue
        tname = str(table.get("name") or "tags")
        for tag in table.get("tags") or []:
            if not isinstance(tag, dict):
                continue
            _add(
                str(tag.get("name") or ""),
                str(tag.get("logical_address") or tag.get("address") or ""),
                str(tag.get("comment") or ""),
                tname,
            )

    if project is not None:
        tables = getattr(project, "tag_tables", None) or {}
        items = tables.values() if isinstance(tables, dict) else tables
        for table in items:
            tname = str(getattr(table, "name", "") or "tags")
            for tag in getattr(table, "tags", None) or []:
                _add(
                    str(getattr(tag, "name", "") or ""),
                    str(getattr(tag, "logical_address", "") or ""),
                    str(getattr(tag, "comment", "") or ""),
                    tname,
                )

    for node in (job.get("knowledge_graph") or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") not in {"Tag", "Variable"}:
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        _add(
            str(props.get("name") or node.get("id") or "").split("::")[-1],
            str(props.get("address") or props.get("logical_address") or ""),
            str(props.get("comment") or ""),
            "kg",
        )
    return found[:24]


def device_sensor_summary(job: dict[str, Any], project: Any | None = None) -> dict[str, Any]:
    """Hook for M1 device cards; degrade to hardware XML / tag heuristics."""
    devices = hardware_rows(job, project)
    sensors = sensor_candidates(job, project)
    has_m1 = bool(job.get("device_cards") or job.get("m1_device_cards"))
    available = bool(devices or sensors or has_m1)
    if has_m1:
        source = "m1_device_cards"
        note = "已消费 M1 device cards。"
    elif devices:
        source = "hardware_xml"
        note = "M1 设备卡尚未到位；使用 Openness 硬件 XML / AML 钩子。"
    elif sensors:
        source = "tag_heuristics"
        note = "未见硬件清单；传感器候选来自 I 区标签/注释启发式。"
    else:
        source = "placeholder"
        note = "硬件/传感器尚未导出或未索引。M1 设备卡可写入 job.device_cards。"
    return {
        "available": available,
        "source": source,
        "devices": devices,
        "sensors": sensors,
        "note": note,
    }


def _main_ob(job: dict[str, Any]) -> dict[str, Any] | None:
    blocks = [b for b in (job.get("blocks") or []) if isinstance(b, dict) and b.get("name")]
    obs = [b for b in blocks if str(b.get("type") or "").upper() == "OB"]
    for b in obs:
        name = str(b.get("name") or "")
        low = name.lower()
        if name.startswith("OB1") or low in {"main", "ob1", "ob1main"} or "main" in low:
            return b
        if b.get("number") == 1:
            return b
    if obs:
        return obs[0]
    for b in blocks:
        if str(b.get("name") or "").lower() in {"main", "ob1"}:
            return b
    return None


def _calls_from(job: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in (job.get("logic_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict) or edge.get("type") != "CALLS":
            continue
        src = str(edge.get("source") or "").split("::")[-1]
        tgt = str(edge.get("target") or "").split("::")[-1]
        if src != name or not tgt or tgt in seen:
            continue
        seen.add(tgt)
        props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
        out.append(
            {
                "callee": tgt,
                "network": str(props.get("network") or edge.get("network") or ""),
                "evidence": str(props.get("evidence") or "CALLS"),
            }
        )
    for edge in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict) or edge.get("type") != "CALLS":
            continue
        src = str(edge.get("source") or "").split("::")[-1]
        tgt = str(edge.get("target") or "").split("::")[-1]
        if src != name or not tgt or tgt in seen:
            continue
        seen.add(tgt)
        props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
        out.append(
            {
                "callee": tgt,
                "network": str(props.get("network") or ""),
                "evidence": str(props.get("evidence") or "CALLS"),
            }
        )
    return out[:16]


def _purpose_line(job: dict[str, Any], main: dict[str, Any] | None) -> str:
    narrative = ""
    u = job.get("engineer_understanding")
    if isinstance(u, dict):
        narrative = str(u.get("process_narrative") or "").strip()
    if narrative:
        return narrative.splitlines()[0][:180]
    name = str(job.get("project_name") or job.get("id") or "PLC 工程")
    if main:
        comment = str(main.get("comment") or "").strip()
        entry = str(main.get("name") or "")
        if comment:
            return f"{name}：入口 `{entry}` — {comment[:120]}"
        return f"{name}：周期入口 `{entry}`（结构先行简报，全文翻译未完成亦可读）"
    return f"{name}：结构清单已可用；主入口尚未识别。"


def _run_logic_line(job: dict[str, Any], main: dict[str, Any] | None, calls: list[dict[str, Any]]) -> str:
    if not main:
        return f"{NOT_EXPORTED}：未见主 OB/入口，不能编造扫描逻辑。"
    entry = str(main.get("name") or "")
    callees = [c["callee"] for c in calls if c.get("callee")]
    comment = str(main.get("comment") or "").strip()
    if callees:
        listed = "、".join(f"`{n}`" for n in callees[:8])
        extra = f"；{comment}" if comment else ""
        return f"`{entry}` 周期扫描，顶层调用 {listed}{extra}"
    if comment:
        return f"`{entry}`：{comment}"
    if is_block_body_missing(job, entry):
        return f"`{entry}` 已列入结构，但程序体{NOT_EXPORTED}，只知入口名。"
    return f"`{entry}` 为入口；顶层 CALLS 尚未索引。"


def is_block_body_missing(job: dict[str, Any], name: str) -> bool:
    from gateway.app.services.plc.citations import is_not_exported_or_indexed

    return is_not_exported_or_indexed(job, name)


def block_counts_by_status(job: dict[str, Any]) -> dict[str, int]:
    counts = {key: 0 for key in (
        "converted",
        "parsed",
        "protected",
        "interface_only",
        "unknown",
        "not_exported",
        "not_indexed",
    )}
    for block in job.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        status = resolve_export_status(block, job)
        counts[status] = counts.get(status, 0) + 1
    return counts


def export_gaps(job: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    queued = []
    for item in job.get("body_pull_queue") or []:
        if isinstance(item, dict):
            queued.append(item)
        elif isinstance(item, str):
            queued.append({"block": item, "reason": "queued"})
    queued_names = {str(i.get("block")) for i in queued}
    for block in job.get("blocks") or []:
        if not isinstance(block, dict) or not block.get("name"):
            continue
        status = resolve_export_status(block, job)
        name = str(block["name"])
        if status not in {"protected", "interface_only", "unknown", "not_exported", "not_indexed"}:
            continue
        reason = str(block.get("comment") or "")[:80]
        if name in queued_names:
            reason = next(
                (str(i.get("reason") or "body_pull_queued") for i in queued if i.get("block") == name),
                "body_pull_queued",
            )
        gaps.append({"block": name, "status": status, "reason": reason or status})
    for item in queued:
        name = str(item.get("block") or "")
        if name and name not in {g["block"] for g in gaps}:
            gaps.append(
                {
                    "block": name,
                    "status": "not_exported",
                    "reason": str(item.get("reason") or "body_pull_queued"),
                }
            )
    return gaps[:80]


def body_pull_queue_from_job(job: dict[str, Any]) -> list[dict[str, str]]:
    queue: list[dict[str, str]] = []
    scl = job.get("scl_sources") or {}
    for block in job.get("blocks") or []:
        if not isinstance(block, dict) or not block.get("name"):
            continue
        name = str(block["name"])
        status = resolve_export_status(block, job)
        if block.get("body_available") is False or status in {
            "not_exported",
            "interface_only",
            "protected",
        }:
            queue.append({"block": name, "reason": status})
        elif name not in scl and status in {"unknown", "not_indexed"}:
            queue.append({"block": name, "reason": "scl_pending"})
    return queue


def precompute_block_stubs(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Cheap one-liner duty / I/O / callers. Skip deep SCL."""
    from gateway.app.services.plc.evidence.blocks import _block_io_lists, _call_relation_names

    stubs: list[dict[str, Any]] = []
    for block in (job.get("blocks") or [])[:80]:
        if not isinstance(block, dict) or not block.get("name"):
            continue
        name = str(block["name"])
        try:
            reads, writes, _inout = _block_io_lists(job, name, block)
            callers, callees = _call_relation_names(job, name)
        except Exception:  # noqa: BLE001
            reads, writes, callers, callees = [], [], [], []
        comment = str(block.get("comment") or "").strip()
        duty = comment or f"{block.get('type') or '块'} {name}"
        stubs.append(
            {
                "block": name,
                "duty": duty[:160],
                "inputs": list(reads)[:8],
                "outputs": list(writes)[:8],
                "callers": list(callers)[:8],
                "callees": list(callees)[:8],
                "export_status": resolve_export_status(block, job),
            }
        )
    return stubs


def persist_structure_snapshot(
    job: dict[str, Any],
    project: Any,
    kg: Any | None = None,
    *,
    phase: str = "structure",
) -> dict[str, Any]:
    """Persist a usable skeleton before full SCL/LAD body download."""
    from gateway.app.services.plc.logic_graph import _logic_graph_from_kg

    if not job.get("blocks"):
        from gateway.app.services.plc.ingest import _block_list

        job["blocks"] = _block_list(project)
    job["summary"] = project.summary() if hasattr(project, "summary") else (job.get("summary") or {})
    if getattr(project, "name", None):
        job["project_name"] = job.get("project_name") or project.name
    job["hardware"] = hardware_rows(job, project)
    job["extraction_notes"] = list(getattr(project, "extraction_notes", None) or job.get("extraction_notes") or [])
    tag_tables: list[dict[str, Any]] = []
    tables = getattr(project, "tag_tables", None) or {}
    items = tables.values() if isinstance(tables, dict) else tables
    for table in list(items)[:20]:
        tags = []
        for tag in list(getattr(table, "tags", None) or [])[:80]:
            tags.append(
                {
                    "name": getattr(tag, "name", ""),
                    "data_type": getattr(tag, "data_type", ""),
                    "logical_address": getattr(tag, "logical_address", ""),
                    "comment": (getattr(tag, "comment", "") or "")[:80],
                }
            )
        tag_tables.append({"name": getattr(table, "name", ""), "tags": tags})
    if tag_tables:
        job["tag_tables"] = tag_tables
    if kg is not None:
        payload = kg.to_json() if hasattr(kg, "to_json") else kg
        if isinstance(payload, dict):
            job["knowledge_graph"] = payload
            job["logic_graph"] = _logic_graph_from_kg(payload)
    for block in job.get("blocks") or []:
        if isinstance(block, dict):
            block["export_status"] = resolve_export_status(block, job)
    job["body_pull_queue"] = body_pull_queue_from_job(job)
    job["block_stubs"] = precompute_block_stubs(job)
    job["brief_ready"] = True
    job["ingest_phase"] = phase if phase in INGEST_PHASES else "structure"
    return job


def refresh_brief_artifacts(job: dict[str, Any]) -> dict[str, Any]:
    """Recompute statuses / queue / stubs after SCL bodies land."""
    for block in job.get("blocks") or []:
        if isinstance(block, dict):
            block["export_status"] = resolve_export_status(block, job)
    job["body_pull_queue"] = body_pull_queue_from_job(job)
    job["block_stubs"] = precompute_block_stubs(job)
    job["brief_ready"] = bool(job.get("blocks"))
    if job.get("status") == "ready":
        job["ingest_phase"] = "ready"
    elif job.get("body_pull_queue"):
        job["ingest_phase"] = "bodies_queued"
    return job


def build_project_brief(job: dict[str, Any]) -> dict[str, Any]:
    main = _main_ob(job)
    main_name = str(main.get("name") or "") if main else ""
    calls = _calls_from(job, main_name) if main_name else []
    phase = str(job.get("ingest_phase") or "")
    if not phase:
        if job.get("status") == "ready":
            phase = "ready"
        elif job.get("brief_ready"):
            phase = "structure"
        else:
            phase = str(job.get("status") or "queued")
    timings = dict(job.get("timings") or {})
    skeleton_ms = timings.get("extract_ms") or timings.get("structure_ms")
    return {
        "job_id": job.get("id"),
        "project_name": job.get("project_name") or "",
        "phase": phase,
        "brief_ready": bool(job.get("brief_ready") or job.get("blocks")),
        "purpose": _purpose_line(job, main),
        "main_ob": main_name or None,
        "main_entry": main_name or None,
        "block_counts_by_status": block_counts_by_status(job),
        "top_level_calls": calls,
        "device_sensor_summary": device_sensor_summary(job),
        "run_logic_entry": _run_logic_line(job, main, calls),
        "export_gaps": export_gaps(job),
        "block_stubs": list(job.get("block_stubs") or [])[:40],
        "engineer_prompts": handover_prompts(),
        "timing": {
            "skeleton_ms": skeleton_ms,
            "extract_ms": timings.get("extract_ms"),
            "kg_ms": timings.get("kg_ms"),
            "scl_ms": timings.get("scl_ms"),
            "total_ms": timings.get("total_ms"),
            "assumptions": TIMING_ASSUMPTIONS,
        },
    }


def format_hardware_brief_answer(job: dict[str, Any]) -> str:
    summary = device_sensor_summary(job)
    lines = ["**硬件 / 传感器（结构简报）**"]
    if not summary["available"]:
        lines.append(f"**{NOT_EXPORTED}**：未见硬件 XML / 设备卡 / 传感器标签，不能编造清单。")
        lines.append(summary["note"])
        return "\n".join(lines)
    lines.append(summary["note"])
    if summary["devices"]:
        lines.append("设备：")
        for d in summary["devices"][:12]:
            bits = [f"`{d['name']}`"]
            if d.get("device_type"):
                bits.append(str(d["device_type"]))
            if d.get("address"):
                bits.append(str(d["address"]))
            if d.get("comment"):
                bits.append(str(d["comment"]))
            lines.append("- " + " · ".join(bits))
    else:
        lines.append(f"设备：**{NOT_EXPORTED}**（等待 M1 设备卡或硬件导出）")
    if summary["sensors"]:
        lines.append("传感器候选：")
        for s in summary["sensors"][:12]:
            bits = [f"`{s['name']}`"]
            if s.get("address"):
                bits.append(str(s["address"]))
            if s.get("comment"):
                bits.append(str(s["comment"]))
            lines.append("- " + " · ".join(bits))
    else:
        lines.append(f"传感器：**{NOT_EXPORTED}**（无 I 区/注释启发式命中）")
    return "\n".join(lines)


def format_run_logic_brief_answer(job: dict[str, Any]) -> str:
    brief = build_project_brief(job)
    lines = [
        "**主运行逻辑入口**",
        brief["run_logic_entry"],
    ]
    if brief.get("main_ob"):
        lines.append(f"入口：`{brief['main_ob']}`")
    if brief.get("top_level_calls"):
        lines.append("顶层调用：")
        for c in brief["top_level_calls"][:12]:
            loc = c.get("network") or ""
            ev = c.get("evidence") or "CALLS"
            extra = f" · {loc}" if loc else ""
            lines.append(f"- `{brief['main_ob']}` → `{c['callee']}`（{ev}{extra}）")
    else:
        if not brief.get("main_ob"):
            lines.append(f"**{NOT_EXPORTED}**：没有可引用的入口调用链。")
    gaps = [g for g in brief.get("export_gaps") or [] if g.get("block") == brief.get("main_ob")]
    if gaps:
        lines.append(f"入口程序体：**{NOT_EXPORTED}**（{gaps[0].get('reason') or gaps[0].get('status')}）")
    return "\n".join(lines)
