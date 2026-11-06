"""Greenfield Phase 2 最后一公里：XML 补充包 + PCEC 账本 + Openness 自动导入编译。

编排 docs/greenfield/02-architecture.md §9 的 P2-4（补 SimaticML XML——OB 与
文件夹不能由 SCL 外部源生成，BR-3）、P2-5（四层静态门禁）、P2-6（PCEC 事务
与基线 fail-closed）与 P2-7/P2-8 的自动导入编译（新建 TIA 项目 → 导入 →
编译 → 结构化结果回传）。Openness 不可用或 TIA 被占用时**显式失败**
（``GF_TIA_UNAVAILABLE`` / ``GF_TIA_EXEC_ERROR`` + ``ok=false`` + 非 HTTP 200），
**禁止**静默降级、禁止返回 200 成功；人工导入指引随错误体回传。

**P0-A 编译判定口径（本批次）**：``CompileDiagnostics`` 结构化诊断，
``compile_ok = (error_count == 0 and static_gate_passed)``；warning 单列、
**禁止并入成功**；四层静态门禁任一拦截即不算通过；``tia_unavailable``
（TIA 不可用）与 ``pending_real_machine``（真机未跑）显式区分，二者均不
视为通过。本批次为离线可推进部分，真机导入编译未执行，一律标
``pending_real_machine``，禁止以离线单测宣称 L2 通过或「编译零错误」。

**sanctioned 边界（§9.2 / R1 裁定）**：本模块刻意不叫 ``greenfield_*``，
是 ``tests/unit/test_greenfield_legacy_guard.py`` 白名单里唯一允许 import
回写链静态门禁（``writeback_linter`` / ``mega_source`` / ``scl_precheck`` /
``writeback_pipeline`` / ``writeback_contract``）与 PCEC 账本（``pcec``）
的模块。只调用、不修改；其余 greenfield_*.py 仍零 import。

OB SimaticML XML 模板复用真机 V19 Openness 导出先例
``.researchos/plc_export_cache/<hash>/plc/CPU_1200/blocks/OB1Main.xml``
（SW.Blocks.OB + LAD FlgNet Call of FB via instance DB）；本轮未在真机
验证自产 XML 的可导入性，manifest 诚实标注 ``xml_package_unverified: true``
（K1 探针项，见 §9.3）。
"""
from __future__ import annotations

import io
import json
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from gateway.app.services.plc import greenfield_service as gf_service
from gateway.app.services.plc.greenfield_session import GreenfieldSession
from plc_engine import pcec, scl_precheck
from plc_engine.af.greenfield_ir import GreenfieldIR, sha256_prefixed
from plc_engine.af.greenfield_ports import GateLockedError
from plc_engine.af.greenfield_spec import FrozenSpec
from plc_engine.canvas_model import CanvasBlock, CanvasState
from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_linter import lint_bundle
from plc_engine.writeback_pipeline import build_plan

#: 交付模式：auto = 尝试 Openness 自动导入编译（不可用则降级）；package = 只出包。
MODES = ("auto", "package")

#: OB SecondaryType 映射（取值均为真机 V19 导出先例中出现过的合法枚举；
#: ProDiag 类 OB 的 SecondaryType 未在本轮确证 → 跳过并在 manifest 记录原因）。
_OB_SECONDARY_TYPES = {"Main": "ProgramCycle", "Startup": "Startup"}
_SKIP_OB_SUFFIXES = ("ProDiag",)

_CALL_DB_RE = re.compile(r'"([A-Za-z0-9_]+)"\s*\(\s*\)')

_FOLDER_NOTE = (
    "文件夹（软件单元分组）与 OB 一样不能由 SCL 外部源生成（BR-3）。本轮未确证 "
    "SW.PlcBlockGroup XML 的可导入性，故以文档化清单交付：可在博途中按本清单"
    "手工建立分组，或由 Openness BlockGroup API（Phase 3）自动建立。"
)

_MANUAL_GUIDANCE_TEMPLATE = (
    "Openness 自动通道不可用（{reason}）。ZIP 交付不受影响，人工导入步骤：\n"
    "1. 在 TIA Portal V19 新建项目并组态 CPU（或用既有 .ap19 副本）；\n"
    "2. 项目树 → PLC → 外部源文件 → 从外部源添加：导入包内 blocks/**/*.scl"
    "（OB 的 .scl 仅供阅读，OB 必须走 XML）；\n"
    "3. 导入 xml_supplement/ob/*.xml（OB SimaticML XML，Main/Startup 调用"
    "Unit/EM 的 CallUnit/CallEquipment 实例 DB）；\n"
    "4. 导入 plc_tags/PLCTags_Frozen.xml（IO 变量表）；\n"
    "5. 按 xml_supplement/folders.json 建立块分组；\n"
    "6. 编译 PLC 软件，零错误即验收通过（AC-P2-3），把 compile_receipt 回填"
    "给 change_id={change_id} 的事务。"
)


# --------------------------------------------- 结构化编译诊断（P0-A / UC-02）

#: 编译诊断的三种来源状态：真机已编译 / TIA 不可用 / 真机未跑（离线）。
COMPILE_STATUS_COMPILED = "compiled"
COMPILE_STATUS_TIA_UNAVAILABLE = "tia_unavailable"
COMPILE_STATUS_PENDING_REAL_MACHINE = "pending_real_machine"

#: TIA 不可用 / 执行中断：显式失败错误码。由网关 ``_fail`` 产出 ``ok=false``
#: + 非 200 状态码（收口阶段 ``_error_status`` 显式映射为 HTTP 503）。
TIA_UNAVAILABLE_ERROR_CODE = "GF_TIA_UNAVAILABLE"
TIA_EXEC_ERROR_CODE = "GF_TIA_EXEC_ERROR"

#: 本批次离线口径：L2 相关验收项全部挂起，M4 发布门禁保持未通过。
L2_STATUS_PENDING = "pending_real_machine"


@dataclass
class CompileDiagnostics:
    """结构化编译诊断（P0-A / UC-02 / G1 L2 证据物）。

    字段覆盖 EvidenceBundle 要求：error 数 / warning 单列清单 / 块清单 /
    耗时 / TIA 版本 / 项目路径 / 静态门禁结论 / 最终判定。``warnings`` 只作
    清单留痕，**绝不参与** ``compile_ok``；``tia_unavailable`` 与
    ``pending_real_machine`` 显式区分，二者都不是一次真机编译结论。
    """

    error_count: int
    warnings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    tia_version: str = ""
    project_path: str = ""
    static_gate_passed: bool = False
    compile_ok: bool = False
    status: str = COMPILE_STATUS_COMPILED
    tia_unavailable: bool = False
    pending_real_machine: bool = False
    xml_package_unverified: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """可复现报告数据（纯 JSON 类型），供 EvidenceBundle / 错误体归档。"""
        return asdict(self)


