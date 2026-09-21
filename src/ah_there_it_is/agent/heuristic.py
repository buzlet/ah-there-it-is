"""Tiny offline rule-based model for development smoke tests only."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)

_WHERE_RE = re.compile(r"^\s*где\s+(.+?)[?\s]*$", re.IGNORECASE)
_MOVE_RE = re.compile(
    r"^\s*(положил|положи|переложил|переложи)\s+(.+?)\s+(?:в|на)\s+(.+?)[.\s]*$",
    re.IGNORECASE,
)


class HeuristicLLMClient:
    """Exercise the agent loop offline for a deliberately tiny Russian subset.

    This is not a substitute for an LLM and must not be used as the production
    natural-language parser. It exists so developers can smoke-test the whole
    search/tool/mutation path without network access or scripted model turns.
    """

    def __init__(self) -> None:
        self._next_call_id = 1

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        del tools
        user_text = self._current_user_text(messages)
        where = _WHERE_RE.match(user_text)
        if where:
            return self._where(messages, where.group(1).strip())

        move = _MOVE_RE.match(user_text)
        if move:
            verb, item_text, location_text = move.groups()
            return self._move(
                messages,
                verb.casefold(),
                item_text.strip(),
                location_text.strip(),
            )

        return LLMResponse(
            content=(
                "Offline heuristic understands only 'Где X?' and "
                "'Положил/переложил X в Y'."
            )
        )

    def _where(self, messages: Sequence[AgentMessage], item_text: str) -> LLMResponse:
        item_result = self._latest_tool_result(messages, "search_items")
        if item_result is None:
            return self._tool("search_items", query=item_text)
        if not item_result.get("ok"):
            return LLMResponse(content="Не удалось выполнить поиск предмета.")
        candidates = item_result["result"]
        if not candidates:
            return LLMResponse(content=f"Не нашёл в каталоге: {item_text}.")
        if len(candidates) > 1:
            names = ", ".join(candidate["name"] for candidate in candidates[:3])
            return LLMResponse(content=f"Нашёл несколько вариантов: {names}. Уточни.")
        candidate = candidates[0]
        path = candidate.get("location_path")
        if path:
            return LLMResponse(content=f"{candidate['name']}: {path}.")
        return LLMResponse(content=f"Для {candidate['name']} место сейчас не указано.")

    def _move(
        self,
        messages: Sequence[AgentMessage],
        verb: str,
        item_text: str,
        location_text: str,
    ) -> LLMResponse:
        mutation = self._latest_mutation_result(messages)
        if mutation is not None:
            if mutation.get("ok"):
                item = mutation["result"]
                return LLMResponse(
                    content=f"Запомнил: {item['name']} → {item.get('location_path') or 'место не указано'}."
                )
            return LLMResponse(content="Не удалось изменить запись; требуется уточнение.")

        item_result = self._latest_tool_result(messages, "search_items")
        if item_result is None:
            return self._tool("search_items", query=item_text)
        if not item_result.get("ok"):
            return LLMResponse(content="Не удалось выполнить поиск предмета.")
        item_candidates = item_result["result"]
        if len(item_candidates) > 1:
            names = ", ".join(candidate["name"] for candidate in item_candidates[:3])
            return LLMResponse(content=f"Какой именно предмет: {names}?")
        if not item_candidates and verb.startswith("перелож"):
            return LLMResponse(content=f"Не нашёл существующий предмет: {item_text}.")

        location_result = self._latest_tool_result(messages, "search_locations")
        if location_result is None:
            return self._tool("search_locations", query=location_text)
        if not location_result.get("ok"):
            return LLMResponse(content="Не удалось выполнить поиск места.")
        location_candidates = location_result["result"]
        if not location_candidates:
            return LLMResponse(content=f"Не нашёл место: {location_text}.")
        if len(location_candidates) > 1:
            paths = ", ".join(candidate.get("path") or candidate["name"] for candidate in location_candidates[:3])
            return LLMResponse(content=f"Какое именно место: {paths}?")

        location_id = location_candidates[0]["id"]
        if item_candidates:
            return self._tool(
                "move_item",
                item_id=item_candidates[0]["id"],
                location_id=location_id,
            )
        return self._tool(
            "create_item",
            name=item_text,
            location_id=location_id,
        )

    def _tool(self, tool_name: str, **arguments: object) -> LLMResponse:
        call_id = f"heuristic-{self._next_call_id}"
        self._next_call_id += 1
        return LLMResponse(
            tool_calls=(ToolCall(id=call_id, name=tool_name, arguments=dict(arguments)),)
        )

    @staticmethod
    def _current_user_text(messages: Sequence[AgentMessage]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        return ""

    @staticmethod
    def _latest_tool_result(
        messages: Sequence[AgentMessage], tool_name: str
    ) -> dict[str, object] | None:
        for message in reversed(messages):
            if message.role == "tool" and message.tool_name == tool_name:
                return json.loads(message.content)
        return None

    @staticmethod
    def _latest_mutation_result(
        messages: Sequence[AgentMessage],
    ) -> dict[str, object] | None:
        for message in reversed(messages):
            if message.role == "tool" and message.tool_name in {"move_item", "create_item"}:
                return json.loads(message.content)
        return None
