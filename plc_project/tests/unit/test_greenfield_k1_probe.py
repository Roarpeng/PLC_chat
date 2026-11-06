"""UC-04 K1 探针修复（自产 XML 可导入性）离线单测。

全离线、不连真机：只断言 ``tia_delivery._render_ob_xml`` /
``build_xml_supplement`` 生成的字符串与真实 V19 导出先例逐字段一致
（culture / namespace / 结构稳定性），以及 ``ob_entries`` 为空时不虚构 OB。

真实 V19 导出先例：
``PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/OB1Main.xml``
（LAD OB，``FlgNet/v5``，空 CompileUnit 用 ``<NetworkSource />``）。
F 的 Gate-0 真机实测见 ``research/Gate0_环境与档位实测_2026-11-06.md`` §6
与 ``docs/greenfield/06-gate0-report.md`` §3。

**诚实口径**：本文件是离线字符串断言，**不构成 L2/L4 证据、不宣称
「编译零错误」、不宣称真机导入成功**。真机导入 / 编译结论见
``docs/greenfield/08-k1-probe-fix.md``，由主 agent 收口决定
``xml_package_unverified`` 的处置。
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from types import SimpleNamespace

import pytest

from gateway.app.services.plc import tia_delivery

# 真实 V19 导出先例的关键 namespace / culture 常量（逐字段对照基准）。
V19_INTERFACE_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"
V19_FLGNET_NS = (
    "http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5"
)
WRONG_STRUCTUREDTEXT_NS = (
    "http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v4"
)
V19_TARGET_CULTURE = "zh-CN"
NON_PROJECT_CULTURES = ("en-US", "de-DE")


def _ob_xml(**kw: object) -> str:
    """渲染一个自产 OB XML（默认空网络，与 F 的 K1 探针复现参数一致）。"""
    defaults: dict[str, object] = dict(
        ob_name="OB1Main",
        ob_number=1,
        secondary_type="ProgramCycle",
        call_db="",
        title="AF V1.2 OB1Main",
        tia_version="V19",
    )
    defaults.update(kw)
    return tia_delivery._render_ob_xml(**defaults)  # type: ignore[arg-type]


def _strip_created(xml: str) -> str:
    """抹掉 ``<Created>`` 时间戳，使两次渲染可逐字节复现比较。"""
    return re.sub(r"<Created>.*?</Created>", "<Created>X</Created>", xml)


def _minimal_delivery(manifest: list[dict[str, object]]) -> dict[str, object]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("blocks/FB_Foo.scl", "FUNCTION_BLOCK FB_Foo\nBEGIN\nEND_FUNCTION_BLOCK")
    return {"zip_bytes": buf.getvalue(), "blocks_manifest": manifest}


def _stub_ir() -> SimpleNamespace:
    # build_xml_supplement 只读 ir.project.tia_version；expected_ob_numbers 被
    # monkeypatch 后不再访问 units / ems，故 SimpleNamespace 足够。
    return SimpleNamespace(project=SimpleNamespace(tia_version="V19"))


# ------------------------------------------------------------- culture 缺陷


def test_ob_xml_cultures_match_target_project_language() -> None:
    """缺陷 1：自产 XML 不得硬编码 en-US/de-DE 等目标项目不存在的 culture。

    依据：F 真机失败码 ``openness_error``「Cannot import multilingual text
    with culture 'en-US' ... does not exist within the current project.」；
    仅 zh-CN 的诊断变体与真实先例改号样本（OB123_from_real.xml）通过 culture
    校验并导入成功。3 个 MultilingualText 块（Comment×2 + Title×1）各 1 个 culture。
    """
    for call_db in ("", "U1_KukaVisionStation_CallUnit_DB"):
        xml = _ob_xml(call_db=call_db)
        assert f"<Culture>{V19_TARGET_CULTURE}</Culture>" in xml
        for culture in NON_PROJECT_CULTURES:
            assert f"<Culture>{culture}</Culture>" not in xml
        assert xml.count("<Culture>") == 3


# ----------------------------------------------------------- namespace 缺陷


def test_ob_xml_never_uses_structuredtext_v4_namespace() -> None:
    """缺陷 2：LAD OB 绝不能用 ``StructuredText/v4``（F 诊断变体失败根因）。"""
    for call_db in ("", "U1_KukaVisionStation_CallUnit_DB"):
        xml = _ob_xml(call_db=call_db)
        assert WRONG_STRUCTUREDTEXT_NS not in xml
        assert "StructuredText" not in xml
        assert "<Token" not in xml
        # Interface 段 namespace 与真实先例一致
        assert V19_INTERFACE_NS in xml


def test_ob_xml_call_network_uses_flgnet_v5_like_precedent() -> None:
    """有 call_db 的 OB：FlgNet/v5 + CallInfo(Instance DB) + Powerrail/NameCon
    与真实 V19 导出先例 OB1Main.xml:83-99 逐字段一致。"""
    xml = _ob_xml(call_db="U1_KukaVisionStation_CallUnit_DB")
    assert V19_FLGNET_NS in xml
    assert '<CallInfo Name="U1_KukaVisionStation_CallUnit" BlockType="FB">' in xml
    assert '<Component Name="U1_KukaVisionStation_CallUnit_DB" />' in xml
    assert "<Powerrail />" in xml
    assert '<NameCon UId="21" Name="en" />' in xml
    assert "<ProgrammingLanguage>LAD</ProgrammingLanguage>" in xml


def test_ob_xml_empty_network_matches_precedent_empty_compileunit() -> None:
    """无 call_db 的 OB：空 CompileUnit 用 ``<NetworkSource />`` 自闭合，
    与真实先例 OB1Main.xml:1140 一致；不构造可能违反 LAD rung 约束的伪网络。"""
    xml = _ob_xml(call_db="")
    assert "<NetworkSource />" in xml
    assert V19_FLGNET_NS not in xml
    assert "<FlgNet" not in xml
    assert "StructuredText" not in xml


# --------------------------------------------------------- 结构稳定 / 可复现


def test_ob_xml_structure_stable_and_reproducible() -> None:
    """模板结构稳定可复现；根元素 / Engineering / OB / Number / LAD 等骨架
    与真实 V19 先例一致（除时间戳外两次渲染逐字节相等）。"""
    a = _strip_created(
        _ob_xml(ob_name="OB123Unit01", ob_number=123, call_db="FB_A_DB")
    )
    b = _strip_created(
        _ob_xml(ob_name="OB123Unit01", ob_number=123, call_db="FB_A_DB")
    )
    assert a == b
    for token in (
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Engineering version="V19" />',
        '<SW.Blocks.OB ID="0">',
        "<AutoNumber>false</AutoNumber>",
        "<Name>OB123Unit01</Name>",
        "<Number>123</Number>",
        "<ProgrammingLanguage>LAD</ProgrammingLanguage>",
        "<SecondaryType>ProgramCycle</SecondaryType>",
        V19_INTERFACE_NS,
        "</Document>",
    ):
        assert token in a


# -------------------------------------- ob_entries 为空时不虚构 OB / 诚实清单


def test_build_xml_supplement_no_fabricated_ob_when_no_ob_in_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资料缺失（ob_entries / OB manifest 为空）→ 不静默近似、不虚构任何 OB XML。"""
    monkeypatch.setattr(tia_delivery, "expected_ob_numbers", lambda ir: {})
    delivery = _minimal_delivery(
        [
            {
                "name": "FB_Foo",
                "block_type": "FB",
                "path": "blocks/FB_Foo.scl",
                "number": 1,
                "folder": "root",
            }
        ]
    )
    supp = tia_delivery.build_xml_supplement(delivery, _stub_ir())  # type: ignore[arg-type]
    assert supp["ob_files"] == {}
    assert supp["generated_obs"] == []
    assert supp["skipped_obs"] == []
    assert not any(
        key.startswith("xml_supplement/ob/") for key in supp["supplement_files"]
    )


