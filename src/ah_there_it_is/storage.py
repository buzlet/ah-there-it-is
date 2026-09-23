"""SQLite backup, validation, restore, and portable inventory export."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import (
    Alias,
    Category,
    Event,
    Item,
    ItemTag,
    Location,
)
from ah_there_it_is.db.session import create_db_engine, create_session_factory


PORTABLE_EXPORT_VERSION = "inventory-portable-v1"


class StorageError(RuntimeError):
    """Backup/restore/export operation cannot be completed safely."""


class DatabaseValidationError(StorageError):
    """A SQLite candidate failed integrity/schema validation."""


@dataclass(frozen=True)
class DatabaseValidation:
    path: str
    size_bytes: int
    sha256: str
    alembic_revision: str
    integrity_check: tuple[str, ...]
    foreign_key_violations: tuple[tuple[Any, ...], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreResult:
    restored_path: str
    safety_backup_path: str
    candidate: DatabaseValidation
    restored: DatabaseValidation

    def as_dict(self) -> dict[str, Any]:
        return {
            "restored_path": self.restored_path,
            "safety_backup_path": self.safety_backup_path,
            "candidate": self.candidate.as_dict(),
            "restored": self.restored.as_dict(),
        }


def expected_alembic_head(alembic_ini: str | Path = "alembic.ini") -> str:
    config = Config(str(alembic_ini))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise StorageError(f"expected exactly one Alembic head, found {heads!r}")
    return heads[0]


def sqlite_path_from_url(database_url: str) -> Path:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        raise StorageError("storage commands currently support SQLite only")
    database = url.database
    if not database or database == ":memory:":
        raise StorageError("storage commands require a file-backed SQLite database")
    return Path(database).expanduser().resolve()


def validate_database(
    path: str | Path,
    *,
    expected_revision: str | None = None,
    alembic_ini: str | Path = "alembic.ini",
) -> DatabaseValidation:
    database = Path(path).expanduser().resolve()
    if not database.is_file():
        raise DatabaseValidationError(f"database file does not exist: {database}")
    revision = expected_revision or expected_alembic_head(alembic_ini)

    try:
        connection = sqlite3.connect(_readonly_uri(database), uri=True)
    except sqlite3.Error as exc:
        raise DatabaseValidationError(f"cannot open SQLite database: {exc}") from exc

    try:
        try:
            integrity = tuple(
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check").fetchall()
            )
            foreign_keys = tuple(
                tuple(row)
                for row in connection.execute("PRAGMA foreign_key_check").fetchall()
            )
            versions = [
                str(row[0])
                for row in connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise DatabaseValidationError(
                f"candidate is not a valid readable application database: {exc}"
            ) from exc
    finally:
        connection.close()

    problems: list[str] = []
    if integrity != ("ok",):
        problems.append(f"integrity_check={integrity!r}")
    if foreign_keys:
        problems.append(f"foreign_key_check={foreign_keys!r}")
    if versions != [revision]:
        problems.append(
            f"alembic revision {versions!r} does not match expected {revision!r}"
        )
    if problems:
        raise DatabaseValidationError("; ".join(problems))

    return DatabaseValidation(
        path=str(database),
        size_bytes=database.stat().st_size,
        sha256=_sha256(database),
        alembic_revision=versions[0],
        integrity_check=integrity,
        foreign_key_violations=foreign_keys,
    )


def create_backup(
    database_url: str,
    destination: str | Path,
    *,
    overwrite: bool = False,
    alembic_ini: str | Path = "alembic.ini",
) -> DatabaseValidation:
    source = sqlite_path_from_url(database_url)
    if not source.is_file():
        raise StorageError(f"source database does not exist: {source}")

    target = Path(destination).expanduser().resolve()
    if source == target:
        raise StorageError("backup destination must differ from the active database")
    if target.exists() and not overwrite:
        raise StorageError(f"backup destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary = _temporary_sibling(target, "backup")
    try:
        _copy_sqlite_snapshot(source, temporary)
        validation = validate_database(
            temporary,
            alembic_ini=alembic_ini,
        )
        if target.exists() and not overwrite:
            raise StorageError(f"backup destination already exists: {target}")
        os.replace(temporary, target)
        _fsync_path(target)
        _fsync_directory(target.parent)
        return DatabaseValidation(
            path=str(target),
            size_bytes=target.stat().st_size,
            sha256=_sha256(target),
            alembic_revision=validation.alembic_revision,
            integrity_check=validation.integrity_check,
            foreign_key_violations=validation.foreign_key_violations,
        )
    finally:
        _unlink_sqlite_files(temporary)


def restore_backup(
    database_url: str,
    candidate: str | Path,
    *,
    safety_backup: str | Path | None = None,
    alembic_ini: str | Path = "alembic.ini",
) -> RestoreResult:
    target = sqlite_path_from_url(database_url)
    source = Path(candidate).expanduser().resolve()
    if not target.is_file():
        raise StorageError(f"active database does not exist: {target}")
    if source == target:
        raise StorageError("restore candidate must differ from the active database")

    candidate_validation = validate_database(source, alembic_ini=alembic_ini)
    safety = (
        Path(safety_backup).expanduser().resolve()
        if safety_backup is not None
        else _default_safety_backup(target)
    )
    create_backup(
        database_url,
        safety,
        overwrite=False,
        alembic_ini=alembic_ini,
    )

    replacement = _temporary_sibling(target, "restore")
    try:
        _copy_sqlite_snapshot(source, replacement)
        validate_database(replacement, alembic_ini=alembic_ini)
        _checkpoint_for_restore(target)
        _unlink_sidecars(target)
        os.replace(replacement, target)
        _fsync_path(target)
        _fsync_directory(target.parent)
        try:
            restored = validate_database(target, alembic_ini=alembic_ini)
        except Exception:
            rollback = _temporary_sibling(target, "rollback")
            try:
                _copy_sqlite_snapshot(safety, rollback)
                validate_database(rollback, alembic_ini=alembic_ini)
                _unlink_sidecars(target)
                os.replace(rollback, target)
                _fsync_path(target)
                _fsync_directory(target.parent)
            finally:
                _unlink_sqlite_files(rollback)
            raise
        return RestoreResult(
            restored_path=str(target),
            safety_backup_path=str(safety),
            candidate=candidate_validation,
            restored=restored,
        )
    finally:
        _unlink_sqlite_files(replacement)


def export_portable_inventory(
    database_url: str,
    destination: str | Path,
    *,
    alembic_ini: str | Path = "alembic.ini",
) -> dict[str, Any]:
    database = sqlite_path_from_url(database_url)
    validation = validate_database(database, alembic_ini=alembic_ini)
    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            document = _portable_document(session, validation.alembic_revision)
    finally:
        engine.dispose()

    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_sibling(target, "json")
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        _fsync_path(target)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return document


def _portable_document(session: Session, alembic_revision: str) -> dict[str, Any]:
    categories = list(session.scalars(select(Category).order_by(Category.id)))
    locations = list(session.scalars(select(Location).order_by(Location.id)))
    items = list(
        session.scalars(
            select(Item)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links).selectinload(ItemTag.tag),
            )
            .order_by(Item.id)
        )
    )
    events = list(session.scalars(select(Event).order_by(Event.id)))

    return {
        "format": PORTABLE_EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "alembic_revision": alembic_revision,
        },
        "inventory": {
            "categories": [
                {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "name": node.name,
                    "description": node.description,
                    "created_at": _iso(node.created_at),
                    "updated_at": _iso(node.updated_at),
                }
                for node in categories
            ],
            "locations": [
                {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "name": node.name,
                    "description": node.description,
                    "created_at": _iso(node.created_at),
                    "updated_at": _iso(node.updated_at),
                }
                for node in locations
            ],
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "state": item.state,
                    "category_id": item.category_id,
                    "location_id": item.current_location_id,
                    "quantity": item.quantity,
                    "attributes": item.attributes,
                    "aliases": [alias.name for alias in sorted(item.aliases, key=lambda a: a.id)],
                    "tags": [
                        link.tag.name
                        for link in sorted(item.tag_links, key=lambda link: link.tag_id)
                    ],
                    "created_at": _iso(item.created_at),
                    "updated_at": _iso(item.updated_at),
                }
                for item in items
            ],
        },
        "history": {
            "events": [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "item_id": event.item_id,
                    "from_location_id": event.from_location_id,
                    "to_location_id": event.to_location_id,
                    "payload": event.payload,
                    "original_text": event.original_text,
                    "created_at": _iso(event.created_at),
                }
                for event in events
            ]
        },
        "excluded": [
            "agent_run_logs",
            "agent_feedback",
            "experiment_runs",
            "experiment_reviews",
            "provider_metadata",
        ],
    }


def _copy_sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _unlink_sqlite_files(destination)
    source_connection = sqlite3.connect(_readonly_uri(source), uri=True)
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
        destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        destination_connection.execute("PRAGMA journal_mode=DELETE")
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def _checkpoint_for_restore(target: Path) -> None:
    connection = sqlite3.connect(str(target), timeout=5)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and int(row[0]) != 0:
            raise StorageError(
                "active database WAL checkpoint is busy; stop the application "
                "before restore"
            )
    finally:
        connection.close()


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _default_safety_backup(target: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = target.suffix or ".sqlite3"
    return target.with_name(f"{target.stem}.pre-restore-{stamp}{suffix}")


def _temporary_sibling(target: Path, label: str) -> Path:
    fd, name = tempfile.mkstemp(
        prefix=f".{target.name}.{label}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(fd)
    path = Path(name)
    path.unlink(missing_ok=True)
    return path


def _unlink_sidecars(path: Path) -> None:
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def _unlink_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    _unlink_sidecars(path)


def _fsync_path(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
