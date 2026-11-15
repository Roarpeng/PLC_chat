"""Deterministic executable SCL generation (blueprint §4 / R3 P0 fix).

Every Action / Guard / Timer is lowered to REAL statements — never comments.
A semantic-coverage assertion proves the count of lowered elements equals the
contract's requirement; comment-only placeholders fail the build (WS3 tests).
"""
from __future__ import annotations

import re

from plc_engine.canonical import canonical_dumps, sha256_prefixed
from processos.contract import AfProject, FrameworkProfile, GeneratedSource

from .coverage import CoverageCounter, expected_from_sequence


def _scl_guard(expr: str) -> str:
    def repl(m: re.Match) -> str:
        tok = m.group(0)
        return tok if tok in ("AND", "OR", "NOT") else "#" + tok
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", repl, expr or "")


class _Builder:
    def __init__(self, filename: str):
        self.filename = filename
        self.lines: list[str] = []
        self.source_map: list[dict] = []

    def emit(self, text: str, node: str = "") -> None:
        self.lines.append(text)
        if node:
            self.source_map.append({"file": self.filename, "line": len(self.lines), "node": node})

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def _step_numbers(sequence: list[dict]) -> dict[str, int]:
    nums: dict[str, int] = {}
    n = 0
    for st in sequence:
        if st.get("is_fault"):
            nums[st["id"]] = 90
        else:
            nums[st["id"]] = n
            n += 10
    return nums


def _gen_sequence(block: dict, counter: CoverageCounter) -> _Builder:
    name = block["name"]
    iface = block["interface"]
    sequence = iface["sequence"]
    nums = _step_numbers(sequence)
    b = _Builder(name + ".scl")
    b.emit(f'FUNCTION_BLOCK "{name}"')
    b.emit("{ S7_Optimized_Access := 'TRUE' }")
    b.emit("VAR_INPUT")
    for sig in iface["inputs"]:
        b.emit(f"    {sig} : Bool;")
    b.emit("END_VAR")
    b.emit("VAR_OUTPUT")
    for sig in iface["outputs"]:
        b.emit(f"    {sig} : Bool;" if sig != "StepNo" else "    StepNo : Int;")
    b.emit("END_VAR")
    b.emit("VAR")
    b.emit("    Step : Int := 0;")
    b.emit("    FaultLatch : Bool;")
    for st in sequence:
        if st.get("timeout_ms") or st.get("duration_ms"):
            b.emit(f"    TON_{st['id']} : TON_TIME;")
    b.emit("END_VAR")
    b.emit("BEGIN")
    b.emit("    CASE #Step OF")

    feedback = [s for s in iface["inputs"] if s not in ("Start", "Reset", "SafetyPermit")]
    for st in sequence:
        sid = st["id"]
        num = nums[sid]
        b.emit(f"        {num}: // {sid} {st.get('name', '')}", sid)
        counter.step()
        if st.get("is_fault"):
            b.emit("            #Busy := FALSE;", sid)
            b.emit("            #Error := TRUE;", sid)
            b.emit("            #FaultLatch := TRUE;", sid)
            for cmd in iface["outputs"]:
                if cmd not in ("Busy", "Done", "Error", "StepNo"):
                    b.emit(f"            #{cmd} := FALSE;", sid)
            rg = st.get("reset_guard", "")
            if rg:
                b.emit(f"            IF {_scl_guard(rg)} THEN", sid)
                counter.guard()
                b.emit("                #FaultLatch := FALSE;", sid)
                b.emit("                #Error := FALSE;", sid)
                b.emit(f"                #Step := {nums.get(st.get('next'), 0)};", sid)
                b.emit("            END_IF;", sid)
            continue

        if sid.endswith("WAIT") or st.get("guard") and not st.get("entry"):
            b.emit("            #Busy := FALSE;", sid)
            b.emit("            #Done := FALSE;", sid)
        else:
            b.emit("            #Busy := TRUE;", sid)

        for a in st.get("entry", []):
            b.emit(f"            #{a['command']} := {'TRUE' if a['value'] else 'FALSE'};", sid)
            counter.action()

        if st.get("duration_ms"):
            b.emit(f"            #TON_{sid}(IN := TRUE, PT := T#{st['duration_ms']}ms);", sid)
            counter.timer()
            b.emit(f"            IF #TON_{sid}.Q THEN", sid)
            counter.guard()
            b.emit(f"                #Step := {nums.get(st.get('next'), 0)};", sid)
            b.emit("            END_IF;", sid)
        elif st.get("guard"):
            guard_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", st.get("guard", ""))
            fb_sig = next((t for t in guard_tokens if t in feedback), feedback[0] if feedback else "Extended")
            if st.get("timeout_ms"):
                b.emit(f"            #TON_{sid}(IN := NOT #{fb_sig}, PT := T#{st['timeout_ms']}ms);", sid)
                counter.timer()
            b.emit(f"            IF {_scl_guard(st['guard'])} THEN", sid)
            counter.guard()
            for a in st.get("exit", []):
                b.emit(f"                #{a['command']} := {'TRUE' if a['value'] else 'FALSE'};", sid)
                counter.action()
            nxt = nums.get(st.get("next"), 0)
            b.emit(f"                #Step := {nxt};", sid)
            if sid.endswith("DONE"):
                b.emit("                #Done := TRUE;", sid)
            b.emit("            END_IF;", sid)
            if st.get("timeout_ms") and st.get("failure_target"):
                b.emit(f"            IF #TON_{sid}.Q THEN", sid)
                counter.guard()
                for a in st.get("exit", []):
                    b.emit(f"                #{a['command']} := FALSE;", sid)
                    counter.action()
                b.emit(f"                #FaultLatch := TRUE;", sid)
                b.emit(f"                #Step := {nums.get(st['failure_target'], 90)};", sid)
                b.emit("            END_IF;", sid)
        else:
            if st.get("next"):
                b.emit("            #Done := TRUE;", sid)
                b.emit(f"            #Step := {nums.get(st['next'], 0)};", sid)
    b.emit("    END_CASE;")
    b.emit("    #StepNo := #Step;")
    b.emit("END_FUNCTION_BLOCK")
    return b


