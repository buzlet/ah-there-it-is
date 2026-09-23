"""Consistent local SQLite backup, validation, restore, and portable export."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url


PORTABLE_EXPORT_FORMAT = "ah-there-it-is-portable-v1"


class StorageOperationError(RuntimeError):
    """Base error for local database maintenance operations."""


class BackupValidationError(StorageOperationError):
    """A database file failed structural/application validation."""


@dataclass(frozen=True)
class DatabaseValidation:
    path: str
    size_bytes: int
    schema_revision: str
    integrity_ok: bool
    foreign_keys_ok: bool
    required_tables_ok: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreResult:
    restored_path: str
    rollback_backup_path: str | None
    schema_revision: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_REQUIRED_TABLES = {
    "alembic_version",
    "categories",
    "locations",
    "items",
    "aliases",
    "tags",
    "item_tags",
    "events",
    "conversations",
    "messages",
    "chat_requests",
    "item_search_fts",
}


def expected_schema_revision() -> str:
    root = Path(__file__).resolve().parents[2]
    config_path = root / "alembic.ini"
    migrations = root / "migrations"
    if not config_path.is_file() or not migrations.is_dir():
        raise StorageOperationError(
            "cannot locate alembic.ini/migrations to determine expected schema head"
        )
    config = Config(str(config_path))
    config.set_main_option("script_location", str(migrations))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise StorageOperationError(
            f"expected exactly one Alembic head, found {len(heads)}: {heads}"
        )
    return heads[0]


def sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise StorageOperationError("storage maintenance currently supports SQLite only")
    database = url.database
    if not database or database == ":memory:":
        raise StorageOperationError(
            "storage maintenance requires a file-backed SQLite database"
        )
    return Path(database).expanduser().resolve()


def validate_database_file(
    path: str | Path,
    *,
    expected_revision: str | None = None,
) -> DatabaseValidation:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise BackupValidationError(f"database file does not exist: {candidate}")
    expected = expected_revision or expected_schema_revision()

    try:
        with _readonly_connection(candidate) as connection:
            integrity = [
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check").fetchall()
            ]
            if integrity != ["ok"]:
                raise BackupValidationError(
                    "SQLite integrity_check failed: " + "; ".join(integrity[:10])
                )

            foreign_key_rows = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if foreign_key_rows:
                raise BackupValidationError(
                    "SQLite foreign_key_check failed: "
                    + repr(foreign_key_rows[:10])
                )

            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type IN ('table', 'view')"
                ).fetchall()
            }
            missing = sorted(_REQUIRED_TABLES - tables)
            if missing:
                raise BackupValidationError(
                    "database is missing required tables: " + ", ".join(missing)
                )

            revisions = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
            if len(revisions) != 1:
                raise BackupValidationError(
                    f"expected one Alembic revision row, found {len(revisions)}"
                )
            revision = str(revisions[0][0])
            if revision != expected:
                raise BackupValidationError(
                    f"database schema revision {revision!r} does not match "
                    f"expected head {expected!r}"
                )
    except sqlite3.DatabaseError as exc:
        raise BackupValidationError(
            f"cannot validate SQLite database {candidate}: {exc}"
        ) from exc

    return DatabaseValidation(
        path=str(candidate),
        size_bytes=candidate.stat().st_size,
        schema_revision=revision,
        integrity_ok=True,
        foreign_keys_ok=True,
        required_tables_ok=True,
    )


def backup_database(
    database_url: str,
    destination: str | Path,
    *,
    expected_revision: str | None = None,
) -> DatabaseValidation:
    source = sqlite_database_path(database_url)
    if not source.is_file():
        raise StorageOperationError(f"source database does not exist: {source}")

    target = Path(destination).expanduser().resolve()
    if target == source:
        raise StorageOperationError("backup destination must differ from source database")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path_near(target)

    try:
        with _readonly_connection(source) as source_connection:
            destination_connection = sqlite3.connect(str(temp_path), timeout=5.0)
            try:
                source_connection.backup(
                    destination_connection,
                    pages=256,
                    sleep=0.05,
                )
            finally:
                destination_connection.close()

        validation = validate_database_file(
            temp_path,
            expected_revision=expected_revision,
        )
        os.replace(temp_path, target)
        return DatabaseValidation(
            path=str(target),
            size_bytes=target.stat().st_size,
            schema_revision=validation.schema_revision,
            integrity_ok=True,
            foreign_keys_ok=True,
            required_tables_ok=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def restore_database(
    database_url: str,
    candidate: str | Path,
    *,
    confirm_app_stopped: bool,
    rollback_backup: str | Path | None = None,
    expected_revision: str | None = None,
) -> RestoreResult:
    if not confirm_app_stopped:
        raise StorageOperationError(
            "restore requires explicit confirmation that the application is stopped"
        )

    target = sqlite_database_path(database_url)
    source = Path(candidate).expanduser().resolve()
    if source == target:
        raise StorageOperationError("restore candidate must differ from active database")
    validation = validate_database_file(
        source,
        expected_revision=expected_revision,
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    rollback: Path | None = None
    if target.exists():
        rollback = (
            Path(rollback_backup).expanduser().resolve()
            if rollback_backup is not None
            else target.with_name(
                f"{target.stem}.pre-restore-{_timestamp()}-{uuid.uuid4().hex[:8]}"
                f"{target.suffix or '.db'}"
            )
        )
        backup_database(
            database_url,
            rollback,
            expected_revision=expected_revision,
        )
        _assert_exclusive_write_access(target)

    prepared = _temp_path_near(target)
    try:
        shutil.copy2(source, prepared)
        validate_database_file(
            prepared,
            expected_revision=expected_revision,
        )
        os.replace(prepared, target)
        _remove_sidecars(target)
        final = validate_database_file(
            target,
            expected_revision=expected_revision,
        )
    finally:
        prepared.unlink(missing_ok=True)

    return RestoreResult(
        restored_path=str(target),
        rollback_backup_path=str(rollback) if rollback is not None else None,
        schema_revision=final.schema_revision or validation.schema_revision,
    )


def export_portable_json(
    database_url: str,
    *,
    include_evaluations: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ah-there-it-is-export-") as directory:
        snapshot = Path(directory) / "snapshot.db"
        validation = backup_database(
            database_url,
            snapshot,
            expected_revision=expected_revision,
        )
        with _readonly_connection(snapshot) as connection:
            document: dict[str, Any] = {
                "format": PORTABLE_EXPORT_FORMAT,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "schema_revision": validation.schema_revision,
                "inventory": {
                    "categories": _rows(
                        connection,
                        "categories",
                        [
                            "id",
                            "parent_id",
                            "name",
                            "description",
                            "created_at",
                            "updated_at",
                        ],
                    ),
                    "locations": _rows(
                        connection,
                        "locations",
                        [
                            "id",
                            "parent_id",
                            "name",
                            "description",
                            "created_at",
                            "updated_at",
                        ],
                    ),
                    "items": _rows(
                        connection,
                        "items",
                        [
                            "id",
                            "name",
                            "description",
                            "state",
                            "category_id",
                            "current_location_id",
                            "quantity",
                            "attributes",
                            "created_at",
                            "updated_at",
                        ],
                        json_columns={"attributes"},
                    ),
                    "aliases": _rows(
                        connection,
                        "aliases",
                        ["id", "item_id", "name"],
                    ),
                    "tags": _rows(
                        connection,
                        "tags",
                        ["id", "name"],
                    ),
                    "item_tags": _rows(
                        connection,
                        "item_tags",
                        ["item_id", "tag_id"],
                    ),
                    "events": _rows(
                        connection,
                        "events",
                        [
                            "id",
                            "event_type",
                            "item_id",
                            "from_location_id",
                            "to_location_id",
                            "payload",
                            "original_text",
                            "created_at",
                        ],
                        json_columns={"payload"},
                    ),
                },
                "interaction_audit": {
                    "conversations": _rows(
                        connection,
                        "conversations",
                        ["id", "created_at", "updated_at"],
                    ),
                    "messages": _rows(
                        connection,
                        "messages",
                        ["id", "conversation_id", "role", "content", "created_at"],
                    ),
                    "chat_requests": _rows(
                        connection,
                        "chat_requests",
                        [
                            "id",
                            "request_key",
                            "requested_conversation_id",
                            "message",
                            "status",
                            "agent_run_id",
                            "error",
                            "recovered_from_id",
                            "recovery_note",
                            "created_at",
                            "updated_at",
                        ],
                    ),
                },
                "evaluation_included": include_evaluations,
            }
            if include_evaluations:
                document["evaluation"] = {
                    "agent_run_logs": _rows(
                        connection,
                        "agent_run_logs",
                        [
                            "id",
                            "conversation_id",
                            "user_message_id",
                            "assistant_message_id",
                            "prompt_version",
                            "prompt_hash",
                            "system_prompt",
                            "llm_provider",
                            "llm_model",
                            "llm_config",
                            "input_messages",
                            "tool_trace",
                            "final_content",
                            "rounds",
                            "status",
                            "error",
                            "created_at",
                        ],
                        json_columns={"llm_config", "input_messages", "tool_trace"},
                    ),
                    "agent_feedback": _rows(
                        connection,
                        "agent_feedback",
                        [
                            "id",
                            "agent_run_id",
                            "rating",
                            "comment",
                            "created_at",
                            "updated_at",
                        ],
                    ),
                    "experiment_runs": _rows(
                        connection,
                        "experiment_runs",
                        [
                            "id",
                            "source_run_id",
                            "experiment_name",
                            "prompt_version",
                            "prompt_hash",
                            "system_prompt",
                            "llm_provider",
                            "llm_model",
                            "llm_config",
                            "input_messages",
                            "tool_trace",
                            "final_content",
                            "rounds",
                            "status",
                            "error",
                            "divergence_reason",
                            "created_at",
                        ],
                        json_columns={"llm_config", "input_messages", "tool_trace"},
                    ),
                    "experiment_reviews": _rows(
                        connection,
                        "experiment_reviews",
                        [
                            "id",
                            "experiment_run_id",
                            "choice",
                            "variant_rating",
                            "comment",
                            "created_at",
                            "updated_at",
                        ],
                    ),
                }
            return document


def _rows(
    connection: sqlite3.Connection,
    table: str,
    columns: list[str],
    *,
    json_columns: set[str] | None = None,
) -> list[dict[str, Any]]:
    json_columns = json_columns or set()
    quoted = ", ".join(f'"{column}"' for column in columns)
    rows = connection.execute(
        f'SELECT {quoted} FROM "{table}" ORDER BY rowid'
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        record = dict(zip(columns, row, strict=True))
        for column in json_columns:
            raw = record.get(column)
            if isinstance(raw, str):
                record[column] = json.loads(raw)
        result.append(record)
    return result


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _assert_exclusive_write_access(path: Path) -> None:
    try:
        connection = sqlite3.connect(str(path), timeout=0.1)
        try:
            connection.execute("PRAGMA busy_timeout=100")
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
        finally:
            connection.close()
    except sqlite3.OperationalError as exc:
        raise StorageOperationError(
            "active database is locked; stop the application before restore"
        ) from exc


def _remove_sidecars(path: Path) -> None:
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def _temp_path_near(target: Path) -> Path:
    return target.with_name(
        f".{target.name}.{uuid.uuid4().hex}.tmp"
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
