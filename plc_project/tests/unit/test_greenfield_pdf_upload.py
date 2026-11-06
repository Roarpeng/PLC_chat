"""T-PDF · TIA Portal 打印版 PDF 导入与 S7 标准访问字节.位偏移校验回归。"""
from __future__ import annotations

from pathlib import Path

from gateway.app.services.plc.greenfield_upload import (
    UploadItem,
    parse_upload_batch,
    strict_validate_db,
    strict_validate_io,
)
from plc_engine.af.greenfield_contract import confirm_receipt, freeze_contract
from plc_engine.af.std_layout import PdfDbRow, verify_and_build_std_db

PDF_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "greenfield" / "legacy_pdf"


def _pdf_item(name: str) -> UploadItem:
    return UploadItem(filename=name, data=(PDF_DIR / name).read_bytes())


def test_plc_io_pdf_extracts_113_tags_exact() -> None:
    entries, errors = strict_validate_io(_pdf_item("PLC_IO.pdf"))
    assert errors == []
    assert len(entries) == 113
    inputs = [e for e in entries if e["logical_address"].startswith("%I")]
    outputs = [e for e in entries if e["logical_address"].startswith("%Q")]
    assert len(inputs) == 64
    assert len(outputs) == 49
    int_tags = {e["name"]: e["logical_address"] for e in entries if e["data_type"] == "Int"}
    assert int_tags == {"IW10": "%IW10", "QW10": "%QW10", "IW12": "%IW12"}


def test_kuka_and_pc_db_pdfs_verify_standard_access_offsets() -> None:
    kuka_structs, kuka_errors = strict_validate_db(_pdf_item("KUKA_DATA.pdf"))
    assert kuka_errors == []
    assert len(kuka_structs) == 1
    kuka = kuka_structs[0]
    assert kuka["name"] == "DB720_KuKa_MainCtrl"
    assert kuka["optimized_access"] == "FALSE"
    kuka_by_name = {m["name"]: m for m in kuka["members"]}
    assert "CmdOut.di_ChgGrp_Ack" in kuka_by_name
    assert kuka_by_name["StatusIn.SP"]["data_type"] == "Array[1..33] of Byte"
    assert kuka_by_name["StatusIn.SP"]["offset"] == 78
    assert kuka_by_name["EdgeDetc.Pulse"]["data_type"] == "Array[0..15] of Bool"
    assert kuka_by_name["EdgeDetc.Pulse"]["offset"] == 284

    pc_structs, pc_errors = strict_validate_db(_pdf_item("PC_DATA.pdf"))
    assert pc_errors == []
    assert len(pc_structs) == 1
    pc = pc_structs[0]
    assert pc["name"] == "DB1900_Communication_PC"
    assert pc["optimized_access"] == "FALSE"
    pc_by_name = {m["name"]: m for m in pc["members"]}
    assert pc_by_name["Send.Spare"]["data_type"] == "Array[0..21] of Byte"
    assert pc_by_name["Send.Spare"]["offset"] == 58
    assert pc_by_name["Para.Auto_Force"]["data_type"] == "Array[1..200] of Real"
    assert pc_by_name["Para.Auto_Force"]["offset"] == 226


def test_batch_three_pdfs_parses_and_freezes_contract() -> None:
    receipt = parse_upload_batch(
        [
            _pdf_item("PLC_IO.pdf"),
            _pdf_item("KUKA_DATA.pdf"),
            _pdf_item("PC_DATA.pdf"),
        ]
    )
    assert receipt.status == "parsed", [e.to_dict() for e in receipt.errors]
    assert len(receipt.draft["io_entries"]) == 113
    assert len(receipt.draft["db_structs"]) == 2
    confirm_receipt(receipt, by="engineer")
    contract = freeze_contract(receipt, frozen_at="2026-11-05T08:00:00Z")
    assert contract.immutable is True
    assert len(contract.io_entries) == 113
    assert len(contract.db_structs) == 2


def test_corrupt_pdf_and_offset_mismatch_fail_closed() -> None:
    bad_pdf = UploadItem(filename="corrupt.pdf", data=b"not a pdf")
    receipt = parse_upload_batch([bad_pdf])
    assert receipt.status == "rejected"
    assert receipt.items_accepted == 0
    assert any(e.code == "GF_UPLOAD_PDF_PARSE_FAILED" for e in receipt.errors)

    layout = verify_and_build_std_db(
        "DB_BadOffset",
        100,
        [
            PdfDbRow(level=0, name="Header", data_type="Struct", pdf_offset="0.0"),
            PdfDbRow(level=1, name="Flag", data_type="Bool", pdf_offset="0.0"),
            PdfDbRow(level=1, name="Count", data_type="Int", pdf_offset="1.0"),  # 应为 2.0（偶数字节对齐）
        ],
    )
    assert len(layout.mismatches) == 1
    assert layout.mismatches[0].expected_offset == "2.0"
    assert layout.mismatches[0].actual_offset == "1.0"