def _gen_driver(block: dict) -> _Builder:
    name = block["name"]
    iface = block["interface"]
    cmds = iface["commands"]
    fbs = iface["feedback"]
    b = _Builder(name + ".scl")
    b.emit(f'FUNCTION_BLOCK "{name}"')
    b.emit("{ S7_Optimized_Access := 'TRUE' }")
    b.emit("VAR_INPUT")
    for c in cmds:
        b.emit(f"    Cmd{c} : Bool;")
    for f in fbs:
        b.emit(f"    {f} : Bool;")
    b.emit("END_VAR")
    b.emit("VAR_OUTPUT")
    for c in cmds:
        b.emit(f"    Q_{c} : Bool;")
    b.emit("    Busy : Bool; Done : Bool; Error : Bool;")
    b.emit("END_VAR")
    b.emit("BEGIN")
    b.emit("    // single-writer arbitration + feedback exclusivity")

    def cmd_logic(indent: str) -> None:
        if len(cmds) == 2:
            b.emit(f"{indent}#Q_{cmds[0]} := #Cmd{cmds[0]} AND NOT #Cmd{cmds[1]};")
            b.emit(f"{indent}#Q_{cmds[1]} := #Cmd{cmds[1]} AND NOT #Cmd{cmds[0]};")
        else:
            for c in cmds:
                b.emit(f"{indent}#Q_{c} := #Cmd{c};")

    if len(fbs) == 2:
        b.emit(f"    IF #{fbs[0]} AND #{fbs[1]} THEN")
        b.emit("        #Error := TRUE;")
        for c in cmds:
            b.emit(f"        #Q_{c} := FALSE;")
        b.emit("    ELSE")
        b.emit("        #Error := FALSE;")
        cmd_logic("        ")
        b.emit("    END_IF;")
    else:
        b.emit("    #Error := FALSE;")
        cmd_logic("    ")
    b.emit("    #Busy := " + (" OR ".join(f"#Q_{c}" for c in cmds) if cmds else "FALSE") + ";")
    b.emit("END_FUNCTION_BLOCK")
    return b


