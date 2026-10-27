"""AF V1.2 Mermaid Sequence Diagram Parser (D 线契约 docs/24 §D).

把 Mermaid ``sequenceDiagram`` 纯文本解析为步序并组装成官方 AF V1.2 领域模型:

- ``parse_mermaid_sequence(text)``:纯文本解析(零 LLM),识别
  ``participant X as 名称`` / ``actor``、``X->>Y: 消息``(含 ``-->>``/``->``/
  ``-->``/``-x``/``--x``)、``alt 条件`` / ``else`` / ``end``、``Note over X: 内容``;
  未声明的消息收发方按首次出现顺序补进 participants。
- ``mermaid_to_af_steps(parsed, cms=None)``:participant → CM(类型复用
  ``planner._classify_cm_type`` 按名称推断);消息文本 → action/transition
  (复用 ``planner._synthesize_step_action_and_condition``,命令严格走
  ``#controlNodes.<cm>.commands/status``);``alt`` 首臂视作条件主路径,
  ``else`` 臂视作异常分支(9xx 错误区步号 ×10 链,description 标注
  ``[异常分支:条件]``,alt 前最后一个主步的 ``error_step_id`` 指向首个异常步,
  异常链末步回 999 错误步);Note → 步骤注释。
- ``plan_from_mermaid(mermaid_text, project_name)``:组装完整 ``AfProject``
  (复用 af_model 结构 + ``planner._build_default_steps_for_cms`` 兜底)。

非法输入(空文本/非 sequenceDiagram/alt-end 不配对/无参与方无步骤)抛
``MermaidParseError``(ValueError 子类,code 即 str(exc)),由上层 API 映射 400。
"""

from __future__ import annotations

import re
from typing import Any

from plc_engine.af.af_model import (
    AfCm,
    AfEm,
    AfJob,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)
from plc_engine.af.planner import (
    _KEYWORD_TO_CM_INFO,
    _build_default_steps_for_cms,
    _classify_cm_type,
    _clean_identifier,
    _extract_latin_identifier,
    _synthesize_step_action_and_condition,
)

__all__ = [
    "MermaidParseError",
    "mermaid_participants_to_cms",
    "mermaid_to_af_steps",
    "parse_mermaid_sequence",
    "plan_from_mermaid",
]

# 消息箭头行:发送方/接收方不含 '-' 和 '.',避免 "A-->B" 的发送方贪婪吃掉 '--'
_ARROW_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_\u4e00-\u9fa5]+)"            # 发送方
    r"\s*(-->>|--x|-->|->>|-x|->)"                  # 箭头(长操作符在前)
    r"\s*([A-Za-z0-9_\u4e00-\u9fa5]+)"             # 接收方
    r"\s*:\s*(.*)$"                                 # 消息文本
)
_PARTICIPANT_LINE_RE = re.compile(
    r"^\s*(?:participant|actor)\s+([^\s]+)(?:\s+[Aa][Ss]\s+(.+))?$"
)
_ALT_LINE_RE = re.compile(r"^\s*alt\s+(.+)$")
_ELSE_LINE_RE = re.compile(r"^\s*else\s*(.*)$")
_OPT_LINE_RE = re.compile(r"^\s*opt\s+(.+)$")
_NOTE_LINE_RE = re.compile(
    r"^\s*[Nn]ote\s+(?:over|left of|right of)\s+([^:]+?)\s*:\s*(.*)$"
)
# 会开作用域(需自有 end 配对)的其它 Mermaid 块;and/also/option 是 par/critical
# 的子臂,不单独开作用域,不在此列
_BLOCK_OPEN_RE = re.compile(r"^\s*(?:loop|par|critical|break|box|rect|background)\b")
_END_LINE_RE = re.compile(r"^\s*end\b")
_SEQ_HEADER_RE = re.compile(r"^\s*sequenceDiagram\b", re.IGNORECASE)

#: 异常分支步号基址(9xx 错误区,避开 AF 约定的 999 错误步;仍保持 ×10 链)
_EXC_STEP_BASE = 900


class MermaidParseError(ValueError):
    """Mermaid 文本不合法(空/非时序图/块不配对),API 层映射 400。"""


