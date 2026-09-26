"""Read-only access to the ChatGPT credential already maintained by Codex."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Protocol


class CredentialSourceError(RuntimeError):
    """The Codex cache cannot safely provide ChatGPT credentials."""


@dataclass(frozen=True)
class ChatGPTCredentials:
    access_token: str = field(repr=False)
    account_id: str | None = field(default=None, repr=False)


class ChatGPTCredentialSource(Protocol):
    def get(self) -> ChatGPTCredentials: ...


class CodexAuthFileCredentialSource:
    """Re-read Codex's file-backed auth cache on every credential request.

    This class intentionally has no write, refresh, or fallback-to-API-key path.
    The full auth document remains local to ``get`` and only the access token and
    account ID leave the source.
    """

    def __init__(
        self,
        auth_file: Path | str | None = None,
        *,
        codex_home: Path | str | None = None,
    ) -> None:
        if auth_file is not None and codex_home is not None:
            raise ValueError("provide auth_file or codex_home, not both")
        if auth_file is not None:
            selected = Path(auth_file).expanduser()
        else:
            home = Path(codex_home).expanduser() if codex_home is not None else Path(
                os.environ.get("CODEX_HOME", Path.home() / ".codex")
            ).expanduser()
            selected = home / "auth.json"
        self._auth_file = selected

    def get(self) -> ChatGPTCredentials:
        try:
            with self._auth_file.open("rb") as auth_file:
                raw = auth_file.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise CredentialSourceError(
                    "Codex ChatGPT credentials are unavailable or invalid"
                )
            parsed = json.loads(raw)
        except CredentialSourceError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise CredentialSourceError(
                "Codex ChatGPT credentials are unavailable or invalid"
            ) from None

        if not isinstance(parsed, dict) or parsed.get("auth_mode") != "chatgpt":
            raise CredentialSourceError(
                "Codex is not using file-backed ChatGPT authentication"
            )
        tokens = parsed.get("tokens")
        if not isinstance(tokens, dict):
            raise CredentialSourceError("Codex ChatGPT credentials are incomplete")
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        if not isinstance(access_token, str) or not access_token.strip():
            raise CredentialSourceError("Codex ChatGPT access credential is missing")
        if account_id is not None and (
            not isinstance(account_id, str) or not account_id.strip()
        ):
            account_id = None
        return ChatGPTCredentials(
            access_token=access_token,
            account_id=account_id,
        )


@dataclass(frozen=True)
class StaticChatGPTCredentialSource:
    """Credential source for deterministic tests and one-shot probes."""

    credentials: ChatGPTCredentials = field(repr=False)

    def get(self) -> ChatGPTCredentials:
        return self.credentials
