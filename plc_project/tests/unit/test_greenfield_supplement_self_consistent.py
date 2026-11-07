"""Agent X · 正式产品通道 ``build_xml_supplement`` 的 FB/DB 自洽接线离线单测。

纯离线：不连真机 / 不启动 SessionServer / 不跑 TIA CLI / 不占用 8791/8000。
只断言正式 ``deliver_tia(session, mode="package")`` 产出的 ZIP 里：

- ``xml_supplement/blocks/*.xml`` 下 FB / 实例 DB 块存在（当 ``blocks_manifest``
  有对应真实条目时）；
- 每个带 ``call_db`` 的 OB 的 ``CallInfo.Name`` / ``Component.Name`` 与包内
  FB/DB XML 的 ``<Name>`` 逐字一致、DB 的 ``InstanceOfName`` 回链 FB；
- ``import_order`` 严格 FB → DB → OB、``references_self_consistent=True``；
- ``xml_supplement/manifest.json`` 保留 ``xml_package_unverified is True`` /
  ``pending_real_machine is True``，并诚实写明正式包尚未单独真机验证；
- ``blocks_manifest`` 缺对应 FB/DB 条目或 ``call_db`` 不以 ``_DB`` 结尾时，
  不虚构编号、不生成假块、``skipped_blocks`` 留痕。

**诚实口径**：本文件是离线字符串 / 包内自洽断言，**不构成 L2/L4 证据、
不宣称正式包真机导入成功 / 编译零错误 / UC-04 完全闭环**。自产 OB/FB/DB
XML 的独立包探针级真机验证见 ``evidence/uc04_full_package_real.json``（Agent W），
但那针对 ``tools/build_full_af_package.py`` 的独立包；**正式产品通道产出的本包
尚未单独真机验证**，由后续 agent 在临时副本上按 ``import_order`` 验证。

复用 ``tests.unit.test_greenfield_tia_delivery._frozen_session`` 构造真实会话；
未改 ``tia_delivery.py`` 的任何 import（渲染函数均为同文件内 U 已新增的符号）。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.app.services.plc import tia_delivery
from gateway.app.services.plc.greenfield_session import registry
from tests.unit.test_greenfield_tia_delivery import _frozen_session


@pytest.fixture()
def isolated_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PLC_WORK_DIR 隔离：spec / staged 包 / PCEC 账本全部落在 tmp_path（纯离线）。"""
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path))
    registry.reset()
    return tmp_path


def _deliver(session_id: str) -> tuple[object, dict]:
    """复用 _frozen_session 走完冻结全链，再走正式 package 交付通道。"""
    session = _frozen_session(session_id)
    result = tia_delivery.deliver_tia(session, mode="package")
    return session, result


def _zip(result: dict) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(result["zip_bytes"]))


def _decode_xml(data: bytes) -> str:
    """按 utf-8-sig 解码（与现有 OB XML 一致）并校验可解析。"""
    text = data.decode("utf-8-sig")
    ET.fromstring(text)
    return text


def _tag_text(text: str, tag: str) -> str:
    """提取无 namespace 的简单元素文本（<Name> / <Number> / <InstanceOfName>）。"""
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", text)
    assert m, f"缺 <{tag}>"
    return m.group(1)


def _callinfo_component(text: str) -> tuple[str, str]:
    """从 Call 网络 OB XML 提取 CallInfo.Name / Component.Name。"""
    ci = re.search(r'<CallInfo Name="([^"]+)" BlockType="FB">', text)
    comp = re.search(r'<Component Name="([^"]+)" />', text)
    assert ci and comp, "Call 网络 OB 应含 CallInfo / Component"
    return ci.group(1), comp.group(1)