def evaluate_compile(
    *,
    error_count: int,
    static_gate_passed: bool,
    warnings: list[str] | None = None,
    blocks: list[str] | None = None,
    elapsed_ms: float = 0.0,
    tia_version: str = "",
    project_path: str = "",
    status: str = COMPILE_STATUS_COMPILED,
    reason: str = "",
    xml_package_unverified: bool = True,
) -> CompileDiagnostics:
    """P0-A 唯一判定口径（纯函数，单测直接调用，不连真机）。

    ``compile_ok = (error_count == 0 and static_gate_passed)``；warning 单列、
    禁止并入成功；四层静态门禁任一拦截即 False；``tia_unavailable`` /
    ``pending_real_machine`` 不是一次真机编译结论，一律 False（RK4 / N9）。
    """
    tia_unavailable = status == COMPILE_STATUS_TIA_UNAVAILABLE
    pending = status == COMPILE_STATUS_PENDING_REAL_MACHINE

    # P0-A 唯一判定式：error_count == 0 且四层静态门禁无拦截。
    compile_ok = (error_count == 0 and static_gate_passed)
    # 真机未跑 / TIA 不可用不得被计为编译通过（禁止静默降级）。
    if tia_unavailable or pending or status != COMPILE_STATUS_COMPILED:
        compile_ok = False

    return CompileDiagnostics(
        error_count=error_count,
        warnings=list(warnings or []),
        blocks=list(blocks or []),
        elapsed_ms=elapsed_ms,
        tia_version=tia_version,
        project_path=project_path,
        static_gate_passed=static_gate_passed,
        compile_ok=compile_ok,
        status=status,
        tia_unavailable=tia_unavailable,
        pending_real_machine=pending,
        xml_package_unverified=xml_package_unverified,
        reason=reason,
    )


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _warning_list(inner: dict[str, Any]) -> list[str]:
    """warning 单列清单：只收 warning 文本，绝不把 error / state 混进来。"""
    raw = inner.get("warnings")
    if raw is None:
        raw = inner.get("warningMessages") or inner.get("warningList") or []
    items: list[str] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                items.append(str(item.get("message") or item.get("text") or item))
            else:
                items.append(str(item))
    elif isinstance(raw, str) and raw:
        items.append(raw)
    return items


def build_compile_diagnostics(
    compiled: dict[str, Any] | None,
    *,
    static_gate_passed: bool,
    tia_version: str,
    project_path: str,
    blocks: list[str] | None = None,
    elapsed_ms: float = 0.0,
) -> CompileDiagnostics:
    """把 Openness CLI ``compile-plc`` 原始结果解析为可复现的结构化诊断。

    只读取字段、不改 CLI 语义；解析不出 error 数时按 fail-closed 记非零，
    **绝不**因 ``state`` 含 ``warning`` / ``Success`` 就把编译判为成功（RK4）。
    """
    compiled = compiled if isinstance(compiled, dict) else {}
    inner = compiled.get("compile") if isinstance(compiled.get("compile"), dict) else {}
    state = str(inner.get("state") or compiled.get("state") or "")

    raw_errors = inner.get("errorCount", inner.get("error_count"))
    if raw_errors is None:
        raw_errors = inner.get("errors")
    if isinstance(raw_errors, (list, tuple)):
        error_count = len(raw_errors)
    elif raw_errors is not None:
        error_count = _as_int(raw_errors, 0)
    else:
        # 无显式计数：ok=false 或 state 含 error/fail 时 fail-closed 记非零。
        ok_flag = bool(compiled.get("ok")) or bool(inner.get("ok"))
        error_count = 0 if ok_flag and "error" not in state.lower() and "fail" not in state.lower() else 1

    warnings = _warning_list(inner)
    if not warnings and "warnings" in compiled:
        warnings = _warning_list({"warnings": compiled.get("warnings")})

    if elapsed_ms <= 0:
        elapsed_ms = _as_float(
            inner.get("elapsedMs", inner.get("compileMs", compiled.get("elapsedMs"))), 0.0
        )

    return evaluate_compile(
        error_count=error_count,
        static_gate_passed=static_gate_passed,
        warnings=warnings,
        blocks=blocks,
        elapsed_ms=elapsed_ms,
        tia_version=tia_version,
        project_path=project_path,
        status=COMPILE_STATUS_COMPILED,
    )


def unavailable_diagnostics(
    *,
    reason: str,
    static_gate_passed: bool,
    tia_version: str,
    project_path: str,
    blocks: list[str] | None = None,
) -> CompileDiagnostics:
    """TIA / Openness 不可用：显式失败诊断（不是「真机未跑」，更不是成功）。"""
    return evaluate_compile(
        error_count=0,
        static_gate_passed=static_gate_passed,
        blocks=blocks,
        tia_version=tia_version,
        project_path=project_path,
        status=COMPILE_STATUS_TIA_UNAVAILABLE,
        reason=reason,
    )


def pending_real_machine_diagnostics(
    *,
    static_gate_passed: bool,
    tia_version: str,
    project_path: str,
    blocks: list[str] | None = None,
) -> CompileDiagnostics:
    """``package`` 模式 / 离线批次：真机未跑，显式标 ``pending_real_machine``。

    与 ``tia_unavailable``（探测到 TIA 不可用而失败）严格区分；本函数只表示
    「本次未尝试真机编译」，不构成 L2 证据。
    """
    return evaluate_compile(
        error_count=0,
        static_gate_passed=static_gate_passed,
        blocks=blocks,
        tia_version=tia_version,
        project_path=project_path,
        status=COMPILE_STATUS_PENDING_REAL_MACHINE,
        reason="本批次为离线可推进部分，真机导入编译未执行（WP-01 K1 探针 / P0-B 属真机项，不在本批次）",
    )


def _diagnostics_from_run(
    run: dict[str, Any],
    *,
    gates: dict[str, Any],
    delivery: dict[str, Any],
    tia_version: str,
) -> CompileDiagnostics:
    """auto 通道结果归一：块清单以 ``delivery`` 为权威、门禁结论以 ``gates`` 为准，
    判定式统一走 :func:`evaluate_compile`，禁止 mock / 旧口径数据绕过。
    """
    blocks = [str(entry["name"]) for entry in delivery["blocks_manifest"]]
    static_gate_passed = bool(gates.get("ok"))
    raw = run.get("diagnostics")
    if isinstance(raw, dict):
        return evaluate_compile(
            error_count=_as_int(raw.get("error_count"), 0),
            static_gate_passed=static_gate_passed,
            warnings=list(raw.get("warnings") or []),
            blocks=blocks,
            elapsed_ms=_as_float(raw.get("elapsed_ms"), 0.0),
            tia_version=str(raw.get("tia_version") or tia_version),
            project_path=str(raw.get("project_path") or run.get("project_path") or ""),
            status=str(raw.get("status") or COMPILE_STATUS_COMPILED),
            reason=str(raw.get("reason") or ""),
        )
    return build_compile_diagnostics(
        run.get("compile"),
        static_gate_passed=static_gate_passed,
        tia_version=tia_version,
        project_path=str(run.get("project_path") or ""),
        blocks=blocks,
        elapsed_ms=_as_float(run.get("elapsed_ms"), 0.0),
    )


