from pathlib import Path

from ah_there_it_is.agent.runner import SYSTEM_PROMPT


def test_versioned_v1_prompt_matches_builtin_default() -> None:
    prompt = Path("prompts/inventory-v1.txt").read_text(encoding="utf-8")
    assert prompt == SYSTEM_PROMPT


def test_russian_quantity_removed_restore_undo_guidance_is_explicit() -> None:
    assert "Отвечай по-русски" in SYSTEM_PROMPT
    assert "remove_item" in SYSTEM_PROMPT
    assert "undo_last_action" in SYSTEM_PROMPT
    assert "точность стала неизвестной" in SYSTEM_PROMPT
