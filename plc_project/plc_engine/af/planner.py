"""AF V1.2 Architecture Planner.

Transforms process specifications (natural language text, structured requirement cards,
or JSON dictionaries) into official Siemens Automation Framework (AF) V1.2 domain models
(AfProject, AfUnit, AfEm, AfJob, AfSequence, AfCm).

Enforces AF V1.2 rules:
- Auto-assigns LBC_* control modules for equipment:
  * Cylinder / Actuator -> LBC_TwoWayActuator
  * Sensor / Detector   -> LBC_DigitalSignal
  * Motor / Conveyor    -> LBC_MotorStarter
  * Servo / Axis        -> LBC_AxisControl
- Generates Sequence steps strictly commanding CMs via #controlNodes.<cm>.commands.
- Chaining steps with valid step IDs (10, 20, 30...) and transitions based on #controlNodes.<cm>.status.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from plc_engine.af.af_model import (
    AfCm,
    AfCmType,
    AfEm,
    AfJob,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)

logger = logging.getLogger("researchos.plc.af.planner")

VALID_CM_TYPES: set[str] = {
    "LBC_TwoWayActuator",
    "LBC_SimpleActuator",
    "LBC_ThreeWayActuator",
    "LBC_DigitalSignal",
    "LBC_AnalogInput",
    "LBC_AnalogOutput",
    "LBC_AxisControl",
    "LBC_Pt1Filter",
    "LBC_MotorStarter",
    "LBC_DriveControl_StdPlc",
}

# Common name transliterations/mappings for Chinese process keywords
_KEYWORD_TO_CM_INFO: list[tuple[list[str], str, AfCmType]] = [
    # (keywords, default_identifier_prefix, CM_Type)
    (["伺服", "轴", "servo", "axis", "步进", "stepper"], "axis", "LBC_AxisControl"),
    (["电机", "马达", "传送带", "输送", "conveyor", "motor", "pump", "泵"], "motor", "LBC_MotorStarter"),
    (["气缸", "气动", "双向执行器", "推料", "顶升", "夹爪", "夹紧", "压头", "cylinder", "actuator", "clamp", "pusher", "lifter"], "cyl", "LBC_TwoWayActuator"),
    (["传感器", "检测", "到位", "料位", "光电", "接近开关", "探头", "sensor", "detector", "switch", "partpresent"], "sensor", "LBC_DigitalSignal"),
]


def _clean_identifier(name: str, fallback_prefix: str = "item") -> str:
    """Sanitize name to a valid SCL identifier (alphanumeric + underscore)."""
    # Extract latin letters/numbers/underscore
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"{fallback_prefix}_{cleaned}" if cleaned else fallback_prefix
    # Ensure camelCase or PascalCase start
    return cleaned


def _classify_cm_type(name: str, desc: str = "") -> AfCmType:
    """Classify device into an AF LBC_* control module type."""
    combined = f"{name} {desc}".lower()

    if any(k in combined for k in ["servo", "axis", "伺服", "轴", "stepper", "步进"]):
        return "LBC_AxisControl"
    if any(k in combined for k in ["motor", "conveyor", "电机", "马达", "传送带", "输送", "pump", "泵"]):
        return "LBC_MotorStarter"
    if any(k in combined for k in ["sensor", "detector", "switch", "传感器", "检测", "到位", "料位", "光电", "接近"]):
        return "LBC_DigitalSignal"
    # Default to cylinder/actuator if motion/cylinder implied
    return "LBC_TwoWayActuator"


def _extract_latin_identifier(text: str) -> str | None:
    """Extract first distinct English identifier from text, if any."""
    matches = re.findall(r"\b[A-Za-z][A-Za-z0-9_]{2,30}\b", text)
    # Filter out common English keywords
    stopwords = {"step", "station", "unit", "and", "the", "for", "with", "true", "false", "then", "wait"}
    for m in matches:
        if m.lower() not in stopwords:
            return m
    return None


def _parse_devices_from_text(text: str) -> list[AfCm]:
    """Parse Control Modules (CMs) from natural language or bullet text."""
    cms: list[AfCm] = []
    seen_names: set[str] = set()

    lines = text.splitlines()
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        # Skip lines that look like step definitions or titles
        if re.match(r"^(?:(?:工步|步骤|step)\s*\d+|\d+[.:、\s])", line_s, re.IGNORECASE):
            continue
        if any(h in line_s.lower() for h in ["工位", "station", "项目", "project"]):
            continue

        # Check if line describes a device / CM
        cm_type: AfCmType | None = None
        prefix = "dev"
        for kw_list, pref, ctype in _KEYWORD_TO_CM_INFO:
            if any(k in line_s.lower() for k in kw_list):
                cm_type = ctype
                prefix = pref
                break

        if cm_type is None:
            continue

        # Attempt to find explicit English identifier
        ident = _extract_latin_identifier(line_s)
        if not ident:
            # Generate identifier from prefix and count
            count = sum(1 for c in cms if c.cm_type == cm_type) + 1
            ident = f"{prefix}{count}"

        ident = _clean_identifier(ident, prefix)
        if ident in seen_names:
            continue
        seen_names.add(ident)

        cms.append(
            AfCm(
                name=ident,
                cm_type=cm_type,
                description=line_s[:100],
            )
        )

    # If no devices found in non-step lines, scan step lines for device mentions
    if not cms:
        for line in lines:
            line_s = line.strip()
            for kw_list, pref, ctype in _KEYWORD_TO_CM_INFO:
                if any(k in line_s.lower() for k in kw_list):
                    ident = _extract_latin_identifier(line_s)
                    if not ident:
                        count = sum(1 for c in cms if c.cm_type == ctype) + 1
                        ident = f"{pref}{count}"
                    ident = _clean_identifier(ident, pref)
                    if ident not in seen_names:
                        seen_names.add(ident)
                        cms.append(AfCm(name=ident, cm_type=ctype, description=line_s[:100]))

    return cms


def _synthesize_step_action_and_condition(
    step_text: str,
    cms: list[AfCm],
) -> tuple[str, list[str], str]:
    """Derive step name, SCL command actions, and transition condition for a step.

    Strict AF V1.2 rule: actions must use #controlNodes.<cm>.commands.<cmd> := TRUE;
    conditions must use #controlNodes.<cm>.status.<field>.
    """
    txt_lower = step_text.lower()

    # Find the target CM mentioned or best matching
    matched_cm: AfCm | None = None
    for cm in cms:
        if cm.name.lower() in txt_lower:
            matched_cm = cm
            break

    # If no exact CM name match, match by CM type keywords in step text
    if not matched_cm:
        for kw_list, _, ctype in _KEYWORD_TO_CM_INFO:
            if any(k in txt_lower for k in kw_list):
                for cm in cms:
                    if cm.cm_type == ctype:
                        matched_cm = cm
                        break
            if matched_cm:
                break

    # If still no match, fallback to first available CM
    if not matched_cm and cms:
        matched_cm = cms[0]

    # If no CMs exist at all, return generic step
    if not matched_cm:
        return ("EXECUTE_STEP", ["// User sequence logic"], "TRUE")

    cm_name = matched_cm.name
    cm_type = matched_cm.cm_type

    # 1. Cylinder / Actuator actions
    if cm_type in {"LBC_TwoWayActuator", "LBC_SimpleActuator", "LBC_ThreeWayActuator"}:
        if any(k in txt_lower for k in ["缩回", "复位", "原位", "松开", "抬起", "retract", "home", "release"]):
            step_name = f"{cm_name.upper()}_RETRACT"
            actions = [f"#controlNodes.{cm_name}.commands.homePosition := TRUE;"]
            transition = f"#controlNodes.{cm_name}.status.inHomePosition"
            return (step_name, actions, transition)
        else:  # extend, push, clamp, work position
            step_name = f"{cm_name.upper()}_EXTEND"
            actions = [f"#controlNodes.{cm_name}.commands.workPosition := TRUE;"]
            transition = f"#controlNodes.{cm_name}.status.inWorkPosition"
            return (step_name, actions, transition)

    # 2. Sensor / Detector actions
    if cm_type == "LBC_DigitalSignal":
        step_name = f"WAIT_{cm_name.upper()}"
        actions = [f"// Wait for sensor {cm_name}"]
        transition = f"#controlNodes.{cm_name}.status.signal"
        return (step_name, actions, transition)

    # 3. Motor actions
    if cm_type in {"LBC_MotorStarter", "LBC_DriveControl_StdPlc"}:
        if any(k in txt_lower for k in ["停", "stop", "halt"]):
            step_name = f"{cm_name.upper()}_STOP"
            actions = [f"#controlNodes.{cm_name}.commands.stop := TRUE;"]
            transition = f"#controlNodes.{cm_name}.status.stopped"
            return (step_name, actions, transition)
        else:  # start, run, forward
            step_name = f"{cm_name.upper()}_FORWARD"
            actions = [f"#controlNodes.{cm_name}.commands.forward := TRUE;"]
            transition = f"#controlNodes.{cm_name}.status.running"
            return (step_name, actions, transition)

    # 4. Servo / Axis actions
    if cm_type == "LBC_AxisControl":
        if any(k in txt_lower for k in ["停", "stop"]):
            step_name = f"{cm_name.upper()}_STOP"
            actions = [f"#controlNodes.{cm_name}.commands.stop := TRUE;"]
            transition = f"#controlNodes.{cm_name}.status.standstill"
            return (step_name, actions, transition)
        else:  # move, position
            step_name = f"{cm_name.upper()}_MOVE"
            actions = [f"#controlNodes.{cm_name}.commands.moveAbsolute := TRUE;"]
            transition = f"#controlNodes.{cm_name}.status.inPosition"
            return (step_name, actions, transition)

    # Default fallback
    step_name = f"RUN_{cm_name.upper()}"
    return (step_name, [f"// Step for {cm_name}"], "TRUE")


def _parse_steps_from_text(text: str, cms: list[AfCm]) -> list[AfSequenceStep]:
    """Parse step definitions from natural language text or bullet points."""
    raw_steps: list[tuple[int | None, str]] = []

    # Patterns matching step definitions:
    # "工步10: 等待工件到位", "10 等待工件到位", "Step 10: Extend cylinder", "1. 等待工件"
    step_re = re.compile(
        r"^(?:(?:工步|步骤|step)\s*(\d+)|(\d+)[.:、\s]+)(.*)$",
        re.IGNORECASE,
    )

    for line in text.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        m = step_re.match(line_s)
        if m:
            step_num_str = m.group(1) or m.group(2)
            step_id = int(step_num_str) if step_num_str else None
            desc = (m.group(3) or "").strip(" :、-")
            if desc:
                raw_steps.append((step_id, desc))
        elif any(k in line_s for k in ["等待", "伸出", "缩回", "启动", "停止", "移动", "wait", "extend", "retract", "start", "stop"]):
            # Line looks like an unnumbered step
            raw_steps.append((None, line_s))

    # If no steps found in text, construct default steps from CMS
    if not raw_steps:
        return _build_default_steps_for_cms(cms)

    steps: list[AfSequenceStep] = []
    curr_id = 10
    for sid, desc in raw_steps:
        actual_id = sid if sid is not None and sid >= 10 else curr_id
        if sid is not None and sid < 10:
            actual_id = sid * 10  # convert 1 -> 10, 2 -> 20

        s_name, actions, transition = _synthesize_step_action_and_condition(desc, cms)
        step = AfSequenceStep(
            step_id=actual_id,
            name=s_name,
            description=desc[:120],
            actions=actions,
            transition_condition=transition,
            timeout_ms=5000,
            error_step_id=999,
        )
        steps.append(step)
        curr_id = actual_id + 10

    # Chain next_step_ids
    for i, st in enumerate(steps):
        if i < len(steps) - 1:
            st.next_step_id = steps[i + 1].step_id
        else:
            # Last step loops back to ready step (1)
            st.next_step_id = 1

    return steps


def _build_default_steps_for_cms(cms: list[AfCm]) -> list[AfSequenceStep]:
    """Build a standard sequence covering the provided CMs."""
    steps: list[AfSequenceStep] = []
    step_id = 10

    # 1. Sensors first: wait for condition
    for cm in cms:
        if cm.cm_type == "LBC_DigitalSignal":
            steps.append(
                AfSequenceStep(
                    step_id=step_id,
                    name=f"WAIT_{cm.name.upper()}",
                    description=f"Wait for sensor {cm.name}",
                    actions=[f"// Wait for {cm.name}"],
                    transition_condition=f"#controlNodes.{cm.name}.status.signal",
                    next_step_id=step_id + 10,
                )
            )
            step_id += 10

    # 2. Actuators next: extend then retract
    for cm in cms:
        if cm.cm_type in {"LBC_TwoWayActuator", "LBC_SimpleActuator"}:
            steps.append(
                AfSequenceStep(
                    step_id=step_id,
                    name=f"{cm.name.upper()}_EXTEND",
                    description=f"Extend {cm.name} to work position",
                    actions=[f"#controlNodes.{cm.name}.commands.workPosition := TRUE;"],
                    transition_condition=f"#controlNodes.{cm.name}.status.inWorkPosition",
                    next_step_id=step_id + 10,
                )
            )
            step_id += 10
            steps.append(
                AfSequenceStep(
                    step_id=step_id,
                    name=f"{cm.name.upper()}_RETRACT",
                    description=f"Retract {cm.name} to home position",
                    actions=[f"#controlNodes.{cm.name}.commands.homePosition := TRUE;"],
                    transition_condition=f"#controlNodes.{cm.name}.status.inHomePosition",
                    next_step_id=step_id + 10,
                )
            )
            step_id += 10

    # 3. Motors / Axis
    for cm in cms:
        if cm.cm_type == "LBC_MotorStarter":
            steps.append(
                AfSequenceStep(
                    step_id=step_id,
                    name=f"{cm.name.upper()}_RUN",
                    description=f"Run motor {cm.name}",
                    actions=[f"#controlNodes.{cm.name}.commands.forward := TRUE;"],
                    transition_condition=f"#controlNodes.{cm.name}.status.running",
                    next_step_id=step_id + 10,
                )
            )
            step_id += 10
        elif cm.cm_type == "LBC_AxisControl":
            steps.append(
                AfSequenceStep(
                    step_id=step_id,
                    name=f"{cm.name.upper()}_MOVE",
                    description=f"Move axis {cm.name}",
                    actions=[f"#controlNodes.{cm.name}.commands.moveAbsolute := TRUE;"],
                    transition_condition=f"#controlNodes.{cm.name}.status.inPosition",
                    next_step_id=step_id + 10,
                )
            )
            step_id += 10

    # Fallback if no steps created
    if not steps:
        steps.append(
            AfSequenceStep(
                step_id=10,
                name="AUTO_CYCLE",
                description="Default automatic cycle step",
                actions=["// Default process action"],
                transition_condition="TRUE",
                next_step_id=1,
            )
        )
    else:
        # Loop back last step to 1 (Ready)
        steps[-1].next_step_id = 1

    return steps


def _plan_em_from_text(
    em_idx: int,
    name: str,
    text: str,
    default_cms: list[AfCm] | None = None,
) -> AfEm:
    """Plan an Equipment Module (AfEm) from descriptive text."""
    cms: list[AfCm] = list(default_cms) if default_cms else []
    seen = {c.name for c in cms}
    parsed = _parse_devices_from_text(text)
    for c in parsed:
        if c.name not in seen:
            cms.append(c)
            seen.add(c.name)

    # Ensure at least minimal standard CMs exist if none found
    if not cms:
        cms = [
            AfCm(name="cylActuator", cm_type="LBC_TwoWayActuator", description="Standard pneumatic actuator"),
            AfCm(name="sensorPartPresent", cm_type="LBC_DigitalSignal", description="Part presence detector"),
        ]

    steps = _parse_steps_from_text(text, cms)

    seq = AfSequence(
        initial_step=0,
        ready_step=1,
        steps=steps,
    )

    jobs = [
        AfJob(
            job_id=1,
            name="AutoProduction",
            description="Automatic production cycle job",
            initial_step=steps[0].step_id if steps else 10,
        )
    ]

    return AfEm(
        em_idx=em_idx,
        name=_clean_identifier(name, f"Em{em_idx}"),
        description=text[:150],
        jobs=jobs,
        sequence=seq,
        control_modules=cms,
    )


def _plan_from_requirement_card(card: dict[str, Any], project_name: str) -> AfProject:
    """Plan AfProject from a RequirementStore card dictionary."""
    proj_name = str(card.get("project_name") or project_name or "AF_Project").strip()
    intent_summary = str(card.get("intent_summary") or "")
    origin_prompt = str(card.get("origin_prompt") or "")
    items = card.get("items") or []

    # Gather all descriptive text from items and prompts
    text_parts: list[str] = [intent_summary, origin_prompt]
    sequence_texts: list[str] = []

    for it in items:
        if isinstance(it, dict):
            kind = it.get("kind")
            txt = str(it.get("text") or "").strip()
            if kind == "sequence":
                sequence_texts.append(txt)
            else:
                text_parts.append(txt)

    full_spec_text = "\n".join(text_parts + sequence_texts)

    # Look for linked signals or hints
    linked_signals = card.get("linked_signals") or []
    explicit_cms: list[AfCm] = []
    for sig in linked_signals:
        sig_str = str(sig).strip()
        if sig_str:
            cm_type = _classify_cm_type(sig_str)
            explicit_cms.append(AfCm(name=_clean_identifier(sig_str, "sig"), cm_type=cm_type))

    # Parse EM
    em_name = "ProcessStation"
    # Try extracting station name from intent or items
    m_station = re.search(r"(?:工位|station)[:：\s]*([A-Za-z0-9_\u4e00-\u9fa5]+)", full_spec_text, re.IGNORECASE)
    if m_station:
        em_name = m_station.group(1).strip()

    em1 = _plan_em_from_text(
        em_idx=1,
        name=em_name,
        text=full_spec_text,
        default_cms=explicit_cms if explicit_cms else None,
    )

    unit1 = AfUnit(
        unit_idx=1,
        name=_clean_identifier(proj_name, "Unit1"),
        description=intent_summary,
        equipment_modules=[em1],
    )

    return AfProject(
        name=proj_name,
        description=intent_summary,
        units=[unit1],
    )


def _plan_from_structured_dict(spec: dict[str, Any], project_name: str) -> AfProject:
    """Plan AfProject from a structured dictionary."""
    # Check if spec is already close to AfProject schema
    if "units" in spec and isinstance(spec["units"], list):
        try:
            return AfProject.from_dict(spec)
        except Exception as exc:
            logger.warning("AfProject.from_dict failed on input spec: %s", exc)

    proj_name = str(spec.get("name") or spec.get("project_name") or project_name or "AF_Project").strip()
    desc = str(spec.get("description") or "")

    # Look for stations / equipment modules in spec
    raw_stations = (
        spec.get("stations")
        or spec.get("equipment_modules")
        or spec.get("modules")
        or spec.get("ems")
    )

    ems: list[AfEm] = []
    if isinstance(raw_stations, list) and raw_stations:
        for idx, st in enumerate(raw_stations, start=1):
            if isinstance(st, dict):
                st_name = st.get("name") or f"Station{idx}"
                st_desc = st.get("description") or ""

                cms: list[AfCm] = []
                # parse control modules
                for cm_item in (st.get("control_modules") or st.get("actuators") or st.get("sensors") or []):
                    if isinstance(cm_item, dict):
                        cm_name = _clean_identifier(cm_item.get("name", f"cm_{len(cms)+1}"))
                        ctype = cm_item.get("type") or cm_item.get("cm_type")
                        if not ctype or ctype not in VALID_CM_TYPES:
                            ctype = _classify_cm_type(cm_name, str(cm_item.get("description", "")))
                        cms.append(AfCm(name=cm_name, cm_type=ctype, description=cm_item.get("description", "")))

                # parse steps
                raw_steps = st.get("steps") or st.get("sequence", {}).get("steps") if isinstance(st.get("sequence"), dict) else []
                steps: list[AfSequenceStep] = []
                if isinstance(raw_steps, list) and raw_steps:
                    for s_idx, s in enumerate(raw_steps):
                        if isinstance(s, dict):
                            step_id = s.get("step_id") or s.get("id") or ((s_idx + 1) * 10)
                            s_name = s.get("name") or f"STEP_{step_id}"
                            actions = s.get("actions") or []
                            if isinstance(actions, str):
                                actions = [actions]
                            cond = s.get("transition_condition") or s.get("condition") or "TRUE"
                            next_id = s.get("next_step_id") or (step_id + 10 if s_idx < len(raw_steps) - 1 else 1)
                            steps.append(
                                AfSequenceStep(
                                    step_id=step_id,
                                    name=s_name,
                                    description=s.get("description", ""),
                                    actions=actions,
                                    transition_condition=cond,
                                    next_step_id=next_id,
                                )
                            )
                if not steps:
                    steps = _build_default_steps_for_cms(cms)

                ems.append(
                    AfEm(
                        em_idx=idx,
                        name=_clean_identifier(st_name, f"Em{idx}"),
                        description=st_desc,
                        jobs=[AfJob(job_id=1, name="AutoProduction", initial_step=steps[0].step_id if steps else 10)],
                        sequence=AfSequence(initial_step=0, ready_step=1, steps=steps),
                        control_modules=cms,
                    )
                )

    if not ems:
        # Fallback to text parsing of dictionary values
        dict_text = " ".join(f"{k}: {v}" for k, v in spec.items() if isinstance(v, (str, list)))
        ems.append(_plan_em_from_text(1, "MainStation", dict_text))

    unit1 = AfUnit(
        unit_idx=1,
        name=_clean_identifier(proj_name, "Unit1"),
        description=desc,
        equipment_modules=ems,
    )

    return AfProject(
        name=proj_name,
        description=desc,
        units=[unit1],
    )


def plan_af_project_from_spec(spec: dict[str, Any] | str, project_name: str = "AF_Project") -> AfProject:
    """Plan an official Siemens AF V1.2 project from specification.

    Args:
        spec: Natural language string, structured dict, or RequirementCard dict.
        project_name: Project name fallback if not specified in spec.

    Returns:
        AfProject domain model conforming to AF V1.2 architecture.
    """
    if isinstance(spec, str):
        # Natural language specification
        text = spec.strip()
        # Look for station / unit hints
        stations: list[tuple[str, str]] = []

        # Split into stations if defined (e.g. "工位1: 进料工位 (FeederStation)", "工位: 组装工位", "Station 1: Feeder")
        st_matches = list(re.finditer(r"(?:^|\n)(?:工位|Station)\s*(\d*)[:：\s]*([^\n]+)", text, re.IGNORECASE))
        if st_matches:
            for idx, m in enumerate(st_matches):
                st_raw = m.group(2).strip()
                # Check for explicit latin identifier in parentheses or text
                m_ident = _extract_latin_identifier(st_raw)
                st_name = m_ident if m_ident else _clean_identifier(st_raw, f"Station{idx+1}")
                start_pos = m.end()
                end_pos = st_matches[idx + 1].start() if idx + 1 < len(st_matches) else len(text)
                st_body = text[start_pos:end_pos]
                stations.append((st_name, st_body))
        else:
            stations.append(("Station1", text))

        ems: list[AfEm] = []
        for i, (s_name, s_body) in enumerate(stations, start=1):
            ems.append(_plan_em_from_text(i, s_name, s_body))

        unit1 = AfUnit(
            unit_idx=1,
            name=_clean_identifier(project_name, "Unit1"),
            description=text[:150],
            equipment_modules=ems,
        )

        return AfProject(
            name=project_name,
            description=text[:200],
            units=[unit1],
        )

    if isinstance(spec, dict):
        if "items" in spec or "requirement_id" in spec:
            return _plan_from_requirement_card(spec, project_name)
        return _plan_from_structured_dict(spec, project_name)

    raise TypeError(f"spec must be dict or str, got {type(spec).__name__}")
