"""Application configuration."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ah_there_it_is.data_paths import default_database_url


def database_url_override(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if environ is None else environ
    value = env.get("AH_THERE_IT_IS_DATABASE_URL")
    if value is None or not value.strip():
        return None
    return value


def resolve_database_url(
    environ: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    override = database_url_override(env)
    if override is not None:
        return override
    return default_database_url(environ=env)


class Settings(BaseModel):
    """Small environment-backed settings object without extra dependencies."""

    model_config = ConfigDict(frozen=True)

    app_name: str = "Ah, There It Is!"
    environment: str = "development"
    database_url: str = Field(default_factory=resolve_database_url)
    llm_provider: str = "heuristic"
    llm_provider_name: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_retry_backoff_seconds: float = Field(default=1.0, ge=0, le=60)
    llm_temperature: float | None = None
    llm_extra_body: dict[str, Any] = Field(default_factory=dict)
    agent_max_rounds: int = Field(default=8, ge=1, le=32)
    prompt_version: str = "inventory-v1"
    prompt_file: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_user_id: int | None = None
    telegram_source_label: str | None = None
    telegram_base_url: str = "https://api.telegram.org"
    telegram_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    telegram_max_retries: int = Field(default=2, ge=0, le=5)
    telegram_retry_backoff_seconds: float = Field(default=0.2, ge=0, le=30)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("AH_THERE_IT_IS_APP_NAME", "Ah, There It Is!"),
        environment=os.getenv("AH_THERE_IT_IS_ENV", "development"),
        database_url=resolve_database_url(),
        llm_provider=os.getenv("AH_THERE_IT_IS_LLM_PROVIDER", "heuristic"),
        llm_provider_name=os.getenv("AH_THERE_IT_IS_LLM_PROVIDER_NAME") or None,
        llm_base_url=os.getenv("AH_THERE_IT_IS_LLM_BASE_URL") or None,
        llm_api_key=os.getenv("AH_THERE_IT_IS_LLM_API_KEY") or None,
        llm_model=os.getenv("AH_THERE_IT_IS_LLM_MODEL") or None,
        llm_timeout_seconds=float(os.getenv("AH_THERE_IT_IS_LLM_TIMEOUT_SECONDS", "60")),
        llm_max_retries=int(os.getenv("AH_THERE_IT_IS_LLM_MAX_RETRIES", "2")),
        llm_retry_backoff_seconds=float(
            os.getenv("AH_THERE_IT_IS_LLM_RETRY_BACKOFF_SECONDS", "1")
        ),
        llm_temperature=_optional_float(os.getenv("AH_THERE_IT_IS_LLM_TEMPERATURE")),
        llm_extra_body=_json_object(os.getenv("AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON")),
        agent_max_rounds=int(os.getenv("AH_THERE_IT_IS_AGENT_MAX_ROUNDS", "8")),
        prompt_version=os.getenv("AH_THERE_IT_IS_PROMPT_VERSION", "inventory-v1"),
        prompt_file=os.getenv("AH_THERE_IT_IS_PROMPT_FILE") or None,
        telegram_bot_token=os.getenv("AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN") or None,
        telegram_allowed_user_id=_optional_int(
            os.getenv("AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID")
        ),
        telegram_source_label=os.getenv("AH_THERE_IT_IS_TELEGRAM_SOURCE_LABEL") or None,
        telegram_base_url=os.getenv(
            "AH_THERE_IT_IS_TELEGRAM_BASE_URL", "https://api.telegram.org"
        ),
        telegram_timeout_seconds=float(
            os.getenv("AH_THERE_IT_IS_TELEGRAM_TIMEOUT_SECONDS", "30")
        ),
        telegram_max_retries=int(
            os.getenv("AH_THERE_IT_IS_TELEGRAM_MAX_RETRIES", "2")
        ),
        telegram_retry_backoff_seconds=float(
            os.getenv("AH_THERE_IT_IS_TELEGRAM_RETRY_BACKOFF_SECONDS", "0.2")
        ),
    )


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value)


def _json_object(value: str | None) -> dict[str, Any]:
    if value is None or not value.strip():
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON must decode to an object")
    return parsed