def test_folders_json_is_documentation_manifest_not_simaticml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """folders.json 是文档化清单，不是可 import-xml 的 SimaticML 对象。"""
    monkeypatch.setattr(tia_delivery, "expected_ob_numbers", lambda ir: {})
    delivery = _minimal_delivery(
        [
            {
                "name": "FB_Foo",
                "block_type": "FB",
                "path": "blocks/FB_Foo.scl",
                "number": 1,
                "folder": "Unit_01/EM_01",
            }
        ]
    )
    supp = tia_delivery.build_xml_supplement(delivery, _stub_ir())  # type: ignore[arg-type]
    raw = supp["supplement_files"]["xml_supplement/folders.json"].decode("utf-8")
    folders = json.loads(raw)
    assert "folders" in folders and "note" in folders
    assert "Unit_01/EM_01" in folders["folders"]
    assert "文件夹" in folders["note"]
    assert "SW.PlcBlockGroup" in folders["note"]
    assert "<SW.Blocks" not in raw
    assert "<Document" not in raw


def test_manifest_keeps_xml_package_unverified_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """诚实口径：离线单测不得擅自消除 ``xml_package_unverified``。
    修复模板后该标志仍为 True，真机复测结论由主 agent 收口决定。"""
    monkeypatch.setattr(tia_delivery, "expected_ob_numbers", lambda ir: {})
    supp = tia_delivery.build_xml_supplement(
        _minimal_delivery([]), _stub_ir()  # type: ignore[arg-type]
    )
    assert supp["xml_package_unverified"] is True
