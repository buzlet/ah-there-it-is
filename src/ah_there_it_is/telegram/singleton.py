"""Host-local lifetime lock for the one production Telegram poller."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from typing import Iterator

from ah_there_it_is.storage import sqlite_path_from_url


class TelegramSingletonError(RuntimeError):
    """The poller cannot acquire exclusive ownership of its database."""


def lock_path(database_url: str) -> Path:
    database = sqlite_path_from_url(database_url)
    return database.with_name(database.name + ".telegram.lock")


@contextmanager
def telegram_singleton(database_url: str) -> Iterator[Path]:
    """Keep the lock file and descriptor alive until polling has fully stopped.

    Never unlink the file: doing so could give two processes different inodes.
    The kernel releases the lock after a crash, including SIGKILL.
    """
    path = lock_path(database_url)
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise TelegramSingletonError(f"cannot open Telegram poller lock: {path}") from None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TelegramSingletonError(
                f"Telegram poller already owns database lock: {path}"
            ) from None
        yield path
    finally:
        os.close(descriptor)
