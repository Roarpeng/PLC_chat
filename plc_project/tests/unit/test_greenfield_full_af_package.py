"""Agent U · 批次 4 · UC-04 完整 AF 包自洽化离线单测。

纯离线、不连真机 / 不启动 SessionServer / 不跑 TIA CLI / 不占用端口：
只断言 ``tools/build_full_af_package.py`` 产出的完整包（Call 网络 OB + FB +
全局实例 DB）在**包内引用自洽**、XML 结构与真实 V19 导出先例一致、
manifest 逐文件 sha256 可复算 / 两次生成可复现、旧调用向后兼容、
空 ``ob_entries`` 不虚构 OB。

真实 V19 导出先例（只读参考）：
- ``PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/OB1Main.xml``（Call 网络）
- ``.../001_KL_Standard_FB_FB1000_StdSignal.xml``（``SW.Blocks.FB``）
- ``.../001_KL_Standard_FB_DB1000_StdSignal.xml``（``SW.Blocks.InstanceDB``）

**诚实口径**：本文件是离线字符串 / 纯函数断言，**不构成 L2/L4 证据、
不宣称 UC-04 通过、不宣称完整包编译零错误、不宣称真机导入成功**。
真机导入编译由阶段 B 的 Agent W 验证；``xml_package_unverified`` 保持 True。
"""
from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.app.services.plc import tia_delivery  # noqa: E402
import tools.build_full_af_package as pkg  # noqa: E402

V19_INTERFACE_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"
V19_FLGNET_NS = (
    "http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5"
)
WRONG_STRUCTUREDTEXT_NS = (
    "http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v4"
)
NON_PROJECT_CULTURES = ("en-US", "de-DE")


def _xml_text(data: bytes) -> str:
    """按 utf-8-sig 解码（与真机先例/K 修复后自产 XML 编码一致）并校验可解析。"""
    text = data.decode("utf-8-sig")
    ET.fromstring(text)  # 合法 XML
    return text


def _block_name(data: bytes) -> str:
    """从块 XML 的 ``<Name>`` 提取块名（无 namespace 元素）。"""
    root = ET.fromstring(data.decode("utf-8-sig"))
    el = root.find(".//Name")
    assert el is not None and el.text
    return el.text


def _package():
    files = pkg.render_package()
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    return files, manifest


# --------------------------------------------- 引用关系：Call OB ↔ FB / DB 自洽


def test_call_network_names_match_package_fb_db_names() -> None:
    """Call 网络 ``CallInfo.Name`` / ``Component.Name`` 与包内 FB/DB 的
    ``<Name>`` 逐字一致（修复批次 3「FB 名从实例 DB 名反推」的根因）。"""
    files, manifest = _package()
    fb_name = _block_name(files[manifest["fb"]["path"]])
    db_name = _block_name(files[manifest["db"]["path"]])
    assert fb_name == pkg.DEFAULT_FB_NAME
    assert db_name == pkg.DEFAULT_DB_NAME

    assert manifest["references"], "至少一个 Call 网络 OB"
    ref = manifest["references"][0]
    assert ref["call_fb"] == fb_name
    assert ref["call_db"] == db_name
    assert ref["fb_block"] == fb_name
    assert ref["db_block"] == db_name
    assert manifest["references_self_consistent"] is True

    call_ob = _xml_text(files[ref["ob_xml"]])
    assert f'<CallInfo Name="{fb_name}" BlockType="FB">' in call_ob
    assert f'<Component Name="{db_name}" />' in call_ob
    assert V19_FLGNET_NS in call_ob
    # 新路径：FB/DB 独立命名，绝不退化成 call_db 整体（批次 3 失败形态）
    assert f'<CallInfo Name="{db_name}" BlockType="FB">' not in call_ob


def test_instance_db_links_back_to_fb() -> None:
    """实例 DB 根元素以先例为准 ``SW.Blocks.InstanceDB``（非 GlobalDB），
    ``InstanceOfName`` / ``InstanceOfType`` 关联回包内 FB。"""
    files, manifest = _package()
    fb_name = _block_name(files[manifest["fb"]["path"]])
    db_xml = _xml_text(files[manifest["db"]["path"]])
    assert '<SW.Blocks.InstanceDB ID="0">' in db_xml
    assert "SW.Blocks.GlobalDB" not in db_xml
    assert f"<InstanceOfName>{fb_name}</InstanceOfName>" in db_xml
    assert "<InstanceOfType>FB</InstanceOfType>" in db_xml
    assert manifest["db"]["instance_of_fb"] == fb_name


# --------------------------------------------- XML 结构 / culture / namespace


