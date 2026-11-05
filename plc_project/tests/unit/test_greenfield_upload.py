"""T02 · 只读冻结契约 + 上传 fail-closed 回归（§3.4 / §7 T02 验收点）。

覆盖：正常夹具解析（嵌套点路径 / Array 上下界 / 初值 / 注释 / scl_body）、
坏夹具整批原子拒绝 + 逐条明细、白名单与九项上限、底层零 diff、
契约六类物理不可变拦截、回执未确认不冻结（Q3）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gateway.app.services.plc.greenfield_upload import (
    DB_ENCODINGS,
    DB_MAX_FILE_BYTES,
    DB_MAX_MEMBERS_PER_UNIT,
    DB_MAX_STRUCT_DEPTH,
    IO_ENCODINGS,
    IO_MAX_FILE_BYTES,
    IO_MAX_ROWS,
    LIMITS,
    MAX_BATCH_BYTES,
    MAX_FILES,
    UPLOAD_ERROR_CODES,
    UploadItem,
    parse_upload_batch,
    strict_validate_db,
    strict_validate_io,
)
from plc_engine.af.greenfield_contract import (
    CompatContract,
    ContractMutation,
    IMMUTABLE_CATEGORIES,
    IMMUTABLE_FIELD_MAP,
    ParseReceipt,
    assert_immutable,
    confirm_receipt,
    contract_sha256,
    freeze_contract,
)
from plc_engine.af.greenfield_ports import ContractViolationError, GateLockedError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "greenfield"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _item(name: str) -> UploadItem:
    """从夹具目录读取一个上传项（保留原始字节与编码）。"""
    return UploadItem(filename=name, data=(FIXTURES / name).read_bytes())


def _codes(receipt: ParseReceipt) -> list[str]:
    return [e.code for e in receipt.errors]


# ---------------------------------------------------------------------------
# 正常夹具
# ---------------------------------------------------------------------------

def test_good_csv_gbk_and_chinese_header_variants() -> None:
    entries, errors = strict_validate_io(_item("PLCTags_sample.csv"))
    assert errors == []
    assert len(entries) == 5
    assert entries[0]["name"] == "I0_0_PartPresent"
    assert entries[0]["path"] == "PLC Tags/Default"
    assert entries[0]["data_type"] == "Bool"
    assert entries[0]["logical_address"] == "%I0.0"
    assert entries[0]["comment"] == "工件到位"
    assert entries[-1]["logical_address"] == "%IW64"
    assert IO_ENCODINGS == ("utf-8-sig", "gbk")


def test_good_xlsx_first_matching_sheet() -> None:
    entries, errors = strict_validate_io(_item("PLCTags_sample.xlsx"))
    assert errors == []
    assert len(entries) == 5
    assert entries[2]["name"] == "Q0_0_Conveyor"


def test_good_db_scl_nested_paths_array_initial_comment_body() -> None:
    structs, errors = strict_validate_db(_item("DB_sample.scl"))
    assert errors == []
    assert len(structs) == 1
    db = structs[0]
    assert db["name"] == "DB1900_Communication_PC"
    assert db["optimized_access"] == "FALSE"
    names = [m["name"] for m in db["members"]]
    assert "Send.Heart" in names, "嵌套 STRUCT 应展成点路径"
    assert "Recv.Values" in names
    arrays = {m["name"]: m["data_type"] for m in db["members"] if "Array[" in m["data_type"]}
    assert "Array[0..21] of Byte" in arrays.values()
    assert "Array[1..8] of Real" in arrays.values()
    assert db["initial_assignments"]["Send.Heart"] == "TRUE"
    assert any(m["comment"] == "心跳" for m in db["members"])
    assert "DATA_BLOCK" in db["scl_body"] and "END_DATA_BLOCK" in db["scl_body"]
    assert all(isinstance(m["offset"], int) for m in db["members"])
    assert DB_ENCODINGS == ("utf-8-sig", "utf-8", "gb18030")


def test_good_batch_is_parsed_but_not_confirmed() -> None:
    receipt = parse_upload_batch(
        [_item("PLCTags_sample.csv"), _item("DB_sample.scl")]
    )
    assert receipt.status == "parsed"
    assert receipt.items_accepted == 5 + 5
    assert receipt.items_total == receipt.items_accepted
    assert receipt.errors == []
    assert receipt.contract_draft_hash.startswith("sha256:")
    assert receipt.user_confirmed is False
    assert len(receipt.receipt_id) == len("RCP_") + 12
    assert "DB 成员偏移" in " ".join(receipt.draft["compat_notes"])
    assert receipt.draft["ob_entries"] == []
    assert receipt.draft["safety_entries"] == []


def test_batch_is_deterministic() -> None:
    items = [_item("PLCTags_sample.csv"), _item("DB_sample.scl")]
    a, b = parse_upload_batch(items), parse_upload_batch(items)
    assert a.receipt_id == b.receipt_id
    assert a.contract_draft_hash == b.contract_draft_hash
    assert a.to_dict() == b.to_dict()


def test_pasted_text_is_supported() -> None:
    pasted = UploadItem(
        text="Name,Data Type,Logical Address,Comment\nI0_9_Test,Bool,%I0.9,粘贴测试\n"
    )
    receipt = parse_upload_batch([pasted])
    assert receipt.status == "parsed"
    assert receipt.items_accepted == 1
    scl_paste = UploadItem(text=(FIXTURES / "DB_sample.scl").read_text(encoding="utf-8-sig"))
    assert parse_upload_batch([scl_paste]).status == "parsed"


# ---------------------------------------------------------------------------
# 坏夹具：整批原子拒绝
# ---------------------------------------------------------------------------

def test_bad_csv_rejects_whole_batch_with_itemized_errors() -> None:
    receipt = parse_upload_batch([_item("PLCTags_bad.csv"), _item("DB_sample.scl")])
    assert receipt.status == "rejected"
    assert receipt.items_accepted == 0
    assert receipt.contract_draft_hash == ""
    assert receipt.draft == {}
    assert receipt.user_confirmed is False
    assert len(receipt.errors) >= 4
    for error in receipt.errors:
        detail = error.to_dict()
        assert set(detail) == {"file", "row", "column", "code", "message"}
        assert detail["file"]
        assert detail["code"].startswith("GF_UPLOAD_")
        assert detail["message"]
    codes = _codes(receipt)
    assert "GF_UPLOAD_IO_ADDR_INVALID" in codes
    assert "GF_UPLOAD_IO_NAME_DUPLICATE" in codes
    assert "GF_UPLOAD_IO_ROW_DROPPED" in codes
    assert "GF_UPLOAD_IO_ADDR_DUPLICATE" in codes


def test_rejected_receipt_cannot_freeze_contract() -> None:
    receipt = parse_upload_batch([_item("PLCTags_bad.csv")])
    with pytest.raises(GateLockedError):
        freeze_contract(receipt)
    assert confirm_receipt.__name__ == "confirm_receipt"


# ---------------------------------------------------------------------------
# 上限逐项断言
# ---------------------------------------------------------------------------

def test_limits_constants() -> None:
    assert LIMITS["io_max_file_bytes"] == IO_MAX_FILE_BYTES == 5 * 1024 * 1024
    assert LIMITS["io_max_rows"] == IO_MAX_ROWS == 5000
    assert LIMITS["db_max_file_bytes"] == DB_MAX_FILE_BYTES == 2 * 1024 * 1024
    assert LIMITS["db_max_units"] == 50
    assert LIMITS["db_max_members_per_unit"] == DB_MAX_MEMBERS_PER_UNIT == 2000
    assert LIMITS["db_max_struct_depth"] == DB_MAX_STRUCT_DEPTH == 8
    assert LIMITS["max_files"] == MAX_FILES == 5
    assert LIMITS["max_batch_bytes"] == MAX_BATCH_BYTES == 10 * 1024 * 1024
    assert LIMITS["max_total_io_entries"] == 5000
    assert LIMITS["max_total_db_members"] == 20000
    assert "GF_UPLOAD_ENCODING_FALLBACK" in UPLOAD_ERROR_CODES


def test_limit_batch_file_count_and_size() -> None:
    items = [_item("PLCTags_sample.csv") for _ in range(MAX_FILES + 1)]
    assert "GF_UPLOAD_BATCH_TOO_MANY_FILES" in _codes(parse_upload_batch(items))
    huge = UploadItem(filename="huge.csv", data=b"x" * (MAX_BATCH_BYTES + 1))
    codes = _codes(parse_upload_batch([huge]))
    assert "GF_UPLOAD_BATCH_TOO_LARGE" in codes
    assert "GF_UPLOAD_FILE_TOO_LARGE" in codes


def test_limit_single_file_size_and_row_count() -> None:
    too_big = UploadItem(filename="big.csv", data=b"x" * (IO_MAX_FILE_BYTES + 1))
    assert "GF_UPLOAD_FILE_TOO_LARGE" in [
        e.code for e in strict_validate_io(too_big)[1]
    ]
    rows = ["Name,Data Type,Logical Address"] + [
        f"N{i},Bool,%I0.{i % 8}" for i in range(IO_MAX_ROWS + 1)
    ]
    many_rows = UploadItem(filename="rows.csv", data=("\n".join(rows)).encode("utf-8"))
    _, errors = strict_validate_io(many_rows)
    assert "GF_UPLOAD_IO_ROW_LIMIT" in [e.code for e in errors]


def test_limit_encoding_fallback_and_extension() -> None:
    undecodable = UploadItem(filename="bad.csv", data=b"\xff\xff\xff\xff")
    assert "GF_UPLOAD_ENCODING_FALLBACK" in [
        e.code for e in strict_validate_io(undecodable)[1]
    ]
    assert "GF_UPLOAD_ENCODING_FALLBACK" in [
        e.code for e in strict_validate_db(
            UploadItem(filename="bad.scl", data=b"\xff\xff\xff\xff")
        )[1]
    ]
    assert "GF_UPLOAD_EXT_UNSUPPORTED" in [
        e.code for e in strict_validate_io(UploadItem(filename="tags.xml", data=b"x"))[1]
    ]
    assert "GF_UPLOAD_EXT_UNSUPPORTED" in [
        e.code for e in strict_validate_db(UploadItem(filename="db.xml", data=b"x"))[1]
    ]


def test_limit_db_members_struct_depth_and_db_count() -> None:
    members = "\n".join(f"      M{i} : Bool;" for i in range(DB_MAX_MEMBERS_PER_UNIT + 1))
    big_db = f'DATA_BLOCK "DB_BIG"\n   STRUCT\n{members}\n   END_STRUCT;\nBEGIN\nEND_DATA_BLOCK\n'
    _, errors = strict_validate_db(UploadItem(filename="big.scl", data=big_db.encode("utf-8")))
    assert "GF_UPLOAD_DB_MEMBER_LIMIT" in [e.code for e in errors]

    nested = 'DATA_BLOCK "DB_DEEP"\n   STRUCT\n'
    for i in range(DB_MAX_STRUCT_DEPTH + 1):
        nested += f"      L{i} : Struct\n"
    nested += "      Leaf : Bool;\n"
    for _ in range(DB_MAX_STRUCT_DEPTH + 1):
        nested += "      END_STRUCT;\n"
    nested += "   END_STRUCT;\nBEGIN\nEND_DATA_BLOCK\n"
    assert "GF_UPLOAD_DB_STRUCT_DEPTH" in [
        e.code for e in strict_validate_db(
            UploadItem(filename="deep.scl", data=nested.encode("utf-8"))
        )[1]
    ]

    many_dbs = "\n".join(
        f'DATA_BLOCK "DB{i}"\n   STRUCT\n      V : Bool;\n   END_STRUCT;\nBEGIN\nEND_DATA_BLOCK'
        for i in range(51)
    )
    assert "GF_UPLOAD_DB_UNIT_LIMIT" in [
        e.code for e in strict_validate_db(
            UploadItem(filename="many.scl", data=many_dbs.encode("utf-8"))
        )[1]
    ]


def test_limit_array_bounds_and_begin_expression() -> None:
    bad_array = (
        'DATA_BLOCK "DB_ARR"\n   STRUCT\n'
        "      A : Array[5..3] of Byte;\n"
        "      B : Array[0..70000] of Byte;\n"
        "   END_STRUCT;\nBEGIN\nEND_DATA_BLOCK\n"
    )
    codes = [
        e.code for e in strict_validate_db(
            UploadItem(filename="arr.scl", data=bad_array.encode("utf-8"))
        )[1]
    ]
    assert codes.count("GF_UPLOAD_DB_ARRAY_BOUNDS") >= 2

    expression = (
        'DATA_BLOCK "DB_EXPR"\n   STRUCT\n      A : Bool;\n   END_STRUCT;\n'
        "BEGIN\n   A := SomeFunc(1) + 2;\nEND_DATA_BLOCK\n"
    )
    assert "GF_UPLOAD_DB_INITIAL_EXPRESSION" in [
        e.code for e in strict_validate_db(
            UploadItem(filename="expr.scl", data=expression.encode("utf-8"))
        )[1]
    ]


def test_cross_file_duplicates_and_db_name_clash_reject_batch() -> None:
    codes = _codes(parse_upload_batch([
        _item("PLCTags_sample.csv"),
        UploadItem(filename="PLCTags_copy.csv", data=(FIXTURES / "PLCTags_sample.csv").read_bytes()),
    ]))
    assert "GF_UPLOAD_IO_NAME_DUPLICATE" in codes
    assert "GF_UPLOAD_IO_ADDR_DUPLICATE" in codes

    two_same = (
        'DATA_BLOCK "DB_SAME"\n   STRUCT\n      A : Bool;\n   END_STRUCT;\nBEGIN\nEND_DATA_BLOCK\n'
        'DATA_BLOCK "DB_SAME"\n   STRUCT\n      B : Bool;\n   END_STRUCT;\nBEGIN\nEND_DATA_BLOCK\n'
    )
    assert "GF_UPLOAD_DB_NAME_DUPLICATE" in [
        e.code for e in strict_validate_db(
            UploadItem(filename="dup.scl", data=two_same.encode("utf-8"))
        )[1]
    ]


def test_empty_batch_is_rejected() -> None:
    receipt = parse_upload_batch([])
    assert receipt.status == "rejected"
    assert "GF_UPLOAD_EMPTY_BATCH" in _codes(receipt)


# ---------------------------------------------------------------------------
# 底层零 diff + 契约不可变 + Q3
# ---------------------------------------------------------------------------

def test_underlying_importers_have_zero_diff() -> None:
    baseline = json.loads((FIXTURES / "legacy_baseline.json").read_text(encoding="utf-8"))
    for rel in (
        "gateway/app/services/plc/io_import.py",
        "gateway/app/services/plc/db_import.py",
    ):
        current = "sha256:" + hashlib.sha256((PROJECT_ROOT / rel).read_bytes()).hexdigest()
        assert current == baseline["files"][rel], f"{rel} 必须零 diff"


def test_contract_is_stable_and_reproducible() -> None:
    receipt = parse_upload_batch([_item("PLCTags_sample.csv"), _item("DB_sample.scl")])
    confirm_receipt(receipt, by="tester")
    contract = freeze_contract(receipt, frozen_at="2026-11-04T02:30:00Z")
    assert contract.immutable is True
    assert contract.contract_sha.startswith("sha256:")
    assert contract_sha256(contract) == contract.contract_sha
    assert contract.contract_id.startswith("CC_")
    restored = CompatContract.from_dict(contract.to_dict())
    assert restored.contract_sha == contract.contract_sha
    assert restored.summary()["counts"]["io_entries"] == 5
    assert restored.summary()["counts"]["db_members"] == 5
    contract.assert_immutable()  # 完整性校验通过


def test_six_immutable_categories_are_intercepted() -> None:
    receipt = parse_upload_batch([_item("PLCTags_sample.csv"), _item("DB_sample.scl")])
    confirm_receipt(receipt, by="tester")
    contract = freeze_contract(receipt, frozen_at="2026-11-04T02:30:00Z")
    assert len(IMMUTABLE_CATEGORIES) == 6
    for category in IMMUTABLE_CATEGORIES:
        field = IMMUTABLE_FIELD_MAP[category][0]
        with pytest.raises(ContractViolationError) as caught:
            assert_immutable(contract, ContractMutation(category, field, "ILLEGAL_WRITE"))
        assert caught.value.code == "GF_CONTRACT_IMMUTABLE"
        assert caught.value.details["category"] == category
    # 直接字段赋值同样被拦截
    with pytest.raises(ContractViolationError):
        contract.io_entries = ()
    with pytest.raises(ContractViolationError):
        contract.contract_sha = "sha256:forged"
    ref = contract.ref("IO_TAG", "%I0.0")
    assert ref.immutable is True
    assert ref.contract_sha == contract.contract_sha


def test_receipt_must_be_user_confirmed_before_freeze() -> None:
    receipt = parse_upload_batch([_item("PLCTags_sample.csv"), _item("DB_sample.scl")])
    with pytest.raises(GateLockedError) as caught:
        freeze_contract(receipt)
    assert caught.value.code == "GF_GATE_NOT_CONFIRMED"
    assert receipt.user_confirmed is False
    confirm_receipt(receipt, by="engineer")
    assert receipt.user_confirmed is True
    assert freeze_contract(receipt).immutable is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
