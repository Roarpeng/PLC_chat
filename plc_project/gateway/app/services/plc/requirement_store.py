"""Server-side process-requirement store + LLM draft assembly (契约 docs/22 §1/§2).

工艺需求卡(ProcessRequirement)是工作台「从工艺需求开始」入口的后端权威数据:
LLM 生成草稿(**不落盘**)→ 工程师编辑/确认后整卡 PUT → confirm-writeback 时按
可选 ``requirement_id`` 弱关联进 PCEC 事务 intent。

铁律(契约 §1):``confirmation_status=confirmed`` 仅表示工艺意图确认,本存储
不触发任何 ops/写回——后端只记账,动作永远由确认门禁端点承载。

存储布局(风格对齐 ``session_store.py``)::

    requirements/<id>/meta.json          # id/summary/status/updated_at/task_kind(列表只读这个)
    requirements/<id>/requirement.json   # 完整需求卡(items/open_questions/...)

写入为 temp+rename 原子替换;列表按 updated_at 降序;坏文件跳过不炸列表;
单卡 10MB 上限;id 形如 ``req-<hex12>``。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_REQUIREMENT_ID_RE = re.compile(r"^req-[0-9a-f]{12}$")
_MAX_REQUIREMENT_BYTES = 10 * 1024 * 1024  # 单卡 10MB 上限,防异常输入撑爆磁盘

#: items[].kind 五类拆解(契约 §1)
ITEM_KINDS = ("precondition", "sequence", "exception", "constraint", "acceptance")
#: items[].source 三态:engineering(带 source_ref)/user/inferred
ITEM_SOURCES = ("engineering", "user", "inferred")
#: confirmation_status 三值;confirmed 仅表示工艺意图确认,绝不触发写回
CONFIRMATION_STATUSES = ("proposed", "confirmed", "rejected")
#: 任务四态(契约 §3 TaskKind)
TASK_KINDS = ("understand", "diagnose", "improve", "refactor")


def requirements_root(settings: Any | None = None) -> Path:
    work = ""
    if settings is not None:
        work = str(getattr(settings, "plc_work_dir", "") or "").strip()
    if not work:
        work = os.getenv("PLC_WORK_DIR", "").strip()
    base = Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"
    root = base / "requirements"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _valid_id(requirement_id: str) -> bool:
    return bool(_REQUIREMENT_ID_RE.match(requirement_id or ""))


def is_valid_requirement_id(requirement_id: str) -> bool:
    """公开的 id 格式判定(confirm-writeback 弱关联透传前校验用)。"""
    return _valid_id(requirement_id)


def new_requirement_id() -> str:
    return f"req-{uuid.uuid4().hex[:12]}"


def _now_ts() -> float:
    return time.time()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x or "").strip()]


def _normalize_items(raw: Any) -> list[dict[str, Any]]:
    """items 结构校验+归一:必须是 list(允许空),每条 kind∈五类、source∈三态。"""
    if not isinstance(raw, list):
        raise ValueError("requirement.items must be a list")
    items: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"requirement.items[{i}] must be an object")
        kind = str(item.get("kind") or "")
        if kind not in ITEM_KINDS:
            raise ValueError(
                f"requirement.items[{i}].kind must be one of: {', '.join(ITEM_KINDS)}"
            )
        source = str(item.get("source") or "")
        if source not in ITEM_SOURCES:
            raise ValueError(
                f"requirement.items[{i}].source must be one of: {', '.join(ITEM_SOURCES)}"
            )
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(f"requirement.items[{i}].text required")
        items.append(
            {
                "id": str(item.get("id") or f"it-{i + 1}"),
                "kind": kind,
                "text": text,
                "source": source,
                "source_ref": str(item.get("source_ref") or ""),
            }
        )
    return items


def validate_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    """校验并归一为契约 §1 的 12 字段规范形;非法结构抛 ValueError(路由层→400)。"""
    data = requirement if isinstance(requirement, dict) else {}
    rid = str(data.get("requirement_id") or "")
    if not _valid_id(rid):
        raise ValueError("requirement.requirement_id invalid (expected req-<hex12>)")
    confirmation = str(data.get("confirmation_status") or "")
    if confirmation not in CONFIRMATION_STATUSES:
        raise ValueError(
            "requirement.confirmation_status must be one of: "
            + ", ".join(CONFIRMATION_STATUSES)
        )
    task_kind = str(data.get("task_kind") or "").strip()
    if not task_kind:
        task_kind = "understand"
    if task_kind not in TASK_KINDS:
        raise ValueError(f"requirement.task_kind must be one of: {', '.join(TASK_KINDS)}")
    return {
        "requirement_id": rid,
        "project_name": str(data.get("project_name") or ""),
        "created_at": float(data.get("created_at") or 0.0),
        "updated_at": float(data.get("updated_at") or 0.0),
        "confirmation_status": confirmation,
        "intent_summary": str(data.get("intent_summary") or ""),
        "items": _normalize_items(data.get("items")),
        "open_questions": _str_list(data.get("open_questions")),
        "linked_blocks": _str_list(data.get("linked_blocks")),
        "linked_signals": _str_list(data.get("linked_signals")),
        "task_kind": task_kind,
        "origin_prompt": str(data.get("origin_prompt") or ""),
    }


def _meta_from_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(requirement.get("requirement_id") or ""),
        "summary": str(requirement.get("intent_summary") or "")[:120],
        "status": str(requirement.get("confirmation_status") or ""),
        "updated_at": requirement.get("updated_at") or 0,
        "task_kind": str(requirement.get("task_kind") or ""),
    }


def list_requirements(settings: Any | None = None) -> list[dict[str, Any]]:
    """全部需求卡 meta,按 updated_at 降序;坏文件跳过不炸列表。"""
    metas: list[dict[str, Any]] = []
    for meta_file in requirements_root(settings).glob("*/meta.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            metas.append(data)
    metas.sort(key=lambda m: (-(float(m.get("updated_at") or 0)), str(m.get("id"))))
    return metas


def get_requirement(requirement_id: str, settings: Any | None = None) -> dict[str, Any] | None:
    """读完整需求卡;非法 id / 缺失 / 坏文件返回 None。"""
    if not _valid_id(requirement_id):
        return None
    path = requirements_root(settings) / requirement_id / "requirement.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def put_requirement(requirement: dict[str, Any], settings: Any | None = None) -> dict[str, Any]:
    """整卡 upsert:校验归一 → 原子写 requirement.json + meta.json,返回规范形。

    非法 id / items 结构 / 枚举值拒绝(ValueError);超 10MB 拒绝;更新时保留
    首次 created_at,updated_at 取当前时刻。
    """
    rid = str((requirement or {}).get("requirement_id") or "")
    if not _valid_id(rid):
        raise ValueError("requirement.requirement_id invalid (expected req-<hex12>)")
    normalized = validate_requirement(requirement)
    now = _now_ts()
    existing = get_requirement(rid, settings)
    normalized["created_at"] = float(
        (existing or {}).get("created_at") or normalized["created_at"] or now
    )
    normalized["updated_at"] = now
    payload = json.dumps(normalized, ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_REQUIREMENT_BYTES:
        raise ValueError("requirement too large (>10MB)")
    root = requirements_root(settings) / rid
    _atomic_write(root / "requirement.json", payload)
    _atomic_write(
        root / "meta.json", json.dumps(_meta_from_requirement(normalized), ensure_ascii=False)
    )
    return normalized


def delete_requirement(requirement_id: str, settings: Any | None = None) -> bool:
    """删除需求卡;幂等(目录不存在也返回 True);非法 id 返回 False。"""
    if not _valid_id(requirement_id):
        return False
    import shutil

    path = requirements_root(settings) / requirement_id
    if not path.is_dir():
        return True
    shutil.rmtree(path, ignore_errors=True)
    return True


# ------------------------------------------------------- LLM 草稿组装(§2) --


def build_draft_messages(
    prompt: str, block_names: list[str], task_kind: str = ""
) -> list[dict[str, str]]:
    """需求卡草稿提示词:系统角色=工艺需求分析师,输出严格 JSON(契约 §1 结构)。"""
    system = (
        "你是一位资深 PLC 工艺需求分析师。把用户的工艺描述拆解成结构化需求卡,"
        "严格输出一个 JSON 对象(不要 markdown 代码块、不要 JSON 以外的任何文字),结构:\n"
        "{\n"
        '  "project_name": "项目名(未知给空串)",\n'
        '  "intent_summary": "一句话工艺意图",\n'
        '  "items": [{"id": "it-1", '
        '"kind": "precondition|sequence|exception|constraint|acceptance", '
        '"text": "条目内容(中文)", '
        '"source": "engineering|user|inferred", '
        '"source_ref": "证据引用(块名或块名+网络号,无证据给空串)"}],\n'
        '  "open_questions": ["必须工程师确认的问题"],\n'
        '  "task_kind": "understand|diagnose|improve|refactor"\n'
        "}\n"
        "拆解与来源规则:\n"
        "1. items 按前置条件(precondition)/动作序列(sequence)/异常处理(exception)/"
        "约束(constraint)/验收标准(acceptance)五类拆解;\n"
        "2. 来源判定:内容能对应到「画布块清单」中的块时标 engineering,source_ref 写块名"
        "(可附网络号);用户原话明确表达的要求标 user;你推测/补全的内容标 inferred;\n"
        "3. 任何未知数值参数(超时时间、延时时长、阈值等)一律不得编造数值:不写入 items,"
        '而是把"XX 取多少?(需工程师确认)"这类问题写入 open_questions;\n'
        "4. 不要输出 confirmation_status / linked_blocks(服务端固定/计算);全部中文。"
    )
    user = json.dumps(
        {
            "用户输入": prompt,
            "任务类型": task_kind or "understand",
            "画布块清单(来源判定与 source_ref 只允许引用这里的块名)": list(block_names or []),
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_draft_json(text: str) -> dict[str, Any]:
    """LLM 输出 → JSON 对象;容忍 ```json 围栏或前后杂文字;失败抛 ValueError。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("LLM output is empty")
    try:
        data = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM output is not JSON") from None
        try:
            data = json.loads(raw[start : end + 1])
        except ValueError as exc:
            raise ValueError(f"LLM output is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("LLM output must be a JSON object")
    return data


def match_linked_blocks(items: list[dict[str, Any]], block_names: list[str]) -> list[str]:
    """linked_blocks = items(text+source_ref)提及的画布块名(大小写不敏感,保持画布顺序)。"""
    corpus = " \n".join(
        f"{str(it.get('text') or '')} {str(it.get('source_ref') or '')}" for it in items
    ).lower()
    return [name for name in block_names or [] if name and name.lower() in corpus]


def requirement_from_llm_payload(
    text: str,
    *,
    prompt: str,
    block_names: list[str],
    task_kind: str = "",
    project_name_fallback: str = "",
) -> dict[str, Any]:
    """LLM 原始输出 → 契约 §1 规范形草稿;结构不符抛 ValueError(路由层重试一次)。

    服务端硬规则:confirmation_status 恒 ``proposed``(无视 LLM 输出);
    requirement_id/时间戳服务端生成;linked_blocks 从 items 提及的画布块名匹配;
    task_kind 以请求体优先,其次 LLM 输出,再缺省 understand。
    """
    payload = parse_draft_json(text)
    summary = str(payload.get("intent_summary") or "").strip()
    if not summary:
        raise ValueError("draft.intent_summary required")
    items = _normalize_items(payload.get("items"))
    if not items:
        raise ValueError("draft.items must be a non-empty list")
    effective_task = str(task_kind or payload.get("task_kind") or "").strip()
    if not effective_task:
        effective_task = "understand"
    if effective_task not in TASK_KINDS:
        raise ValueError(f"draft.task_kind must be one of: {', '.join(TASK_KINDS)}")
    now = _now_ts()
    draft = {
        "requirement_id": new_requirement_id(),
        "project_name": str(payload.get("project_name") or project_name_fallback or ""),
        "created_at": now,
        "updated_at": now,
        "confirmation_status": "proposed",
        "intent_summary": summary,
        "items": items,
        "open_questions": _str_list(payload.get("open_questions")),
        "linked_blocks": match_linked_blocks(items, block_names),
        "linked_signals": [],
        "task_kind": effective_task,
        "origin_prompt": prompt,
    }
    return validate_requirement(draft)
