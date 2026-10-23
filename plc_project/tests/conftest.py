"""Pytest bootstrap — hermetic unit tests.

1. Disable broken host ROS launch_testing plugins if present (use env
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 on ROS hosts).
2. Autouse fixture: keep unit tests away from live LLM endpoints. Some agent
   code paths call locally-configured model bindings (gateway llm_settings /
   LiteLLM planner); when that server happens to be running on the dev box,
   answers differ run-to-run. Tests must be deterministic unless they opt in.
3. Autouse fixture: directory ingests persist raw-source artifacts into the
   export dir (contract docs/15 §2); scrub any that land under fixtures.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

FIXTURES_ROOT = str(Path(__file__).resolve().parent / "fixtures")


@pytest.fixture(autouse=True)
def _hermetic_no_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCHOS_DISABLE_LLM", "1")
    # Only cleared when the test did not set its own explicit value.
    if "LITELLM_BASE_URL" not in os.environ or os.environ["LITELLM_BASE_URL"] == "":
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("HYDE_ENABLED", raising=False)


@pytest.fixture(autouse=True)
def _scrub_fixture_source_artifacts() -> None:
    yield
    for stale in Path(FIXTURES_ROOT).rglob("_source_artifacts"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
