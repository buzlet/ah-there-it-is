"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from ah_there_it_is.agent import HeuristicLLMClient, LLMClient
from ah_there_it_is.agent.runner import SYSTEM_PROMPT
from ah_there_it_is.config import Settings, get_settings
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.web.routes import build_router

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_PACKAGE_DIR / "web" / "templates"))
_STATIC_DIR = _PACKAGE_DIR / "web" / "static"


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    llm_factory: Callable[[], LLMClient] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")
    application.state.settings = settings
    application.state.system_prompt = _load_system_prompt(settings)

    if session_factory is None:
        engine = create_db_engine(settings.database_url)
        session_factory = create_session_factory(engine)
        application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.llm_factory = llm_factory or _default_llm_factory(settings)

    application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    application.include_router(build_router(_TEMPLATES))

    @application.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "llm_provider": settings.llm_provider,
        }

    return application


def _load_system_prompt(settings: Settings) -> str:
    if settings.prompt_file is None:
        return SYSTEM_PROMPT
    return Path(settings.prompt_file).read_text(encoding="utf-8")


def _default_llm_factory(settings: Settings) -> Callable[[], LLMClient]:
    if settings.llm_provider == "heuristic":
        return HeuristicLLMClient
    raise ValueError(
        f"unsupported LLM provider {settings.llm_provider!r}; "
        "only the offline 'heuristic' provider exists in Stage 4"
    )


app = create_app()
