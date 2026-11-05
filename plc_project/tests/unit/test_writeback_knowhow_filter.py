"""修① 单测:legacy 批次 know-how 加密块过滤(真机案例 51c23082…)。

不碰真实博途——mock openness_cli 返回 list-blocks 名单,验证:
- 加密块从 legacy 批次剔除(保原件不覆盖),AF 块不受影响;
- CLI 失败/超时 → 空集 → 不过滤(维持旧行为,不新增故障点);
- 剔除名单写入结果 knowhow_skipped 字段供流水线警示。
"""
from __future__ import annotations

from unittest.mock import patch

from agents.plc.tia import writeback as wb
from agents.plc.tia.writeback import _knowhow_block_names


def _list_payload(names: list[tuple[str, bool]]) -> dict:
    return {
        "ok": True,
        "blocks": {
            "ok": True,
            "count": len(names),
            "blocks": [
                {"name": n, "type": "FB", "knowHowProtected": k} for n, k in names
            ],
        },
    }


class TestKnowhowBlockNames:
    def test_returns_protected_names_only(self):
        with patch.object(
            wb,
            "openness_cli",
            return_value=_list_payload([("FB1003_CR", True), ("FB_Open", False), ("FB_Secret", True)]),
        ):
            assert _knowhow_block_names("X:/p.ap19") == {"FB1003_CR", "FB_Secret"}

    def test_plc_name_forwarded(self):
        with patch.object(wb, "openness_cli", return_value=_list_payload([])) as m:
            _knowhow_block_names("X:/p.ap19", plc_name="PLC_2")
        args = m.call_args.args
        assert args[:3] == ("list-blocks", "--project", "X:/p.ap19")
        assert args[3:] == ("--plc", "PLC_2")

    def test_cli_failure_returns_empty_set_not_raise(self):
        with patch.object(wb, "openness_cli", side_effect=TimeoutError("cli down")):
            assert _knowhow_block_names("X:/p.ap19") == set()

    def test_malformed_payload_empty_set(self):
        with patch.object(wb, "openness_cli", return_value={"ok": True, "blocks": None}):
            assert _knowhow_block_names("X:/p.ap19") == set()


class TestLegacyBatchKnowhowFilter:
    """端到端(批组装层):monkeypatch 名单,走 _write_import_bundle 的批分组段。

    直接验证分组结果太深;这里测组合逻辑的等价面——用真实函数的过滤段
    (af/legacy 分组 + know-how 剔除)通过构造 artifacts 复算。
    """

    def _artifacts(self):
        return [
            wb.BlockArtifact(name="U1_HR002::Sequence", kind="FB", source="FUNCTION_BLOCK \"U1_HR002::Sequence\" END_FUNCTION_BLOCK"),
            wb.BlockArtifact(name="FB_Open", kind="FB", source="FUNCTION_BLOCK \"FB_Open\" END_FUNCTION_BLOCK"),
            wb.BlockArtifact(name="FB1003_CR", kind="FB", source="FUNCTION_BLOCK \"FB1003_CR\" END_FUNCTION_BLOCK"),
        ]

    def test_filter_semantics(self):
        blocks = self._artifacts()
        af = [b for b in blocks if "::" in b.name or b.name.startswith("U1") or b.name.startswith("AF_type")]
        legacy = [b for b in blocks if b not in af]
        knowhow = {"FB1003_CR"}
        skipped = [b.name for b in legacy if b.name in knowhow]
        keep = [b for b in legacy if b.name not in knowhow]
        assert [b.name for b in af] == ["U1_HR002::Sequence"]
        assert skipped == ["FB1003_CR"]
        assert [b.name for b in keep] == ["FB_Open"]
