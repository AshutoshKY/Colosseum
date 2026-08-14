"""Application configuration via pydantic-settings.

Credentials are reused from the sibling `superclaims-ai` / `healthpay-ai` projects.
Rather than copy secrets into this repo, we *layer in* their `.env` files (paths given
by ``EXTERNAL_ENV_FILES``) before reading Colosseum's own `.env`. Colosseum's `.env` and
the real process environment always win on conflicts.

Load order (lowest precedence first):
  1. Each file in ``EXTERNAL_ENV_FILES`` (superclaims-ai/.env, healthpay-ai/.env, ...)
  2. Colosseum's own ``.env``
  3. The actual process environment
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = .../Colosseum
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def _bootstrap_external_env() -> None:
    """Populate ``os.environ`` from external dotenv files without clobbering existing keys.

    Reads ``EXTERNAL_ENV_FILES`` (comma-separated absolute paths) from either the process
    env or Colosseum's `.env`, then for each existing file injects any *missing* keys into
    ``os.environ``. Existing env vars are never overwritten, so the real environment and
    Colosseum's `.env` keep precedence.
    """
    # Discover the external file list from the process env, falling back to Colosseum's .env.
    local_values = dotenv_values(DEFAULT_ENV_FILE) if DEFAULT_ENV_FILE.exists() else {}
    raw = os.environ.get("EXTERNAL_ENV_FILES")
    if raw is None:
        raw = local_values.get("EXTERNAL_ENV_FILES")
    if not raw:
        return

    for spec in raw.split(","):
        path = Path(spec.strip()).expanduser()
        if not spec.strip() or not path.is_file():
            continue
        for key, value in dotenv_values(path).items():
            if value is not None and key not in os.environ and key not in local_values:
                os.environ[key] = value


# Side effect at import time: make reused creds visible before Settings is constructed.
_bootstrap_external_env()


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    colosseum_env: str = "local"
    log_level: str = "INFO"

    # ---- Storage ----
    database_url: str = (
        "postgresql+psycopg://colosseum:colosseum@localhost:5433/colosseum"
    )
    redis_url: str = "redis://localhost:6380/0"

    # ---- External env layering (informational; already applied at import time) ----
    external_env_files: str = ""

    # ---- Google / Vertex AI ----
    google_application_credentials: str | None = Field(default=None)
    vertexai_project: str | None = Field(default=None)
    vertexai_location: str = "us-central1"
    colosseum_default_gemini_model: str = "vertex_ai/gemini-2.5-flash"
    judge_default_model: str = "gemini-3.1-pro"

    # ---- AWS Bedrock ----
    aws_bearer_token_bedrock: str | None = None
    aws_region_name: str = "ap-south-1"

    # ---- Self-deployed Qwen3-VL (vLLM / OpenAI-compatible) ----
    qwen_vl_base_url: str = "http://15.252.27.168:8000/v1"
    qwen_vl_api_key: str = "EMPTY"

    # ---- OpenRouter (single gateway fronting many upstream vendors) ----
    openrouter_api_key: str | None = None

    # ---- Pricing ----
    pricing_version: str = "2026-06"

    # ---- Observability (Phase 4) ----
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def has_vertex_credentials(self) -> bool:
        """Whether enough is present to attempt a real Vertex call.

        Accepts either an explicit service-account JSON path or ambient Application
        Default Credentials (``GOOGLE_APPLICATION_CREDENTIALS`` / ``GOOGLE_CLOUD_PROJECT``).
        """
        creds = self.google_application_credentials or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        project = self.vertexai_project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        return bool(creds and Path(creds).expanduser().is_file()) and bool(project)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
