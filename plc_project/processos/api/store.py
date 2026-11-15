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
from processos.evidence.passport import EvidencePassport
from processos.frameworks import get_profile, register_hr001_af_v19
from processos.scenario import run_all
from processos.semantics import validate


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
        new_contract, new_rev = apply_patch(state.contract, patch, state.revision)
        state.contract = new_contract
        state.revision = new_rev
        state.change_log.append({"rev": new_rev, "request_id": patch.request_id, "source": patch.source})
        self.passport.record(
            "patch_applied", revision_hash=contract_semantic_hash(new_contract),
            profile_id=state.profile_id, evidence_level="offline_verified",
            payload={"rev": new_rev, "ops": [o.to_dict() for o in patch.ops]},
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
            "diff": list(state.change_log),
        }
        state.changesets[cs_id] = cs
        self.passport.record(
            "changeset_frozen", revision_hash=spec, profile_id=profile.profile_id,
            evidence_level="offline_verified", payload={"changeset_id": cs_id},
        )
        return cs

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

    def create_delivery(self, project_id: str) -> dict:
        state = self._get(project_id)
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