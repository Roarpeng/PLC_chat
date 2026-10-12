"""Runtime settings from environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="dev", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    litellm_base_url: str | None = Field(default=None, alias="LITELLM_BASE_URL")
    litellm_master_key: str | None = Field(default=None, alias="LITELLM_MASTER_KEY")
    litellm_default_model: str = Field(default="default", alias="LITELLM_DEFAULT_MODEL")

    # When true, skip plan_approval human interrupt
    dev_auto_approve: bool = Field(default=False, alias="DEV_AUTO_APPROVE")

    runtime_host: str = Field(default="0.0.0.0", alias="RUNTIME_HOST")
    runtime_port: int = Field(default=8100, alias="RUNTIME_PORT")

    # inprocess | stdio
    mcp_hello_mode: str = Field(default="inprocess", alias="MCP_HELLO_MODE")
    # cli | stdio — how Runtime invokes tia.open_project / list_blocks / export_block
    mcp_tia_mode: str = Field(default="cli", alias="MCP_TIA_MODE")
    max_supervisor_hops: int = Field(default=32, alias="MAX_SUPERVISOR_HOPS")


@lru_cache
def get_settings() -> RuntimeSettings:
    return RuntimeSettings()
