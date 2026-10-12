"""Unified chat turn orchestration — research or PLC from one conversation API."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import BackgroundTasks

from gateway.app.services import knowledge_extract as kx
from gateway.app.services import plc_jobs as plc
from gateway.app.services import store as mem
from gateway.app.services.intent_route import detect_route
from gateway.app.services.llm_settings import resolve_model_profile
from gateway.app.services.runtime_client import RuntimeClient
from gateway.app.services.store import new_task

logger = logging.getLogger("researchos.gateway.chat")

ScheduleIngest = Callable[[Callable[..., Any]], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _knowledge_recall_appendix(query: str) -> str:
    """Best-effort hybrid recall for research replies."""
    try:
        from gateway.app.services import knowledge_service as ksvc

        space_ids = list(mem.store.spaces.keys()) or None
        pack = ksvc.recall(query, knowledge_space_ids=space_ids, top_k=5)
        return str(pack.get("citation_block") or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("knowledge recall skipped: %s", exc)
        return ""


def _with_knowledge_recall(assistant: str, query: str) -> str:
    appendix = _knowledge_recall_appendix(query)
    if not appendix:
        return assistant
    return f"{assistant}\n\n---\n{appendix}"


def _assistant_from_plc(job: dict[str, Any]) -> str:
    if job.get("status") == "failed":
        err = str(job.get("error") or "unknown")
        kind, _ = _plc_source_kind(job)
        head = f"{kind}解析失败。" if kind else "PLC 解析失败。"
        return f"{head}\n{err}"

    status = str(job.get("status") or "")
    if status in {"queued", "running"}:
        return _pending_ingest_message(job)

    name = job.get("project_name") or job.get("id")
    kind, source_label = _plc_source_kind(job)
    kind_line = f"已检测为{kind}：{source_label or name}"
    try:
        from agents.plc.tia.understanding import format_welcome_interview

        return f"{kind_line}\n{format_welcome_interview(job)}"
    except Exception:  # noqa: BLE001
        blocks = job.get("blocks") or []
        summary = job.get("summary") or {}
        return (
            f"{kind_line}\n"
            f"工程「{name}」· 程序块 {len(blocks)} 个"
            + (f"（{_summary_brief(summary)}）" if summary else "")
            + "\n画布已更新。我还没懂这条线，需要你确认几件事。"
            + "可点画布块，用「工艺主控 / 设备驱动 / 厂商库 / 可拆辅助 / 不要动」作答。"
        )


def _pending_ingest_message(job: dict[str, Any]) -> str:
    kind, source_label = _plc_source_kind(job)
    label = source_label or job.get("project_name") or job.get("id")
    status = job.get("status") or "queued"
    extra = ""
    if job.get("brief_ready"):
        extra = "结构简报已可用（全文翻译仍在排队），可先问硬件/主循环/如何调整。"
    return (
        f"工程已接收，正在解析…\n"
        f"已检测为{kind}：{label}\n"
        f"作业 ID：{job['id']}（状态：{status}）\n"
        f"{extra or '解析完成后画布会自动更新，届时可直接提问。'}"
    )


def _replace_last_assistant_chat(job: dict[str, Any], content: str) -> None:
    chat = job.get("chat") or []
    for i in range(len(chat) - 1, -1, -1):
        if isinstance(chat[i], dict) and chat[i].get("role") == "assistant":
            chat[i]["content"] = content
            job["chat"] = chat
            job["updated_at"] = _now()
            return
    plc.append_chat_turn(job, role="assistant", content=content, block_name=None)


def _ingest_and_refresh_welcome(job_id: str, task_id: str | None = None) -> None:
    """Background ingest then refresh welcome chat + linked task canvas."""
    try:
        job = plc.run_ingest_job(job_id, publish_graph=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("async plc ingest failed job=%s: %s", job_id, exc)
        job = plc.get_job(job_id)
        if not job:
            return

    pending_q = ""
    if task_id:
        task0 = mem.store.tasks.get(task_id)
        if task0:
            pending_q = str((task0.get("result") or {}).get("pending_question") or "").strip()

    welcome = _assistant_from_plc(job)
    _replace_last_assistant_chat(job, welcome)
    msg = welcome
    if pending_q and job.get("status") == "ready":
        plc.append_chat_turn(job, role="user", content=pending_q, block_name=None)
        answer = plc.answer_block_chat(job, pending_q, None)
        plc.append_chat_turn(job, role="assistant", content=answer, block_name=None)
        msg = f"{welcome}\n\n——\n{answer}"

    if not task_id:
        return
    task = mem.store.tasks.get(task_id)
    if not task:
        return
    _link_plc_to_task(task, job, query=task.get("query") or "")
    result = dict(task.get("result") or {})
    result["assistant_message"] = msg
    result.pop("pending_question", None)
    task["result"] = result
    _attach_canvas(
        task,
        user_text="",
        assistant_text=msg,
        job=job,
    )
    with mem.store._lock:
        mem.store.tasks[task["id"]] = task


def _schedule_plc_ingest(
    *,
    job_id: str,
    task_id: str | None,
    background: BackgroundTasks | None,
    schedule_ingest: ScheduleIngest | None,
) -> None:
    """Queue ingest without blocking the chat HTTP response."""

    def _run() -> None:
        _ingest_and_refresh_welcome(job_id, task_id)

    if schedule_ingest is not None:
        schedule_ingest(_run)
        return
    if background is not None:
        background.add_task(_run)
        return
    threading.Thread(target=_run, name=f"plc-ingest-{job_id}", daemon=True).start()
    logger.warning("plc ingest scheduled via daemon thread job=%s (no BackgroundTasks)", job_id)


def _summary_brief(summary: dict[str, Any]) -> str:
    parts = [f"{k} {v}" for k, v in summary.items() if v]
    return " · ".join(parts[:8])


def _plc_source_kind(job: dict[str, Any]) -> tuple[str, str]:
    """Infer Siemens PLC source kind from upload name / path. Returns (kind_zh, label)."""
    upload = str(job.get("upload_filename") or "").strip()
    src = Path(str(job.get("source_path") or ""))
    probe = " ".join(
        p for p in [upload, src.name, str(src), str(job.get("project_path") or "")] if p
    ).lower()
    label = upload or src.name or str(job.get("project_name") or "")
    suffix = Path(upload or src.name).suffix.lower()

    if re.search(r"\.zap\d*\b", probe) or (suffix.startswith(".zap")):
        return "西门子 PLC 工程（TIA .zap 归档）", label
    if suffix in {".ap15", ".ap16", ".ap17", ".ap18", ".ap19", ".ap20"} or re.search(
        r"\.ap\d{2}\b", probe
    ):
        return "西门子 PLC 工程（TIA .apxx）", label
    if suffix == ".xml" or "simaticml" in probe or src.suffix.lower() == ".xml":
        return "西门子 PLC 导出（SimaticML XML）", label
    if suffix == ".zip":
        return "西门子 PLC 工程包（zip）", label
    if job.get("source_type") == "path":
        return "西门子 PLC 工程（本地路径）", label
    return "西门子 PLC 工程", label


def _parse_user_edges(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for e in data:
        if not isinstance(e, dict):
            continue
        s, t = e.get("source"), e.get("target")
        if not s or not t:
            continue
        out.append(
            {
                "id": str(e.get("id") or f"ue_{uuid4().hex[:8]}"),
                "source": str(s),
                "target": str(t),
                "label": str(e.get("label") or "关联"),
                "user_created": True,
            }
        )
    return out


def _parse_positions(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _attach_canvas(
    task: dict[str, Any],
    *,
    user_text: str,
    assistant_text: str,
    job: dict[str, Any] | None = None,
    user_edges: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    focus_node: dict[str, Any] | None = None,
) -> dict[str, Any]:
    turn_id = f"turn_{uuid4().hex[:10]}"
    task_id = str(task["id"])
    result = task.setdefault("result", {})
    canvas = result.get("knowledge_canvas") or kx.empty_canvas()
    canvas = kx.apply_node_positions(canvas, positions)

    new_nodes: list[dict[str, Any]] = []
    new_edges: list[dict[str, Any]] = []

    # Always refresh PLC knowledge + logic graph onto the canvas when job is ready.
    if job and job.get("status") == "ready":
        canvas = kx.strip_job_plc_nodes(canvas, job_id=str(job.get("id") or ""))
        canvas = kx.strip_dialogue_nodes(canvas)
        plc_nodes = kx.nodes_from_plc_job(job, task_id=task_id, turn_id=turn_id)
        new_nodes.extend(plc_nodes)
        new_edges.extend(kx.edges_from_plc_logic(job, plc_nodes))

    # PLC job canvas = implementation graph only — do not inject dialogue snippets
    if not job and user_text:
        new_nodes.extend(
            kx.nodes_from_text(
                text=user_text,
                role="user",
                turn_id=turn_id,
                task_id=task_id,
                source_type="dialogue",
                start_index=len(canvas.get("nodes") or []) + len(new_nodes),
                limit=2,
            )
        )
    if not job and assistant_text:
        new_nodes.extend(
            kx.nodes_from_text(
                text=assistant_text,
                role="assistant",
                turn_id=turn_id,
                task_id=task_id,
                source_type="dialogue",
                start_index=len(canvas.get("nodes") or []) + len(new_nodes),
                limit=3,
            )
        )

    if not job and focus_node and assistant_text:
        for n in new_nodes:
            if n.get("kind") == "insight":
                new_edges.append(
                    {
                        "id": f"e_{uuid4().hex[:8]}",
                        "source": focus_node["id"],
                        "target": n["id"],
                        "label": "深入",
                        "user_created": False,
                    }
                )

    canvas = kx.merge_canvas(
        canvas,
        new_nodes=new_nodes,
        new_edges=new_edges,
        user_edges=user_edges,
    )
    result["knowledge_canvas"] = canvas
    if job and job.get("status") == "ready":
        result["logic_graph"] = job.get("logic_graph")
        result["blocks"] = job.get("blocks")
    task["result"] = result
    return task


def _link_plc_to_task(task: dict[str, Any], job: dict[str, Any], *, query: str) -> dict[str, Any]:
    task["mode"] = "industrial"
    task["route"] = "plc"
    task["plc_job_id"] = job["id"]
    task["status"] = "completed" if job.get("status") == "ready" else job.get("status") or "queued"
    task["result"] = {
        "route": "plc",
        "plc_job_id": job["id"],
        "summary": job.get("summary"),
        "report": job.get("report"),
        "logic_graph": job.get("logic_graph"),
        "blocks": job.get("blocks"),
        "assistant_message": _assistant_from_plc(job),
        "export_ready": job.get("export_ready"),
        "knowledge_canvas": (task.get("result") or {}).get("knowledge_canvas"),
    }
    task["plan"] = {
        "steps": [
            {"id": "ingest", "title": "PLC ingest", "status": job.get("status")},
            {"id": "graph", "title": "Logic / knowledge graph", "status": "done"},
            {"id": "chat", "title": "Block Q&A", "status": "ready"},
        ]
    }
    task["updated_at"] = _now()
    task["query"] = query or task.get("query") or job.get("project_name") or job["id"]
    return task


def _pack(
    task: dict[str, Any],
    *,
    assistant_message: str,
    route: str,
    plc_job: dict[str, Any] | None,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "task": task,
        "assistant_message": assistant_message,
        "route": route,
        "plc_job": plc_job,
        "knowledge_canvas": (task.get("result") or {}).get("knowledge_canvas") or kx.empty_canvas(),
        "citations": list(citations or []),
    }


async def handle_chat_turn(
    *,
    message: str,
    principal_subject: str,
    workspace_id: str | None,
    session_id: str | None,
    request_id: str,
    runtime: RuntimeClient,
    task_id: str | None = None,
    upload_bytes: bytes | None = None,
    upload_filename: str | None = None,
    mode: str = "deep",
    tia_export_dir: str | None = None,
    focus_node_id: str | None = None,
    block_name: str | None = None,
    canvas_edges_json: str | None = None,
    canvas_positions_json: str | None = None,
    background: BackgroundTasks | None = None,
    schedule_ingest: ScheduleIngest | None = None,
) -> dict[str, Any]:
    text = (message or "").strip()
    user_text = text  # keep original for PLC answers (no deep-dive wrapper echo)
    if not text and not upload_bytes:
        raise ValueError("message or file required")

    user_edges = _parse_user_edges(canvas_edges_json)
    positions = _parse_positions(canvas_positions_json)
    focus_node: dict[str, Any] | None = None
    explicit_block = (block_name or "").strip() or None

    if task_id:
        task = mem.store.tasks.get(task_id)
        if not task:
            raise KeyError(task_id)
        canvas = ((task.get("result") or {}).get("knowledge_canvas")) or kx.empty_canvas()
        if focus_node_id:
            focus_node = kx.find_node(canvas, focus_node_id)
            if focus_node is None and explicit_block:
                # Frontend may use plc_b_{job}_{name} ids while server canvas uses hashed ids.
                focus_node = kx.find_node_by_block_name(canvas, explicit_block)
            # Research route may still wrap; PLC path uses user_text + block_name only.

        plc_job_id = task.get("plc_job_id") or (task.get("result") or {}).get("plc_job_id")
        if plc_job_id:
            job = plc.get_job(str(plc_job_id))
            if not job:
                raise KeyError(plc_job_id)
            if upload_bytes and upload_filename:
                saved = plc.save_upload(upload_filename, upload_bytes)
                job = plc.create_job_record(
                    source_type="upload",
                    source_path=str(saved),
                    project_name="",
                    created_by=principal_subject,
                    upload_filename=upload_filename,
                )
                _link_plc_to_task(task, job, query=text or upload_filename)
                msg = _pending_ingest_message(job)
                task["result"] = {
                    **(task.get("result") or {}),
                    "assistant_message": msg,
                }
                plc.append_chat_turn(
                    job,
                    role="user",
                    content=message or f"上传 {upload_filename}",
                    block_name=None,
                )
                plc.append_chat_turn(job, role="assistant", content=msg, block_name=None)
                _attach_canvas(
                    task,
                    user_text=message,
                    assistant_text=msg,
                    job=job,
                    user_edges=user_edges,
                    positions=positions,
                    focus_node=focus_node,
                )
                with mem.store._lock:
                    mem.store.tasks[task["id"]] = task
                _schedule_plc_ingest(
                    job_id=job["id"],
                    task_id=task["id"],
                    background=background,
                    schedule_ingest=schedule_ingest,
                )
                return _pack(task, assistant_message=msg, route="plc", plc_job=job)

            job_status = str(job.get("status") or "")
            if job_status in {"queued", "running"} and not job.get("brief_ready"):
                msg = (
                    f"工程仍在解析中（状态：{job_status}），请稍候再提问。"
                    f"作业 ID：{job['id']}"
                    "结构清单就绪后可先读 Project Brief，不必等全文翻译。"
                )
                plc.append_chat_turn(job, role="user", content=user_text, block_name=None)
                plc.append_chat_turn(job, role="assistant", content=msg, block_name=None)
                task["updated_at"] = _now()
                task["result"] = {
                    **(task.get("result") or {}),
                    "route": "plc",
                    "plc_job_id": job["id"],
                    "assistant_message": msg,
                }
                with mem.store._lock:
                    mem.store.tasks[task["id"]] = task
                return _pack(task, assistant_message=msg, route="plc", plc_job=job)

            resolved_block = explicit_block
            if not resolved_block and focus_node and focus_node.get("kind") == "plc_block":
                src = focus_node.get("source") if isinstance(focus_node.get("source"), dict) else {}
                resolved_block = str(
                    (src or {}).get("block_name") or focus_node.get("label") or ""
                ).strip() or None
            plc.append_chat_turn(job, role="user", content=user_text, block_name=resolved_block)
            answer = plc.answer_block_chat(job, user_text, resolved_block)
            citations = list(job.pop("_last_citations", None) or [])
            plc.append_chat_turn(
                job,
                role="assistant",
                content=answer,
                block_name=resolved_block,
                citations=citations,
            )
            task["updated_at"] = _now()
            task["result"] = {
                **(task.get("result") or {}),
                "route": "plc",
                "plc_job_id": job["id"],
                "assistant_message": answer,
                "report": job.get("report"),
                "logic_graph": job.get("logic_graph"),
                "blocks": job.get("blocks"),
                "chat": job.get("chat"),
            }
            _attach_canvas(
                task,
                user_text=message,
                assistant_text=answer,
                job=job,
                user_edges=user_edges,
                positions=positions,
                focus_node=focus_node,
            )
            with mem.store._lock:
                mem.store.tasks[task["id"]] = task
            return _pack(
                task,
                assistant_message=answer,
                route="plc",
                plc_job=job,
                citations=citations,
            )

    decision = detect_route(
        text or (upload_filename or ""),
        tia_export_dir=tia_export_dir,
        mode=mode,
        has_upload=bool(upload_bytes),
    )

    if decision.route == "plc_need_source":
        task = new_task(
            {
                "query": message or text,
                "mode": "industrial",
                "workspace_id": workspace_id,
                "session_id": session_id,
                "options": {"model_profile": resolve_model_profile("default")},
                "context": {},
                "route": "plc",
                "plc_job_id": None,
            }
        )
        msg = "需要工程路径或上传 XML / ZIP / .zap / .ap19。"
        task["status"] = "interrupted"
        task["result"] = {"route": "plc", "needs_source": True, "assistant_message": msg}
        task["interrupts"] = [
            {"id": "need_plc_source", "prompt": "提供 PLC 工程路径或上传文件", "options": ["path", "upload"]}
        ]
        _attach_canvas(
            task,
            user_text=message,
            assistant_text=msg,
            user_edges=user_edges,
            positions=positions,
            focus_node=focus_node,
        )
        return _pack(task, assistant_message=msg, route="plc", plc_job=None)

    if decision.route == "plc":
        if upload_bytes and upload_filename:
            saved = plc.save_upload(upload_filename, upload_bytes)
            job = plc.create_job_record(
                source_type="upload",
                source_path=str(saved),
                project_name="",
                created_by=principal_subject,
                upload_filename=upload_filename,
            )
        else:
            path = decision.path or (tia_export_dir or "").strip()
            if not path:
                raise ValueError("PLC route requires path or upload")
            resolved = plc.resolve_allowed_path(path)
            job = plc.create_job_record(
                source_type="path",
                source_path=str(resolved),
                project_name="",
                created_by=principal_subject,
            )
        task = new_task(
            {
                "query": text or upload_filename or job.get("project_name") or job["id"],
                "mode": "industrial",
                "workspace_id": workspace_id,
                "session_id": session_id,
                "options": {"model_profile": resolve_model_profile("default")},
                "context": {},
            }
        )
        _link_plc_to_task(task, job, query=task["query"])
        msg = _pending_ingest_message(job)
        task["result"] = {
            **(task.get("result") or {}),
            "assistant_message": msg,
        }
        plc.append_chat_turn(
            job,
            role="user",
            content=message or upload_filename or task["query"],
            block_name=None,
        )
        plc.append_chat_turn(job, role="assistant", content=msg, block_name=None)
        # Path + extra question: deferred until ingest completes (frontend re-asks / polls).
        pending_q = ""
        if text and decision.path:
            pending_q = text.replace(decision.path, "").strip()
        if pending_q:
            task["result"]["pending_question"] = pending_q
        _attach_canvas(
            task,
            user_text=message,
            assistant_text=msg,
            job=job,
            user_edges=user_edges,
            positions=positions,
            focus_node=focus_node,
        )
        _schedule_plc_ingest(
            job_id=job["id"],
            task_id=task["id"],
            background=background,
            schedule_ingest=schedule_ingest,
        )
        return _pack(task, assistant_message=msg, route="plc", plc_job=job)

    opts_profile = resolve_model_profile("default")
    # Continue research thread: keep same task id when provided and not PLC
    if task_id and mem.store.tasks.get(task_id) and not (
        mem.store.tasks[task_id].get("plc_job_id")
        or (mem.store.tasks[task_id].get("result") or {}).get("plc_job_id")
    ):
        task = mem.store.tasks[task_id]
        payload = {
            "query": text,
            "mode": task.get("mode") or "deep",
            "workspace_id": workspace_id,
            "session_id": session_id,
            "request_id": request_id,
            "created_by": principal_subject,
            "options": task.get("options")
            or {
                "language": "zh-CN",
                "enable_web": True,
                "citation_required": True,
                "report_format": ["markdown"],
                "model_profile": opts_profile,
            },
            "context": {},
        }
        upstream = await runtime.create_task({**payload, "task_id": task["id"]})
        assistant = (
            f"围绕已有话题继续研究。\n焦点：{focus_node.get('label') if focus_node else '（全局）'}\n"
            f"状态：{upstream.get('status', 'queued')}"
        )
        if focus_node:
            assistant += f"\n节点摘要：{focus_node.get('summary')}"
        assistant = _with_knowledge_recall(assistant, text)
        task["status"] = upstream.get("status", "queued")
        task["result"] = {
            **(task.get("result") or {}),
            "route": "research",
            "runtime": upstream,
            "assistant_message": assistant,
        }
        task["updated_at"] = _now()
        _attach_canvas(
            task,
            user_text=message,
            assistant_text=assistant,
            user_edges=user_edges,
            positions=positions,
            focus_node=focus_node,
        )
        with mem.store._lock:
            mem.store.tasks[task["id"]] = task
        return _pack(task, assistant_message=assistant, route="research", plc_job=None)

    payload = {
        "query": text,
        "mode": mode if mode in {"quick", "deep", "industrial"} else "deep",
        "workspace_id": workspace_id,
        "session_id": session_id,
        "request_id": request_id,
        "created_by": principal_subject,
        "options": {
            "language": "zh-CN",
            "enable_web": True,
            "citation_required": True,
            "report_format": ["markdown"],
            "model_profile": opts_profile,
        },
        "context": {},
    }
    task = new_task(
        {
            "query": text,
            "mode": payload["mode"],
            "workspace_id": workspace_id,
            "session_id": session_id,
            "options": payload["options"],
            "context": {},
            "route": "research",
        }
    )
    upstream = await runtime.create_task({**payload, "task_id": task["id"]})
    assistant = _with_knowledge_recall(
        "已记录研究议题。画布会出现本轮提炼的知识节点。",
        text,
    )
    task["status"] = upstream.get("status", "queued")
    task["result"] = {
        "route": "research",
        "runtime": upstream,
        "assistant_message": assistant,
    }
    task["updated_at"] = _now()
    _attach_canvas(
        task,
        user_text=message,
        assistant_text=assistant,
        user_edges=user_edges,
        positions=positions,
        focus_node=focus_node,
    )
    logger.info("chat turn route=research task=%s request_id=%s", task["id"], request_id)
    return _pack(task, assistant_message=assistant, route="research", plc_job=None)
