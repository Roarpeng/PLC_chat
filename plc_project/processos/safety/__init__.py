"""Fail-closed safety boundaries (PLAN §11)."""
from processos.safety.errors import ERROR_CODES, SafetyError, register_safety_exception_handler

__all__ = ["ERROR_CODES", "SafetyError", "register_safety_exception_handler"]
