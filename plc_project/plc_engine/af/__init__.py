"""Siemens Automation Framework (AF) V1.2 Engine.

Contains domain models, generators, numbering allocators, linters,
and startup template baselines for AF V1.2 projects.
"""

from plc_engine.af.af_generator import (
    generate_af_em_blocks,
    generate_af_project_blocks,
    generate_af_unit_blocks,
)
from plc_engine.af.af_linter import AfFinding, lint_af_canvas
from plc_engine.af.af_mapper import (
    CandidateEm,
    CandidateUnit,
    ExtractedStep,
    InterlockEntry,
    IoMappingEntry,
    LegacyAnalysis,
    LegacyToAfMapper,
)
from plc_engine.af.af_model import (
    AfCm,
    AfCmType,
    AfEm,
    AfEm0,
    AfJob,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
)
from plc_engine.af.af_numbering import (
    AfObNumbers,
    get_em0_ob_numbers,
    get_em_ob_numbers,
    get_unit_ob_numbers,
    validate_af_ob_number,
)
from plc_engine.af.baseline import (
    clone_startup_template,
    get_reference_zip,
    get_startup_zip,
)
from plc_engine.af.planner import plan_af_project_from_spec
from plc_engine.af.refactor import refactor_canvas_to_af

__all__ = [
    "AfCm",
    "AfCmType",
    "AfEm",
    "AfEm0",
    "AfFinding",
    "AfJob",
    "AfObNumbers",
    "AfProject",
    "AfSequence",
    "AfSequenceStep",
    "AfUnit",
    "CandidateEm",
    "CandidateUnit",
    "ExtractedStep",
    "InterlockEntry",
    "IoMappingEntry",
    "LegacyAnalysis",
    "LegacyToAfMapper",
    "clone_startup_template",
    "generate_af_em_blocks",
    "generate_af_project_blocks",
    "generate_af_unit_blocks",
    "get_em0_ob_numbers",
    "get_em_ob_numbers",
    "get_reference_zip",
    "get_startup_zip",
    "get_unit_ob_numbers",
    "lint_af_canvas",
    "plan_af_project_from_spec",
    "refactor_canvas_to_af",
    "validate_af_ob_number",
]
