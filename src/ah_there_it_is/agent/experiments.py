"""Controlled prompt/model replay against captured tool evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ah_there_it_is.agent.errors import AgentLoopLimitError
from ah_there_it_is.agent.protocol import AgentMessage, LLMClient
from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.db.models import AgentRunLog, ExperimentRun
from ah_there_it_is.services.experiments import ExperimentService


class ReplayDivergenceError(RuntimeError):
    """A variant requested tool evidence unavailable in the captured source run."""


@dataclass(frozen=True)
class ExperimentRunResult:
    experiment_run_id: int
    status: str
    content: str | None
    rounds: int
    divergence_reason: str | None = None


class CapturedEvidenceReplay:
    """Replay source tool results in exact captured order without touching live data."""

    def __init__(self, source_trace: list[dict[str, Any]]) -> None:
        self._evidence = [
            entry
            for round_trace in source_trace
            for entry in round_trace.get("tool_results", [])
        ]
        self._cursor = 0

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._cursor >= len(self._evidence):
            raise ReplayDivergenceError(
                f"variant requested extra tool call {name}({self._canonical(arguments)})"
            )
        expected = self._evidence[self._cursor]
        expected_name = expected.get("tool_name")
        expected_arguments = expected.get("arguments") or {}
        if expected_name != name or self._canonical(expected_arguments) != self._canonical(arguments):
            raise ReplayDivergenceError(
                "tool sequence diverged at evidence index "
                f"{self._cursor}: expected {expected_name}({self._canonical(expected_arguments)}), "
                f"got {name}({self._canonical(arguments)})"
            )
        self._cursor += 1
        result = expected.get("result")
        if not isinstance(result, dict):
            raise ReplayDivergenceError("captured tool result is not an object")
        return result

    @staticmethod
    def _canonical(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ExperimentRunner:
    """Run a variant model/prompt without mutating inventory or conversation history."""

    def __init__(self, session: Session, llm: LLMClient, *, max_rounds: int = 8) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.session = session
        self.llm = llm
        self.max_rounds = max_rounds
        self.service = ExperimentService(session)

    def run(
        self,
        source: AgentRunLog,
        *,
        experiment_name: str,
        system_prompt: str,
        prompt_version: str,
    ) -> ExperimentRunResult:
        input_messages = self._variant_input(source.input_messages, system_prompt)
        messages = [AgentMessage.model_validate(message) for message in input_messages]
        definitions = ToolDispatcher(self.session).definitions()
        evidence = CapturedEvidenceReplay(source.tool_trace)
        tool_trace: list[dict[str, Any]] = []
        rounds = 0

        try:
            for round_number in range(1, self.max_rounds + 1):
                rounds = round_number
                response = self.llm.complete(messages, definitions)
                round_trace: dict[str, Any] = {
                    "round": round_number,
                    "assistant": {
                        "content": response.content,
                        "tool_calls": [call.model_dump(mode="json") for call in response.tool_calls],
                        "metadata": response.metadata,
                    },
                    "tool_results": [],
                }
                tool_trace.append(round_trace)
                messages.append(
                    AgentMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )
                if not response.tool_calls:
                    return self._persist(
                        source=source,
                        experiment_name=experiment_name,
                        system_prompt=system_prompt,
                        prompt_version=prompt_version,
                        input_messages=input_messages,
                        tool_trace=tool_trace,
                        final_content=response.content.strip(),
                        rounds=round_number,
                        status="completed",
                    )

                for call in response.tool_calls:
                    try:
                        result = evidence.execute(call.name, call.arguments)
                    except ReplayDivergenceError as exc:
                        round_trace["tool_results"].append(
                            {
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "arguments": call.arguments,
                                "diverged": True,
                                "reason": str(exc),
                            }
                        )
                        return self._persist(
                            source=source,
                            experiment_name=experiment_name,
                            system_prompt=system_prompt,
                            prompt_version=prompt_version,
                            input_messages=input_messages,
                            tool_trace=tool_trace,
                            final_content=None,
                            rounds=round_number,
                            status="diverged",
                            divergence_reason=str(exc),
                        )
                    round_trace["tool_results"].append(
                        {
                            "tool_call_id": call.id,
                            "tool_name": call.name,
                            "arguments": call.arguments,
                            "result": result,
                            "source": "captured_evidence",
                        }
                    )
                    messages.append(
                        AgentMessage(
                            role="tool",
                            content=ToolDispatcher.as_tool_message_content(result),
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )

            raise AgentLoopLimitError(
                f"experiment exceeded max_rounds={self.max_rounds} without a final response"
            )
        except Exception as exc:
            if isinstance(exc, ReplayDivergenceError):
                raise
            result = self._persist(
                source=source,
                experiment_name=experiment_name,
                system_prompt=system_prompt,
                prompt_version=prompt_version,
                input_messages=input_messages,
                tool_trace=tool_trace,
                final_content=None,
                rounds=rounds,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return result

    def _persist(
        self,
        *,
        source: AgentRunLog,
        experiment_name: str,
        system_prompt: str,
        prompt_version: str,
        input_messages: list[dict[str, Any]],
        tool_trace: list[dict[str, Any]],
        final_content: str | None,
        rounds: int,
        status: str,
        error: str | None = None,
        divergence_reason: str | None = None,
    ) -> ExperimentRunResult:
        info = self.llm.info
        run: ExperimentRun = self.service.record_run(
            source_run_id=source.id,
            experiment_name=experiment_name,
            prompt_version=prompt_version,
            prompt_hash=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
            system_prompt=system_prompt,
            llm_provider=info.provider,
            llm_model=info.model,
            llm_config=info.config,
            input_messages=input_messages,
            tool_trace=tool_trace,
            final_content=final_content,
            rounds=rounds,
            status=status,
            error=error,
            divergence_reason=divergence_reason,
        )
        return ExperimentRunResult(
            experiment_run_id=run.id,
            status=status,
            content=final_content,
            rounds=rounds,
            divergence_reason=divergence_reason,
        )

    @staticmethod
    def _variant_input(
        source_input: list[dict[str, Any]], system_prompt: str
    ) -> list[dict[str, Any]]:
        messages = [dict(message) for message in source_input]
        if messages and messages[0].get("role") == "system":
            messages[0] = {"role": "system", "content": system_prompt, "tool_calls": ()}
        else:
            messages.insert(0, {"role": "system", "content": system_prompt, "tool_calls": ()})
        return messages