def parse_mermaid_sequence(text: str) -> dict[str, Any]:
    """解析 Mermaid sequenceDiagram 文本为步序结构(纯文本解析,不用 LLM)。

    Returns:
        ``{
            "participants": [显示名, ...],   # 声明序;消息隐式参与方按首现追加
            "steps": [{
                "seq": int,                  # 1 起的消息序号(Note 不占号)
                "actor": 发送方显示名,
                "target": 接收方显示名,
                "action": 消息文本,
                "condition": None | 所在 alt/opt/else 臂条件,
                "note": None | 附着的 Note 内容,
                "branch": None | {"index": 臂序号, "kind": "alt"|"opt"|"else"},
            }],
            "alt_branches": [{"condition": str, "kind": "alt"|"opt"|"else", "steps": [seq]}],
        }``

    Raises:
        MermaidParseError: 空文本 / 无 sequenceDiagram 头 / alt-end 不配对 /
            既无参与方也无步骤。
    """
    if not isinstance(text, str) or not text.strip():
        raise MermaidParseError("MERMAID_EMPTY")

    lines = text.splitlines()
    if not any(_SEQ_HEADER_RE.match(ln) for ln in lines):
        raise MermaidParseError("MERMAID_NOT_SEQUENCE")

    participants: list[str] = []
    alias_map: dict[str, str] = {}  # `participant X as 名称` 的别名 → 显示名
    steps: list[dict[str, Any]] = []
    alt_branches: list[dict[str, Any]] = []
    # 作用域栈:alt/opt 推入臂上下文(is_branch);loop/par 等推入普通块标记(内部步骤归主链)
    stack: list[dict[str, Any]] = []
    pending_note: str | None = None  # 尚无前序步骤可挂的 Note,向后挂到下一条消息

    def _ensure_participant(name: str) -> str:
        name = name.strip()
        if name and name not in participants:
            participants.append(name)
        return name

    def _resolve_participant(name: str) -> str:
        return _ensure_participant(alias_map.get(name.strip(), name.strip()))

    def _current_arm() -> dict[str, Any] | None:
        for ctx in reversed(stack):
            if ctx.get("is_branch"):
                return ctx
        return None

    for line in lines:
        # 1) participant / actor 声明
        m = _PARTICIPANT_LINE_RE.match(line)
        if m:
            alias = m.group(1)
            display = (m.group(2) or m.group(1)).strip()
            if display:
                alias_map[alias] = display
                _ensure_participant(display)
            continue

        # 2) Note over / left of / right of
        m = _NOTE_LINE_RE.match(line)
        if m:
            note_text = (m.group(2) or "").strip()
            if not note_text:
                continue
            if steps:
                last = steps[-1]
                last["note"] = (
                    f'{last["note"]}; {note_text}' if last.get("note") else note_text
                )
            else:
                pending_note = (
                    f"{pending_note}; {note_text}" if pending_note else note_text
                )
            continue

        # 3) 消息 X->>Y: text(收发方先过别名映射)
        m = _ARROW_LINE_RE.match(line)
        if m:
            actor = _resolve_participant(m.group(1))
            target = _resolve_participant(m.group(3))
            action = (m.group(4) or "").strip()
            if not action:
                continue
            arm = _current_arm()
            step: dict[str, Any] = {
                "seq": len(steps) + 1,
                "actor": actor,
                "target": target,
                "action": action,
                "condition": arm["condition"] if arm else None,
                "note": pending_note,
                "branch": (
                    {"index": arm["branch_index"], "kind": arm["kind"]} if arm else None
                ),
            }
            pending_note = None
            steps.append(step)
            if arm is not None:
                alt_branches[arm["branch_index"]]["steps"].append(step["seq"])
            continue

        # 4) alt / opt / else / end / 其它块开闭
        m = _ALT_LINE_RE.match(line)
        if m:
            cond = m.group(1).strip()
            alt_branches.append({"condition": cond, "kind": "alt", "steps": []})
            stack.append(
                {
                    "is_branch": True,
                    "kind": "alt",
                    "condition": cond,
                    "branch_index": len(alt_branches) - 1,
                }
            )
            continue
        m = _OPT_LINE_RE.match(line)
        if m:
            cond = m.group(1).strip()
            alt_branches.append({"condition": cond, "kind": "opt", "steps": []})
            stack.append(
                {
                    "is_branch": True,
                    "kind": "opt",
                    "condition": cond,
                    "branch_index": len(alt_branches) - 1,
                }
            )
            continue
        m = _ELSE_LINE_RE.match(line)
        if m:
            arm = _current_arm()
            if arm is None:
                raise MermaidParseError("MERMAID_UNBALANCED")
            cond = (m.group(1) or "").strip() or f'否则({arm["condition"]}不成立)'
            arm["kind"] = "else"
            arm["condition"] = cond
            alt_branches.append({"condition": cond, "kind": "else", "steps": []})
            arm["branch_index"] = len(alt_branches) - 1
            continue
        if _END_LINE_RE.match(line):
            if not stack:
                raise MermaidParseError("MERMAID_UNBALANCED")
            stack.pop()
            continue
        if _BLOCK_OPEN_RE.match(line):
            stack.append({"is_branch": False})
            continue

        # 5) 头/注释/autonumber/title/空行等:静默跳过(sequenceDiagram 头已校验)

    if stack:
        raise MermaidParseError("MERMAID_UNBALANCED")
    if not participants and not steps:
        raise MermaidParseError("MERMAID_EMPTY")

    return {"participants": participants, "steps": steps, "alt_branches": alt_branches}


