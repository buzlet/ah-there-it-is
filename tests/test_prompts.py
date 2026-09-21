from pathlib import Path

from ah_there_it_is.agent.runner import SYSTEM_PROMPT


def test_versioned_v1_prompt_matches_builtin_default() -> None:
    prompt = Path("prompts/inventory-v1.txt").read_text(encoding="utf-8")
    assert prompt == SYSTEM_PROMPT
