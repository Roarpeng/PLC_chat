"""Knowledge engine settings (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    litellm_base_url: str | None = Field(default=None, alias="LITELLM_BASE_URL")
    litellm_master_key: str | None = Field(default=None, alias="LITELLM_MASTER_KEY")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=64, alias="EMBEDDING_DIM")
    # docs/knowledge/08-embedding-strategy.md configuration model
    embedding_policy: str = Field(
        default="prefer_highest_available", alias="EMBEDDING_POLICY"
    )  # prefer_highest_available | local_only
    embedding_priority: str = Field(
        default="voyage,openai,bge_m3,nomic,pseudo_v1", alias="EMBEDDING_PRIORITY"
    )
    embedding_require_local: bool = Field(default=False, alias="EMBEDDING_REQUIRE_LOCAL")

    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_collection: str = Field(default="researchos_chunks", alias="QDRANT_COLLECTION")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    neo4j_uri: str | None = Field(default=None, alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str | None = Field(default=None, alias="NEO4J_PASSWORD")

    minio_endpoint: str | None = Field(default=None, alias="MINIO_ENDPOINT")
    minio_access_key: str | None = Field(default=None, alias="MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field(default=None, alias="MINIO_SECRET_KEY")
    minio_bucket_documents: str = Field(default="ros-documents", alias="MINIO_BUCKET_DOCUMENTS")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    local_objects_dir: str = Field(default="./data/objects", alias="LOCAL_OBJECTS_DIR")
    default_workspace_id: str = Field(default="default", alias="KNOWLEDGE_WORKSPACE_ID")

    rrf_k: int = Field(default=60, alias="RRF_K")
    chunk_soft_max_chars: int = Field(default=2400, alias="CHUNK_SOFT_MAX_CHARS")
    chunk_hard_max_chars: int = Field(default=4800, alias="CHUNK_HARD_MAX_CHARS")

    @property
    def objects_path(self) -> Path:
        return Path(self.local_objects_dir).expanduser().resolve()


@lru_cache
def get_settings() -> KnowledgeSettings:
    return KnowledgeSettings()
