"""PCEC 核心模块单测(契约 docs/19 §2/§3,并行线 A)。

覆盖:状态机全迁移矩阵(合法+全部非法)、终态封锁、基线哈希稳定性与灵敏度、
账本 CRUD+坏文件跳过、ops 超限截断、change_id 校验。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from plc_engine import pcec

# ----------------------------------------------------------------- 测试数据 --


def _baseline() -> dict:
    return {
        "project_hash": "sha256:" + "a" * 64,
        "tia_version": "V19",
        "parser_version": pcec.VERSION,
    }


def _make_change(**over) -> dict:
    chg = pcec.new_change(
        "writeback", "给 FB_X 加使能", [{"op": "set", "block": "FB_X"}], ["FB_X", "DB_Y"],
        _baseline(),
    )
    chg.update(over)
    return chg


@pytest.fixture
def work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    d = tmp_path / "plcwork"
    monkeypatch.setenv("PLC_WORK_DIR", str(d))
    return d


def _make_project(root: Path) -> Path:
    proj = root / "HR001_plc"
    for sub in ("plc", "Logs", "TMP", "XRef", "_researchos_cache"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    (proj / "HR001.ap19").write_text("<Project/>", encoding="utf-8")
    (proj / "plc" / "blocks.xml").write_text("<blocks>FB_X</blocks>", encoding="utf-8")
    (proj / "plc" / "tags.json").write_text('{"tags":[]}', encoding="utf-8")
    (proj / "Logs" / "run.log").write_text("noise", encoding="utf-8")
    (proj / "TMP" / "t.tmp").write_text("noise", encoding="utf-8")
    (proj / "XRef" / "x.bin").write_text("noise", encoding="utf-8")
    (proj / "_researchos_cache" / "c.json").write_text("noise", encoding="utf-8")
    return proj


# ------------------------------------------------------------- new_change --


def test_new_change_shape() -> None:
    bl = _baseline()
    chg = pcec.new_change("writeback", "给 FB_X 加使能", [{"op": "set"}], ["FB_X", "DB_Y"], bl)
    assert re.match(r"^chg-[0-9a-f]{12}$", chg["change_id"])
    assert chg["status"] == "proposed"
    assert chg["events"] == [{"ts": chg["created_at"], "event": "created"}]
    assert chg["updated_at"] == chg["created_at"]
    assert chg["project_baseline"] == bl
    assert chg["project_baseline"] is not bl  # baseline 取副本
    assert chg["intent"] == {
        "kind": "writeback", "request": "给 FB_X 加使能", "summary": "给 FB_X 加使能",
    }
    assert chg["touched_blocks"] == ["FB_X", "DB_Y"]
    assert chg["impact"] == {"blocks": [], "signals": [], "hmi_widgets": []}
    assert chg["verification"]["v0_parsed"] == "pending"
    assert chg["verification"]["v2_tia_compile"] == "pending"
    assert chg["verification"]["v3_behavior"] == "pending"
    assert chg["approval"] == {}
    assert chg["rollback"]["restore_verified"] is False
    json.dumps(chg)  # 纯 dict、JSON 可序列化
    other = pcec.new_change("fix", "r", [], [], bl)
    assert other["change_id"] != chg["change_id"]


# ---------------------------------------------------------------- 状态机 ---

LEGAL = {
    ("proposed", "analyzed"),
    ("analyzed", "validated"),
    ("analyzed", "rejected"),
    ("validated", "approved"),
    ("validated", "failed"),
    ("approved", "applied"),
    ("approved", "failed"),
    ("applied", "rolled_back"),
    ("proposed", "expired"),
    ("analyzed", "expired"),
    ("validated", "expired"),
    ("approved", "expired"),
}

_PATHS = {
    "proposed": [],
    "analyzed": ["analyzed"],
    "validated": ["analyzed", "validated"],
    "approved": ["analyzed", "validated", "approved"],
    "applied": ["analyzed", "validated", "approved", "applied"],
    "failed": ["analyzed", "validated", "failed"],
    "rejected": ["analyzed", "rejected"],
    "expired": ["expired"],
    "rolled_back": ["analyzed", "validated", "approved", "applied", "rolled_back"],
}


def _at(status: str) -> dict:
    chg = _make_change()
    for step in _PATHS[status]:
        pcec.transition(chg, step)
    assert chg["status"] == status
    return chg


def test_transition_table_matches_contract() -> None:
    assert set(pcec.ALLOWED_TRANSITIONS) == LEGAL
    assert pcec.TERMINAL_STATUSES == {"applied", "failed", "expired", "rejected", "rolled_back"}
    assert pcec.NON_TERMINAL_STATUSES == {"proposed", "analyzed", "validated", "approved"}


def test_full_transition_matrix() -> None:
    for frm in sorted(pcec.STATUSES):
        for to in sorted(pcec.STATUSES):
            chg = _at(frm)
            if (frm, to) in LEGAL:
                out = pcec.transition(chg, to)
                assert out["status"] == to, (frm, to)
                assert out["events"][-1]["event"] == to  # 缺省事件名=目标状态
                assert out["updated_at"] >= out["created_at"]
            else:
                n_events = len(chg["events"])
                with pytest.raises(pcec.PcecTransitionError):
                    pcec.transition(chg, to)
                assert chg["status"] == frm  # 失败不产生副作用
                assert len(chg["events"]) == n_events


def test_terminal_states_sealed() -> None:
    for terminal in sorted(pcec.TERMINAL_STATUSES):
        chg = _at(terminal)
        for to in sorted(pcec.STATUSES):
            if (terminal, to) in LEGAL:
                continue  # 仅 applied→rolled_back 例外
            with pytest.raises(pcec.PcecTransitionError):
                pcec.transition(chg, to)
    # 例外:applied 可回滚
    assert pcec.transition(_at("applied"), "rolled_back")["status"] == "rolled_back"


def test_transition_event_patch_and_status_guard() -> None:
    chg = _at("analyzed")
    out = pcec.transition(
        chg, "validated",
        verification={"v0_parsed": "pass", "v1_static": "pass"},
        event="static_ok",
    )
    assert out is chg  # 就地更新并返回同一对象
    assert chg["status"] == "validated"
    assert chg["verification"]["v1_static"] == "pass"
    assert chg["events"][-1]["event"] == "static_ok"
    assert chg["events"][-1]["ts"] == chg["updated_at"]
    # patch 里的 status 无法绕过状态机
    chg2 = _make_change()
    pcec.transition(chg2, "analyzed", status="applied")
    assert chg2["status"] == "analyzed"


def test_transition_rejects_malformed_change() -> None:
    with pytest.raises(TypeError):
        pcec.transition({}, "analyzed")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        pcec.transition({"status": 1}, "analyzed")  # type: ignore[arg-type]


def test_transition_unknown_status() -> None:
    with pytest.raises(pcec.PcecTransitionError):
        pcec.transition(_make_change(), "withdrawn")


# ------------------------------------------------------------- 基线哈希 ---


def test_baseline_stable_and_shape(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    b1 = pcec.project_baseline(proj)
    b2 = pcec.project_baseline(str(proj))  # str 路径同样可用
    assert b1 == b2  # 同目录两次一致
    assert b1["project_hash"].startswith("sha256:")
    assert re.fullmatch(r"[0-9a-f]{64}", b1["project_hash"].split(":", 1)[1])
    assert b1["tia_version"] == "V19"  # *.ap19 → V19
    assert b1["parser_version"] == pcec.VERSION


def test_baseline_sensitive_to_changes(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    base = pcec.project_baseline(proj)["project_hash"]
    # 内容变化 → 变
    (proj / "plc" / "blocks.xml").write_text("<blocks>FB_X FB_Z</blocks>", encoding="utf-8")
    assert pcec.project_baseline(proj)["project_hash"] != base
    (proj / "plc" / "blocks.xml").write_text("<blocks>FB_X</blocks>", encoding="utf-8")
    # 大小变化 → 变(同内容不同长度)
    (proj / "plc" / "blocks.xml").write_text("<blocks>FB_X </blocks>", encoding="utf-8")
    assert pcec.project_baseline(proj)["project_hash"] != base
    (proj / "plc" / "blocks.xml").write_text("<blocks>FB_X</blocks>", encoding="utf-8")
    assert pcec.project_baseline(proj)["project_hash"] == base
    # 新增文件 → 变
    (proj / "plc" / "extra.xml").write_text("x", encoding="utf-8")
    assert pcec.project_baseline(proj)["project_hash"] != base
    (proj / "plc" / "extra.xml").unlink()
    # 相对路径变化(改名,内容不变)→ 变
    (proj / "plc" / "tags.json").rename(proj / "plc" / "tags2.json")
    assert pcec.project_baseline(proj)["project_hash"] != base
    (proj / "plc" / "tags2.json").rename(proj / "plc" / "tags.json")


def test_baseline_skips_noise_dirs(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    base = pcec.project_baseline(proj)["project_hash"]
    for noise in (
        proj / "Logs" / "another.log",
        proj / "TMP" / "another.tmp",
        proj / "XRef" / "another.bin",
        proj / "_researchos_cache" / "another.json",
        proj / "_researchos_export" / "deep" / "f.xml",  # 前缀匹配任意 _researchos*
    ):
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text("more noise", encoding="utf-8")
    assert pcec.project_baseline(proj)["project_hash"] == base


def test_baseline_tia_version_inference(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.txt").write_text("a", encoding="utf-8")
    assert pcec.project_baseline(plain)["tia_version"] == "unknown"
    (plain / "proj.ap17").write_text("x", encoding="utf-8")
    assert pcec.project_baseline(plain)["tia_version"] == "V17"
    apxx_file = tmp_path / "HR001.ap19"
    apxx_file.write_text("x", encoding="utf-8")
    assert pcec.project_baseline(apxx_file)["tia_version"] == "V19"  # 单描述符文件也可


def test_baseline_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        pcec.project_baseline(tmp_path / "nope")


def test_baseline_matches(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    chg = pcec.new_change("writeback", "r", [], ["FB_X"], pcec.project_baseline(proj))
    assert pcec.baseline_matches(chg, proj) is True
    (proj / "plc" / "blocks.xml").write_text("changed", encoding="utf-8")
    assert pcec.baseline_matches(chg, proj) is False
    assert pcec.baseline_matches(chg, tmp_path / "missing") is False  # fail-closed
    assert pcec.baseline_matches({}, proj) is False
    assert pcec.baseline_matches({"project_baseline": {}}, proj) is False
    assert pcec.baseline_matches({"project_baseline": {"project_hash": ""}}, proj) is False


# ----------------------------------------------------------------- 账本 ---


def test_changes_root_resolution(work: Path, tmp_path: Path, monkeypatch) -> None:
    assert pcec.changes_root() == work / "changes"
    assert (work / "changes").is_dir()  # 自动创建
    other = SimpleNamespace(plc_work_dir=str(tmp_path / "other"))
    assert pcec.changes_root(other) == tmp_path / "other" / "changes"
    assert (tmp_path / "other" / "changes").is_dir()
    import tempfile as _tf
    monkeypatch.delenv("PLC_WORK_DIR", raising=False)
    assert pcec.changes_root() == Path(_tf.gettempdir()) / "researchos_plc" / "changes"


def test_put_get_roundtrip(work: Path) -> None:
    chg = _make_change()
    meta = pcec.put_change(chg)
    assert meta == {
        "id": chg["change_id"],
        "kind": "writeback",
        "summary": "给 FB_X 加使能",
        "status": "proposed",
        "updated_at": chg["updated_at"],
        "touched_count": 2,
    }
    root = pcec.changes_root() / chg["change_id"]
    assert (root / "change.json").is_file()
    assert (root / "meta.json").is_file()
    assert pcec.get_change(chg["change_id"]) == chg  # 深度相等往返
    # 更新后 upsert 生效
    pcec.transition(chg, "analyzed", verification={"v0_parsed": "pass"})
    pcec.put_change(chg)
    stored = pcec.get_change(chg["change_id"])
    assert stored["status"] == "analyzed"
    assert stored["verification"]["v0_parsed"] == "pass"
    assert stored["events"][-1]["event"] == "analyzed"


def test_get_change_invalid_or_missing(work: Path) -> None:
    for bad in ("", "chg-12345", "chg-ABCDEF123456", "CHG-abcdef123456",
                "chg_abcdef123456", "chg-abcdef12345g", "x" * 20):
        assert pcec.get_change(bad) is None
    assert pcec.get_change("chg-" + "0" * 12) is None  # 合法格式但不存在
    corrupt_id = "chg-" + "1" * 12
    root = pcec.changes_root() / corrupt_id
    root.mkdir(parents=True)
    (root / "change.json").write_text("{not json", encoding="utf-8")
    assert pcec.get_change(corrupt_id) is None  # 坏文件 → None,不抛


def test_put_change_rejects_invalid_id(work: Path) -> None:
    for bad in ("", "chg-123", "chg-GGGGGGGGGGGG", "chg_abcdef123456", None, 123):
        chg = _make_change()
        chg["change_id"] = bad
        with pytest.raises(ValueError):
            pcec.put_change(chg)  # type: ignore[arg-type]


def test_put_change_requires_json_serializable(work: Path) -> None:
    chg = _make_change()
    chg["ops"] = [object()]
    with pytest.raises(TypeError):
        pcec.put_change(chg)


def test_list_changes_order_and_bad_meta_skip(work: Path) -> None:
    a, b, c = _make_change(), _make_change(), _make_change()
    a["updated_at"] = 100.0
    b["updated_at"] = 300.0
    c["updated_at"] = 200.0
    for chg in (a, b, c):
        pcec.put_change(chg)
    ids = [m["id"] for m in pcec.list_changes()]
    assert ids == [b["change_id"], c["change_id"], a["change_id"]]  # updated_at 降序
    # 坏 meta 跳过,但同 id 的 change.json 仍可读
    bad_meta = pcec.changes_root() / b["change_id"] / "meta.json"
    bad_meta.write_text("{oops", encoding="utf-8")
    ids2 = [m["id"] for m in pcec.list_changes()]
    assert ids2 == [c["change_id"], a["change_id"]]
    assert pcec.get_change(b["change_id"]) == b
    # 非 dict meta 同样跳过
    (pcec.changes_root() / c["change_id"] / "meta.json").write_text("[1,2]", encoding="utf-8")
    assert [m["id"] for m in pcec.list_changes()] == [a["change_id"]]


# ----------------------------------------------------------- ops 超限截断 --


def test_ops_over_limit_truncated_to_digest(work: Path) -> None:
    ops = [{"op": "insert", "block": f"FB_{i}", "payload": "x" * 1024} for i in range(11_000)]
    chg = pcec.new_change("writeback", "bulk ops", ops, ["FB_0", "FB_1"], _baseline())
    n_events = len(chg["events"])
    meta = pcec.put_change(chg)
    assert meta["touched_count"] == 2
    stored = pcec.get_change(chg["change_id"])
    assert isinstance(stored["ops"], dict)
    assert stored["ops"]["truncated"] is True
    assert stored["ops"]["ops_count"] == 11_000
    assert stored["ops"]["touched_blocks"] == ["FB_0", "FB_1"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", stored["ops"]["ops_hash"])
    assert stored["events"][-1]["event"] == "ops_truncated"
    # 截断是存储行为:内存对象保持完整 ops,事件不变
    assert len(chg["ops"]) == 11_000
    assert len(chg["events"]) == n_events
    # 落盘文件低于上限
    change_json = pcec.changes_root() / chg["change_id"] / "change.json"
    assert change_json.stat().st_size < pcec._MAX_CHANGE_BYTES
    assert pcec._MAX_CHANGE_BYTES == 10 * 1024 * 1024


def test_put_change_still_too_large_after_truncation(work: Path) -> None:
    chg = pcec.new_change("writeback", "x" * (pcec._MAX_CHANGE_BYTES + 1024), [], [], _baseline())
    with pytest.raises(ValueError):
        pcec.put_change(chg)