def _minimal_delivery(call_db: str) -> dict:
    """最小离线 delivery：仅一个带 call_db 的 OB，无对应 FB/DB 条目。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr(
            "blocks/X_Main.scl",
            'FUNCTION_BLOCK "X_Main"\nBEGIN\n  "' + call_db + '"();\nEND_FUNCTION_BLOCK\n',
        )
    return {
        "zip_bytes": buf.getvalue(),
        "blocks_manifest": [
            {
                "name": "X_Main",
                "block_type": "OB",
                "number": 1001,
                "folder": "root",
                "path": "blocks/X_Main.scl",
            }
        ],
    }


def _stub_ir() -> SimpleNamespace:
    return SimpleNamespace(project=SimpleNamespace(tia_version="V19"))


# ---------------------------------------------------- 正式包 blocks/ 下 FB/DB 存在


def test_package_zip_contains_fb_and_instance_db_xml(isolated_work: Path) -> None:
    """正式 deliver_tia(package) 的 ZIP 含 xml_supplement/blocks/*.xml，
    且与 result / manifest.json 的 generated_blocks 对齐（blocks_manifest 有对应条目时）。"""
    _, result = _deliver("x-zip-blocks")
    zf = _zip(result)
    names = set(zf.namelist())
    block_paths = sorted(
        n for n in names
        if n.startswith("xml_supplement/blocks/") and n.endswith(".xml")
    )
    assert block_paths, "正式包应产出被引用的 FB / 实例 DB 块 XML"

    generated = result["generated_blocks"]
    assert {b["path"] for b in generated} == set(block_paths)
    assert {b["type"] for b in generated} == {"FB", "InstanceDB"}
    manifest = json.loads(zf.read("xml_supplement/manifest.json").decode("utf-8"))
    assert {b["path"] for b in manifest["generated_blocks"]} == set(block_paths)
    for path in block_paths:
        text = _decode_xml(zf.read(path))
        assert "<Name>" in text and "<Number>" in text
        assert "<Culture>zh-CN</Culture>" in text


# ---------------------------------------------------- CallInfo / Component 逐字一致


def test_call_network_names_match_package_fb_db_names(isolated_work: Path) -> None:
    """每个带 call_db 的 OB：CallInfo.Name == 包内 FB <Name>、Component.Name ==
    包内 DB <Name>，且按产品通道约定 call_fb = re.sub(r'_DB$', '', call_db)。"""
    _, result = _deliver("x-ref-names")
    zf = _zip(result)
    fb_names = {
        b["name"] for b in result["generated_blocks"] if b["type"] == "FB"
    }
    db_names = {
        b["name"] for b in result["generated_blocks"] if b["type"] == "InstanceDB"
    }
    checked = 0
    for ob in result["generated_obs"]:
        if not ob["call_db"]:
            continue
        call_fb = re.sub(r"_DB$", "", ob["call_db"])
        ci, comp = _callinfo_component(zf.read(ob["path"]).decode("utf-8-sig"))
        assert ci == call_fb
        assert comp == ob["call_db"]
        assert ci in fb_names
        assert comp in db_names
        # 逐字一致：包内 FB/DB XML 的 <Name> 与 CallInfo / Component 同名
        fb_xml = _decode_xml(zf.read(f"xml_supplement/blocks/{ci}.xml"))
        db_xml = _decode_xml(zf.read(f"xml_supplement/blocks/{comp}.xml"))
        assert _tag_text(fb_xml, "Name") == ci
        assert _tag_text(db_xml, "Name") == comp
        checked += 1
    assert checked >= 1, "参考会话至少有一个 Call 网络 OB"


def test_instance_db_links_back_to_fb(isolated_work: Path) -> None:
    """实例 DB 根为 SW.Blocks.InstanceDB，InstanceOfName == 包内 FB <Name>。"""
    _, result = _deliver("x-inst-db")
    zf = _zip(result)
    fbs = {b["name"]: b for b in result["generated_blocks"] if b["type"] == "FB"}
    dbs = [b for b in result["generated_blocks"] if b["type"] == "InstanceDB"]
    assert dbs
    for db in dbs:
        text = _decode_xml(zf.read(db["path"]))
        assert '<SW.Blocks.InstanceDB ID="0">' in text
        assert "SW.Blocks.GlobalDB" not in text
        assert "<InstanceOfType>FB</InstanceOfType>" in text
        iof = _tag_text(text, "InstanceOfName")
        fb_name = db["instance_of_fb"]
        assert fb_name in fbs
        fb_text = _decode_xml(zf.read(fbs[fb_name]["path"]))
        assert iof == fb_name == _tag_text(fb_text, "Name")


# ---------------------------------------------------- import_order / 自洽 / 诚实标注


def test_import_order_fb_db_then_ob_and_self_consistent(isolated_work: Path) -> None:
    """import_order 严格 FB → DB → OB（FB/DB 开头、OB 在后），且两处 manifest
    组装（result 回执 + xml_supplement/manifest.json）都同步了增量键。"""
    _, result = _deliver("x-order")
    zf = _zip(result)
    manifest = json.loads(zf.read("xml_supplement/manifest.json").decode("utf-8"))
    for src in (result, manifest):
        assert src["references_self_consistent"] is True
        assert src["generated_blocks"]
        assert src["skipped_blocks"] == []
        assert src["import_order"] == result["import_order"]
        for key in ("generated_blocks", "skipped_blocks", "import_order",
                    "references_self_consistent"):
            assert key in src

    order = result["import_order"]
    fb_paths = {
        b["path"] for b in result["generated_blocks"] if b["type"] == "FB"
    }
    db_paths = {
        b["path"] for b in result["generated_blocks"] if b["type"] == "InstanceDB"
    }
    first_ob = next(
        (i for i, p in enumerate(order) if p.startswith("xml_supplement/ob/")),
        None,
    )
    assert first_ob is not None and first_ob > 0
    assert all(p in fb_paths | db_paths for p in order[:first_ob])
    assert all(p.startswith("xml_supplement/ob/") for p in order[first_ob:])
    # FB 全部排在 DB 之前（DB 的 InstanceOfName 依赖 FB）
    positions = {p: i for i, p in enumerate(order)}
    assert max(positions[p] for p in fb_paths) < min(positions[p] for p in db_paths)
    # import_order 完整覆盖全部块 + 全部生成 OB
    assert set(order) == (fb_paths | db_paths) | {
        o["path"] for o in result["generated_obs"]
    }


def test_manifest_keeps_honest_flags(isolated_work: Path) -> None:
    """诚实口径：manifest.json 保留 xml_package_unverified / pending_real_machine
    为 True，pending_reason / note 写明独立包已验证但正式包尚未单独真机验证。"""
    _, result = _deliver("x-honest")
    zf = _zip(result)
    manifest = json.loads(zf.read("xml_supplement/manifest.json").decode("utf-8"))
    assert manifest["xml_package_unverified"] is True
    assert manifest["pending_real_machine"] is True
    combined = manifest["pending_reason"] + manifest["note"]
    assert "evidence/uc04_full_package_real.json" in combined
    assert "尚未单独真机验证" in combined
    assert "不宣称" in manifest["note"]
    # 禁止宣称正式包已真机通过
    assert "正式产品通道产出的本包已" not in combined
    # receipt（另一条交付路径）同样保留诚实标志
    assert result["xml_package_unverified"] is True
    assert result["pending_real_machine"] is True


# ---------------------------------------------------- 真实编号 / 去重 / sha256


def test_generated_blocks_use_real_numbers_and_dedup(isolated_work: Path) -> None:
    """generated_blocks 编号取自 blocks_manifest 真实条目（不虚构）、按 name 去重
    （同 DB 被多个 OB 引用只生成一次）、sha256 可复算、<Name>/<Number> 与清单一致。"""
    session, result = _deliver("x-real-num")
    zf = _zip(result)
    manifest_numbers = {
        str(e["name"]): int(e["number"])
        for e in session.last_delivery["blocks_manifest"]
        if str(e.get("block_type") or "").upper() in {"FB", "DB"}
    }
    names = [b["name"] for b in result["generated_blocks"]]
    assert len(names) == len(set(names)), "同一 FB/DB 被多个 OB 引用应只生成一次"
    for b in result["generated_blocks"]:
        assert b["number"] == manifest_numbers[b["name"]], "不得虚构块编号"
        data = zf.read(b["path"])
        assert b["sha256"] == "sha256:" + hashlib.sha256(data).hexdigest()
        text = _decode_xml(data)
        assert _tag_text(text, "Name") == b["name"]
        assert int(_tag_text(text, "Number")) == b["number"]
        assert len(b["referenced_by_obs"]) >= 1
    # 参考会话确有 DB 被 2 个 OB 引用，验证去重口径
    assert any(len(b["referenced_by_obs"]) >= 2 for b in result["generated_blocks"])


# ---------------------------------------------------- 缺条目 / 非 _DB 后缀：不虚构


def test_missing_fb_db_entries_are_skipped_not_fabricated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blocks_manifest 缺对应 FB/DB 条目 → 不虚构编号、不生成假块、
    skipped_blocks 有原因、references_self_consistent=False。"""
    monkeypatch.setattr(tia_delivery, "expected_ob_numbers", lambda ir: {"x": 1001})
    supp = tia_delivery.build_xml_supplement(
        _minimal_delivery("X_CallUnit_DB"), _stub_ir()  # type: ignore[arg-type]
    )
    assert supp["generated_blocks"] == []
    assert supp["skipped_blocks"], "缺条目必须留痕"
    assert any(
        "blocks_manifest 无对应" in s["reason"] and "不虚构" in s["reason"]
        for s in supp["skipped_blocks"]
    )
    assert not any(
        k.startswith("xml_supplement/blocks/") for k in supp["supplement_files"]
    ), "不得生成假块 XML"
    assert supp["references_self_consistent"] is False


def test_call_db_without_db_suffix_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """call_db 不以 _DB 结尾 → 按产品通道命名约定不猜 FB 名、跳过并留痕。"""
    monkeypatch.setattr(tia_delivery, "expected_ob_numbers", lambda ir: {"x": 1001})
    supp = tia_delivery.build_xml_supplement(
        _minimal_delivery("X_InstDB"), _stub_ir()  # type: ignore[arg-type]
    )
    assert supp["generated_blocks"] == []
    assert supp["skipped_blocks"], "非 _DB 后缀必须留痕"
    assert any("不以 _DB" in s["reason"] for s in supp["skipped_blocks"])
    assert not any(
        k.startswith("xml_supplement/blocks/") for k in supp["supplement_files"]
    )
    assert supp["references_self_consistent"] is False
