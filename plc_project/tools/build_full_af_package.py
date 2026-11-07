"""Agent U · 批次 4 · UC-04 完整 AF 包离线构造（Call 网络 OB + FB + 全局实例 DB）。

批次 3 的完整 AF 包只含 5 个 OB，缺少被引用的 FB 块与实例 DB 块，且
``_render_call_network`` 从 ``call_db`` 反推 FB 名（``xxx_DB`` → ``xxx``）——
真实 V19 先例是 FB / DB **独立命名**（``FB1000_StdSignal`` / ``DB1000_StdSignal``），
故批次 3 的 Call 网络 OB 导入即失败。本脚本：

- 用修复后的 ``_render_ob_xml(call_fb=...)`` 生成 Call 网络 OB；
- 用 ``render_fb_xml`` / ``render_instance_db_xml`` 生成被引用的 FB / 实例 DB 块；
- 输出自洽的完整包：``folders.json`` + FB XML + 实例 DB XML + 多个 OB XML +
  ``manifest.json``（逐文件 sha256 + 引用关系 + ``import_order`` + 诚实标注）。

**诚实边界**：本脚本纯离线构造，不连真机 / 不启动 SessionServer / 不跑 TIA CLI /
不占用端口。真机导入编译由阶段 B 的 Agent W 在临时副本上验证。
**不宣称 UC-04 通过 / 完整包编译零错误 / L2 通过**；``xml_package_unverified``
保持 ``True``，由主 agent 收口按 W 的真实结果决定，任何 agent 不得擅自改 False。

CLI：
    python tools/build_full_af_package.py --out <dir> [--tia-version V19]

``--out`` 为必填（默认不写产品目录）；同样参数两次生成的 ``manifest.json``
字节级一致（固定 ``<Created>`` + 确定性 JSON 序列化），可复现。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.app.services.plc.tia_delivery import (  # noqa: E402
    _render_ob_xml,
    render_fb_xml,
    render_instance_db_xml,
)

#: 与真实 V19 导出先例同构的**独立命名**（FB1000_… / DB1000_…），
#: 刻意不是 ``xxx_DB`` → ``xxx`` 关系，用于复现批次 3 的失败输入并验证新路径。
DEFAULT_FB_NAME = "FB1000_StdSignal"
DEFAULT_DB_NAME = "DB1000_StdSignal"
DEFAULT_FB_NUMBER = 1000
DEFAULT_DB_NUMBER = 1000
DEFAULT_TIA_VERSION = "V19"

#: 固定 ``<Created>`` 时间戳：去掉真实时间，保证逐文件 sha256 / manifest 字节级可复现。
FIXED_CREATED = "2000-01-01T00:00:00Z"

#: 与 K 修复后真机导入成功的自产 OB XML 编码一致（带 BOM）。
XML_ENCODING = "utf-8-sig"


def default_ob_entries(
    fb_name: str = DEFAULT_FB_NAME,
    db_name: str = DEFAULT_DB_NAME,
) -> list[dict[str, Any]]:
    """默认 OB 清单：多个 OB，至少一个 Call 网络 OB 且引用包内真实 FB/DB。

    OB 号沿用批次 3 包级探针的取值（不虚构地址）；空网络 OB 不传 call_db /
    call_fb。``ob_entries`` 为空时本函数不会被调用，调用方显式传 ``[]`` 即
    不生成任何 OB（不虚构 OB 条目）。
    """
    return [
        {
            "name": "GF_U1_Startup",
            "number": 1000,
            "secondary_type": "Startup",
            "call_db": "",
            "call_fb": "",
            "folder": "AF_Unit_01",
        },
        {
            "name": "GF_U1_Main",
            "number": 1001,
            "secondary_type": "ProgramCycle",
            "call_db": "",
            "call_fb": "",
            "folder": "AF_Unit_01",
        },
        {
            "name": "GF_U1EM1_CallOB",
            "number": 1012,
            "secondary_type": "ProgramCycle",
            "call_db": db_name,
            "call_fb": fb_name,
            "folder": "AF_Unit_01/AF_EM_01",
        },
    ]


def _default_folders(
    fb_name: str,
    db_name: str,
    ob_entries: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """文档化文件夹清单：供 ``create-block-group`` Openness API 消费。"""
    folders: dict[str, list[str]] = {"root": [fb_name, db_name]}
    for entry in ob_entries:
        folders.setdefault(str(entry.get("folder") or "root"), []).append(
            str(entry["name"])
        )
    return folders


def _ob_entry_record(entry: dict[str, Any]) -> dict[str, Any]:
    """回显 OB 条目（固定键，确定性序列化，不虚构字段）。"""
    return {
        "name": str(entry["name"]),
        "number": int(entry["number"]),
        "secondary_type": str(entry["secondary_type"]),
        "call_db": str(entry.get("call_db") or ""),
        "call_fb": str(entry.get("call_fb") or ""),
    }


def render_package(
    *,
    tia_version: str = DEFAULT_TIA_VERSION,
    fb_name: str = DEFAULT_FB_NAME,
    fb_number: int = DEFAULT_FB_NUMBER,
    db_name: str = DEFAULT_DB_NAME,
    db_number: int = DEFAULT_DB_NUMBER,
    ob_entries: list[dict[str, Any]] | None = None,
    folders: dict[str, list[str]] | None = None,
) -> dict[str, bytes]:
    """纯函数：返回完整包全部文件 ``{相对路径: 字节}``（不写盘，供单测/复现）。

    ``ob_entries=None`` → 用 ``default_ob_entries()``；显式传 ``[]`` → 不生成
    任何 OB。引用关系 **fail-closed**：任何含 ``call_db`` 的 OB，其
    ``call_fb`` / ``call_db`` 必须逐字等于包内 FB / DB 块名，否则抛
    ``ValueError``，拒绝产出不自洽的包。
    """
    if ob_entries is None:
        ob_entries = default_ob_entries(fb_name, db_name)

    for entry in ob_entries:
        if entry.get("call_db") and (
            entry.get("call_fb") != fb_name or entry["call_db"] != db_name
        ):
            raise ValueError(
                f"OB {entry.get('name')} 的 call_fb/call_db 与包内 FB/DB 名不一致，"
                "拒绝生成引用不自洽的完整 AF 包"
            )

    if folders is None:
        folders = _default_folders(fb_name, db_name, ob_entries)

    fb_path = f"blocks/{fb_name}.xml"
    db_path = f"blocks/{db_name}.xml"
    fb_bytes = render_fb_xml(
        fb_name=fb_name,
        fb_number=fb_number,
        title=f"AF V1.2 {fb_name}",
        tia_version=tia_version,
        created=FIXED_CREATED,
    ).encode(XML_ENCODING)
    db_bytes = render_instance_db_xml(
        db_name=db_name,
        db_number=db_number,
        instance_of_fb=fb_name,
        title=f"AF V1.2 {db_name}",
        tia_version=tia_version,
        created=FIXED_CREATED,
    ).encode(XML_ENCODING)

    files: dict[str, bytes] = {fb_path: fb_bytes, db_path: db_bytes}
    file_kinds: dict[str, str] = {fb_path: "fb", db_path: "instance_db"}
    ob_paths: list[str] = []
    references: list[dict[str, str]] = []

    for entry in ob_entries:
        name = str(entry["name"])
        ob_path = f"ob/{name}.xml"
        files[ob_path] = _render_ob_xml(
            ob_name=name,
            ob_number=int(entry["number"]),
            secondary_type=str(entry["secondary_type"]),
            call_db=str(entry.get("call_db") or ""),
            call_fb=str(entry.get("call_fb") or ""),
            title=f"AF V1.2 {name}",
            tia_version=tia_version,
            created=FIXED_CREATED,
        ).encode(XML_ENCODING)
        file_kinds[ob_path] = "ob"
        ob_paths.append(ob_path)
        if entry.get("call_db"):
            references.append(
                {
                    "ob": name,
                    "ob_xml": ob_path,
                    "call_fb": str(entry["call_fb"]),
                    "call_db": str(entry["call_db"]),
                    "fb_block": fb_name,
                    "db_block": db_name,
                    "fb_xml": fb_path,
                    "db_xml": db_path,
                }
            )

    files["folders.json"] = json.dumps(
        {
            "schema": "gf-uc04-folders-v1",
            "mechanism": "create-block-group Openness API (NOT SW.PlcBlockGroup XML import-xml)",
            "folders": folders,
            "note": (
                "SW.PlcBlockGroup XML 经 import-xml --kind auto|block 真机确证不可导入"
                "（exit=4 / openness_error，见 evidence/uc04_package_probe.json#probe_a）。"
                "文件夹由 create-block-group Openness API 建立（F 已真机验证 ok=true/saved=true）。"
                "本清单是文档化清单、非可 import-xml 的 SimaticML 对象，供该 API 消费。"
            ),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    file_kinds["folders.json"] = "folders"

    import_order = [fb_path, db_path, *ob_paths]
    file_records = [
        {
            "path": path,
            "kind": file_kinds[path],
            "sha256": hashlib.sha256(files[path]).hexdigest(),
            "bytes": len(files[path]),
        }
        for path in sorted(files)
    ]

    manifest: dict[str, Any] = {
        "schema": "gf-uc04-full-af-package-v1",
        "tia_version": tia_version,
        "generator": "tools/build_full_af_package.py",
        "created": FIXED_CREATED,
        "reproducible": True,
        "fb": {
            "name": fb_name,
            "number": fb_number,
            "path": fb_path,
            "sha256": hashlib.sha256(fb_bytes).hexdigest(),
        },
        "db": {
            "name": db_name,
            "number": db_number,
            "instance_of_fb": fb_name,
            "path": db_path,
            "sha256": hashlib.sha256(db_bytes).hexdigest(),
        },
        "ob_entries": [_ob_entry_record(e) for e in ob_entries],
        "generated_ob_count": len(ob_entries),
        "files": file_records,
        "references": references,
        "references_self_consistent": all(
            r["call_fb"] == fb_name
            and r["call_db"] == db_name
            and r["fb_block"] == fb_name
            and r["db_block"] == db_name
            for r in references
        ),
        "import_order": import_order,
        "xml_package_unverified": True,
        "pending_real_machine": True,
        "notes": [
            "本包由 Agent U 纯离线构造（不连真机 / 不启动 SessionServer / 不跑 TIA CLI / 不占用端口）。",
            "真机导入编译由阶段 B 的 Agent W 在 Temp/gf_real_* 临时副本上按 import_order 验证。",
            "folders.json 是文档化清单，SW.PlcBlockGroup XML 不可 import-xml，文件夹须走 create-block-group API。",
            "不宣称 UC-04 通过 / 完整包编译零错误 / L2 通过；离线单测不构成真机证据。",
            "xml_package_unverified 保持 True，由主 agent 收口按 W 真实结果决定，不擅自改 False。",
        ],
    }
    files["manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    return files


def build_package(out_dir: str | Path, **kwargs: Any) -> dict[str, Any]:
    """把完整包写到 ``out_dir`` 并返回解析后的 manifest dict。"""
    files = render_package(**kwargs)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return json.loads(files["manifest.json"].decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="UC-04 完整 AF 包离线构造（Call 网络 OB + FB + 实例 DB），供 W 真机复现"
    )
    parser.add_argument(
        "--out",
        required=True,
        help="输出目录（必填；默认不写产品目录，建议 AppData/Local/Temp/gf_real_* 下）",
    )
    parser.add_argument(
        "--tia-version",
        default=DEFAULT_TIA_VERSION,
        help=f"TIA 版本（默认 {DEFAULT_TIA_VERSION}）",
    )
    args = parser.parse_args(argv)
    manifest = build_package(args.out, tia_version=args.tia_version)
    summary = {
        "out": str(Path(args.out).resolve()),
        "tia_version": manifest["tia_version"],
        "import_order": manifest["import_order"],
        "generated_ob_count": manifest["generated_ob_count"],
        "references": manifest["references"],
        "references_self_consistent": manifest["references_self_consistent"],
        "xml_package_unverified": manifest["xml_package_unverified"],
        "pending_real_machine": manifest["pending_real_machine"],
        "file_count": len(manifest["files"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