def test_fb_db_ob_xml_culture_namespace_number() -> None:
    """FB/DB/OB XML：culture 仅 zh-CN、Interface namespace 与先例一致、
    ``<Number>`` 存在、绝不出现 StructuredText/v4。"""
    files, manifest = _package()
    xml_paths = [r["path"] for r in manifest["files"] if r["path"].endswith(".xml")]
    assert len(xml_paths) == 2 + manifest["generated_ob_count"]
    for path in xml_paths:
        xml = _xml_text(files[path])
        assert "<Culture>zh-CN</Culture>" in xml
        for culture in NON_PROJECT_CULTURES:
            assert f"<Culture>{culture}</Culture>" not in xml
        assert V19_INTERFACE_NS in xml
        assert "<Number>" in xml
        assert WRONG_STRUCTUREDTEXT_NS not in xml
        assert "StructuredText" not in xml
        assert "<Token" not in xml


def test_fb_root_and_language_match_precedent() -> None:
    """FB 根元素 / ProgrammingLanguage 与真实先例一致；空 CompileUnit 不虚构网络。"""
    files, manifest = _package()
    fb_xml = _xml_text(files[manifest["fb"]["path"]])
    assert '<SW.Blocks.FB ID="0">' in fb_xml
    assert "<ProgrammingLanguage>LAD</ProgrammingLanguage>" in fb_xml
    assert "<Number>1000</Number>" in fb_xml
    # 先例 FB 的 ObjectList 只有 Title，不含 CompileUnit / 网络
    assert "SW.Blocks.CompileUnit" not in fb_xml
    assert "<FlgNet" not in fb_xml


def test_instance_db_language_is_db() -> None:
    """实例 DB 的 ProgrammingLanguage=DB（先例），Number 原生指定。"""
    files, manifest = _package()
    db_xml = _xml_text(files[manifest["db"]["path"]])
    assert "<ProgrammingLanguage>DB</ProgrammingLanguage>" in db_xml
    assert "<Number>1000</Number>" in db_xml
    assert "<AutoNumber>false</AutoNumber>" in db_xml


# --------------------------------------------- import_order / manifest 可复现


def test_import_order_complete_and_fb_db_ob_order() -> None:
    """``import_order`` 完整覆盖 FB → DB → 全部 OB，供 W 按序导入。"""
    files, manifest = _package()
    order = manifest["import_order"]
    assert order[0] == manifest["fb"]["path"]
    assert order[1] == manifest["db"]["path"]
    # OB 内部顺序按 ob_entries 顺序（确定性），大类严格 FB → DB → OB
    assert order[2:] == [f"ob/{e['name']}.xml" for e in manifest["ob_entries"]]
    assert {p for p in order[2:]} == {
        r["path"] for r in manifest["files"] if r["kind"] == "ob"
    }
    xml_paths = {r["path"] for r in manifest["files"] if r["path"].endswith(".xml")}
    assert set(order) == xml_paths
    assert len(order) == len(xml_paths)
    assert len(order) == 2 + manifest["generated_ob_count"]


def test_manifest_per_file_sha256_recomputable() -> None:
    """manifest 逐文件 sha256 / bytes 可复算；manifest.json 自身不入清单（无自指）。"""
    files, manifest = _package()
    records = {r["path"]: r for r in manifest["files"]}
    assert "manifest.json" not in records
    for path, rec in records.items():
        data = files[path]
        assert rec["sha256"] == hashlib.sha256(data).hexdigest()
        assert rec["bytes"] == len(data)
    assert set(records) == {p for p in files if p != "manifest.json"}


def test_two_renders_are_byte_reproducible() -> None:
    """同样参数两次生成：全部文件字节一致，manifest 内容 sha256 一致
    （固定 ``<Created>`` + 确定性 JSON 序列化，去掉真实时间戳）。"""
    f1 = pkg.render_package()
    f2 = pkg.render_package()
    assert f1.keys() == f2.keys()
    for path in f1:
        assert f1[path] == f2[path], f"文件不可复现：{path}"
    s1 = hashlib.sha256(f1["manifest.json"]).hexdigest()
    s2 = hashlib.sha256(f2["manifest.json"]).hexdigest()
    assert s1 == s2
    # 固定时间戳确实生效
    assert b"<Created>2000-01-01T00:00:00Z</Created>" in f1[manifest_fb_path(f1)]


def manifest_fb_path(files) -> str:
    """辅助：从渲染产物里找出 FB XML 路径（确定性）。"""
    return next(p for p in files if p.startswith("blocks/") and "FB" in p)


