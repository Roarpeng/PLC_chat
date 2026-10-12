"""HTTP client for LangGraph Runtime — full lifecycle support."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("researchos.gateway.runtime_client")


class RuntimeClient:
    def __init__(self, base_url: str | None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or "").rstrip("/") or None
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    async def startup(self) -> None:
        if self.base_url:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def configured(self) -> bool:
        return self.base_url is not None

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /runs to start a research graph execution."""
        if not self._client or not self.base_url:
            return {
                "status": "queued",
                "runtime": "local_echo",
                "echo": payload,
            }
        try:
            body = {
                "goal": payload.get("query") or payload.get("goal", ""),
                "workflow": payload.get("mode") or "deep_research",
                "task_id": payload.get("task_id"),
            }
            export_dir = (payload.get("tia_export_dir") or "").strip()
            if export_dir:
                body["tia_export_dir"] = export_dir
            # Map UI modes to runtime workflow names used by the planner.
            if body["workflow"] in {"deep", "quick"}:
                body["workflow"] = "deep_research"
            resp = await self._client.post("/runs", json=body)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime create_task failed, falling back to echo: %s", exc)
            return {
                "status": "queued",
                "runtime": "local_echo_fallback",
                "echo": payload,
                "upstream_error": str(exc),
            }

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """GET /runs/{task_id} to retrieve current state."""
        if not self._client or not self.base_url:
            return None
        try:
            resp = await self._client.get(f"/runs/{task_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime get_task failed: %s", exc)
            return None

    async def resume_task(
        self,
        task_id: str,
        resolution: str | dict[str, Any] = "approve",
        interrupt_id: str | None = None,
    ) -> dict[str, Any] | None:
        """POST /runs/{task_id}/resume to continue after HITL interrupt."""
        if not self._client or not self.base_url:
            return None
        try:
            body: dict[str, Any] = {"resolution": resolution}
            if interrupt_id:
                body["interrupt_id"] = interrupt_id
            resp = await self._client.post(f"/runs/{task_id}/resume", json=body)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime resume_task failed task_id=%s: %s", task_id, exc)
            return None

    async def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        """POST /runs/{task_id}/cancel to abort a running task."""
        if not self._client or not self.base_url:
            return None
        try:
            resp = await self._client.post(f"/runs/{task_id}/cancel")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime cancel_task failed task_id=%s: %s", task_id, exc)
            return None
