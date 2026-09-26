"""Isolation, structured output, and timeout coverage for the CLI experiment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import textwrap
import time

import pytest

from ah_there_it_is.agent.codex_credentials import (
    ChatGPTCredentials,
    StaticChatGPTCredentialSource,
)
from ah_there_it_is.agent.codex_exec import (
    CodexExecConfig,
    CodexExecLLMClient,
    UnexpectedCodexToolError,
    _decode_structured_result,
    _output_schema,
    parse_codex_exec_jsonl,
)
from ah_there_it_is.agent.errors import ProviderProtocolError, ProviderRequestError
from ah_there_it_is.agent.protocol import AgentMessage, ToolDefinition


TOKEN = "exec-test-access-secret"
TOOL = ToolDefinition(
    name="inspect",
    description="Synthetic test tool",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)


def _fake_cli(tmp_path: Path, code: str) -> Path:
    executable = tmp_path / "codex-fake"
    executable.write_text(f"#!{sys.executable}\n" + textwrap.dedent(code))
    executable.chmod(0o700)
    return executable


def _provider(executable: Path, *, timeout: float = 5, max_output: int = 1_000_000, source=None):
    return CodexExecLLMClient(
        CodexExecConfig(
            model="gpt-test",
            timeout_seconds=timeout,
            max_output_bytes=max_output,
            binary=str(executable),
            codex_home=executable.parent / "codex-home",
        ),
        credential_source=source or StaticChatGPTCredentialSource(
            ChatGPTCredentials(TOKEN, "exec-test-account")
        ),
    )


def test_argv_environment_and_strict_schema_are_isolated(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "codex"
    executable.touch()
    executable.chmod(0o700)
    provider = CodexExecLLMClient(CodexExecConfig(
        model="gpt-test",
        binary=str(executable),
        codex_home=tmp_path / "codex-home",
    ))
    schema_path = tmp_path / "schema.json"
    argv = provider._argv(executable, tmp_path, schema_path)
    environment = provider._environment(executable)
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", "sqlite:///sensitive.db")
    monkeypatch.setenv("AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "platform-secret")

    assert "--ephemeral" in argv
    assert "--json" in argv
    assert "--ignore-user-config" in argv and "--ignore-rules" in argv
    assert "--skip-git-repo-check" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--cd") + 1] == str(tmp_path)
    assert argv[-1] == "-"
    assert set(environment) == {"PATH", "HOME", "CODEX_HOME", "LANG"}
    assert "sensitive.db" not in repr(environment)
    assert "telegram-secret" not in repr(environment)
    assert "platform-secret" not in repr(environment)
    schema = _output_schema([TOOL])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["tool_calls"]["items"]["additionalProperties"] is False


def test_fake_exec_uses_empty_temp_cwd_and_returns_structured_tool_call(tmp_path: Path, monkeypatch) -> None:
    script = _fake_cli(tmp_path, """
        import json, os, pathlib, sys
        argv = sys.argv[1:]
        schema_path = pathlib.Path(argv[argv.index("--output-schema") + 1])
        answer = {
            "content": "",
            "tool_calls": [{
                "name": "inspect",
                "arguments_json": json.dumps({
                    "cwd": os.getcwd(),
                    "files": sorted(path.name for path in pathlib.Path.cwd().iterdir()),
                    "argv": argv,
                    "env_keys": sorted(os.environ),
                    "schema": json.loads(schema_path.read_text()),
                }),
            }],
        }
        print(json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(answer)},
        }))
    """)
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", "sqlite:///secret.db")
    monkeypatch.setenv("OPENAI_API_KEY", "api-secret")
    captured = {}
    import subprocess

    def popen(*args, **kwargs):
        captured.update({"args": args, "kwargs": kwargs})
        return subprocess.Popen(*args, **kwargs)

    provider = CodexExecLLMClient(
        CodexExecConfig(
            model="gpt-test",
            binary=str(script),
            codex_home=tmp_path / "codex-home",
        ),
        credential_source=StaticChatGPTCredentialSource(
            ChatGPTCredentials(TOKEN, "account-secret")
        ),
        popen=popen,
    )
    result = provider.complete([AgentMessage(role="user", content="audit")], [TOOL])
    arguments = result.tool_calls[0].arguments

    assert result.content == ""
    assert result.tool_calls[0].name == "inspect"
    assert Path(arguments["cwd"]).name.startswith("ah-there-it-is-codex-exec-")
    assert arguments["files"] == ["output-schema.json"]
    assert "--ephemeral" in arguments["argv"]
    assert arguments["argv"][arguments["argv"].index("--sandbox") + 1] == "read-only"
    assert arguments["env_keys"] == ["CODEX_HOME", "HOME", "LANG", "PATH"]
    assert arguments["schema"]["properties"]["tool_calls"]["type"] == "array"
    kwargs = captured["kwargs"]
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is (os.name == "posix")
    assert Path(kwargs["cwd"]) != Path.cwd()
    assert "AH_THERE_IT_IS_DATABASE_URL" not in kwargs["env"]
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert TOKEN not in repr(provider.info)
    assert result.metadata["internal_tool_events"] == 0


def test_jsonl_final_message_and_structured_tool_call_parsing() -> None:
    output = "\n".join([
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps({
                    "content": "",
                    "tool_calls": [{
                        "name": "inspect",
                        "arguments_json": '{"value":7}',
                    }],
                }),
            },
        }),
        json.dumps({"type": "turn.completed"}),
    ])
    final = parse_codex_exec_jsonl(output)
    result = _decode_structured_result(
        final, allowed_tools={"inspect"}, call_prefix="test",
    )
    assert result["tool_calls"][0].id == "test_1"
    assert result["tool_calls"][0].arguments == {"value": 7}


@pytest.mark.parametrize("output", [
    "not-json",
    json.dumps({"type": "strange.event"}),
    json.dumps({
        "type": "item.started",
        "item": {"type": "command_execution", "command": "id"},
    }),
])
def test_jsonl_malformed_unknown_and_internal_tool_events_fail(output: str) -> None:
    expected = UnexpectedCodexToolError if "command_execution" in output else ProviderProtocolError
    with pytest.raises(expected):
        parse_codex_exec_jsonl(output)


@pytest.mark.parametrize("raw, message", [
    ('{"content":1,"tool_calls":[]}', "invalid structured"),
    ('{"content":"","tool_calls":[{"name":"bad","arguments_json":"{}"}]}', "unknown structured"),
    ('{"content":"","tool_calls":[{"name":"inspect","arguments_json":"["}]}', "malformed tool arguments"),
    ('{"content":"","tool_calls":[{"name":"inspect","arguments_json":"[]"}]}', "JSON object"),
])
def test_structured_output_rejects_malformed_or_unknown_results(raw: str, message: str) -> None:
    with pytest.raises(ProviderProtocolError, match=message):
        _decode_structured_result(raw, allowed_tools={"inspect"}, call_prefix="x")


def test_unexpected_internal_command_event_terminates_process_group(tmp_path: Path) -> None:
    script = _fake_cli(tmp_path, """
        import json, subprocess, time
        subprocess.Popen(["/bin/sleep", "20"])
        print(json.dumps({
            "type": "item.started",
            "item": {"type": "command_execution", "command": "sleep 20"},
        }), flush=True)
        time.sleep(20)
    """)
    provider = _provider(script, timeout=5)
    started = time.monotonic()
    with pytest.raises(UnexpectedCodexToolError) as raised:
        provider.complete([AgentMessage(role="user", content="INTERNAL_TOOL")], [])
    assert raised.value.tool_event_count >= 1
    assert time.monotonic() - started < 4


def test_exec_timeout_and_bounded_output(tmp_path: Path) -> None:
    sleeping = _fake_cli(tmp_path, """
        import time
        time.sleep(20)
    """)
    provider = _provider(sleeping, timeout=0.1)
    started = time.monotonic()
    with pytest.raises(ProviderRequestError, match="timed out"):
        provider.complete([AgentMessage(role="user", content="wait")], [])
    assert time.monotonic() - started < 3

    noisy = _fake_cli(tmp_path, """
        import sys
        sys.stdout.write("x" * 1000000)
        sys.stdout.flush()
    """)
    provider = _provider(noisy, timeout=3, max_output=1024)
    with pytest.raises(ProviderProtocolError, match="output exceeded size limit"):
        provider.complete([AgentMessage(role="user", content="noise")], [])


def test_nonzero_exec_error_redacts_cached_credentials(tmp_path: Path) -> None:
    script = _fake_cli(tmp_path, f"""
        import sys
        sys.stderr.write({TOKEN!r})
        raise SystemExit(9)
    """)
    provider = _provider(
        script,
        source=StaticChatGPTCredentialSource(ChatGPTCredentials(TOKEN, "exec-test-account")),
    )
    with pytest.raises(ProviderRequestError) as raised:
        provider.complete([AgentMessage(role="user", content="fail")], [])
    assert "status 9" in str(raised.value)
    assert TOKEN not in str(raised.value)