def mermaid_participants_to_cms(participants: list[str]) -> list[AfCm]:
    """participant 显示名 → ``AfCm`` 列表(类型按名称复用 ``planner._classify_cm_type``)。

    标识符优先取名称内首个拉丁词,其次名称本身清洗;纯中文名回退到
    关键词表前缀(cyl/motor/axis/sensor)。重复标识符加序号去重。
    """
    cms: list[AfCm] = []
    used: set[str] = set()
    for display in participants:
        name = str(display or "").strip()
        if not name:
            continue
        cm_type = _classify_cm_type(name)
        prefix = "dev"
        for kw_list, pref, _ctype in _KEYWORD_TO_CM_INFO:
            if any(k in name.lower() for k in kw_list):
                prefix = pref
                break
        ident = _extract_latin_identifier(name) or _clean_identifier(name, prefix)
        if not re.search(r"[A-Za-z]", ident):  # 纯中文清洗为空 → 关键词前缀兜底
            ident = prefix
        if ident in used:
            i = 2
            while f"{ident}{i}" in used:
                i += 1
            ident = f"{ident}{i}"
        used.add(ident)
        cms.append(AfCm(name=ident, cm_type=cm_type, description=name[:100]))
    return cms


def mermaid_to_af_steps(
    parsed: dict[str, Any], cms: list[AfCm] | None = None
) -> list[AfSequenceStep]:
    """解析结果 → ``AfSequenceStep`` 列表(步号 ×10 链)。

    - participant → CM(``cms`` 缺省时按 participants 现场推断);
    - 消息文本(+ 接收方名)→ action/transition,复用
      ``planner._synthesize_step_action_and_condition``(命令严格走
      ``#controlNodes.<cm>.commands/status``);
    - alt/opt 首臂 = 条件主路径:进主链 10/20/30…,description 标注
      ``[分支:条件]``,末步回 1(Ready,与 planner 约定一致);
    - else 臂 = 异常分支:进 9xx 错误区步号链(900/910…),description 标注
      ``[异常分支:条件]``,alt 结构前最后一个主步的 ``error_step_id`` 指向
      首个异常步,异常链末步回 999(AF 错误步);
    - Note → 追加为步骤注释 action(``// Note: ...``)。
    """
    participants = list(parsed.get("participants") or [])
    if cms is None:
        cms = mermaid_participants_to_cms(participants)

    raw_steps = list(parsed.get("steps") or [])
    main_raw = [s for s in raw_steps if (s.get("branch") or {}).get("kind") != "else"]
    exc_raw = [s for s in raw_steps if (s.get("branch") or {}).get("kind") == "else"]
    first_exc_seq = min((int(s.get("seq") or 0) for s in exc_raw), default=None)

    def _build(raw: dict[str, Any], tag: str) -> AfSequenceStep:
        target = str(raw.get("target") or "")
        action = str(raw.get("action") or "")
        s_name, actions, transition = _synthesize_step_action_and_condition(
            f"{target} {action}", cms
        )
        description = action[:120]
        condition = raw.get("condition")
        if condition:
            description = f"[{tag}:{condition}] {description}"
        note = raw.get("note")
        if note:
            actions = [*actions, f"// Note: {note}"]
            description = f"{description} (Note: {note})"
        return AfSequenceStep(
            step_id=0,  # 由下方统一编链
            name=s_name,
            description=description[:200],
            actions=actions,
            transition_condition=transition,
        )

    # 主链:10/20/30…(含 alt/opt 首臂条件路径)
    main_steps: list[tuple[int, AfSequenceStep]] = []  # (原始 seq, step)
    step_id = 10
    for raw in main_raw:
        st = _build(raw, tag="分支")
        st.step_id = step_id
        main_steps.append((int(raw.get("seq") or 0), st))
        step_id += 10
    for i in range(len(main_steps)):
        main_steps[i][1].next_step_id = (
            main_steps[i + 1][1].step_id if i + 1 < len(main_steps) else 1
        )

    # 异常分支链(else 臂):9xx 错误区,末步回 999
    exc_steps: list[AfSequenceStep] = []
    exc_id = _EXC_STEP_BASE
    for raw in exc_raw:
        st = _build(raw, tag="异常分支")
        st.step_id = exc_id
        exc_steps.append(st)
        exc_id += 10
    for i in range(len(exc_steps)):
        exc_steps[i].next_step_id = (
            exc_steps[i + 1].step_id if i + 1 < len(exc_steps) else 999
        )

    # alt 结构前最后一个主步 error_step_id → 首个异常步(异常路径锚点)
    if exc_steps and first_exc_seq is not None:
        anchor: AfSequenceStep | None = None
        for raw_seq, st in main_steps:
            if raw_seq < first_exc_seq:
                anchor = st
        if anchor is not None:
            anchor.error_step_id = exc_steps[0].step_id

    return [st for _, st in main_steps] + exc_steps


