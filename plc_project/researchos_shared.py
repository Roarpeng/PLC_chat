"""Shared ResearchOS package markers and logging helpers."""

from __future__ import annotations

import logging
import sys
from typing import Any


def configure_logging(level: str = "INFO", **bound: Any) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
    logger = logging.getLogger("researchos")
    if bound:
        logger = logging.LoggerAdapter(logger, bound)  # type: ignore[assignment]
    return logger  # type: ignore[return-value]