def test_build_package_writes_disk_and_manifest_matches(tmp_path: Path) -> None:
    """``build_package`` 写盘后：每个清单文件存在、sha256 可复算，
    落盘 manifest.json 与返回 dict 一致；两次写到不同目录仍可复现。"""
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    man_a = pkg.build_package(out_a)
    man_b = pkg.build_package(out_b)
    for rec in man_a["files"]:
        disk = out_a / rec["path"]
        assert disk.exists()
        assert hashlib.sha256(disk.read_bytes()).hexdigest() == rec["sha256"]
    disk_manifest = (out_a / "manifest.json").read_bytes()
    assert json.loads(disk_manifest.decode("utf-8")) == man_a
    assert disk_manifest == (out_b / "manifest.json").read_bytes()
    assert man_a == man_b


def test_cli_main_writes_to_required_out_dir(tmp_path: Path) -> None:
    """CLI ``--out <dir>`` 必填、写指定目录、不写产品目录（默认值不落盘）。"""
    out = tmp_path / "cli"
    assert pkg.main(["--out", str(out), "--tia-version", "V19"]) == 0
    assert (out / "manifest.json").exists()
    assert (out / "folders.json").exists()
    assert (out / manifest_fb_path(pkg.render_package())).exists()


# --------------------------------------------- 旧调用向后兼容 / 空清单不虚构


def test_legacy_call_db_only_path_still_valid() -> None:
    """旧调用只传 ``call_db``（不传 ``call_fb``）不抛异常，仍产出合法 XML，
    且保守回退到既有 ``_DB`` 后缀剥离推导（K1 探针 / build_xml_supplement 口径）。"""
    xml = tia_delivery._render_ob_xml(
        ob_name="OB124_K1Fixed_Call",
        ob_number=124,
        secondary_type="ProgramCycle",
        call_db="K1_CallUnit_DB",
        title="AF V1.2 OB124_K1Fixed_Call",
        tia_version="V19",
    )
    _xml_text(xml.encode("utf-8-sig"))
    assert '<CallInfo Name="K1_CallUnit" BlockType="FB">' in xml
    assert '<Component Name="K1_CallUnit_DB" />' in xml
    assert "<Culture>zh-CN</Culture>" in xml
    for culture in NON_PROJECT_CULTURES:
        assert f"<Culture>{culture}</Culture>" not in xml
    assert "<Number>124</Number>" in xml


def test_empty_ob_entries_do_not_fabricate_ob() -> None:
    """``ob_entries=[]`` → 不虚构任何 OB XML / 引用 / OB 导入条目。"""
    files, manifest = _package()
    empty = pkg.render_package(ob_entries=[])
    empty_manifest = json.loads(empty["manifest.json"].decode("utf-8"))
    assert not any(p.startswith("ob/") for p in empty)
    assert empty_manifest["generated_ob_count"] == 0
    assert empty_manifest["ob_entries"] == []
    assert empty_manifest["references"] == []
    assert empty_manifest["import_order"] == [
        manifest["fb"]["path"],
        manifest["db"]["path"],
    ]
    # 默认包确有 Call 网络 OB，反证空清单不是「默认行为」
    assert manifest["generated_ob_count"] >= 1
    assert manifest["references"]


def test_inconsistent_reference_is_rejected() -> None:
    """fail-closed：Call OB 的 call_fb/call_db 与包内 FB/DB 名不一致 → 拒绝出包。"""
    bad = [
        {
            "name": "GF_Bad_CallOB",
            "number": 1099,
            "secondary_type": "ProgramCycle",
            "call_db": pkg.DEFAULT_DB_NAME,
            "call_fb": "Wrong_FB_Name",
        }
    ]
    with pytest.raises(ValueError, match="不自洽"):
        pkg.render_package(ob_entries=bad)


# --------------------------------------------- 诚实标注


def test_manifest_keeps_honest_flags() -> None:
    """诚实口径：``xml_package_unverified`` / ``pending_real_machine`` 保持 True，
    notes 明确「仅离线构造、真机由 Agent W 验证、不宣称通过」。"""
    _, manifest = _package()
    assert manifest["xml_package_unverified"] is True
    assert manifest["pending_real_machine"] is True
    assert manifest["reproducible"] is True
    notes = " ".join(manifest["notes"])
    assert "Agent W" in notes
    assert "不宣称" in notes
    assert "xml_package_unverified" in notes
    folders = json.loads(pkg.render_package()["folders.json"].decode("utf-8"))
    assert folders["mechanism"].startswith("create-block-group")
    assert "SW.PlcBlockGroup" in folders["note"]
    assert "<Document" not in json.dumps(folders)  # 非 SimaticML 对象