def plan_from_mermaid(mermaid_text: str, project_name: str = "AF_Project") -> AfProject:
    """Mermaid sequenceDiagram → 完整 ``AfProject``(docs/24 §D)。

    participant → CM;消息/alt/Note → 步序;无消息时复用
    ``planner._build_default_steps_for_cms`` 兜底标准工序。单 Unit 起步
    (``U1_<工程名>``),EM1 命名 ``ProcessStation``,结构与 planner 产物一致,
    可直接喂给 ``af_generator.generate_af_project_blocks``。
    """
    parsed = parse_mermaid_sequence(mermaid_text)

    cms = mermaid_participants_to_cms(parsed["participants"])
    steps = mermaid_to_af_steps(parsed, cms)
    if not steps:
        steps = _build_default_steps_for_cms(cms)

    proj_name = _clean_identifier(
        str(project_name or "").strip() or "AF_Project", "Project"
    )
    em1 = AfEm(
        em_idx=1,
        name="ProcessStation",
        description=(
            f"From Mermaid sequenceDiagram: {len(parsed['steps'])} steps, "
            f"{len(parsed['alt_branches'])} branches"
        ),
        jobs=[
            AfJob(
                job_id=1,
                name="AutoProduction",
                description="Automatic production cycle job (from Mermaid)",
                initial_step=steps[0].step_id if steps else 10,
            )
        ],
        sequence=AfSequence(initial_step=0, ready_step=1, steps=steps),
        control_modules=cms,
    )
    unit1 = AfUnit(
        unit_idx=1,
        name=_clean_identifier(proj_name, "Unit1"),
        description=(
            f"Generated from Mermaid sequenceDiagram "
            f"({len(parsed['participants'])} participants)"
        ),
        equipment_modules=[em1],
    )
    return AfProject(
        name=proj_name,
        description=(
            f"AF V1.2 project planned from Mermaid sequenceDiagram "
            f"({len(parsed['participants'])} participants, {len(parsed['steps'])} steps)"
        ),
        units=[unit1],
    )
