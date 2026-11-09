"""V2 component / driver kernel (WP-02).

Re-exports the strong-typed driver entities. DriverCatalog, FSM, validation and
compiler live in sibling modules and all consume these exact types, so there is
only one definition of ``DriverSpec`` / ``TypedPort`` / ``ComponentDefinition``.
"""
from __future__ import annotations

from plc_engine.components.driver_spec import (
    CompileMode,
    ComponentDefinition,
    DriverSpec,
    FailurePolicy,
    FieldSource,
    PortDataType,
    PortDirection,
    PortRole,
    TypedPort,
)

__all__ = [
    "CompileMode",
    "ComponentDefinition",
    "DriverSpec",
    "FailurePolicy",
    "FieldSource",
    "PortDataType",
    "PortDirection",
    "PortRole",
    "TypedPort",
]
