"""Installed-package runtime CLI and read-only startup schema gate."""

from __future__ import annotations

import argparse
import ipaddress
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

import uvicorn

from ah_there_it_is.config import database_url_override, get_settings
from ah_there_it_is.data_paths import resolve_data_dir
from ah_there_it_is.db.migrations import migration_heads
from ah_there_it_is.storage import StorageError, sqlite_path_from_url


_EXPLICIT_UPGRADE = "python -m ah_there_it_is.storage_cli upgrade"


class RuntimeSchemaError(RuntimeError):
    """The configured database is not safe to serve with this package."""


@dataclass(frozen=True)
class RuntimeSchemaStatus:
    database_path: str
    database_heads: tuple[str, ...]
    packaged_heads: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def runtime_schema_gate(database_url: str) -> RuntimeSchemaStatus:
    """Require an existing SQLite database at exactly the packaged Alembic heads."""
    try:
        database = sqlite_path_from_url(database_url)
    except StorageError as exc:
        raise RuntimeSchemaError(
            f"configured database is not a supported file-backed SQLite database: {exc}"
        ) from exc

    packaged_heads = tuple(sorted(migration_heads()))
    if not packaged_heads:
        raise RuntimeSchemaError("installed package contains no Alembic migration head")
    if not database.is_file():
        raise RuntimeSchemaError(
            f"configured database does not exist: {database}; "
            f"run {_EXPLICIT_UPGRADE!r} before 'ah-there-it-is serve'"
        )

    database_heads = _read_database_heads(database)
    if not database_heads:
        raise RuntimeSchemaError(
            f"configured database is not initialized with Alembic: {database}; "
            f"run {_EXPLICIT_UPGRADE!r} before 'ah-there-it-is serve'"
        )
    if database_heads != packaged_heads:
        raise RuntimeSchemaError(
            "configured database schema does not match this installed package: "
            f"database heads={database_heads!r}, packaged heads={packaged_heads!r}; "
            f"if the database is behind, run {_EXPLICIT_UPGRADE!r} explicitly; "
            "otherwise install a package compatible with the database"
        )

    return RuntimeSchemaStatus(
        database_path=str(database),
        database_heads=database_heads,
        packaged_heads=packaged_heads,
    )


def _read_database_heads(database: Path) -> tuple[str, ...]:
    uri = database.as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise RuntimeSchemaError(
            f"cannot open configured database read-only: {database}: {exc}"
        ) from exc
    try:
        try:
            rows = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).fetchall()
        except sqlite3.Error as exc:
            raise RuntimeSchemaError(
                f"configured database has no readable Alembic revision state: {database}; "
                f"run {_EXPLICIT_UPGRADE!r} before 'ah-there-it-is serve'"
            ) from exc
    finally:
        connection.close()
    return tuple(str(row[0]) for row in rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ah-there-it-is", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("paths", help="show resolved local data paths")
    subparsers.add_parser("doctor", help="read-only active database health check")
    subparsers.add_parser("repair-search-index", help="explicitly rebuild derived FTS state")

    serve = subparsers.add_parser("serve", help="start the local web application")
    serve.add_argument("--host", type=_host, default="127.0.0.1")
    serve.add_argument("--port", type=_port, default=8000)
    serve.add_argument(
        "--allow-nonlocal",
        action="store_true",
        help="allow unauthenticated serving beyond loopback",
    )
    return parser


def _host(value: str) -> str:
    host = value.strip()
    if not host or any(character.isspace() for character in host):
        raise argparse.ArgumentTypeError("host must be a non-blank address or hostname")
    return host


def _is_loopback_host(value: str) -> bool:
    if value.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def runtime_paths(database_url: str) -> dict[str, object]:
    explicit = database_url_override() is not None
    database: dict[str, object] = {
        "source": "explicit" if explicit else "default",
        "path": None,
    }
    try:
        database["path"] = str(sqlite_path_from_url(database_url))
    except StorageError:
        if not explicit:
            raise RuntimeSchemaError(
                "default database configuration is not a file-backed SQLite URL"
            )
    return {
        "data_dir": str(resolve_data_dir()),
        "database": database,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    if args.command == "paths":
        print(json.dumps(runtime_paths(settings.database_url), sort_keys=True))
        return 0

    if args.command in {"doctor", "repair-search-index"}:
        from ah_there_it_is.database_doctor import diagnose_database, repair_search_index

        operation = diagnose_database if args.command == "doctor" else repair_search_index
        report = operation(settings.database_url)
        print(json.dumps(report.as_dict(), sort_keys=True))
        return 0 if report.ok else 2

    if args.command == "serve":
        if not _is_loopback_host(args.host):
            if not args.allow_nonlocal:
                print(
                    "error: non-loopback serving requires --allow-nonlocal; "
                    "the application has no authentication",
                    file=sys.stderr,
                )
                return 2
            print(
                "warning: application has no authentication and is being exposed "
                f"beyond loopback (host={args.host!r})",
                file=sys.stderr,
            )

        try:
            runtime_schema_gate(settings.database_url)
        except RuntimeSchemaError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        uvicorn.run(
            "ah_there_it_is.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=False,
        )
        return 0
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