# ---------------------------------------------------------------- XML 补充包


def _ob_secondary_type(ob_name: str) -> str | None:
    """OB 名后缀 → SimaticML SecondaryType；未确证类型返回 None（跳过）。"""
    for suffix, secondary in _OB_SECONDARY_TYPES.items():
        if ob_name.endswith(f"_{suffix}"):
            return secondary
    return None


def _render_multilingual(id_base: int, composition: str, text: str) -> str:
    """三种文化的 MultilingualText 块（结构与真机 V19 导出一致）。"""
    items = []
    for offset, culture in enumerate(("zh-CN", "en-US", "de-DE")):
        items.append(
            f'          <MultilingualTextItem ID="{id_base + 1 + offset}" CompositionName="Items">\n'
            "            <AttributeList>\n"
            f"              <Culture>{culture}</Culture>\n"
            f"              <Text>{escape(text)}</Text>\n"
            "            </AttributeList>\n"
            "          </MultilingualTextItem>"
        )
    body = "\n".join(items)
    return (
        f'      <MultilingualText ID="{id_base}" CompositionName="{composition}">\n'
        "        <ObjectList>\n"
        f"{body}\n"
        "        </ObjectList>\n"
        "      </MultilingualText>"
    )


def _render_call_network(call_db: str) -> str:
    """LAD FlgNet：经全局实例 DB 调用 FB（复刻 OB1Main.xml 真机先例）。"""
    call_fb = re.sub(r"_DB$", "", call_db)
    return (
        '<NetworkSource><FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">\n'
        "  <Parts>\n"
        '    <Call UId="21">\n'
        f'      <CallInfo Name="{escape(call_fb)}" BlockType="FB">\n'
        '        <Instance Scope="GlobalVariable" UId="22">\n'
        f'          <Component Name="{escape(call_db)}" />\n'
        "        </Instance>\n"
        "      </CallInfo>\n"
        "    </Call>\n"
        "  </Parts>\n"
        "  <Wires>\n"
        '    <Wire UId="23">\n'
        "      <Powerrail />\n"
        '      <NameCon UId="21" Name="en" />\n'
        "    </Wire>\n"
        "  </Wires>\n"
        "</FlgNet></NetworkSource>"
    )


def _render_empty_network() -> str:
    """空体 OB 的最小 StructuredText 网络（复刻 FB StructuredText v4 先例形态）。"""
    return (
        '<NetworkSource><StructuredText xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v4">\n'
        '  <Token Text=";" UId="21" />\n'
        "</StructuredText></NetworkSource>"
    )


def _render_ob_xml(
    *,
    ob_name: str,
    ob_number: int,
    secondary_type: str,
    call_db: str,
    title: str,
    tia_version: str,
) -> str:
    """渲染最小可导入的 SW.Blocks.OB 文档（模板改参自真机 V19 导出 OB1Main.xml）。"""
    network = _render_call_network(call_db) if call_db else _render_empty_network()
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        f'  <Engineering version="{escape(tia_version)}" />\n'
        "  <DocumentInfo>\n"
        f"    <Created>{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}</Created>\n"
        "    <ExportSetting>WithDefaults</ExportSetting>\n"
        "  </DocumentInfo>\n"
        '  <SW.Blocks.OB ID="0">\n'
        "    <AttributeList>\n"
        "      <AutoNumber>false</AutoNumber>\n"
        "      <HeaderAuthor />\n"
        "      <HeaderFamily />\n"
        "      <HeaderName />\n"
        "      <HeaderVersion>0.1</HeaderVersion>\n"
        '      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">\n'
        '  <Section Name="Temp" />\n'
        '  <Section Name="Constant" />\n'
        "</Sections></Interface>\n"
        "      <IsIECCheckEnabled>false</IsIECCheckEnabled>\n"
        "      <MemoryLayout>Optimized</MemoryLayout>\n"
        f"      <Name>{escape(ob_name)}</Name>\n"
        "      <Namespace />\n"
        f"      <Number>{int(ob_number)}</Number>\n"
        "      <ProgrammingLanguage>LAD</ProgrammingLanguage>\n"
        f"      <SecondaryType>{escape(secondary_type)}</SecondaryType>\n"
        "      <SetENOAutomatically>false</SetENOAutomatically>\n"
        "    </AttributeList>\n"
        "    <ObjectList>\n"
        f"{_render_multilingual(1, 'Comment', '')}\n"
        '      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">\n'
        "        <AttributeList>\n"
        f"          {network}\n"
        "          <ProgrammingLanguage>LAD</ProgrammingLanguage>\n"
        "        </AttributeList>\n"
        "        <ObjectList>\n"
        f"{_render_multilingual(6, 'Comment', '')}\n"
        "        </ObjectList>\n"
        "      </SW.Blocks.CompileUnit>\n"
        f"{_render_multilingual(10, 'Title', title)}\n"
        "    </ObjectList>\n"
        "  </SW.Blocks.OB>\n"
        "</Document>\n"
    )


def _ir_ob_numbers(ir: GreenfieldIR) -> dict[str, int]:
    """IR ob_numbers（units + ems）展平为 OB 号映射，供与产物清单交叉核对。"""
    numbers: dict[str, int] = {}
    for unit in ir.units:
        for kind, number in (unit.ob_numbers or {}).items():
            numbers[f"{unit.id}:{kind}"] = int(number)
    for em in ir.ems:
        for kind, number in (em.ob_numbers or {}).items():
            numbers[f"{em.id}:{kind}"] = int(number)
    return numbers


def expected_ob_numbers(ir: GreenfieldIR) -> dict[str, int]:
    """OB 号合法域 = IR ob_numbers ∪ AF V1.2 编号公式（IR 派生时同源）。

    planner 产出的 IR 不单独记录 EM0 General（``af_generator`` 对每个 Unit
    无条件派生 EM0 OB，编号来自 ``af_numbering.get_em0_ob_numbers``），故除
    IR 显式记录值外，再按 ``unit_idx``/``em_idx`` 用公式补全集；OB 编号必须
    落在该合法域内，否则 K6/K7 冲突 fail-closed。
    """
    from plc_engine.af.af_numbering import (
        get_em0_ob_numbers,
        get_em_ob_numbers,
        get_unit_ob_numbers,
    )

    numbers = dict(_ir_ob_numbers(ir))
    for unit in ir.units:
        uidx = int(unit.unit_idx or 0) or (int(unit.id[1:]) if unit.id[:1] in {"U", "u"} and unit.id[1:].isdigit() else 0)
        if not uidx:
            continue
        for prefix, obs in (
            (f"{unit.id}", get_unit_ob_numbers(uidx)),
            (f"{unit.id}EM0", get_em0_ob_numbers(uidx)),
        ):
            numbers.update(
                {f"{prefix}:{kind}": value for kind, value in (("startup", obs.startup), ("main", obs.main), ("prodiag", obs.prodiag))}
            )
        for em in ir.ems:
            if em.unit_id != unit.id:
                continue
            eidx = int(getattr(em, "em_idx", 0) or 0)
            if not eidx:
                continue
            obs = get_em_ob_numbers(uidx, eidx)
            numbers.update(
                {f"{em.id}:{kind}": value for kind, value in (("startup", obs.startup), ("main", obs.main), ("prodiag", obs.prodiag))}
            )
    return numbers


