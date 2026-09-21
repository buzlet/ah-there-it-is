"""Minimal live-provider connectivity smoke test for CI/manual verification."""

from __future__ import annotations

from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.agent.protocol import AgentMessage
from ah_there_it_is.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.llm_provider == "heuristic":
        raise SystemExit("live provider smoke requires AH_THERE_IT_IS_LLM_PROVIDER=openai-compatible")
    client = build_llm_factory(settings)()
    response = client.complete(
        [
            AgentMessage(role="system", content="Reply briefly and do not call tools."),
            AgentMessage(role="user", content="Return the word OK."),
        ],
        [],
    )
    if not response.content.strip():
        raise SystemExit("provider returned no text")
    print(response.content.strip())


if __name__ == "__main__":
    main()
