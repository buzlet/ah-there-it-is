"""Experimental, isolated codex exec adapter.

The CLI owns its OAuth/backend interaction. This adapter asks it for strict JSON
describing generic text/tool calls and never gives it application tools.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

from pydantic import ValidationError

from ah_there_it_is.agent.codex_credentials import (
    ChatGPTCredentialSource,
    CodexAuthFileCredentialSource,
)
from ah_there_it_is.agent.errors import ProviderProtocolError, ProviderRequestError
from ah_there_it_is.agent.metadata import redact_sensitive_text
from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClientInfo,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)


_MAX_PROMPT_BYTES = 1024 * 1024
_ALLOWED_ITEM_TYPES = {"agent_message", "reasoning"}
_ALLOWED_EVENT_TYPES = {
    "thread.started", "turn.started", "turn.completed", "turn.failed", "error",
    "item.started", "item.updated", "item.completed",
}


@dataclass(frozen=True)
class CodexExecConfig:
    model: str
    timeout_seconds: float = 90.0
    max_output_bytes: int = 1024 * 1024
    binary: str = "codex"
    codex_home: Path | str | None = None


class UnexpectedCodexToolError(ProviderRequestError):
    """The CLI attempted an internal tool that is outside this adapter contract."""

    def __init__(self, tool_event_count: int = 1) -> None:
        self.tool_event_count = tool_event_count
        super().__init__("codex exec attempted internal tool execution")


class CodexExecLLMClient:
    """Run an isolated, read-only, ephemeral Codex CLI call per completion."""

    def __init__(
        self,
        config: CodexExecConfig,
        *,
        credential_source: ChatGPTCredentialSource | None = None,
        popen=subprocess.Popen,
    ) -> None:
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if config.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be > 0")
        self.config = config
        self._credential_source = credential_source or CodexAuthFileCredentialSource()
        self._popen = popen
        self._codex_home = Path(
            config.codex_home
            or os.environ.get("CODEX_HOME", Path.home() / ".codex")
        ).expanduser()
        self._call_number = 0

    @property
    def info(self) -> LLMClientInfo:
        return LLMClientInfo(
            provider="codex-exec-experiment",
            model=self.config.model,
            config={
                "backend": "installed-codex-cli",
                "transport": "ephemeral-jsonl-subprocess",
                "sandbox": "read-only",
                "timeout_seconds": self.config.timeout_seconds,
                "max_output_bytes": self.config.max_output_bytes,
            },
        )

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        prompt = self._prompt(messages, tools)
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise ProviderProtocolError("codex exec prompt exceeded size limit")
        self._call_number += 1
        try:
            credentials = self._credential_source.get()
            redaction_secrets = (credentials.access_token, credentials.account_id or "")
        except Exception:
            # Codex can also read an OS keyring. The source here only supplies
            # best-effort error redaction and is not used to authenticate CLI.
            redaction_secrets = ()

        executable = shutil.which(self.config.binary)
        if executable is None:
            raise ProviderRequestError("codex executable is unavailable")
        schema = _output_schema(tools)
        with tempfile.TemporaryDirectory(prefix="ah-there-it-is-codex-exec-") as scratch:
            working_dir = Path(scratch)
            schema_path = working_dir / "output-schema.json"
            schema_path.write_text(json.dumps(schema, separators=(",", ":")))
            command = self._argv(Path(executable), working_dir, schema_path)
            environment = self._environment(Path(executable))
            try:
                returncode, stdout, stderr, process_data = _run_process(
                    self._popen,
                    command,
                    prompt,
                    environment,
                    working_dir,
                    timeout_seconds=self.config.timeout_seconds,
                    max_output_bytes=self.config.max_output_bytes,
                )
            except TimeoutError:
                raise ProviderRequestError("codex exec timed out and was terminated") from None
            except UnexpectedCodexToolError:
                raise
            except ProviderProtocolError:
                raise
            except Exception:
                raise ProviderRequestError("codex exec could not be completed") from None

        if process_data["output_overflow"]:
            raise ProviderProtocolError("codex exec output exceeded size limit")
        if returncode != 0:
            detail = ""
            if redaction_secrets:
                detail = redact_sensitive_text(
                    stderr.decode("utf-8", errors="replace")[:1200],
                    redaction_secrets,
                )
            raise ProviderRequestError(
                f"codex exec exited with status {returncode}"
                + (f": {detail}" if detail.strip() else "")
            )
        result_text = parse_codex_exec_jsonl(
            stdout.decode("utf-8", errors="replace"),
        )
        payload = _decode_structured_result(
            result_text,
            allowed_tools={tool.name for tool in tools},
            call_prefix=f"codex_exec_{self._call_number}",
        )
        return LLMResponse(
            content=payload["content"],
            tool_calls=tuple(payload["tool_calls"]),
            metadata={
                "transport": "ephemeral-jsonl-subprocess",
                "total_wall_seconds": process_data["total_wall_seconds"],
                "process_start_seconds": process_data["process_start_seconds"],
                "first_stdout_byte_seconds": process_data["first_stdout_byte_seconds"],
                "internal_tool_events": 0,
            },
        )

    def _argv(self, executable: Path, cwd: Path, schema: Path) -> list[str]:
        return [
            str(executable), "exec",
            "--ephemeral",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox", "read-only",
            "--cd", str(cwd),
            "--model", self.config.model,
            "--output-schema", str(schema),
            "-",
        ]

    def _environment(self, executable: Path) -> dict[str, str]:
        # Only runtime essentials and Codex's own credential-home selector cross
        # the boundary. App DB, bot, provider, and API-key settings are excluded.
        path_parts = [str(executable.parent), os.defpath]
        return {
            "PATH": os.pathsep.join(dict.fromkeys(path_parts)),
            "HOME": str(Path.home()),
            "CODEX_HOME": str(self._codex_home),
            "LANG": "C.UTF-8",
        }

    def _prompt(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> str:
        self_messages = [message.model_dump(mode="json") for message in messages]
        tool_data = [tool.model_dump(mode="json") for tool in tools]
        return (
            "You are acting only as a model-call adapter. Do not inspect or change files, "
            "run commands, use web search, MCP, collaboration, or any internal tool. "
            "Return only the JSON object required by the supplied output schema. "
            "Choose application tools by returning tool_calls; do not execute them. "
            "Use the full messages array as conversation history and the tools array as "
            "the only available application tools. For a final answer, set content and "
            "return an empty tool_calls array. For tool calls, return empty content unless "
            "a brief assistant message is needed. Tool arguments must be JSON objects "
            "encoded in arguments_json.\n\n"
            "MESSAGES_JSON:\n" + json.dumps(self_messages, ensure_ascii=False) +
            "\n\nTOOLS_JSON:\n" + json.dumps(tool_data, ensure_ascii=False)
        )


def _output_schema(tools: Sequence[ToolDefinition]) -> dict[str, Any]:
    name_schema: dict[str, Any] = {"type": "string", "enum": [tool.name for tool in tools]}
    if not tools:
        name_schema = {"type": "string", "enum": [""]}
    call_schema = {
        "type": "object",
        "properties": {
            "name": name_schema,
            "arguments_json": {"type": "string"},
        },
        "required": ["name", "arguments_json"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "tool_calls": {"type": "array", "items": call_schema},
        },
        "required": ["content", "tool_calls"],
        "additionalProperties": False,
    }


def parse_codex_exec_jsonl(
    output: str,
) -> str:
    """Extract the final agent message and reject internal tool activity."""
    messages: list[str] = []
    unexpected_count = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            raise ProviderProtocolError("codex exec emitted malformed JSONL") from None
        if not isinstance(event, dict):
            raise ProviderProtocolError("codex exec emitted an invalid JSONL event")
        event_type = event.get("type")
        item = event.get("item")
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise ProviderProtocolError("codex exec emitted an unexpected event type")
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type not in _ALLOWED_ITEM_TYPES:
                unexpected_count += 1
                continue
            if item_type == "agent_message" and event_type in (
                "item.completed", "item.updated", "item.started",
            ):
                text = item.get("text")
                if isinstance(text, str):
                    messages.append(text)
        if event_type == "error":
            raise ProviderRequestError("codex exec emitted an error event")
    if unexpected_count:
        raise UnexpectedCodexToolError(unexpected_count)
    if not messages:
        raise ProviderProtocolError("codex exec produced no final agent message")
    return messages[-1]


def _decode_structured_result(
    raw: str,
    *,
    allowed_tools: set[str],
    call_prefix: str,
) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ProviderProtocolError("codex exec returned malformed structured output") from None
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"content", "tool_calls"}
        or not isinstance(parsed["content"], str)
        or not isinstance(parsed["tool_calls"], list)
    ):
        raise ProviderProtocolError("codex exec returned invalid structured output")
    calls: list[ToolCall] = []
    for index, call in enumerate(parsed["tool_calls"], start=1):
        if (
            not isinstance(call, dict)
            or set(call) != {"name", "arguments_json"}
            or not isinstance(call["name"], str)
            or call["name"] not in allowed_tools
            or not isinstance(call["arguments_json"], str)
        ):
            raise ProviderProtocolError("codex exec returned an unknown structured tool call")
        try:
            arguments = json.loads(call["arguments_json"])
        except json.JSONDecodeError:
            raise ProviderProtocolError("codex exec returned malformed tool arguments") from None
        if not isinstance(arguments, dict):
            raise ProviderProtocolError("codex exec tool arguments must be a JSON object")
        try:
            calls.append(ToolCall(
                id=f"{call_prefix}_{index}",
                name=call["name"],
                arguments=arguments,
            ))
        except ValidationError:
            raise ProviderProtocolError("codex exec returned invalid tool arguments") from None
    return {"content": parsed["content"], "tool_calls": calls}


def _event_has_unexpected_tool(line: bytes) -> bool:
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(event, dict):
        return False
    item = event.get("item")
    if isinstance(item, dict):
        item_type = item.get("type")
        return item_type not in _ALLOWED_ITEM_TYPES
    return event.get("type") not in _ALLOWED_EVENT_TYPES


def _run_process(
    popen,
    command: list[str],
    prompt: str,
    environment: dict[str, str],
    cwd: Path,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[int, bytes, bytes, dict[str, Any]]:
    """Launch with bounded readers and kill the entire process group on timeout/tool use."""
    started = time.perf_counter()
    spawn_started = time.perf_counter()
    process = popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=(os.name == "posix"),
    )
    process_start_seconds = time.perf_counter() - spawn_started
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = threading.Event()
    tool_event_count = 0
    first_stdout_byte: float | None = None
    stdout_lines = bytearray()
    lock = threading.Lock()

    def drain(name: str, stream) -> None:
        nonlocal tool_event_count, first_stdout_byte
        while True:
            read_chunk = getattr(stream, "read1", stream.read)
            chunk = read_chunk(4096)
            if not chunk:
                return
            if name == "stdout" and first_stdout_byte is None:
                first_stdout_byte = time.perf_counter() - started
            target = buffers[name]
            remaining = max_output_bytes - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(chunk) > max(0, remaining):
                overflow.set()
            if name == "stdout":
                with lock:
                    if not overflow.is_set() and len(stdout_lines) + len(chunk) <= max_output_bytes:
                        stdout_lines.extend(chunk)
                    while True:
                        newline = stdout_lines.find(b"\n")
                        if newline < 0:
                            break
                        line = bytes(stdout_lines[:newline])
                        del stdout_lines[: newline + 1]
                        if _event_has_unexpected_tool(line):
                            tool_event_count += 1

    stdout_thread = threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True)
    stderr_thread = threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    def write_prompt() -> None:
        assert process.stdin is not None
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
        except (BrokenPipeError, OSError):
            return

    stdin_thread = threading.Thread(target=write_prompt, daemon=True)
    stdin_thread.start()
    deadline = started + timeout_seconds
    terminated_for_tool = False
    terminated_for_overflow = False
    while process.poll() is None:
        with lock:
            if tool_event_count:
                terminated_for_tool = True
        if terminated_for_tool:
            _terminate_process_group(process)
            break
        if overflow.is_set():
            terminated_for_overflow = True
            _terminate_process_group(process)
            break
        if time.perf_counter() >= deadline:
            _terminate_process_group(process)
            process.wait()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            stdin_thread.join(timeout=1)
            raise TimeoutError
        time.sleep(0.01)
    returncode = process.wait()
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    stdin_thread.join(timeout=1)
    if terminated_for_tool:
        raise UnexpectedCodexToolError(tool_event_count)
    if tool_event_count:
        raise UnexpectedCodexToolError(tool_event_count)
    if terminated_for_overflow:
        raise ProviderProtocolError("codex exec output exceeded size limit")
    return returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"]), {
        "output_overflow": overflow.is_set(),
        "unexpected_tool_count": tool_event_count,
        "total_wall_seconds": round(time.perf_counter() - started, 6),
        "process_start_seconds": round(process_start_seconds, 6),
        "first_stdout_byte_seconds": (
            round(first_stdout_byte, 6) if first_stdout_byte is not None else None
        ),
    }


def _terminate_process_group(process) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError:
        process.kill()
