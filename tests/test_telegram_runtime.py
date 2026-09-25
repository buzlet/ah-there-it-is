from __future__ import annotations

from types import SimpleNamespace

import pytest

from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import Base
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.runtime_cli import build_parser, main
from ah_there_it_is.telegram.client import TelegramClientError
from ah_there_it_is.telegram.runtime import (
    TelegramRuntime,
    TelegramRuntimeConfigurationError,
    build_telegram_runtime,
    run_telegram_bot,
    validate_telegram_settings,
)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def bot_settings(tmp_path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{tmp_path / 'bot.db'}",
        "telegram_bot_token": "telegram-token-secret",
        "telegram_allowed_user_id": 7,
    }
    values.update(overrides)
    return Settings(**values)


def test_telegram_parser_has_explicit_bounded_poll_options() -> None:
    args = build_parser().parse_args(
        ["telegram-bot", "--poll-timeout", "12", "--limit", "19"]
    )

    assert args.command == "telegram-bot"
    assert args.poll_timeout == 12
    assert args.limit == 19


def test_missing_telegram_settings_fail_only_bot_command_without_echoing_token(
    monkeypatch, capsys
) -> None:
    from ah_there_it_is import runtime_cli

    settings = Settings(database_url="sqlite:///already-checked.db")
    gate_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(runtime_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_cli,
        "runtime_schema_gate",
        lambda url, *, command_name: gate_calls.append((url, command_name)),
    )

    assert main(["telegram-bot"]) == 2
    assert gate_calls == [(settings.database_url, "telegram-bot")]
    error = capsys.readouterr().err
    assert "Telegram bot token is required" in error
    assert "telegram-token-secret" not in error

    # Telegram settings remain optional for an ordinary command/import path.
    monkeypatch.setattr(runtime_cli, "runtime_paths", lambda _url: {"ok": True})
    assert main(["paths"]) == 0


def test_telegram_cli_runs_runtime_only_after_schema_gate(monkeypatch, tmp_path) -> None:
    from ah_there_it_is import runtime_cli
    import ah_there_it_is.telegram.runtime as module

    settings = bot_settings(tmp_path)
    order: list[str] = []
    monkeypatch.setattr(runtime_cli, "get_settings", lambda: settings)

    def gate(url: str, *, command_name: str):
        order.append(f"gate:{url}:{command_name}")
        return None

    monkeypatch.setattr(runtime_cli, "runtime_schema_gate", gate)

    def run(selected, *, poll_timeout: int, limit: int) -> int:
        order.append(f"run:{selected.telegram_bot_token}:{poll_timeout}:{limit}")
        return 0

    monkeypatch.setattr(module, "run_telegram_bot", run)

    assert main(["telegram-bot", "--poll-timeout", "9", "--limit", "11"]) == 0
    assert order == [
        f"gate:{settings.database_url}:telegram-bot",
        "run:telegram-token-secret:9:11",
    ]


def test_build_runtime_constructs_shared_application_and_closes_client(tmp_path) -> None:
    settings = bot_settings(tmp_path)
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    client = FakeTelegramClient()

    runtime = build_telegram_runtime(
        settings,
        session_factory=factory,
        llm_factory=lambda: SimpleNamespace(),
        telegram_client=client,
    )
    try:
        assert runtime.polling.adapter.client is client
        assert runtime.polling.adapter.allowed_user_id == 7
        assert runtime.polling.poll_timeout == 30
    finally:
        runtime.close()
        engine.dispose()
    assert client.closed is True


def test_build_runtime_loads_versioned_prompt_and_handles_client_without_close(tmp_path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("custom prompt", encoding="utf-8")
    settings = bot_settings(tmp_path, prompt_file=str(prompt_file))
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    runtime = build_telegram_runtime(
        settings,
        session_factory=factory,
        llm_factory=lambda: SimpleNamespace(),
        telegram_client=object(),
    )
    try:
        assert runtime.polling.adapter.source_identity == "telegram:7"
        assert runtime.polling.adapter.chat_service.system_prompt == "custom prompt"
    finally:
        runtime.close()
        runtime.close()
        engine.dispose()


def test_build_runtime_default_resources_and_constructor_failure_clean_up(tmp_path) -> None:
    settings = bot_settings(tmp_path)
    runtime = build_telegram_runtime(settings, llm_factory=lambda: SimpleNamespace())
    runtime.close()

    with pytest.raises(ValueError, match="poll_timeout"):
        build_telegram_runtime(
            settings,
            llm_factory=lambda: SimpleNamespace(),
            poll_timeout=51,
        )


def test_runtime_retries_bounded_transport_error_and_honors_stop_event(session) -> None:
    stop = __import__("threading").Event()
    sleeps: list[float] = []

    class Polling:
        def __init__(self) -> None:
            self.calls = 0

        def run_once(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise TelegramClientError("transient")
            stop.set()

    polling = Polling()
    settings = bot_settings(__import__("pathlib").Path("/tmp"))
    runtime = TelegramRuntime(
        settings=settings,
        session=session,
        client=FakeTelegramClient(),
        polling=polling,  # type: ignore[arg-type]
        sleep=sleeps.append,
    )

    runtime.run_forever(stop_event=stop)

    assert polling.calls == 2
    assert sleeps == [settings.telegram_retry_backoff_seconds]


def test_run_bot_handles_keyboard_interrupt_and_closes(monkeypatch, tmp_path) -> None:
    settings = bot_settings(tmp_path)
    state = {"closed": False}

    class Runtime:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            state["closed"] = True

        def run_forever(self, *, stop_event=None):
            raise KeyboardInterrupt

    def fake_builder(*_args, **_kwargs):
        return Runtime()

    import ah_there_it_is.telegram.runtime as module

    monkeypatch.setattr(module, "build_telegram_runtime", fake_builder)
    assert run_telegram_bot(settings) == 0
    assert state["closed"] is True


def test_run_bot_handles_interrupt_before_runtime_construction(monkeypatch, tmp_path) -> None:
    import ah_there_it_is.telegram.runtime as module

    monkeypatch.setattr(
        module,
        "build_telegram_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert run_telegram_bot(bot_settings(tmp_path)) == 0


def test_validate_telegram_settings_never_includes_secret() -> None:
    settings = Settings(
        telegram_bot_token="super-secret-token",
        telegram_allowed_user_id=None,
    )

    with pytest.raises(TelegramRuntimeConfigurationError) as error:
        validate_telegram_settings(settings)

    assert "super-secret-token" not in str(error.value)


def test_source_label_cannot_persist_bot_token(tmp_path) -> None:
    token = "TEST_SECRET_DO_NOT_PERSIST_7391"
    settings = bot_settings(
        tmp_path, telegram_bot_token=token, telegram_source_label=f"audit:{token}"
    )

    with pytest.raises(TelegramRuntimeConfigurationError) as error:
        validate_telegram_settings(settings)
    assert token not in str(error.value)


def test_nonpositive_allowed_user_id_fails_configuration(tmp_path) -> None:
    with pytest.raises(TelegramRuntimeConfigurationError, match="allowed user id"):
        validate_telegram_settings(bot_settings(tmp_path, telegram_allowed_user_id=-1))
