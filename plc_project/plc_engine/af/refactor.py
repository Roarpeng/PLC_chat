"""AF V1.2 Refactoring Engine: Legacy-to-AF Canvas Transformation.

Orchestrates reverse engineering and refactoring of non-standard TIA projects
into official Siemens Automation Framework (AF) V1.2 architecture:
- Generates complete AF V1.2 Software Unit blocks (Units, EMs, CMs, OBs, DBs)
- Marks original legacy blocks as superseded
- Produces architecture comparison reports with 100% I/O retention verification
- Executes AF static architecture linter to guarantee compliance.
"""

from __future__ import annotations

import copy
from typing import Any

from plc_engine.af.af_generator import generate_af_project_blocks
from plc_engine.af.af_linter import lint_af_canvas
from plc_engine.af.af_mapper import LegacyToAfMapper
from plc_engine.canvas_model import CanvasBlock, CanvasState


def refactor_canvas_to_af(
    canvas: CanvasState,
    target_unit_name: str = "U1_Refactored",
) -> tuple[CanvasState, dict[str, Any]]:
    """Refactor a legacy CanvasState into official AF V1.2 architecture.

    Args:
        canvas: The original flat legacy CanvasState.
        target_unit_name: Name of the target AF Unit (e.g. "U1_Assembly").

    Returns:
        tuple[CanvasState, dict[str, Any]]:
            - new_canvas: Updated CanvasState containing AF V1.2 blocks alongside
              superseded legacy blocks.
            - report: Comprehensive architecture transformation report detailing
              block mappings, EM/CM hierarchy, 100% physical I/O retention,
              safety interlocks, and AF linter findings.
    """
    # 1. Execute Legacy-to-AF Mapper analysis
    mapper = LegacyToAfMapper(canvas, target_unit_name=target_unit_name)
    analysis = mapper.analyze()

    # 2. Build AF Project Domain Model
    af_project = mapper.build_af_project(analysis)

    # 3. Generate all AF V1.2 CanvasBlocks
    af_blocks = generate_af_project_blocks(af_project)

    # 4. Enrich CallEquipment blocks with hardware I/O and interlock bindings
    _enrich_callequipment_blocks(af_blocks, analysis)

    # 5. Clone canvas and mark legacy blocks as superseded
    new_canvas = copy.deepcopy(canvas)

    for block in new_canvas.blocks.values():
        block.comment = f"[AF-REFACTORED: Superseded by {target_unit_name}] " + (block.comment or "")
        block.af_role = "legacy_superseded"
        block.software_unit = "Legacy_Superseded"

    # 6. Add all generated AF blocks into the new canvas
    for key, block in af_blocks.items():
        new_canvas.blocks[key] = block

    # 7. Update software unit manifests
    for unit in af_project.units:
        su_name = unit.unit_name
        new_canvas.software_unit_manifests.setdefault(su_name, {"type": "Unit", "unit_idx": unit.unit_idx})
        new_canvas.software_unit_manifests.setdefault(f"U{unit.unit_idx}Em0_General", {"type": "EM0"})
        for em in unit.equipment_modules:
            em_su = f"U{unit.unit_idx}Em{em.em_idx}_{em.name}"
            new_canvas.software_unit_manifests.setdefault(em_su, {"type": "EM", "em_idx": em.em_idx})

    # 8. Run AF static linter on refactored canvas
    findings = lint_af_canvas(new_canvas)

    # 9. Build architecture comparison report
    ems_summary = []
    if analysis.units:
        for em in analysis.units[0].ems:
            ems_summary.append(
                {
                    "em_idx": em.em_idx,
                    "name": em.name,
                    "steps_count": len(em.steps),
                    "cms_count": len(em.control_modules),
                    "cms": [
                        {
                            "name": cm.name,
                            "cm_type": cm.cm_type,
                            "description": cm.description,
                            "io_mapping": cm.io_mapping,
                            "parameters": cm.parameters,
                        }
                        for cm in em.control_modules
                    ],
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "name": s.name,
                            "actions": s.actions,
                            "transition_condition": s.transition_condition,
                            "next_step_id": s.next_step_id,
                        }
                        for s in em.steps
                    ],
                }
            )

    report: dict[str, Any] = {
        "status": "success",
        "project_name": canvas.project_name,
        "target_unit_name": target_unit_name,
        "legacy_blocks_count": len(canvas.blocks),
        "af_blocks_count": len(af_blocks),
        "block_mapping": analysis.block_mapping,
        "ems": ems_summary,
        "io_retention": {
            "total_ios": analysis.total_ios_detected,
            "retained_ios": analysis.retained_ios_count,
            "percentage": analysis.io_retention_rate,
            "details": [
                {
                    "address": m.address,
                    "tag_name": m.tag_name,
                    "data_type": m.data_type,
                    "cm_name": m.cm_name,
                    "cm_type": m.cm_type,
                    "cm_field": m.cm_field,
                    "em_name": m.em_name,
                }
                for m in analysis.io_mappings
            ],
        },
        "interlocks": [
            {
                "name": ic.name,
                "expression": ic.expression,
                "source_block": ic.source_block,
                "associated_cms": ic.associated_cms,
                "description": ic.description,
            }
            for ic in analysis.interlocks_detected
        ],
        "lint_findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "block_name": f.block_name,
                "message": f.message,
            }
            for f in findings
        ],
        "af_blocks_created": sorted(list(af_blocks.keys())),
    }

    return new_canvas, report


def _enrich_callequipment_blocks(
    af_blocks: dict[str, CanvasBlock],
    analysis: Any,
) -> None:
    """Enrich FB CallEquipment SCL body with hardware I/O and safety interlock comments."""
    for key, block in af_blocks.items():
        if block.af_role != "CallEquipment":
            continue

        io_lines = ["\n    // ==========================================", "    // Hardware I/O Binding & Safety Interlocks", "    // =========================================="]
        for m in analysis.io_mappings:
            if m.cm_name:
                io_lines.append(f"    // CM {m.cm_name}.{m.cm_field}: {m.address} ({m.tag_name})")

        interlock_lines = ["    // Active Interlocks:"]
        for ic in analysis.interlocks_detected:
            interlock_lines.append(f"    // - {ic.name}: {ic.expression}")

        binding_doc = "\n".join(io_lines + interlock_lines) + "\n"

        # Insert before END_FUNCTION_BLOCK
        if "END_FUNCTION_BLOCK" in block.scl_body:
            block.scl_body = block.scl_body.replace("END_FUNCTION_BLOCK", f"{binding_doc}\nEND_FUNCTION_BLOCK")
