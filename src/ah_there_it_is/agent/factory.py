"""LLM provider construction from application settings."""

from __future__ import annotations

from collections.abc import Callable

from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient
from ah_there_it_is.agent.heuristic import HeuristicLLMClient
from ah_there_it_is.agent.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from ah_there_it_is.agent.protocol import LLMClient
from ah_there_it_is.config import Settings


def build_llm_factory(settings: Settings) -> Callable[[], LLMClient]:
    if settings.llm_provider == "heuristic":
        return HeuristicLLMClient
    if settings.llm_provider == "gemini":
        if not settings.llm_model:
            raise ValueError("AH_THERE_IT_IS_LLM_MODEL is required")
        if not settings.llm_api_key:
            raise ValueError("AH_THERE_IT_IS_LLM_API_KEY is required")
        config = GeminiConfig(
            base_url=settings.llm_base_url or "https://generativelanguage.googleapis.com/v1beta",
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            provider_name=settings.llm_provider_name or "gemini",
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_retries=settings.llm_max_retries,
            retry_backoff_seconds=settings.llm_retry_backoff_seconds,
            extra_body=settings.llm_extra_body,
        )
        return lambda: GeminiLLMClient(config)
    if settings.llm_provider == "openai-compatible":
        if not settings.llm_base_url:
            raise ValueError("AH_THERE_IT_IS_LLM_BASE_URL is required")
        if not settings.llm_model:
            raise ValueError("AH_THERE_IT_IS_LLM_MODEL is required")
        config = OpenAICompatibleConfig(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            provider_name=settings.llm_provider_name or "openai-compatible",
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            extra_body=settings.llm_extra_body,
        )
        return lambda: OpenAICompatibleLLMClient(config)
    raise ValueError(f"unsupported LLM provider {settings.llm_provider!r}")
