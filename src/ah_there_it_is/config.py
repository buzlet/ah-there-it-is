"""Application configuration."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """Small environment-backed settings object without extra dependencies."""

    model_config = ConfigDict(frozen=True)

    app_name: str = "Ah, There It Is!"
    environment: str = "development"
    database_url: str = "sqlite:///./ah_there_it_is.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("AH_THERE_IT_IS_APP_NAME", "Ah, There It Is!"),
        environment=os.getenv("AH_THERE_IT_IS_ENV", "development"),
        database_url=os.getenv(
            "AH_THERE_IT_IS_DATABASE_URL",
            "sqlite:///./ah_there_it_is.db",
        ),
    )