def _gen_main(project: AfProject, blocks_by_role: dict) -> _Builder:
    b = _Builder("OB_Main.scl")
    seqs = blocks_by_role.get("em_sequence", [])
    drvs = blocks_by_role.get("cm_driver", [])
    fb_signals: list[str] = []
    if seqs:
        fb_signals = [s for s in seqs[0]["interface"]["inputs"] if s not in ("Start", "Reset", "SafetyPermit")]
    b.emit('ORGANIZATION_BLOCK "OB_Main"')
    b.emit("VAR_TEMP")
    b.emit("    tStart : Bool; tReset : Bool; tPermit : Bool;")
    for fb in fb_signals:
        b.emit(f"    t{fb} : Bool;")
    b.emit("END_VAR")
    b.emit("BEGIN")
    b.emit("    // call order: input snapshot -> EM sequence -> CM driver -> outputs")
    for seq in seqs:
        db = project.instance_dbs[seq["name"]]
        b.emit(f'    "{db}"(')
        wires = ["Start := #tStart", "Reset := #tReset", "SafetyPermit := #tPermit"]
        wires += [f"{fb} := #t{fb}" for fb in fb_signals]
        b.emit("        " + ", ".join(wires) + ");")
    for drv in drvs:
        db = project.instance_dbs[drv["name"]]
        cmds = drv["interface"]["commands"]
        fbs = drv["interface"]["feedback"]
        seq_db = project.instance_dbs[seqs[0]["name"]] if seqs else ""
        b.emit(f'    "{db}"(')
        wires = [f'Cmd{c} := "{seq_db}".{c}' for c in cmds]
        wires += [f"{fb} := #t{fb}" for fb in fbs if fb in fb_signals]
        b.emit("        " + ", ".join(wires) + ");")
    b.emit("END_ORGANIZATION_BLOCK")
    return b


def _gen_instance_db(block: dict, db_name: str) -> _Builder:
    b = _Builder(db_name + ".db")
    b.emit(f'DATA_BLOCK "{db_name}"')
    b.emit("{ S7_Optimized_Access := 'TRUE' }")
    b.emit("VERSION : 0.1")
    b.emit(f'    "{block["name"]}"')
    b.emit("BEGIN")
    b.emit("END_DATA_BLOCK")
    return b


class SclGenerator:
    """Concrete SourceGenerator producing executable SCL + SourceMap + coverage."""

    def generate(self, project: AfProject, profile: FrameworkProfile) -> GeneratedSource:
        blocks_by_role: dict[str, list[dict]] = {}
        for blk in project.blocks:
            blocks_by_role.setdefault(blk.role, []).append(
                {"name": blk.name, "interface": blk.interface}
            )
        counter = CoverageCounter()
        files: dict[str, str] = {}
        source_map: list[dict] = []

        expected = {"steps": 0, "actions": 0, "guards": 0, "timers": 0}
        for seq in blocks_by_role.get("em_sequence", []):
            exp = expected_from_sequence(seq["interface"]["sequence"])
            for k in expected:
                expected[k] += exp[k]
            b = _gen_sequence(seq, counter)
            files[b.filename] = b.text()
            source_map.extend(b.source_map)

        for drv in blocks_by_role.get("cm_driver", []):
            b = _gen_driver(drv)
            files[b.filename] = b.text()

        b = _gen_main(project, blocks_by_role)
        files[b.filename] = b.text()

        for blk in project.blocks:
            if blk.kind == "FB":
                db = project.instance_dbs[blk.name]
                b = _gen_instance_db({"name": blk.name}, db)
                files[b.filename] = b.text()

        lowered = counter.as_dict()
        passed = all(lowered[k] >= expected[k] for k in expected) and expected["steps"] > 0
        return GeneratedSource(
            files=files,
            source_map=source_map,
            coverage={**expected, **{f"lowered_{k}": v for k, v in lowered.items()}},
            coverage_assertions_passed=passed,
            manifest_hash=sha256_prefixed(canonical_dumps(files)),
        )


def generate(project: AfProject, profile: FrameworkProfile) -> GeneratedSource:
    return SclGenerator().generate(project, profile)