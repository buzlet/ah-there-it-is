"""Manual live probes for the isolated ChatGPT Codex provider experiments.

Run with python -m ah_there_it_is.agent.provider_probe. This module is not part
of normal application startup and does not use inventory or production DBs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

from ah_there_it_is.agent.chatgpt_codex import ChatGPTCodexConfig, ChatGPTCodexLLMClient
from ah_there_it_is.agent.codex_exec import (
    CodexExecConfig,
    CodexExecLLMClient,
    UnexpectedCodexToolError,
)
from ah_there_it_is.agent.codex_credentials import CodexAuthFileCredentialSource
from ah_there_it_is.agent.protocol import AgentMessage, LLMResponse, ToolDefinition


TOOL = ToolDefinition(
    name="lookup_item",
    description="Look up a synthetic read-only inventory item by its name.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
)
_PROBE_SYSTEM = (
    "You are doing a small provider compatibility probe. Follow the user instruction "
    "exactly. Do not invent any real inventory data."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("direct", "exec"), required=True)
    parser.add_argument(
        "--scenario",
        choices=("text", "tool-selection", "multi-round", "no-tool"),
        required=True,
    )
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1 or args.repeat > 5:
        parser.error("--repeat must be between 1 and 5")

    source = CodexAuthFileCredentialSource()
    if args.provider == "direct":
        client = ChatGPTCodexLLMClient(ChatGPTCodexConfig(model=args.model), credential_source=source)
    else:
        client = CodexExecLLMClient(CodexExecConfig(model=args.model), credential_source=source)

    outcomes = []
    try:
        for index in range(args.repeat):
            started = time.perf_counter()
            try:
                detail = run_scenario(client, args.scenario)
                outcome = {
                    "provider": args.provider,
                    "scenario": args.scenario,
                    "iteration": index + 1,
                    "model": client.info.model,
                    "backend": client.info.config.get("backend"),
                    "success": True,
                    "wall_seconds": round(time.perf_counter() - started, 6),
                    **detail,
                }
            except Exception as exc:
                outcome = {
                    "provider": args.provider,
                    "scenario": args.scenario,
                    "iteration": index + 1,
                    "model": client.info.model,
                    "backend": client.info.config.get("backend"),
                    "success": False,
                    "wall_seconds": round(time.perf_counter() - started, 6),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:800],
                    "internal_tool_events": (
                        exc.tool_event_count
                        if isinstance(exc, UnexpectedCodexToolError)
                        else 0 if args.provider == "exec" else None
                    ),
                }
            outcomes.append(outcome)
            print(json.dumps(outcome, ensure_ascii=True, sort_keys=True))
    finally:
        if isinstance(client, ChatGPTCodexLLMClient):
            client.close()
    elapsed = [item["wall_seconds"] for item in outcomes]
    successes = sum(item["success"] for item in outcomes)
    print(json.dumps({
        "summary": True,
        "provider": args.provider,
        "scenario": args.scenario,
        "model": args.model,
        "successes": successes,
        "attempts": len(outcomes),
        "median_wall_seconds": round(statistics.median(elapsed), 6),
    }, sort_keys=True))
    return 0 if successes == len(outcomes) else 2


def run_scenario(client, scenario: str) -> dict[str, object]:
    if scenario == "text":
        response = client.complete(
            [
                AgentMessage(role="system", content="Reply briefly and do not call tools."),
                AgentMessage(role="user", content="Reply with the exact marker LANPROBE-27."),
            ],
            [],
        )
        if not response.content.strip() or response.tool_calls:
            raise RuntimeError("text scenario did not produce final text")
        if "LANPROBE-27" not in response.content:
            raise RuntimeError("text scenario omitted the requested marker")
        return _response_outcome(response, marker="LANPROBE-27")

    if scenario == "tool-selection":
        response = client.complete(
            [
                AgentMessage(role="system", content=_PROBE_SYSTEM),
                AgentMessage(
                    role="user",
                    content="Где находится предмет «синий кабель для теста»? "
                    "Найди его через доступный инструмент.",
                ),
            ],
            [TOOL],
        )
        calls = [call for call in response.tool_calls if call.name == TOOL.name]
        if not calls:
            raise RuntimeError("tool-selection scenario did not return a structured tool call")
        return _response_outcome(response)

    if scenario == "no-tool":
        response = client.complete(
            [
                AgentMessage(role="system", content=_PROBE_SYSTEM),
                AgentMessage(role="user", content="Сколько будет 2 + 2? Ответь кратко."),
            ],
            [TOOL],
        )
        if not response.content.strip() or response.tool_calls:
            raise RuntimeError("no-tool scenario did not return plain text")
        return _response_outcome(response)

    if scenario == "multi-round":
        messages = [
            AgentMessage(role="system", content=_PROBE_SYSTEM),
            AgentMessage(
                role="user",
                content="Где находится предмет «синий кабель для теста»? "
                "Используй доступный инструмент, затем ответь по его результату.",
            ),
        ]
        first = client.complete(messages, [TOOL])
        calls = [call for call in first.tool_calls if call.name == TOOL.name]
        if not calls:
            raise RuntimeError("multi-round first call did not select lookup_item")
        messages.append(AgentMessage(
            role="assistant",
            content=first.content,
            tool_calls=first.tool_calls,
        ))
        for call in calls:
            messages.append(AgentMessage(
                role="tool",
                tool_call_id=call.id,
                tool_name=call.name,
                content=json.dumps({
                    "ok": True,
                    "item": "синий кабель для теста",
                    "location": "синтетическая полка «probe shelf»",
                }, ensure_ascii=False),
            ))
        second = client.complete(messages, [TOOL])
        if not second.content.strip() or second.tool_calls:
            raise RuntimeError("multi-round continuation did not return final text")
        mentions_location = (
            "probe shelf" in second.content.lower()
            or "синтетическая полка" in second.content.lower()
            or "полка" in second.content.lower()
        )
        if not mentions_location:
            raise RuntimeError("multi-round continuation omitted the synthetic location")
        return {
            "rounds": 2,
            "first_round_tool_call_count": len(calls),
            "tool_names": [call.name for call in calls],
            "final_text_length": len(second.content),
            "mentions_synthetic_location": mentions_location,
            "round_wall_seconds": [
                _response_wall(first),
                _response_wall(second),
            ],
        }
    raise ValueError("unknown scenario")


def _response_wall(response: LLMResponse):
    transport = response.metadata.get("transport")
    if isinstance(transport, dict):
        return transport.get("client_wall_seconds")
    return response.metadata.get("total_wall_seconds")


def _response_outcome(response: LLMResponse, *, marker: str | None = None) -> dict[str, object]:
    transport = response.metadata.get("transport")
    transport = transport if isinstance(transport, dict) else {}
    return {
        "text_length": len(response.content),
        "marker_present": marker in response.content if marker else None,
        "tool_calls": [
            {"name": call.name, "argument_keys": sorted(call.arguments)}
            for call in response.tool_calls
        ],
        "request_attempts": transport.get("attempts", 1),
        "provider_wall_seconds": _response_wall(response),
        "process_start_seconds": response.metadata.get("process_start_seconds"),
        "first_stdout_byte_seconds": response.metadata.get("first_stdout_byte_seconds"),
        "internal_tool_events": response.metadata.get("internal_tool_events", 0),
    }


if __name__ == "__main__":
    raise SystemExit(main())
