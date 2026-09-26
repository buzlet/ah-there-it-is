"""Host-local lifetime lock for the one production Telegram poller."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import stat
from typing import Iterator

from ah_there_it_is.storage import sqlite_path_from_url


class TelegramSingletonError(RuntimeError):
    """The poller cannot acquire exclusive ownership of its database."""


def lock_path(database_url: str) -> Path:
    database = sqlite_path_from_url(database_url)
    return database.with_name(database.name + ".telegram.lock")


def bot_lock_path(bot_token: str, *, lock_dir: Path | None = None) -> Path:
    """Hash the secret with a domain separator; never persist the raw token."""
    if not bot_token or not bot_token.strip():
        raise TelegramSingletonError("Telegram bot identity is missing")
    root = lock_dir or (
        Path(pwd.getpwuid(os.geteuid()).pw_dir)
        / ".local" / "state" / "ah-there-it-is" / "locks"
    )
    try:
        token_bytes = bot_token.strip().encode("utf-8")
    except UnicodeError:
        raise TelegramSingletonError("Telegram bot identity is invalid") from None
    digest = hashlib.sha256(
        b"ah-there-it-is/telegram-bot/v1\0" + token_bytes
    ).hexdigest()
    return root / f"bot-{digest}.lock"


def _lock_file(path: Path, *, owner: str) -> int:
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        raise TelegramSingletonError(f"cannot open Telegram {owner} lock") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TelegramSingletonError(f"Telegram {owner} lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TelegramSingletonError(f"Telegram {owner} already has a poller") from None
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def telegram_singleton(
    database_url: str, bot_token: str, *, lock_dir: Path | None = None
) -> Iterator[Path]:
    """Own both the bot identity and database until polling has fully stopped.

    Never unlink either file: doing so could give processes different inodes.
    The kernel releases both locks after a crash, including SIGKILL.
    """
    bot_path = bot_lock_path(bot_token, lock_dir=lock_dir)
    root = bot_path.parent
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise TelegramSingletonError("Telegram bot lock directory is not private")
    except OSError:
        raise TelegramSingletonError(
            "cannot create private Telegram bot lock directory"
        ) from None
    with ExitStack() as stack:
        stack.callback(os.close, _lock_file(bot_path, owner="bot identity"))
        database_path = lock_path(database_url)
        stack.callback(os.close, _lock_file(database_path, owner="database"))
        yield database_path