def build_xml_supplement(delivery: dict[str, Any], ir: GreenfieldIR) -> dict[str, Any]:
    """P2-4 XML 补充包：OB SimaticML XML + 文档化文件夹清单 + 诚实 manifest。

    OB 号以 ``blocks_manifest`` 为准并与 IR ``ob_numbers`` 交叉核对（K6/K7），
    不一致 → fail-closed ``GF_TIA_OB_MISMATCH``。
    """
    zf = zipfile.ZipFile(io.BytesIO(delivery["zip_bytes"]))
    tia_version = str(ir.project.tia_version or "V19")
    ir_numbers = expected_ob_numbers(ir)
    ir_number_values = set(ir_numbers.values())

    ob_files: dict[str, bytes] = {}
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in delivery["blocks_manifest"]:
        if str(entry.get("block_type") or "").upper() != "OB":
            continue
        name = str(entry["name"])
        number = int(entry.get("number") or 0)
        if number not in ir_number_values:
            raise GateLockedError(
                f"OB {name} 编号 {number} 不在 IR ob_numbers 内，拒绝生成 XML",
                code="GF_TIA_OB_MISMATCH",
                details={"ob": name, "number": number, "ir_ob_numbers": ir_numbers},
            )
        secondary = _ob_secondary_type(name)
        if secondary is None:
            skipped.append(
                {
                    "name": name,
                    "number": number,
                    "reason": "SecondaryType 未在本轮真机确证（ProDiag 类），按 K1 探针口径跳过，工程内预置",
                }
            )
            continue
        scl = zf.read(str(entry["path"])).decode("utf-8")
        call_match = None
        for line in scl.splitlines():
            code = line.split("//", 1)[0]
            call_match = _CALL_DB_RE.search(code)
            if call_match:
                break
        call_db = call_match.group(1) if call_match else ""
        rel = f"xml_supplement/ob/{name}.xml"
        ob_files[rel] = _render_ob_xml(
            ob_name=name,
            ob_number=number,
            secondary_type=secondary,
            call_db=call_db,
            title=f"AF V1.2 {name}",
            tia_version=tia_version,
        ).encode("utf-8-sig")
        generated.append(
            {
                "name": name,
                "number": number,
                "secondary_type": secondary,
                "call_db": call_db,
                "path": rel,
                "sha256": sha256_prefixed(ob_files[rel]),
            }
        )

    folders: dict[str, list[str]] = {}
    for entry in delivery["blocks_manifest"]:
        folders.setdefault(str(entry.get("folder") or "root"), []).append(str(entry["name"]))
    folders_json = json.dumps(
        {"folders": folders, "note": _FOLDER_NOTE}, ensure_ascii=False, indent=2
    ).encode("utf-8")
    supplement_files: dict[str, bytes] = {
        **ob_files,
        "xml_supplement/folders.json": folders_json,
        "xml_supplement/README.md": (
            "# XML 补充包（P2-4 / BR-3）\n\n"
            "- `ob/*.xml`：OB SimaticML XML（Main/Startup 调用 Unit/EM 的实例 DB；"
            "模板改参自真机 V19 Openness 导出先例）。\n"
            "- `folders.json`：文档化文件夹清单（SW.PlcBlockGroup XML 可导入性未确证）。\n"
            "- `manifest.json`：生成清单与诚实标注（`xml_package_unverified`）。\n"
        ).encode(),
        "xml_supplement/manifest.json": b"",  # 占位，稍后由调用方写入
    }
    return {
        "ob_files": ob_files,
        "generated_obs": generated,
        "skipped_obs": skipped,
        "folders": folders,
        "supplement_files": supplement_files,
        "xml_package_unverified": True,
    }


# ------------------------------------------------------------- 重建与静态门禁


def _reconstruct_from_zip(delivery: dict[str, Any]) -> tuple[dict[str, CanvasBlock], list[BlockArtifact]]:
    """从交付 ZIP 还原 CanvasBlock（供 scl_precheck）与 BlockArtifact（供 lint/打包）。

    OB 不进外部源批次（BR-3：OB 与软件单元/文件夹不能由 SCL 外部源生成），
    其 SCL 仅供阅读，正片走 XML 补充包。
    """
    zf = zipfile.ZipFile(io.BytesIO(delivery["zip_bytes"]))
    blocks: dict[str, CanvasBlock] = {}
    artifacts: list[BlockArtifact] = []
    kind_map = {"UDT": "UDT", "DB": "GLOBAL_DB", "FC": "FC", "FB": "FB"}
    for entry in delivery["blocks_manifest"]:
        btype = str(entry.get("block_type") or "").upper()
        text = zf.read(str(entry["path"])).decode("utf-8")
        blocks[str(entry["name"])] = CanvasBlock(
            name=str(entry["name"]), block_type=btype, scl_body=text
        )
        if btype == "OB":
            continue
        kind = kind_map.get(btype)
        if kind is None:
            continue
        artifacts.append(BlockArtifact(name=str(entry["name"]), kind=kind, source=text))
    return blocks, artifacts


