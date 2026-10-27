"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"

    # --- LLM provider (any OpenAI-compatible /chat/completions endpoint) ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = Field(default=90, gt=0, le=600)
    llm_max_output_tokens: int = Field(default=3000, ge=256, le=32768)  # hard ceiling per call
    llm_reasoning_effort: str = ""  # optional ("low"|"medium"|"high"); only sent when set, for reasoning models

    # --- HTTP / CORS ---
    # Comma-separated list of allowed browser origins, e.g. "https://x.vercel.app,http://localhost:3000"
    frontend_origin: str = "http://localhost:3000"
    trust_proxy_headers: bool = False  # set true behind nginx so X-Real-IP is used for rate limiting
    max_request_bytes: int = 64 * 1024

    # --- GitHub / repository limits ---
    github_token: str = ""  # optional; only raises the GitHub API rate limit for public repos
    max_repository_size_mb: int = Field(default=50, ge=1, le=2048)
    max_source_files: int = Field(default=5000, ge=10, le=100000)
    max_file_size_kb: int = Field(default=256, ge=1, le=4096)
    clone_timeout_seconds: int = Field(default=60, ge=5, le=600)

    # --- Agent ---
    max_repair_iterations: int = Field(default=3, ge=1, le=6)
    max_context_chars: int = Field(default=12000, ge=4000, le=120000)
    max_patch_files: int = Field(default=5, ge=1, le=20)
    max_patch_bytes: int = Field(default=40_000, ge=1000, le=500_000)
    investigation_timeout_seconds: int = Field(default=600, ge=30, le=3600)

    # --- Sandbox (test validation) ---
    sandbox_enabled: bool = False
    sandbox_image: str = "repopilot-sandbox:latest"
    test_timeout_seconds: int = Field(default=120, ge=5, le=900)
    sandbox_memory_mb: int = Field(default=512, ge=64, le=8192)
    sandbox_cpus: float = Field(default=1.0, gt=0, le=16)
    sandbox_pids_limit: int = Field(default=128, ge=16, le=4096)
    sandbox_output_limit_kb: int = Field(default=64, ge=4, le=1024)
    sandbox_tmpfs_mb: int = Field(default=256, ge=16, le=2048)

    # --- Abuse controls ---
    max_concurrent_investigations: int = Field(default=1, ge=1, le=8)
    rate_limit_per_hour: int = Field(default=5, ge=1, le=1000)
    daily_global_limit: int = Field(default=100, ge=1, le=100000)

    # --- Storage ---
    data_dir: Path = BACKEND_DIR / ".data"
    workspace_root: Path = BACKEND_DIR / ".workspaces"
    result_ttl_hours: int = Field(default=24, ge=1, le=720)
    max_stored_investigations: int = Field(default=200, ge=10, le=10000)

    @field_validator("llm_base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.strip() and self.llm_base_url and self.llm_model.strip())

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
