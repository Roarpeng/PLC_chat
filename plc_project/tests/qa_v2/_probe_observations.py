"""QA 独立验收 · 定向行为探测（非测试，仅用于确认可疑点后再写正式断言）。

运行：uv run python tests/qa_v2/_probe_observations.py
输出留痕：evidence/v2/qa/07_probe_observations.txt
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from plc_engine.components.driver_spec import FieldSource
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import CompileReceipt
from plc_engine.engineering_ir.patch import make_patch
from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.guard_ast import GuardAST
from plc_engine.process.scl_lowering import CompilerService, guard_to_scl
from gateway.app.services.plc.tia_delivery_v2 import (
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    execute_chain,
)
from tests.v2_fixtures import build_valid_demo_ir, make_fake_openness_worker


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print("### " + title)
    print("=" * 78)


def probe_evidence_upcast(tmp: Path) -> None:
    section("P1: fake worker + real_machine=True 是否产生 V19_real / NATIVE_ARCHIVED")
    worker, archive = make_fake_openness_worker(tmp)
    adapter = TiaOpennessCliAdapter(worker=worker, real_machine=True)
    req = DeliveryChainRequest(
        project_id="prj_demo", job_id="job_probe", project_name="Demo",
        workspace_dir=str(tmp / "ws"), cpu_type_identifier="6ES7511-1AK02-0AB0/V2.9",
    )
    chain = execute_chain(adapter, req)
    print("worker_type          =", type(worker).__name__, "(pure python fake, no Siemens.Engineering.dll)")
    print("chain.state          =", chain.state)
    print("chain.evidence_level =", chain.evidence_level)
    print("artifact.evidence    =", chain.artifact.evidence_level.value if chain.artifact else None)
    print("compile.compile_ok   =", chain.artifact.compile.compile_ok if chain.artifact else None)
    print("compile.static_gate  =", chain.artifact.compile.static_gate_passed if chain.artifact else None)
    print("reopen_ok            =", chain.artifact.reopen_ok if chain.artifact else None)


def probe_static_gate(tmp: Path) -> None:
    section("P2: 违反依赖顺序的 manifest -> static_gate_passed=False 是否仍可 NATIVE_ARCHIVED")
    # files: an OB that depends on a UDT; import_order puts OB first (violation).
    udt = ArtifactFile(path="scl/UDT_X.scl", sha256="sha256:aaa", role="UDT", content="x")
    ob = ArtifactFile(path="scl/OB_X.scl", sha256="sha256:bbb", role="OB", content="y")
    bad = ArtifactManifest(
        files=[udt, ob],
        import_order=["scl/OB_X.scl", "scl/UDT_X.scl"],
        dependencies={"scl/OB_X.scl": ["scl/UDT_X.scl"]},
    )
    print("manifest issues      =", bad.validate_import_order())
    worker, archive = make_fake_openness_worker(tmp)
    adapter = TiaOpennessCliAdapter(worker=worker, real_machine=True)
    req = DeliveryChainRequest(
        project_id="prj_demo", job_id="job_probe2", project_name="Demo",
        workspace_dir=str(tmp / "ws2"), cpu_type_identifier="6ES7511-1AK02-0AB0/V2.9",
        manifest=bad,
    )
    chain = execute_chain(adapter, req)
    print("chain.state          =", chain.state)
    print("compile.static_gate  =", chain.artifact.compile.static_gate_passed if chain.artifact else None)
    print("compile.compile_ok   =", chain.artifact.compile.compile_ok if chain.artifact else None)


def probe_compile_ok_definition() -> None:
    section("P3: CompileReceipt.from_worker 的 compile_ok 是否包含 static_gate_passed")
    r = CompileReceipt.from_worker(
        {"ok": True, "compile": {"state": "Success", "errorCount": 0, "warningCount": 0,
                                  "staticGatePassed": False}},
        raw='{"ok":true}', evidence=EvidenceLevel.V19_REAL,
    )
    print("static_gate_passed   =", r.static_gate_passed)
    print("compile_ok           =", r.compile_ok, "(PRD 6.4 规则 2 要求 False)")


def probe_guard_injection() -> None:
    section("P4: GuardAST signal 名注入 SCL")
    payloads = [
        "X : BOOL; (* INJECTED *)",
        "Ok\" OR TRUE; //",
        "Ok\n  #malicious := TRUE;",
        "__import__('os').system('calc')",
    ]
    for text in payloads:
        g = GuardAST.from_dict({"node_type": "SIGNAL", "value_type": "BOOL", "signal": text})
        print("signal  =", repr(text))
        print("scl     =", repr(guard_to_scl(g)))
        print("is_valid=", g.is_valid())
    ir = build_valid_demo_ir("prj_inj")
    ir.process.transitions[0].guard_ast = GuardAST.from_dict(
        {"node_type": "SIGNAL", "value_type": "BOOL", "signal": "X : BOOL; (* QA_INJECTED *)"}
    )
    manifest, _ = CompilerService(ir.af_profile).lower(ir)
    hits = [f.path for f in manifest.files if "QA_INJECTED" in f.content]
    print("SCL files containing injected text =", hits)
    print("ValidationEngine accepts injected signal? =", ValidationEngine().validate(ir).passed)


def probe_unknown_guard_keys() -> None:
    section("P5: GuardAST.from_dict 是否拒绝未知顶层键（docstring 声称 strict）")
    for key in ("expression", "ExPrEsSiOn", "arbitrary_unknown_key", "payload"):
        try:
            GuardAST.from_dict({"node_type": "CONST", "value_type": "BOOL", "value": True, key: "junk"})
            print(f"key {key!r:26} -> ACCEPTED (silently ignored)")
        except Exception as exc:
            print(f"key {key!r:26} -> REJECTED {type(exc).__name__}: {exc}")


def probe_imported_address() -> None:
    section("P6: source=imported 组件绑定真实 %Q 地址是否被 ValidationEngine 接受")
    ir = build_valid_demo_ir("prj_imp")
    component = ir.components[0]
    component.source = FieldSource.IMPORTED
    component.io_bindings = {"CmdExtend": "%Q0.0"}
    report = ValidationEngine().validate(ir)
    print("component.source     =", component.source.value)
    print("validation.passed    =", report.passed)
    print("issues about address =", [i for i in report.issues if "physical address" in i["reason"]])
    print("patch.py:203 允许 imported 地址；ValidationEngine:68 无条件拒绝 -> 一致性观察")


def probe_base_revision() -> None:
    section("P7: base_revision 非法输入在 make_patch 阶段的异常类型")
    ir = build_valid_demo_ir("prj_br")
    for value in (-1, 0, 2**63, 10**40, True, "abc", None, 1.5):
        try:
            p = make_patch(ir.project_id, value, [{"op": "set_view_layout", "layout": {}}])
            print(f"value={value!r:12} -> base_revision={p.base_revision!r}")
        except Exception as exc:
            print(f"value={value!r:12} -> RAISED {type(exc).__name__}: {exc}")


def probe_artifact_tamper(tmp: Path) -> None:
    section("P8: artifact store 中文件被篡改后 download 是否拒绝")
    from gateway.app.services.plc.artifact_store_v2 import ArtifactStore
    from gateway.app.services.plc.workspace_v2 import WorkspaceStore
    from plc_engine.canonical import compute_file_sha256
    from plc_engine.engineering_ir.models import NativeTiaArtifact

    real = tmp / "a.zap19"
    real.write_bytes(b"ORIGINAL ARCHIVE")
    store = WorkspaceStore(db_path=str(tmp / "t.db"), ir_store_dir=str(tmp / "t_ir"))
    astore = ArtifactStore(store, root=tmp / "astore")
    art = NativeTiaArtifact(
        artifact_id="a_tamper", job_id="job_1", project_id="prj_a",
        archive_path=str(real), archive_sha256=compute_file_sha256(real),
        size_bytes=real.stat().st_size, kind="zap19", reopen_ok=True,
    )
    stored = astore.store_file(real)
    astore.register(art.to_dict(), stored=stored)
    stored_file = astore._resolve(stored["path"])
    stored_file.write_bytes(b"TAMPERED ARCHIVE")
    for label, sha in (("no sha256 param", ""), ("correct sha256", art.archive_sha256)):
        try:
            data, _ = astore.download("a_tamper", project_id="prj_a", job_id="job_1", sha256=sha)
            print(f"{label:18} -> DOWNLOADED {data!r}")
        except Exception as exc:
            print(f"{label:18} -> REJECTED {type(exc).__name__}: {exc}")


def main() -> None:
    # Windows keeps sqlite/WAL handles open briefly; ignore_cleanup_errors avoids
    # a cleanup-only PermissionError that is unrelated to the probed behaviour.
    with tempfile.TemporaryDirectory(prefix="qa_v2_probe_", ignore_cleanup_errors=True) as folder:
        tmp = Path(folder)
        probe_evidence_upcast(tmp)
        probe_static_gate(tmp)
        probe_compile_ok_definition()
        probe_guard_injection()
        probe_unknown_guard_keys()
        probe_imported_address()
        probe_base_revision()
        probe_artifact_tamper(tmp)
    print("\nPROBE_DONE")


if __name__ == "__main__":
    main()