def run_static_gates(delivery: dict[str, Any]) -> dict[str, Any]:
    """P2-5 四层静态门禁，按序：af_linter → scl_precheck → writeback_linter → mega_source。

    只调用既有资产，不改任何逻辑；任一 error → fail-closed
    ``GF_TIA_STATIC_GATE_FAILED``，不进入 PCEC / Openness。
    """
    blocks, artifacts = _reconstruct_from_zip(delivery)
    canvas = CanvasState(project_name=str(delivery["project_name"]), blocks=blocks)
    verification = dict(delivery.get("verification") or {})

    stages: list[dict[str, Any]] = []

    af_errors = int(verification.get("linter_error_count") or 0)
    stages.append(
        {
            "name": "af_linter.lint_af_canvas",
            "ok": af_errors == 0 and bool(verification.get("single_writer_audit", {}).get("ok")),
            "error_count": af_errors,
            "note": "复用 AfGreenfieldDelivery.deliver 内嵌的 lint_af_canvas + 单写者审计结论",
        }
    )

    pre = scl_precheck.precheck_canvas(canvas)
    stages.append(
        {
            "name": "scl_precheck.precheck_canvas",
            "ok": bool(pre.get("ok")),
            "error_count": len(pre.get("errors") or []),
            "errors": list(pre.get("errors") or []),
        }
    )

    findings = lint_bundle(artifacts, bom_enabled=True)
    lint_errors = [f for f in findings if f.severity == "error"]
    stages.append(
        {
            "name": "writeback_linter.lint_bundle",
            "ok": not lint_errors,
            "error_count": len(lint_errors),
            "errors": [f.as_dict() if hasattr(f, "as_dict") else str(f) for f in lint_errors[:20]],
        }
    )

    plan = build_plan(artifacts)
    stages.append(
        {
            "name": "mega_source.bundle (via writeback_pipeline.build_plan)",
            "ok": plan.writable,
            "error_count": len(plan.findings) if plan.has_errors else 0,
            "block_order": list(plan.block_names),
            "external_dependencies": list(plan.external_dependencies),
        }
    )

    report: dict[str, Any] = {
        "ok": all(stage["ok"] for stage in stages),
        "stages": stages,
        "artifact_count": len(artifacts),
        "planned_text": plan.planned_text or "",
    }
    if not report["ok"]:
        failed = [s for s in stages if not s["ok"]]
        raise GateLockedError(
            "四层静态门禁未全部通过，拒绝交付（fail-closed）："
            + "；".join(f"{s['name']}×{s['error_count']}" for s in failed),
            code="GF_TIA_STATIC_GATE_FAILED",
            details={"stages": stages},
        )
    return report


# -------------------------------------------------------------- 工作区与基线


def _work_dir() -> Path:
    import os
    import tempfile

    work = os.environ.get("PLC_WORK_DIR", "").strip()
    return Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"


def _safe_zip_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p not in {"", "."}]
    return bool(parts) and not any(p == ".." for p in parts) and not normalized.startswith(("/", "\\"))


def _stage_package(
    session: GreenfieldSession,
    spec: FrozenSpec,
    delivery: dict[str, Any],
    supplement: dict[str, Any],
) -> Path:
    """把 SCL 包 + XML 补充包落盘到确定性工作区，供 PCEC 基线与 Openness 使用。"""
    workspace = _work_dir() / "greenfield_tia" / session.session_id / f"v{spec.spec_version}"
    package = workspace / "package"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)

    zf = zipfile.ZipFile(io.BytesIO(delivery["zip_bytes"]))
    for info in zf.infolist():
        if not _safe_zip_member(info.filename):
            raise GateLockedError(
                f"交付包内出现不安全路径：{info.filename}",
                code="GF_TIA_PACKAGE_UNSAFE",
            )
        target = package / info.filename
        if info.filename.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(info.filename))

    manifest = {
        "xml_package_unverified": supplement["xml_package_unverified"],
        "pending_real_machine": True,
        "pending_reason": (
            "本批次无真机导入验证（WP-01 K1 探针 / P0-B 属真机项，不在本批次）；"
            "自产 OB XML 与 folders.json 的可导入性待 V19 真机确证"
        ),
        "generated_obs": supplement["generated_obs"],
        "skipped_obs": supplement["skipped_obs"],
        "template_source": (
            ".researchos/plc_export_cache/<hash>/plc/CPU_1200/blocks/OB1Main.xml"
            "（TIA V19 Openness 真机导出先例，模板改参）"
        ),
        "ob_count": len(supplement["generated_obs"]),
        "note": (
            "OB Main/Startup XML 结构复刻真机 V19 导出，但自产 XML 尚未在真机验证"
            "导入（K1 探针项），导入前请先在 .ap19 副本上试导。"
        ),
    }
    supplement["supplement_files"]["xml_supplement/manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, indent=2
    ).encode("utf-8")
    for rel, data in supplement["supplement_files"].items():
        target = package / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (workspace / "tia_project").mkdir(parents=True, exist_ok=True)
    return package


