"""Application configuration."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    """Small environment-backed settings object without extra dependencies."""

    model_config = ConfigDict(frozen=True)

    app_name: str = "Ah, There It Is!"
    environment: str = "development"
    database_url: str = "sqlite:///./ah_there_it_is.db"
    llm_provider: str = "heuristic"
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
        agent_max_rounds=int(os.getenv("AH_THERE_IT_IS_AGENT_MAX_ROUNDS", "8")),
        prompt_version=os.getenv("AH_THERE_IT_IS_PROMPT_VERSION", "inventory-v1"),
        prompt_file=os.getenv("AH_THERE_IT_IS_PROMPT_FILE") or None,
    )
