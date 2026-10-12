"""PLC Platform Gateway application factory.

Standalone FastAPI service for PLC ingest, analysis, knowledge graph, device cards,
and handover workbench.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.app.config import get_settings
from gateway.app.routers import plc
from researchos_shared import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("plc.gateway")
    logger.info("PLC Gateway started in env=%s", settings.env)
    try:
        yield
    finally:
        logger.info("PLC Gateway stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PLC Intelligence Gateway",
        version="0.1.0",
        description="PLC Offline Ingest, SCL Translation, Handover Brief & Canvas Workbench API",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(plc.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "plc-gateway"}

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "plc-gateway",
            "docs": "/docs",
            "plc_api": "/api/v1/plc/jobs",
        }

    return app


app = create_app()


def run() -> None:
    """Console entrypoint: plc-gateway."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "gateway.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_dev,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
