"""PLAN §7 · RBAC service: roles, permission matrix, audit log, approver separation."""
from __future__ import annotations

from .service import (
    AUDIT_NAMESPACE,
    PERMISSIONS,
    ROLES,
    Actor,
    AuditLog,
    assert_approver_separation,
    audit_forbidden,
    get_actor,
    register_routes,
    require_role,
    role_matrix,
)

__all__ = [
    "AUDIT_NAMESPACE",
    "PERMISSIONS",
    "ROLES",
    "Actor",
    "AuditLog",
    "assert_approver_separation",
    "audit_forbidden",
    "get_actor",
    "register_routes",
    "require_role",
    "role_matrix",
]
