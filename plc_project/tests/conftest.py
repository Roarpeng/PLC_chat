"""Pytest bootstrap — hermetic unit tests.

1. Disable broken host ROS launch_testing plugins if present (use env
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 on ROS hosts).
2. Autouse fixture: keep unit tests away from live LLM endpoints. Some agent
   code paths call locally-configured model bindings (gateway llm_settings /
   LiteLLM planner); when that server happens to be running on the dev box,
   answers differ run-to-run. Tests must be deterministic unless they opt in.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _hermetic_no_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCHOS_DISABLE_LLM", "1")
    # Only cleared when the test did not set its own explicit value.
    if "LITELLM_BASE_URL" not in os.environ or os.environ["LITELLM_BASE_URL"] == "":
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("HYDE_ENABLED", raising=False)
