"""AF V1.2 Intermediate Representation (Domain Model).

Standard domain model matching Siemens Automation Framework V1.2:
- Project -> Units (U1..U9) -> EMs (EM0 General + EM1..EM99)
- EM -> Jobs (LAF_SelectJob) + Sequence (LAF_ControlSclSequence) + Control Modules (LBC_*)
- Single ControlNodes DB per EM acting as the command/status hub between Sequence and CMs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AfCmType = Literal[
    "LBC_TwoWayActuator",
    "LBC_SimpleActuator",
    "LBC_ThreeWayActuator",
    "LBC_DigitalSignal",
    "LBC_AnalogInput",
    "LBC_AnalogOutput",
    "LBC_AxisControl",
    "LBC_Pt1Filter",
    "LBC_MotorStarter",
    "LBC_DriveControl_StdPlc",
]


@dataclass
class AfCm:
    """Control Module (CM) instance inside an Equipment Module."""

    name: str  # e.g. "cylLoader", "sensorPartPresent", "axisPress"
    cm_type: AfCmType
    description: str = ""
    # Physical I/O tags or symbolic addresses bound to this CM
    io_mapping: dict[str, str] = field(default_factory=dict)
    # Default parameters (e.g. monitoring times, setpoints)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class AfSequenceStep:
    """A step inside an EM FB Sequence."""

    step_id: int  # e.g. 10, 20, 30...
    name: str     # e.g. "WAIT_FOR_PART", "CYL_EXTEND"
    description: str = ""
    # SCL action statements executed while in this step (strictly via #controlNodes)
    actions: list[str] = field(default_factory=list)
    # SCL boolean condition expression to advance to next step
    transition_condition: str = ""
    next_step_id: int = 0
    timeout_ms: int = 5000
    error_step_id: int = 999  # default error step


@dataclass
class AfJob:
    """Job definition dispatched by LAF_SelectJob."""

    job_id: int
    name: str
    description: str = ""
    initial_step: int = 10


@dataclass
class AfSequence:
    """EM sequence logic executed inside FB Sequence."""

    initial_step: int = 0
    ready_step: int = 1
    steps: list[AfSequenceStep] = field(default_factory=list)


@dataclass
class AfEm:
    """Equipment Module (EM 1..99)."""

    em_idx: int
    name: str  # e.g. "LoadingStation", "PressStation"
    description: str = ""
    namespace: str = ""
    jobs: list[AfJob] = field(default_factory=list)
    sequence: AfSequence = field(default_factory=AfSequence)
    control_modules: list[AfCm] = field(default_factory=list)

    @property
    def unit_em_name(self) -> str:
        return f"U{self.unit_idx}Em{self.em_idx}_{self.name}" if hasattr(self, "unit_idx") else f"Em{self.em_idx}_{self.name}"


@dataclass
class AfEm0:
    """EM0 General Software Unit for a Unit."""

    name: str = "General"
    description: str = "General Equipment Module for Unit interlocks and auxiliary functions"
    namespace: str = ""


@dataclass
class AfUnit:
    """Unit Software Unit (U1..U9)."""

    unit_idx: int
    name: str  # e.g. "Unit1", "AssemblyCell"
    description: str = ""
    namespace: str = ""
    em0: AfEm0 = field(default_factory=AfEm0)
    equipment_modules: list[AfEm] = field(default_factory=list)

    @property
    def unit_name(self) -> str:
        return f"U{self.unit_idx}_{self.name}"


@dataclass
class AfProject:
    """Top level AF V1.2 Project Specification."""

    name: str
    description: str = ""
    units: list[AfUnit] = field(default_factory=list)
    global_constants: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AfProject:
        units = []
        for u in data.get("units") or []:
            em0_data = u.get("em0") or {}
            em0 = AfEm0(
                name=em0_data.get("name", "General"),
                description=em0_data.get("description", ""),
                namespace=em0_data.get("namespace", ""),
            )
            ems = []
            for em in u.get("equipment_modules") or []:
                jobs = [AfJob(**j) for j in em.get("jobs") or []]
                steps = [AfSequenceStep(**s) for s in (em.get("sequence") or {}).get("steps") or []]
                seq = AfSequence(
                    initial_step=(em.get("sequence") or {}).get("initial_step", 0),
                    ready_step=(em.get("sequence") or {}).get("ready_step", 1),
                    steps=steps,
                )
                cms = [AfCm(**c) for c in em.get("control_modules") or []]
                ems.append(
                    AfEm(
                        em_idx=em.get("em_idx", 1),
                        name=em.get("name", ""),
                        description=em.get("description", ""),
                        namespace=em.get("namespace", ""),
                        jobs=jobs,
                        sequence=seq,
                        control_modules=cms,
                    )
                )
            unit = AfUnit(
                unit_idx=u.get("unit_idx", 1),
                name=u.get("name", ""),
                description=u.get("description", ""),
                namespace=u.get("namespace", ""),
                em0=em0,
                equipment_modules=ems,
            )
            units.append(unit)
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            units=units,
            global_constants=dict(data.get("global_constants") or {}),
        )
