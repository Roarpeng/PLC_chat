"""In-memory project store + delivery gating (modular monolith, blueprint §10).

Holds the single writable truth (contract + revision), changesets, human
approvals and delivery jobs, and records every step into the Evidence Passport.
Persistence can later swap to PostgreSQL/SQLite without changing the API shape.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from processos.backends import lower
from processos.codegen import generate
from processos.contract import (
    Patch,
    ProcessContract,
    apply_patch,
    contract_semantic_hash,
    contract_spec_hash,
    evaluate_questions,
    resolve_question,
)
from processos.contract.patch import read_doc_path
from processos.evidence.passport import EvidencePassport
from processos.frameworks import get_profile, register_hr001_af_v19
from processos.safety.errors import SafetyError
from processos.scenario import run_all
from processos.semantics import validate
from processos.store.db import utcnow

UNKNOWN = "UNKNOWN"


def _semantic_diff_entry(before_doc: dict, after_doc: dict, op) -> dict:
    """Honest per-op diff: real before/after read off both contract snapshots.

    Values that cannot be resolved on a snapshot surface as explicit ``UNKNOWN``
    (a ``remove`` leaves nothing behind -> ``after=None``); nothing is guessed.
    """
    path = op.timing_path if op.op == "set_scenario_timing" else op.path
    before, ok_before = read_doc_path(before_doc, path)
    after, ok_after = read_doc_path(after_doc, path)
    if op.op == "remove" and not ok_after:
        after = None  # the item is verifiably gone after removal
    return {
        "op": op.op,
        "target": path,
        "before": before if ok_before else UNKNOWN,
        "after": after if ok_after else (None if op.op == "remove" else UNKNOWN),
    }


class DeliveryRunner(Protocol):
    def run(self, job: dict, contract: ProcessContract, profile: Any, generated: Any) -> dict: ...


@dataclass
class ProjectState:
    contract: ProcessContract
    revision: int = 1
    profile_id: str = ""
    changesets: dict[str, dict] = field(default_factory=dict)
    approvals: dict[str, dict] = field(default_factory=dict)
    jobs: dict[str, dict] = field(default_factory=dict)
    change_log: list[dict] = field(default_factory=list)


class StoreError(ValueError):
    """Domain error mapped to HTTP 4xx by the API layer."""


class NotFound(StoreError):
    pass


class GateBlocked(StoreError):
    pass


class ProjectStore:
    def __init__(self, passport: EvidencePassport | None = None):
        self.projects: dict[str, ProjectState] = {}
        self.passport = passport or EvidencePassport()
        self.runner: DeliveryRunner | None = None

    def _get(self, project_id: str) -> ProjectState:
        if project_id not in self.projects:
            raise NotFound(f"unknown project {project_id}")
        return self.projects[project_id]

    def create_project(self, contract: ProcessContract, profile_id: str = "") -> ProjectState:
        if not profile_id:
            profile_id = register_hr001_af_v19().profile_id
        if get_profile(profile_id) is None:
            raise StoreError(f"unknown framework profile {profile_id}")
        pid = contract.id
        if pid in self.projects:
            raise StoreError(f"project {pid} already exists")
        state = ProjectState(contract=contract, revision=1, profile_id=profile_id)
        self.projects[pid] = state
        self.passport.record(
            "project_created", revision_hash=contract_semantic_hash(contract),
            profile_id=profile_id, evidence_level="designed",
            payload={"project_id": pid},
        )
        return state

    def apply_patch(self, project_id: str, patch: Patch) -> ProjectState:
        state = self._get(project_id)
        before_doc = state.contract.to_dict()
        new_contract, new_rev = apply_patch(state.contract, patch, state.revision)
        after_doc = new_contract.to_dict()
        semantic_diff = [_semantic_diff_entry(before_doc, after_doc, o) for o in patch.ops]
        state.contract = new_contract
        state.revision = new_rev
        state.change_log.append({
            "rev": new_rev, "request_id": patch.request_id, "source": patch.source,
            "ops": [o.to_dict() for o in patch.ops],
            "semantic_diff": semantic_diff,
        })
        self.passport.record(
            "patch_applied", revision_hash=contract_semantic_hash(new_contract),
            profile_id=state.profile_id, evidence_level="offline_verified",
            payload={"rev": new_rev, "ops": [o.to_dict() for o in patch.ops],
                     "semantic_diff": semantic_diff},
        )
        return state

    def resolve_question(self, project_id: str, qid: str, resolution: str, by: str) -> ProjectState:
        state = self._get(project_id)
        resolve_question(state.contract, qid, resolution, by)
        return state

    def validate(self, project_id: str) -> dict:
        state = self._get(project_id)
        profile = get_profile(state.profile_id)
        report = validate(state.contract, profile)
        self.passport.record(
            "validation", revision_hash=report.ir_hash, profile_id=state.profile_id,
            evidence_level=report.evidence_level, payload=report.to_dict(),
        )
        return report.to_dict()

    def simulate(self, project_id: str) -> dict:
        state = self._get(project_id)
        results = run_all(state.contract)
        payload = {"results": [r.to_dict() for r in results],
                   "all_passed": all(r.passed for r in results)}
        self.passport.record(
            "simulation", revision_hash=contract_semantic_hash(state.contract),
            profile_id=state.profile_id, evidence_level="simulated", payload=payload,
        )
        return payload

    def generate(self, project_id: str) -> dict:
        state = self._get(project_id)
        profile = get_profile(state.profile_id)
        project = lower(state.contract, profile)
        gen = generate(project, profile)
        self.passport.record(
            "codegen", revision_hash=contract_semantic_hash(state.contract),
            profile_id=state.profile_id, evidence_level="offline_verified",
            payload={"manifest_hash": gen.manifest_hash, "coverage": gen.coverage,
                     "coverage_assertions_passed": gen.coverage_assertions_passed},
        )
        return gen.to_dict()

    def freeze_changeset(self, project_id: str) -> dict:
        state = self._get(project_id)
        profile = get_profile(state.profile_id)
        spec = contract_spec_hash(state.contract, profile.profile_id, profile.template_sha256)
        cs_id = "CS-" + uuid.uuid4().hex[:8]
        cs = {
            "id": cs_id, "spec_hash": spec, "profile_id": profile.profile_id,
            "template_sha256": profile.template_sha256, "rev": state.revision,
            "created_at": utcnow(),
            "diff": list(state.change_log),
        }
        state.changesets[cs_id] = cs
        self.passport.record(
            "changeset_frozen", revision_hash=spec, profile_id=profile.profile_id,
            evidence_level="offline_verified", payload={"changeset_id": cs_id},
        )
        return cs

    def preview_changeset(self, project_id: str, csid: str, *,
                          impact_service: Any = None,
                          subject_resolver: Any = None) -> dict:
        """PLAN §8 preview of a frozen changeset (read-only, no gating).

        {changeset_id, created_at, semantic_diff, impact, test_plan}:
        - semantic_diff: per-op {op, target, before, after} recorded when each
          patch was applied (real before/after snapshots); entries frozen before
          that recording degrade to op-derived diffs with ``before="UNKNOWN"``
          — never fabricated;
        - impact: ImpactReportService over the changeset's ops, subject = the
          registry object behind the first op's target; without an impact
          service or analyzable ops the field is an explicit UNKNOWN;
        - test_plan: the contract's scenarios as [{name, purpose}] ([] when the
          contract carries none).
        Un-frozen ids raise NotFound (404).
        """
        state = self._get(project_id)
        cs = state.changesets.get(csid)
        if cs is None:
            raise NotFound(f"unknown changeset {csid}")
        semantic_diff: list[dict] = []
        ops: list[dict] = []
        for entry in cs.get("diff", []):
            entry_ops = list(entry.get("ops") or [])
            ops.extend(entry_ops)
            if entry.get("semantic_diff"):
                semantic_diff.extend(entry["semantic_diff"])
            else:  # legacy freeze (pre semantic-diff recording): op-derived only
                semantic_diff.extend(
                    {"op": o.get("op", UNKNOWN), "target": o.get("path", UNKNOWN),
                     "before": UNKNOWN,
                     "after": o.get("value") if o.get("op") in ("set", "add") else None}
                    for o in entry_ops)

        impact: Any = UNKNOWN
        if impact_service is None:
            impact = {"impact_report": UNKNOWN,
                      "reason": "no impact service wired (UNKNOWN)",
                      "project_id": project_id}
        elif ops:
            subject = subject_resolver(ops) if subject_resolver is not None else None
            impact = impact_service.build(
                project_id, object_id=subject, patch_ops=ops,
                reason=f"changeset preview {csid}（§8 冻结后预览，不构成审批）")
        else:
            impact = {"impact_report": UNKNOWN,
                      "reason": "changeset records no patch ops (UNKNOWN)",
                      "project_id": project_id}

        test_plan = [{"name": s.name or s.id, "purpose": s.description}
                     for s in state.contract.scenarios]
        return {
            "changeset_id": csid,
            "created_at": cs.get("created_at", UNKNOWN),
            "spec_hash": cs.get("spec_hash", UNKNOWN),
            "revision": cs.get("rev", UNKNOWN),
            "semantic_diff": semantic_diff,
            "impact": impact,
            "test_plan": test_plan,
        }

    def approve(self, project_id: str, changeset_id: str, by: str) -> dict:
        state = self._get(project_id)
        cs = state.changesets.get(changeset_id)
        if cs is None:
            raise NotFound(f"unknown changeset {changeset_id}")
        if not by.strip():
            raise StoreError("approval requires a human identity")
        profile = get_profile(state.profile_id)
        current = contract_spec_hash(state.contract, profile.profile_id, profile.template_sha256)
        if cs["spec_hash"] != current:
            raise GateBlocked("APPROVAL_SPEC_HASH_STALE: contract changed since freeze")
        approval = {"by": by, "changeset_id": changeset_id, "spec_hash": cs["spec_hash"],
                    "rev": state.revision}
        state.approvals[changeset_id] = approval
        self.passport.record(
            "human_approval", revision_hash=cs["spec_hash"], profile_id=profile.profile_id,
            evidence_level="offline_verified", payload=approval,
        )
        return approval

    def delivery_gate(self, project_id: str) -> dict:
        state = self._get(project_id)
        profile = get_profile(state.profile_id)
        current = contract_spec_hash(state.contract, profile.profile_id, profile.template_sha256)
        approved = any(a["spec_hash"] == current for a in state.approvals.values())
        report = validate(state.contract, profile)
        qgate = evaluate_questions(state.contract)
        checks = {
            "approved_and_hash_match": approved,
            "validation_no_errors": report.ok,
            "no_blocking_questions": qgate.deliverable,
            "framework_g0_verified": profile.verified,
        }
        ready = checks["approved_and_hash_match"] and checks["validation_no_errors"] and checks["no_blocking_questions"]
        return {"ready": ready, "checks": checks, "spec_hash": current,
                "note": "G0 unverified: native build runs in restricted demo mode until WS6 proves real compile."}

    def _gate_af_profile(self, project_id: str, state: ProjectState) -> None:
        """PLAN §11 AF_PROFILE_MISMATCH as a runtime delivery gate.

        The framework profile must still be registered and its template sha256
        must equal what was recorded when every approved changeset was frozen
        (freeze records ``template_sha256``; legacy changesets without the
        field compare as UNKNOWN and block — fail-closed, never a guess).
        """
        profile = get_profile(state.profile_id)
        if profile is None:
            raise SafetyError(
                "AF_PROFILE_MISMATCH",
                f"framework profile {state.profile_id!r} 不在注册表中，无法证明标准库接口一致，阻断交付",
                details={"profile_id": state.profile_id,
                         "frozen_template_sha256": UNKNOWN,
                         "current_template_sha256": UNKNOWN},
                http_status=409)
        for csid in state.approvals:
            cs = state.changesets.get(csid)
            frozen = (cs or {}).get("template_sha256") or UNKNOWN
            if frozen != profile.template_sha256:
                raise SafetyError(
                    "AF_PROFILE_MISMATCH",
                    f"changeset {csid} 冻结时记录的模板 sha256 与当前 profile 不一致，阻断交付",
                    details={"changeset_id": csid,
                             "frozen_template_sha256": frozen,
                             "current_template_sha256": profile.template_sha256,
                             "profile_id": profile.profile_id},
                    http_status=409)

    @staticmethod
    def _counterexample_summary(result: dict) -> Any:
        """Compact counterexample digest of a failed scenario (honest NONE)."""
        ces = result.get("counterexamples") or []
        if not ces:
            return "NONE"
        first = ces[0]
        return {"property_ids": [c.get("property_id", UNKNOWN) for c in ces],
                "first": {"property_id": first.get("property_id", UNKNOWN),
                          "cycle": first.get("cycle", UNKNOWN),
                          "description": first.get("description", UNKNOWN)}}

    def _gate_behavior_regression(self, project_id: str, state: ProjectState) -> None:
        """PLAN §11 BEHAVIOR_REGRESSION: a failing scenario blocks delivery.

        Runs the same scenario suite as ``simulate`` (the run is recorded in
        the evidence passport); any failed scenario raises 409 with the failed
        names and a counterexample digest — never silently downgraded.
        """
        sim = self.simulate(project_id)
        failed = [r for r in sim["results"] if not r.get("passed")]
        if failed:
            raise SafetyError(
                "BEHAVIOR_REGRESSION",
                "行为仿真存在失败场景，阻断交付：" + ", ".join(str(r.get("scenario_id")) for r in failed),
                details={"failed_scenarios": [
                    {"name": r.get("scenario_id", UNKNOWN),
                     "fault_reason": r.get("fault_reason") or "",
                     "counterexample": self._counterexample_summary(r)}
                    for r in failed]},
                http_status=409)

    def create_delivery(self, project_id: str) -> dict:
        state = self._get(project_id)
        self._gate_af_profile(project_id, state)
        self._gate_behavior_regression(project_id, state)
        gate = self.delivery_gate(project_id)
        if not gate["ready"]:
            raise GateBlocked("delivery blocked: " + ", ".join(k for k, v in gate["checks"].items() if not v and k != "framework_g0_verified"))
        job_id = "JOB-" + uuid.uuid4().hex[:8]
        job = {"id": job_id, "project_id": project_id, "status": "QUEUED",
               "spec_hash": gate["spec_hash"], "events": [], "diagnostics": [], "artifact": None}
        state.jobs[job_id] = job
        self.passport.record(
            "delivery_queued", revision_hash=gate["spec_hash"], profile_id=state.profile_id,
            evidence_level="designed", payload={"job_id": job_id}, job_id=job_id,
        )
        if self.runner is not None:
            profile = get_profile(state.profile_id)
            gen = generate(lower(state.contract, profile), profile)
            result = self.runner.run(job, state.contract, profile, gen)
            job.update(result)
        return job