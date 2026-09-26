"""The research adapters must not become production factory choices here."""

from __future__ import annotations

import pytest

from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.config import Settings


@pytest.mark.parametrize("provider", ["chatgpt-codex", "codex-exec-experiment"])
def test_experimental_providers_remain_unregistered(provider: str) -> None:
    with pytest.raises(ValueError, match="unsupported LLM provider"):
        build_llm_factory(Settings(llm_provider=provider))