def _assemble_tia_zip(
    delivery: dict[str, Any], supplement: dict[str, Any], receipt: dict[str, Any]
) -> bytes:
    """最终交付 ZIP = SCL 工程包 + xml_supplement/** + tia_delivery.json 回执。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        source = zipfile.ZipFile(io.BytesIO(delivery["zip_bytes"]))
        for info in source.infolist():
            if info.filename.endswith("/"):
                continue
            zf.writestr(info.filename, source.read(info.filename))
        for rel, data in supplement["supplement_files"].items():
            zf.writestr(rel, data)
        zf.writestr(
            "tia_delivery.json",
            json.dumps(receipt, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        )
    return buf.getvalue()


# ------------------------------------------------------------------- Openness


def _openness_probe() -> dict[str, Any]:
    """真机探测：CLI 是否存在 + TIA Openness 是否可达（status 一次性探测）。

    任何异常（exe 缺失 / dotnet 缺失 / 超时 / Openness 未注册）都归为不可用，
    供上层优雅降级；绝不抛出。
    """
    try:
        from agents.plc.tia.openness_cli import find_openness_exe, openness_cli

        exe = find_openness_exe()
        if exe is None:
            return {
                "available": False,
                "reason": "TiaOpenness.Server.exe 未构建且无 dotnet（RESEARCHOS_TIA_OPENNESS_EXE 可覆盖）",
                "exe": "",
            }
        status = openness_cli("status", timeout_s=60)
        ok = bool(status.get("ok")) and bool(status.get("OpennessAvailable"))
        return {
            "available": ok,
            "reason": "" if ok else f"Openness status 探测失败：{str(status.get('error') or status)[:300]}",
            "exe": str(exe),
            "status": status,
        }
    except Exception as exc:  # noqa: BLE001 - 探测失败一律降级
        return {"available": False, "reason": f"Openness 探测异常：{exc}", "exe": ""}


def _device_type_identifier() -> str:
    import os

    return os.environ.get("PLC_GREENFIELD_TIA_DEVICE_TYPE", "").strip()


def _run_openness_import_compile(
    *,
    project_name: str,
    package_dir: Path,
    workspace: Path,
    planned_text: str,
    supplement: dict[str, Any],
    tia_version: str,
) -> dict[str, Any]:
    """自动通道主体：新建 TIA 项目 → 导入 SCL/XML/标签表 → 编译 → 结构化回传。

    任一步失败都返回 ``{"status": "tia_error", ...}``（不抛异常），由上层
    **显式失败**（抛 ``GF_TIA_EXEC_ERROR``），禁止静默降级为 200 成功。
    编译步骤产出 :class:`CompileDiagnostics`（warning 单列、不并入成功）。
    """
    from agents.plc.tia.openness_cli import (
        compile_plc_via_openness_cli,
        create_device_via_openness_cli,
        generate_from_source_via_openness_cli,
        import_xml_via_openness_cli,
        openness_cli,
    )

    steps: list[dict[str, Any]] = []

    def _record(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": ok, "detail": detail[:400]})

    # 1. 新建 TIA 项目（create-project --dir --name）
    project_dir = workspace / "tia_project"
    created = openness_cli(
        "create-project", "--dir", str(project_dir), "--name", project_name, timeout_s=300
    )
    if not created.get("ok"):
        _record("create-project", False, str(created.get("error") or created))
        return {"status": "tia_error", "steps": steps, "compile": None,
                "error": "create-project 失败（TIA 可能被独占占用）"}
    project_path = str(created.get("path") or created.get("project") or project_dir / f"{project_name}.ap19")
    _record("create-project", True, project_path)

    # 2. 组态 CPU 设备（号型来自环境变量，未配置则诚实降级）
    type_id = _device_type_identifier()
    if not type_id:
        _record("create-device", False, "PLC_GREENFIELD_TIA_DEVICE_TYPE 未配置（例：6ES7511-1TK02-0AB0/V4.0）")
        return {"status": "tia_error", "steps": steps, "compile": None, "project_path": project_path,
                "error": "缺少 CPU 号型配置：设置 PLC_GREENFIELD_TIA_DEVICE_TYPE 后重试"}
    device = create_device_via_openness_cli(project_path, type_id, project_name)
    _record("create-device", bool(device.get("ok")), str(device.get("error") or ""))
    if not device.get("ok"):
        return {"status": "tia_error", "steps": steps, "compile": None, "project_path": project_path,
                "error": "create-device 失败"}

    # 3. SCL 外部源导入（mega_source 单文件，UTF-8 BOM；OB 不在其中——BR-3）
    scl_path = workspace / f"{project_name}_AF_bundle.scl"
    scl_path.write_bytes(b"\xef\xbb\xbf" + planned_text.encode("utf-8"))
    gen = generate_from_source_via_openness_cli(project_path, scl_path, timeout_s=900)
    _record("generate-from-source", bool(gen.get("ok")), str(gen.get("error") or ""))
    if not gen.get("ok"):
        return {"status": "tia_error", "steps": steps, "compile": None, "project_path": project_path,
                "error": "SCL 外部源导入失败"}

    # 4. OB SimaticML XML 逐个导入
    for rel in sorted(supplement["ob_files"]):
        xml_path = package_dir / rel
        imported = import_xml_via_openness_cli(
            project_path, xml_path, kind="block", timeout_s=300
        )
        _record(f"import-xml:{Path(rel).name}", bool(imported.get("ok")), str(imported.get("error") or ""))
        if not imported.get("ok"):
            return {"status": "tia_error", "steps": steps, "compile": None, "project_path": project_path,
                    "error": f"OB XML 导入失败：{Path(rel).name}（K1 探针项，必要时改走工程内预置 OB）"}

    # 5. IO 标签表 XML 导入
    tags_xml = package_dir / "plc_tags" / "PLCTags_Frozen.xml"
    if tags_xml.is_file():
        tags = import_xml_via_openness_cli(project_path, tags_xml, kind="tag", timeout_s=300)
        _record("import-xml:PLCTags_Frozen.xml", bool(tags.get("ok")), str(tags.get("error") or ""))
        if not tags.get("ok"):
            return {"status": "tia_error", "steps": steps, "compile": None, "project_path": project_path,
                    "error": "标签表 XML 导入失败"}

    # 6. fail-closed 编译（P0-A：结构化诊断；warning 单列、禁止并入成功）
    t0 = time.perf_counter()
    compiled = compile_plc_via_openness_cli(project_path, timeout_s=900)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    inner = compiled.get("compile") if isinstance(compiled.get("compile"), dict) else {}
    state = str(inner.get("state") or "")
    diagnostics = build_compile_diagnostics(
        compiled,
        static_gate_passed=True,  # 能进入编译说明四层静态门禁已 fail-closed 通过
        tia_version=tia_version,
        project_path=str(project_path),
        blocks=sorted(supplement["ob_files"]),
        elapsed_ms=elapsed_ms,
    )
    # 旧口径 ``or "warning" in state.lower()`` 会把含 warning 的编译算成功，
    # 本批次删除：唯一判定来自 CompileDiagnostics（error 数 + 静态门禁）。
    compile_ok = diagnostics.compile_ok
    _record(
        "compile-plc",
        compile_ok,
        (state or str(compiled.get("error") or ""))
        + f" | error_count={diagnostics.error_count}, warnings={len(diagnostics.warnings)}, "
        + f"elapsed_ms={elapsed_ms:.1f}",
    )
    return {
        "status": "compile_ok" if compile_ok else "compile_failed",
        "steps": steps,
        "compile": compiled,
        "diagnostics": diagnostics.to_dict(),
        "project_path": project_path,
        "tia_version": tia_version,
        "elapsed_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------- 编排


def _merge_verification(change: dict[str, Any], levels: dict[str, str], detail: dict[str, Any]) -> dict[str, Any]:
    """合并 verification（transition 的 patch 是顶层字段合并，直接给会丢默认级别）。"""
    verification = dict(change.get("verification") or {})
    verification.update(levels)
    merged = dict(verification.get("detail") or {})
    merged.update(detail)
    verification["detail"] = merged
    return verification


def _event(session: GreenfieldSession, text: str, payload: dict[str, Any] | None = None) -> None:
    session.add_message("event", "delivery", text, payload)


def deliver_tia(session: GreenfieldSession, *, mode: str = "auto") -> dict[str, Any]:
    """Greenfield 冻结规格 → AF 工程包 + XML 补充包 → 静态门禁 → PCEC 账本 →（可选）Openness 自动导入编译。

    流程对应 §9 P2-4..P2-8；副作用计数沿用 ``session.count("generations")``；
    Openness 不可用 / TIA 占用 → **显式失败**（抛 ``GF_TIA_UNAVAILABLE`` /
    ``GF_TIA_EXEC_ERROR``，由网关 ``_fail`` 产出 ``ok=false`` + 非 HTTP 200），
    **禁止**静默降级、禁止返回 200 成功。``package`` 模式不触 Openness，产出
    ``pending_real_machine`` 诊断；所有回执附 ``compile_diagnostics`` 供归档。
    """
    if mode not in MODES:
        raise GateLockedError(f"未知交付模式 {mode!r}，可选：{'/'.join(MODES)}", code="GF_TIA_MODE_INVALID")

    # a. 前置门禁：FROZEN + specs 非空（动作名 "generate" 走既有门禁矩阵）
    session.assert_gate("generate")
    if not session.specs:
        raise GateLockedError("尚未生成冻结规格，无法交付博途工程", code="GF_GATE_LOCKED")
    spec = session.specs[-1]

    # b. 复用 AfGreenfieldDelivery 产物（session.last_delivery 或现场生成）
    if session.last_delivery is None:
        gf_service.generate_project_package(session)
    delivery = session.last_delivery
    assert delivery is not None
    ir = GreenfieldIR.from_dict(spec.ir_snapshot)
    _event(
        session,
        f"TIA 交付启动（mode={mode}）：复用 AF V1.2 工程包 {delivery['zip_filename']}"
        f"（{delivery['block_count']} blocks，spec {spec.version_label}）",
        {"mode": mode, "spec_version": spec.spec_version, "block_count": delivery["block_count"]},
    )

    # c. P2-4 XML 补充包（OB SimaticML XML + 文档化文件夹清单）
    supplement = build_xml_supplement(delivery, ir)
    _event(
        session,
        f"XML 补充包已生成：OB XML {len(supplement['generated_obs'])} 个"
        f"（跳过 {len(supplement['skipped_obs'])} 个：SecondaryType 未真机确证）"
        f"+ 文件夹清单；xml_package_unverified={supplement['xml_package_unverified']}",
        {
            "ob_count": len(supplement["generated_obs"]),
            "skipped_ob_count": len(supplement["skipped_obs"]),
            "xml_package_unverified": supplement["xml_package_unverified"],
            "pending_real_machine": True,
        },
    )

    # d. P2-5 四层静态门禁（fail-closed；失败不建 PCEC 事务、不触 Openness）
    try:
        gates = run_static_gates(delivery)
    except GateLockedError as exc:
        _event(session, f"四层静态门禁拦截，交付中止：{exc.message}", {"ok": False, "code": exc.code})
        raise
    _event(
        session,
        "四层静态门禁全部通过：af_linter → scl_precheck → writeback_linter → mega_source",
        {"artifact_count": gates["artifact_count"], "stages": [s["name"] for s in gates["stages"]]},
    )

    # 落盘 staged 包并取基线（PCEC R1）
    package_dir = _stage_package(session, spec, delivery, supplement)
    baseline = pcec.project_baseline(package_dir)

    # e. P2-6 PCEC：new_change → analyzed → validated → approved → put_change → baseline_matches
    touched = [str(entry["name"]) for entry in delivery["blocks_manifest"]]
    request_summary = (
        f"Greenfield 冻结规格 {spec.version_label} 生成 AF V1.2 博途工程包"
        f"（{delivery['block_count']} 块，spec_hash={spec.spec_hash}）"
    )
    change = pcec.new_change(
        "greenfield_generate",
        request_summary,
        ops=[
            {
                "op": "generate_af_package",
                "spec_hash": spec.spec_hash,
                "block_count": delivery["block_count"],
                "zip_sha256": delivery.get("zip_sha256", ""),
            }
        ],
        touched_blocks=touched,
        baseline=baseline,
    )
    change = pcec.transition(
        change,
        "analyzed",
        event="analyzed",
        verification=_merge_verification(change, {"v0_parsed": "pass"}, {"spec_hash": spec.spec_hash}),
        preconditions=[
            {"name": "规格已冻结且哈希复现", "ok": True},
            {"name": "四层静态门禁", "ok": True},
        ],
    )
    change = pcec.transition(
        change,
        "validated",
        event="v1_static_pass",
        verification=_merge_verification(change, {"v1_static": "pass"}, {"gates": [s["name"] for s in gates["stages"]]}),
    )
    change = pcec.transition(
        change,
        "approved",
        event="approved",
        approval={
            "reviewer": spec.frozen_by or "user",
            "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": touched,
        },
    )
    pcec.put_change(change)
    change_id = str(change.get("change_id") or "")
    _event(
        session,
        f"PCEC 事务已建立并批准：{change_id}（touched {len(touched)} blocks）",
        {"change_id": change_id, "status": "approved"},
    )

    if not pcec.baseline_matches(change, package_dir):
        change = pcec.transition(
            change,
            "expired",
            event="baseline_expired",
            verification=_merge_verification(change, {"v1_static": "fail"}, {"reason": "工程基线已变化"}),
        )
        pcec.put_change(change)
        _event(
            session,
            f"工程基线已变化，事务 {change_id} 过期，交付拒绝（fail-closed）",
            {"change_id": change_id, "status": "expired", "ok": False},
        )
        raise GateLockedError(
            "工程基线已变化，变更过期拒绝（PCEC fail-closed）",
            code="GF_PCEC_BASELINE_EXPIRED",
            details={"change_id": change_id, "package_dir": str(package_dir)},
        )

    # f. P2-7/P2-8 Openness 自动导入编译（TIA 不可用 → 显式失败，禁止 200 静默通过）
    openness: dict[str, Any] = {"attempted": False, "status": "skipped_package_mode"}
    guidance: str | None = None
    tia_version = str(ir.project.tia_version or "V19")
    block_names = [str(entry["name"]) for entry in delivery["blocks_manifest"]]
    tia_project_path = str(package_dir / "tia_project")
    diagnostics: CompileDiagnostics
    if mode == "auto":
        probe = _openness_probe()
        if not probe.get("available"):
            # UC-03：显式非成功状态，禁止 HTTP 200 静默通过 / 静默降级。
            diagnostics = unavailable_diagnostics(
                reason=str(probe.get("reason") or "未知"),
                static_gate_passed=bool(gates.get("ok")),
                tia_version=tia_version,
                project_path=tia_project_path,
                blocks=block_names,
            )
            openness = {
                "attempted": True,
                "status": "tia_unavailable",
                "probe": probe,
                "compile_diagnostics": diagnostics.to_dict(),
            }
            guidance = _MANUAL_GUIDANCE_TEMPLATE.format(
                reason=str(probe.get("reason") or "未知"), change_id=change_id
            )
            change["events"].append(
                {
                    "ts": time.time(),
                    "event": "tia_unavailable",
                    "detail": str(probe.get("reason") or ""),
                    "compile_diagnostics": diagnostics.to_dict(),
                }
            )
            pcec.put_change(change)
            _event(
                session,
                "Openness 自动通道不可用：显式失败（GF_TIA_UNAVAILABLE，非 HTTP 200）；"
                "事务保持 approved 并标注 tia_unavailable，L2 未达成",
                {"change_id": change_id, "status": "tia_unavailable", "reason": str(probe.get("reason") or "")},
            )
            raise GateLockedError(
                "TIA / Openness 不可用，交付链显式失败："
                + str(probe.get("reason") or "未知")
                + "（error_code=GF_TIA_UNAVAILABLE；禁止静默降级或返回 200 成功）",
                code=TIA_UNAVAILABLE_ERROR_CODE,
                details={
                    "change_id": change_id,
                    "reason": str(probe.get("reason") or ""),
                    "compile_diagnostics": diagnostics.to_dict(),
                    "tia_unavailable": True,
                    "pending_real_machine": False,
                    "guidance": guidance,
                },
            )
        else:
            run = _run_openness_import_compile(
                project_name=str(delivery["project_name"]),
                package_dir=package_dir,
                workspace=package_dir.parent,
                planned_text=str(gates.get("planned_text") or ""),
                supplement=supplement,
                tia_version=tia_version,
            )
            diagnostics = _diagnostics_from_run(
                run, gates=gates, delivery=delivery, tia_version=tia_version
            )
            if run.get("status") == "compile_ok" and diagnostics.compile_ok:
                change = pcec.transition(
                    change,
                    "applied",
                    event="applied_compile_ok",
                    verification=_merge_verification(
                        change,
                        {"v2_tia_compile": "pass"},
                        {
                            "compile_steps": [s["step"] for s in run.get("steps") or []],
                            "compile_diagnostics": diagnostics.to_dict(),
                        },
                    ),
                )
                pcec.put_change(change)
                openness = {
                    **{k: v for k, v in run.items() if k != "diagnostics"},
                    "attempted": True,
                    "status": "compile_ok",
                    "compile_diagnostics": diagnostics.to_dict(),
                }
                _event(
                    session,
                    f"Openness 编译判定 compile_ok=true，事务 {change_id} → applied"
                    "（真机结论以 G1 验收为准，离线 mock 不构成 L2 证据）",
                    {"change_id": change_id, "status": "compile_ok", "project_path": run.get("project_path")},
                )
            elif run.get("status") == "compile_failed" or not diagnostics.compile_ok:
                change = pcec.transition(
                    change,
                    "failed",
                    event="compile_failed",
                    verification=_merge_verification(
                        change,
                        {"v2_tia_compile": "fail"},
                        {
                            "compile_steps": [s["step"] for s in run.get("steps") or []],
                            "compile_diagnostics": diagnostics.to_dict(),
                        },
                    ),
                )
                pcec.put_change(change)
                openness = {
                    **{k: v for k, v in run.items() if k != "diagnostics"},
                    "attempted": True,
                    "status": "compile_failed",
                    "compile_diagnostics": diagnostics.to_dict(),
                }
                _event(
                    session,
                    f"Openness 编译未过零错误口径，事务 {change_id} → failed（结构化诊断见回执）",
                    {"change_id": change_id, "status": "compile_failed", "error_count": diagnostics.error_count},
                )
            else:
                # 执行中断（未产出编译结论）同样是显式失败，禁止静默降级为 200。
                diagnostics = unavailable_diagnostics(
                    reason=str(run.get("error") or "Openness 执行中断"),
                    static_gate_passed=bool(gates.get("ok")),
                    tia_version=tia_version,
                    project_path=str(run.get("project_path") or tia_project_path),
                    blocks=block_names,
                )
                change["events"].append(
                    {
                        "ts": time.time(),
                        "event": "tia_error",
                        "detail": str(run.get("error") or "")[:400],
                        "compile_diagnostics": diagnostics.to_dict(),
                    }
                )
                pcec.put_change(change)
                guidance = _MANUAL_GUIDANCE_TEMPLATE.format(
                    reason=str(run.get("error") or "执行中断"), change_id=change_id
                )
                _event(
                    session,
                    f"Openness 执行中断（{run.get('error') or '未知'}）：显式失败 GF_TIA_EXEC_ERROR，事务 {change_id} 保持 approved",
                    {"change_id": change_id, "status": "tia_error"},
                )
                raise GateLockedError(
                    "Openness 自动通道执行中断，交付链显式失败："
                    + str(run.get("error") or "未知")
                    + "（error_code=GF_TIA_EXEC_ERROR；禁止静默降级或返回 200 成功）",
                    code=TIA_EXEC_ERROR_CODE,
                    details={
                        "change_id": change_id,
                        "reason": str(run.get("error") or "未知"),
                        "compile_diagnostics": diagnostics.to_dict(),
                        "tia_unavailable": True,
                        "pending_real_machine": False,
                        "guidance": guidance,
                    },
                )
    else:
        # package 模式：不触 Openness，真机未跑，显式 pending_real_machine。
        diagnostics = pending_real_machine_diagnostics(
            static_gate_passed=bool(gates.get("ok")),
            tia_version=tia_version,
            project_path=tia_project_path,
            blocks=block_names,
        )
        openness = {
            "attempted": False,
            "status": "skipped_package_mode",
            "compile_diagnostics": diagnostics.to_dict(),
        }
        change["events"].append(
            {"ts": time.time(), "event": "package_only", "pending_real_machine": True}
        )
        pcec.put_change(change)

    # g. 收尾：回执 + 最终 ZIP + 计数
    status = openness.get("status") or "skipped_package_mode"
    final_status = {
        "compile_ok": "delivered_applied",
        "compile_failed": "delivered_compile_failed",
        "skipped_package_mode": "package_only",
    }.get(status, status)
    # ``ok`` 只表示交付编排完成（ApiResponse 信封语义），**绝不代表** L2 通过
    # 或「编译零错误」；L2 状态由 compile_diagnostics.compile_ok 与 l2_status 独立表达（N9）。
    receipt = {
        "ok": True,
        "status": final_status,
        "mode": mode,
        "change_id": change_id,
        "project_name": delivery["project_name"],
        "spec_version": spec.version_label,
        "spec_hash": spec.spec_hash,
        "gates": {k: v for k, v in gates.items() if k != "planned_text"},
        "openness": openness,
        "compile_diagnostics": diagnostics.to_dict(),
        "xml_package_unverified": supplement["xml_package_unverified"],
        "pending_real_machine": diagnostics.pending_real_machine,
        "l2_status": L2_STATUS_PENDING,
        "l2_note": (
            "本批次为离线可推进部分（WP-01 P0-A/P0-C）：真机导入编译与 G1/L2 验收未执行；"
            "compile_diagnostics 仅为离线/mock 口径验证，不构成 L2 证据；"
            "AF 档位（P0-D）结论待 G0 真机实测后拍板，结论前映射层维持档位无关"
        ),
        "generated_obs": supplement["generated_obs"],
        "skipped_obs": supplement["skipped_obs"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    zip_bytes = _assemble_tia_zip(delivery, supplement, receipt)
    zip_filename = f"{delivery['project_name']}_{spec.version_label}_AF_TIA_Full.zip"
    result: dict[str, Any] = {
        **receipt,
        "package": {
            "zip_filename": zip_filename,
            "zip_sha256": sha256_prefixed(zip_bytes.hex()),
            "zip_size_bytes": len(zip_bytes),
            "scl_entry_count": delivery["block_count"],
            "xml_supplement_files": sorted(supplement["supplement_files"]),
            "package_dir": str(package_dir),
        },
        "guidance": guidance,
        "zip_bytes": zip_bytes,
    }
    session.count("generations")
    # 收口接线（J7）：把结构化编译诊断与只读 SCL 预览源回写到会话交付摘要，
    # 供 /state.delivery_summary 与前端读取；无真实产物时 collect 返回 None（禁止虚构）。
    delivery["compile_diagnostics"] = diagnostics.to_dict()
    delivery["scl_sources"] = gf_service.collect_scl_sources(delivery)
    result["scl_sources"] = delivery["scl_sources"]
    return result
