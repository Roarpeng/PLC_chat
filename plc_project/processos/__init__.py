"""aiCoPlc ProcessOS — process-compilation core layer.

Clean-sheet ProcessOS abstractions (process contract IR, semantic validation,
counterexample scenario runner, framework profiles, deterministic codegen,
evidence passport) grafted onto the verified ``plc_engine`` kernel and the real
TIA Openness worker. See docs/aicoplc_processos_blueprint.md.

This package never fabricates native-compile or field-verification evidence.
Offline artifacts are labelled ``offline_verified`` / ``simulated``; only the
Windows Openness worker may produce ``V19_real`` / ``V20_real`` receipts.
"""

__all__ = ["contract"]