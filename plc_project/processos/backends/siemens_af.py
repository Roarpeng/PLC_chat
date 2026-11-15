"""Siemens AF backend: Process Contract IR -> AF Project IR (blueprint §4).

Deterministic mapping to Unit / EM Sequence / CM Driver / instance DB / OB_Main.
No LLM, no free SCL — the codegen consumes this structured AfProject.
"""
from __future__ import annotations

from processos.contract import AfBlock, AfProject, FrameworkProfile, ProcessContract
from processos.contract.hashing import contract_semantic_hash
from processos.frameworks import af_semantics as af


class SiemensAfBackend:
    """Concrete FrameworkBackend for Siemens AF (folder edition)."""

    def lower(self, contract: ProcessContract, profile: FrameworkProfile) -> AfProject:
        blocks: list[AfBlock] = []
        instance_dbs: dict[str, str] = {}
        call_order: list[str] = []

        unit_fb = af.unit_block_name(contract.unit)
        blocks.append(AfBlock(
            name=unit_fb, kind="FB", role="unit",
            source_ids=[contract.unit],
            interface={"mode": "Int", "state": "Int", "permit": "Bool", "fault_summary": "Bool"},
        ))
        instance_dbs[unit_fb] = af.instance_db_name(unit_fb)
        call_order.append(unit_fb)

        for op in contract.operations:
            seq_fb = af.sequence_block_name(op.em)
            inputs = {"Start": "Bool", "Reset": "Bool", "SafetyPermit": "Bool"}
            for rid in op.resource_ids:
                res = contract.resource(rid)
                if res:
                    for fb in res.feedback:
                        inputs[fb] = "Bool"
            outputs = {"Busy": "Bool", "Done": "Bool", "Error": "Bool", "StepNo": "Int"}
            for rid in op.resource_ids:
                res = contract.resource(rid)
                if res:
                    for cmd in res.commands:
                        outputs[cmd] = "Bool"
            blocks.append(AfBlock(
                name=seq_fb, kind="FB", role="em_sequence",
                source_ids=[op.id, *[s.id for s in op.steps]],
                interface={
                    "inputs": inputs,
                    "outputs": outputs,
                    "steps": [s.id for s in op.steps],
                    "sequence": [s.to_dict() for s in op.steps],
                    "fault_policy": op.fault_policy.to_dict(),
                    "resource_ids": list(op.resource_ids),
                },
            ))
            instance_dbs[seq_fb] = af.instance_db_name(seq_fb)
            call_order.append(seq_fb)

        for res in contract.resources:
            drv_fb = af.driver_block_name(res.id)
            blocks.append(AfBlock(
                name=drv_fb, kind="FB", role="cm_driver",
                source_ids=[res.id],
                interface={
                    "commands": list(res.commands),
                    "feedback": list(res.feedback),
                    "status": list(res.status),
                },
            ))
            instance_dbs[drv_fb] = af.instance_db_name(drv_fb)
            call_order.append(drv_fb)

        blocks.append(AfBlock(
            name="OB_Main", kind="OB", role="main",
            source_ids=[contract.id],
            interface={"call_order": list(call_order)},
        ))

        return AfProject(
            profile_id=profile.profile_id,
            blocks=blocks,
            call_order=call_order,
            instance_dbs=instance_dbs,
            ir_hash=contract_semantic_hash(contract),
        )


def lower(contract: ProcessContract, profile: FrameworkProfile) -> AfProject:
    return SiemensAfBackend().lower(contract, profile)