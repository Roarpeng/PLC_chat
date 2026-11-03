"""本地引用对账校验器——设备级编译错误的无 TIA 诊断通道。

翻译体重建后的 SCL 里，编译错误主力是"未定义标识符"类：引用的根符号、
DB 成员路径、物理 tag 在工程里不存在或拼写/引号形态不对。本脚本把每个
draft 块完整 SCL 里的三类引用逐一对 XML 证据树核验，解析不了的引用
（含行号）即编译错误清单——秒级、无 TIA、可反复迭代。

用法: uv run python tools/verify_refs.py [块名1 块名2 ...]   # 缺省查全部 draft 块
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = r"C:\Users\vboxuser\Desktop\Project\Code\PLC_chat\PLC_Openness_data\hr001\export"

sys.path.insert(0, str(ROOT))

from plc_engine.array_evidence import InterfaceMember, load_block_interfaces  # noqa: E402
from plc_engine.canvas_model import (  # noqa: E402
    CanvasState,
    apply_canvas_patch,
    generate_canvas_autofix_patch,
)
from plc_engine.af.refactor import refactor_canvas_to_af  # noqa: E402
from gateway.app.services.plc.refactor_pipeline import _compile_write_scope  # noqa: E402

SCL_KEYWORDS = {
    "IF", "THEN", "ELSE", "ELSIF", "END_IF", "FOR", "TO", "BY", "DO", "END_FOR",
    "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT", "CASE", "OF", "END_CASE",
    "VAR", "END_VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP",
    "BEGIN", "END_FUNCTION_BLOCK", "END_FUNCTION", "END_DATA_BLOCK", "END_TYPE",
    "FUNCTION_BLOCK", "FUNCTION", "DATA_BLOCK", "ORGANIZATION_BLOCK", "TYPE",
    "STRUCT", "END_STRUCT", "ARRAY", "OF", "TRUE", "FALSE", "AND", "OR", "XOR",
    "NOT", "MOD", "RETURN", "GOTO", "CONSTANT", "RETAIN", "NON_RETAIN",
    "AT", ":=", "Bool", "Int", "DInt", "Real", "Time", "String", "Word", "Byte",
}

# DB 路径段的右边界:SCL 运算符/关键字不是路径的一部分(校验器首跑曾把
# ".ExtPos AND NOT" 整段当路径——路径解析必失败,全是伪报)
_PATH_STOP_WORDS = {
    "AND", "OR", "XOR", "NOT", "MOD", "THEN", "ELSE", "ELSIF", "TO", "DO",
    "OF", "END_IF", "END_CASE", "BY", "AT", "RETURN", "GOTO", "TRUE", "FALSE",
}


def build_canvas() -> CanvasState:
    raw = json.loads((ROOT / ".devctl" / "hr001_canvas.json").read_text(encoding="utf-8"))
    cs = CanvasState.from_dict(raw)
    new, _ = refactor_canvas_to_af(cs, None, self_contained=True)
    patch = generate_canvas_autofix_patch(new, [], EVIDENCE_DIR)
    return apply_canvas_patch(new, patch)


def resolve_path(node: InterfaceMember | None, segs: list[str]) -> bool:
    """在证据成员树里逐段解析路径（大小写不敏感；带引号段去引号）。"""
    cur = node
    for seg in segs:
        if cur is None:
            return False
        nxt = cur.members.get(seg)
        if nxt is None:
            low = seg.lower()
            for k, v in cur.members.items():
                if k.lower() == low:
                    nxt = v
                    break
        if nxt is None:
            return False
        cur = nxt
    return True


def strip_quotes(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == '"' and s[-1] == '"' else s


def verify_block(
    name: str,
    scl: str,
    interfaces: dict[str, dict[str, InterfaceMember]],
    tags: set[str],
    block_names: set[str],
) -> list[str]:
    problems: list[str] = []
    lines = scl.splitlines()
    # 声明区结束于 BEGIN;此前收集本块声明根(粗粒度:行内 "X : T;" 形态)
    decl_roots: set[str] = set()
    in_decl = False
    begin_line = 0
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if re.match(r"^VAR(_INPUT|_OUTPUT|_IN_OUT|_TEMP)?\b", s):
            in_decl = True
            continue
        if s == "BEGIN":
            begin_line = i
            in_decl = False
            break
        if in_decl:
            m = re.match(r'^(?:"([^"]+)"|([A-Za-z_]\w*))\s*:\s*(?!Struct\b)', s)
            if m:
                decl_roots.add((m.group(1) or m.group(2)).lower())
    if begin_line == 0:
        return [f"{name}: 无 BEGIN 段"]

    body = "\n".join(lines[begin_line:])
    code = re.sub(r"//[^\n]*", "", body)

    # 1) #root 引用(含 #Root.Path 链与 #"带空格名" 引号形态):根必须在本块声明或证据接口
    iface = interfaces.get(name)
    for m in re.finditer(r'#(?:"([^"]+)"|([A-Za-z_]\w*))(?=[.\s(=:;)\[,])', code):
        root = (m.group(1) or m.group(2) or "").strip()
        if not root or root.upper() in SCL_KEYWORDS:
            continue
        line_no = code[: m.start()].count("\n") + begin_line + 1
        if root.lower() not in decl_roots and not (iface and root in iface):
            problems.append(f"{name}:{line_no} 未声明根 #{root}")

    # 2) "DB".path 引用:DB 必须是块名/证据块/AF 生成块标题;路径须能在证据树解析。
    #    路径段的右边界遇到 SCL 运算符即截断(防止把 ".X AND" 当成路径)。
    for m in re.finditer(r'"([^"]+)"(?:\.([A-Za-z_"][\w." ]*))?', code):
        db, raw_path = m.group(1), m.group(2) or ""
        # 逐段截断:段内出现 SCL 运算符词即在该词前截断(防 ".X AND" 被当路径)
        segs_raw: list[str] = []
        truncated = False
        for seg in raw_path.split("."):
            words = seg.strip().split(" ")
            keep: list[str] = []
            for w in words:
                if w.upper() in _PATH_STOP_WORDS:
                    truncated = True
                    break
                keep.append(w)
            if keep:
                segs_raw.append(" ".join(keep))
            if truncated:
                break
        line_no = code[: m.start()].count("\n") + begin_line + 1
        if not raw_path.strip() or not segs_raw:
            # 裸符号:tag/块名/块标题/本块声明根(含带空格引号实例名)/含~硬件符号
            if (
                db not in tags
                and db not in block_names
                and db != name
                and db.lower() not in decl_roots
                and "~" not in db
            ):
                problems.append(f"{name}:{line_no} 未知符号 \"{db}\"")
            continue
        segs = [strip_quotes(s) for s in segs_raw]
        # IEC_TIMER 实例的指令选择尾段(.TON/.TOF/.TP)是合法调用形态:
        # 截尾后前缀可解析即放行(FB1080 的 #Aux.Heart.TON(...) 真机已编译通过)
        if segs and segs[-1].upper() in {"TON", "TOF", "TP"} and len(segs) >= 2:
            trimmed = segs[:-1]
            db0 = interfaces.get(db)
            if db0 is not None and resolve_path(_RootWrap(db0), trimmed):
                continue
        db_iface = interfaces.get(db)
        if db_iface is None:
            if db not in block_names:
                problems.append(f"{name}:{line_no} 未知DB \"{db}\".{'.'.join(segs)}")
            continue
        if not resolve_path(_RootWrap(db_iface), segs):
            problems.append(f"{name}:{line_no} DB路径不可解析 \"{db}\".{'.'.join(segs)}")
    return problems


class _RootWrap:
    """把顶层成员 dict 包成可走 resolve_path 的节点。"""

    def __init__(self, members: dict[str, InterfaceMember]):
        self.members = members


def main() -> None:
    only = set(sys.argv[1:])
    canvas = build_canvas()
    scoped, _excluded = _compile_write_scope(canvas)
    interfaces = load_block_interfaces(EVIDENCE_DIR)
    tags = {str(t) for t in (canvas.tags or {})}
    block_names = {b.name or k for k, b in scoped.blocks.items()}
    block_names |= set(scoped.blocks.keys())
    # AF/重建块的 SCL 声明标题(如 U1Em1_Kuka_General_ControlNodes)也是合法引用目标
    for _k, b in scoped.blocks.items():
        first = (b.scl_body or "").lstrip()
        _m = re.match(r'^(?:FUNCTION_BLOCK|FUNCTION|DATA_BLOCK|ORGANIZATION_BLOCK)\s+"([^"]+)"', first)
        if _m:
            block_names.add(_m.group(1))

    total = 0
    for key, block in scoped.blocks.items():
        if block.status != "draft":
            continue
        name = block.name or key
        if only and name not in only and key not in only:
            continue
        scl = block.get_full_scl()
        problems = verify_block(name, scl, interfaces, tags, block_names)
        if problems:
            total += len(problems)
            print(f"--- {name}: {len(problems)} 处")
            for p in problems[:15]:
                print("   ", p)
            if len(problems) > 15:
                print(f"    … 共 {len(problems)} 处")
    print(f"合计未解析引用: {total}")


if __name__ == "__main__":
    main()
