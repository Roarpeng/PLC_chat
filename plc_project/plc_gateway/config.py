"""Gateway settings via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="dev", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    jwt_secret: str = Field(default="dev-insecure-change-me-32chars!!", alias="JWT_SECRET")
    jwt_ttl_seconds: int = Field(default=1800, alias="JWT_TTL_SECONDS")
    refresh_ttl_seconds: int = Field(default=604800, alias="REFRESH_TTL_SECONDS")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    auth_api_keys_enabled: bool = Field(default=True, alias="AUTH_API_KEYS_ENABLED")
    dev_api_key: str = Field(default="ros_ak_dev_change_me", alias="DEV_API_KEY")

    runtime_base_url: str | None = Field(default=None, alias="RUNTIME_BASE_URL")
    litellm_base_url: str | None = Field(default=None, alias="LITELLM_BASE_URL")
    litellm_master_key: str | None = Field(default=None, alias="LITELLM_MASTER_KEY")
    litellm_default_model: str = Field(default="default", alias="LITELLM_DEFAULT_MODEL")

    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    neo4j_uri: str | None = Field(default=None, alias="NEO4J_URI")
    minio_endpoint: str | None = Field(default=None, alias="MINIO_ENDPOINT")

    public_api_base: str = Field(default="http://localhost:8000", alias="PUBLIC_API_BASE")
    public_ws_base: str = Field(default="ws://localhost:8000", alias="PUBLIC_WS_BASE")

    # PLC Intelligence feature (path sandbox + upload limits)
    plc_path_allowlist: str = Field(
        default="",
        alias="PLC_PATH_ALLOWLIST",
        description="Semicolon-separated absolute roots allowed for path ingest",
    )
    plc_work_dir: str | None = Field(default=None, alias="PLC_WORK_DIR")
    plc_upload_max_mb: int = Field(default=200, alias="PLC_UPLOAD_MAX_MB")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in {"dev", "development", "local", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
