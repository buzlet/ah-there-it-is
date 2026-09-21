"""Application configuration."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    """Small environment-backed settings object without extra dependencies."""

    model_config = ConfigDict(frozen=True)

    app_name: str = "Ah, There It Is!"
    environment: str = "development"
    database_url: str = "sqlite:///./ah_there_it_is.db"
    llm_provider: str = "heuristic"
    llm_provider_name: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    llm_temperature: float | None = None
    llm_extra_body: dict[str, Any] = Field(default_factory=dict)
    agent_max_rounds: int = Field(default=8, ge=1, le=32)
    prompt_version: str = "inventory-v1"
    prompt_file: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("AH_THERE_IT_IS_APP_NAME", "Ah, There It Is!"),
        environment=os.getenv("AH_THERE_IT_IS_ENV", "development"),
        database_url=os.getenv(
            "AH_THERE_IT_IS_DATABASE_URL",
            "sqlite:///./ah_there_it_is.db",
        ),
        llm_provider=os.getenv("AH_THERE_IT_IS_LLM_PROVIDER", "heuristic"),
        llm_provider_name=os.getenv("AH_THERE_IT_IS_LLM_PROVIDER_NAME") or None,
        llm_base_url=os.getenv("AH_THERE_IT_IS_LLM_BASE_URL") or None,
        llm_api_key=os.getenv("AH_THERE_IT_IS_LLM_API_KEY") or None,
        llm_model=os.getenv("AH_THERE_IT_IS_LLM_MODEL") or None,
        llm_timeout_seconds=float(os.getenv("AH_THERE_IT_IS_LLM_TIMEOUT_SECONDS", "60")),
        llm_temperature=_optional_float(os.getenv("AH_THERE_IT_IS_LLM_TEMPERATURE")),
        llm_extra_body=_json_object(os.getenv("AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON")),
        agent_max_rounds=int(os.getenv("AH_THERE_IT_IS_AGENT_MAX_ROUNDS", "8")),
        prompt_version=os.getenv("AH_THERE_IT_IS_PROMPT_VERSION", "inventory-v1"),
        prompt_file=os.getenv("AH_THERE_IT_IS_PROMPT_FILE") or None,
    )


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _json_object(value: str | None) -> dict[str, Any]:
    if value is None or not value.strip():
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON must decode to an object")
    return parsed
