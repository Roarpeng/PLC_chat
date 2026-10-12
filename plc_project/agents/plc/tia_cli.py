r"""CLI — PLC Offline Analyzer entry point.

Primary user contract:

    researchos-tia-cli --project C:\Proj\Line1.ap19 --result-dir .\ResearchOS_PLC_Result

Also accepts an already-exported SimaticML folder (no TIA required):

    researchos-tia-cli --exports C:\Export\Line1 --result-dir .\ResearchOS_PLC_Result
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.plc.tia import analyze_plc_project, analyze_tia_exports
from agents.plc.tia.package import write_result_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="researchos-tia-cli",
        description=(
            "PLC Offline Analyzer: accept a TIA .apxx project (via Openness) or "
            "a SimaticML export folder, parse logic into PLC-IR, and emit SCL + reports."
        ),
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--project",
        default="",
        help="Path to .ap17/.ap18/.ap19/.ap20 — Openness export then analyze",
    )
    src.add_argument(
        "--exports",
        default="",
        help="Directory with SimaticML XML exports (offline, no TIA)",
    )
    parser.add_argument("--project-name", default="", help="Display name override")
    parser.add_argument(
        "--result-dir",
        default="",
        help=(
            "Write ResearchOS_PLC_Result package "
            "(converted_scl/plc_ir/kg/reports including coverage.json)"
        ),
    )
    parser.add_argument(
        "--out",
        default="",
        help="Legacy: directory for .scl files only (prefer --result-dir)",
    )
    parser.add_argument(
        "--kg",
        default="",
        help="Legacy: path for knowledge graph JSON only (prefer --result-dir)",
    )
    parser.add_argument(
        "--export-dir",
        default="",
        help="When using --project, write Openness XML here (default: temp dir)",
    )
    parser.add_argument(
        "--tia-version",
        default="",
        help="Portal version for Openness DLL (V17|V18|V19|V20); default inferred",
    )
    parser.add_argument("--plc-name", default="", help="PLC device/software name filter")
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="Print machine-readable conversion summary JSON",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit 0 even when no blocks were recognized",
    )
    args = parser.parse_args(argv)

    try:
        if args.project:
            result = analyze_plc_project(
                args.project,
                project_name=args.project_name,
                result_dir=args.result_dir,
                export_dir=args.export_dir,
                tia_version=args.tia_version,
                plc_name=args.plc_name,
            )
        else:
            export_path = Path(args.exports).expanduser()
            if not export_path.is_dir():
                print(f"error: export directory not found: {export_path}", file=sys.stderr)
                return 2
            result = analyze_tia_exports(
                str(export_path), project_name=args.project_name
            )
            if args.result_dir:
                write_result_package(
                    args.result_dir,
                    project=result["project"],
                    knowledge_graph=result["knowledge_graph"],
                    scl_sources=result["scl_sources"],
                    report_md=result["report"],
                    extra_meta={"source_kind": "export_dir", "export_dir": str(export_path)},
                )
                result["result_dir"] = str(Path(args.result_dir).resolve())
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    project = result["project"]
    kg = result["knowledge_graph"]
    scl_sources: dict[str, str] = result["scl_sources"]
    conversion = result.get("conversion_report") or {}

    print(result["report"])
    print()
    print("## Conversion summary")
    print(
        f"- Blocks: {conversion.get('total_blocks', len(project.blocks))} | "
        f"converted={conversion.get('converted', 0)} "
        f"parsed={conversion.get('parsed', 0)} "
        f"protected={conversion.get('protected', 0)} "
        f"failed={conversion.get('failed', 0)}"
    )
    if result.get("result_dir"):
        print(f"- Result package: `{result['result_dir']}`")
        print("- Coverage: `reports/coverage.json` (Part/TODO histogram + F-block flags)")
    coverage = result.get("coverage") or {}
    if coverage:
        print(
            f"- Coverage: todo_rate={coverage.get('todo_rate', 0):.1%} "
            f"todos={coverage.get('todo_count', 0)} "
            f"safety={coverage.get('safety_block_count', 0)}"
        )
    print()

    for name, source in scl_sources.items():
        print(f"{'=' * 72}\n-- SCL: {name}\n{'=' * 72}")
        print(source)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, source in scl_sources.items():
            safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in name)
            target = out_dir / f"{safe}.scl"
            target.write_text(source, encoding="utf-8")
            print(f"wrote {target}")

    if args.kg:
        kg_path = Path(args.kg)
        kg_path.parent.mkdir(parents=True, exist_ok=True)
        kg_path.write_text(
            json.dumps(kg.to_json(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {kg_path}")

    if project.extraction_notes:
        print("\nExtraction notes:", file=sys.stderr)
        for note in project.extraction_notes:
            print(f"  - {note}", file=sys.stderr)

    payload = {
        "ok": bool(project.blocks),
        "project_name": project.name,
        "source_path": project.source_path,
        "result_dir": result.get("result_dir") or "",
        "import": result.get("import"),
        "conversion_report": conversion,
        "coverage_summary": {
            k: coverage.get(k)
            for k in (
                "todo_rate",
                "todo_count",
                "converted",
                "parsed",
                "protected",
                "interface_only",
                "safety_block_count",
            )
            if coverage
        },
        "kg_nodes": len(kg.nodes),
        "kg_edges": len(kg.edges),
        "scl_sources": len(scl_sources),
    }
    if args.json_summary:
        print(json.dumps(payload, ensure_ascii=False))

    if not project.blocks and not args.allow_empty:
        print(
            "error: no PLC blocks recognized. For .apxx ensure Openness export "
            "succeeded; for folders check SimaticML layout.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
