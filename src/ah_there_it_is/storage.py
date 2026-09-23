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

from alembic import command
from alembic.config import Config
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
    Tag,
)
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.states import ItemState


PORTABLE_EXPORT_VERSION = "inventory-portable-v1"
CURRENT_SCHEMA_REVISION = "a31d7f4e9c20"


class StorageError(RuntimeError):
    """Backup/restore/export operation cannot be completed safely."""


class DatabaseValidationError(StorageError):
    """A SQLite candidate failed integrity/schema validation."""


class PortableInventoryValidationError(StorageError):
    """A portable inventory document is structurally or semantically invalid."""


class _PortableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PortableSource(_PortableModel):
    alembic_revision: str


class PortableTreeNode(_PortableModel):
    id: int = Field(gt=0)
    parent_id: int | None
    name: str
    description: str | None
    created_at: str
    updated_at: str


class PortableItem(_PortableModel):
    id: int = Field(gt=0)
    name: str
    description: str | None
    state: str
    category_id: int | None
    location_id: int | None
    quantity: int = Field(ge=1)
    attributes: dict[str, Any]
    aliases: list[str]
    tags: list[str]
    created_at: str
    updated_at: str


class PortableEvent(_PortableModel):
    id: int = Field(gt=0)
    event_type: str
    item_id: int | None
    from_location_id: int | None
    to_location_id: int | None
    payload: dict[str, Any]
    original_text: str | None
    created_at: str


class PortableInventory(_PortableModel):
    categories: list[PortableTreeNode]
    locations: list[PortableTreeNode]
    items: list[PortableItem]


class PortableHistory(_PortableModel):
    events: list[PortableEvent]


class PortableInventoryDocument(_PortableModel):
    format: str
    exported_at: str
    source: PortableSource
    inventory: PortableInventory
    history: PortableHistory
    excluded: list[str]


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


@dataclass(frozen=True)
class PortableImportResult:
    imported_path: str
    format: str
    source_alembic_revision: str
    categories: int
    locations: int
    items: int
    events: int
    database: DatabaseValidation

    def as_dict(self) -> dict[str, Any]:
        return {
            "imported_path": self.imported_path,
            "format": self.format,
            "source_alembic_revision": self.source_alembic_revision,
            "categories": self.categories,
            "locations": self.locations,
            "items": self.items,
            "events": self.events,
            "database": self.database.as_dict(),
        }


def parse_portable_inventory(data: Any) -> PortableInventoryDocument:
    """Dispatch an already-decoded portable inventory document by format."""
    if not isinstance(data, dict):
        raise PortableInventoryValidationError("portable document must be a JSON object")
    if "format" not in data:
        raise PortableInventoryValidationError("portable document is missing required format")
    if not isinstance(data["format"], str):
        raise PortableInventoryValidationError("portable document format must be a string")

    parser = _PORTABLE_FORMAT_PARSERS.get(data["format"])
    if parser is None:
        raise PortableInventoryValidationError(
            f"unsupported portable format {data['format']!r}; "
            f"expected {PORTABLE_EXPORT_VERSION!r}"
        )
    return parser(data)


def _parse_portable_inventory_v1(
    data: dict[str, Any],
) -> PortableInventoryDocument:
    """Validate the frozen inventory-portable-v1 contract."""
    try:
        document = PortableInventoryDocument.model_validate(data)
    except ValidationError as exc:
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "<document>"
            details.append(f"{location}: {error['msg']}")
        raise PortableInventoryValidationError(
            "invalid portable document structure: " + "; ".join(details)
        ) from exc

    _validate_portable_semantics(document)
    return document


_PORTABLE_FORMAT_PARSERS = {
    PORTABLE_EXPORT_VERSION: _parse_portable_inventory_v1,
}


def load_portable_inventory(path: str | Path) -> PortableInventoryDocument:
    """Read and purely validate portable JSON without touching any database."""
    source = Path(path).expanduser().resolve()
    try:
        serialized = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"cannot read portable inventory: {source}: {exc}") from exc
    try:
        data = json.loads(serialized, object_pairs_hook=_json_object_no_duplicates)
    except _DuplicateJsonKey as exc:
        raise PortableInventoryValidationError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise PortableInventoryValidationError(
            f"invalid portable JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return parse_portable_inventory(data)


def validate_portable_inventory(path: str | Path) -> PortableInventoryDocument:
    """Validate a portable JSON file without creating or mutating a database."""
    return load_portable_inventory(path)


def validate_portable_import_target(
    database_url: str,
    destination: str | Path,
) -> Path:
    """Validate that portable import would target a genuinely new database path."""
    active = sqlite_path_from_url(database_url)
    target = Path(destination).expanduser().resolve()
    if target == active:
        raise StorageError(
            "portable import destination must differ from the active database"
        )
    occupied = [
        path
        for path in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm"))
        if path.exists()
    ]
    if occupied:
        raise StorageError(
            f"portable import destination already exists or has sidecars: {occupied[0]}"
        )
    return target


def _validate_portable_semantics(document: PortableInventoryDocument) -> None:
    _portable_datetime(document.exported_at, "exported_at")
    if not document.source.alembic_revision.strip():
        raise PortableInventoryValidationError(
            "source.alembic_revision must not be empty"
        )
    if len(document.excluded) != len(set(document.excluded)):
        raise PortableInventoryValidationError("excluded contains duplicate entries")

    categories = _portable_ids(document.inventory.categories, "category")
    locations = _portable_ids(document.inventory.locations, "location")
    items = _portable_ids(document.inventory.items, "item")
    _portable_ids(document.history.events, "event")

    _validate_portable_tree(categories, "category")
    _validate_portable_tree(locations, "location")

    known_tags: dict[str, str] = {}
    for index, item in enumerate(document.inventory.items):
        path = f"inventory.items.{index}"
        _portable_name(item.name, f"{path}.name")
        _portable_created_updated(item.created_at, item.updated_at, path)
        try:
            ItemState(item.state)
        except ValueError as exc:
            allowed = ", ".join(state.value for state in ItemState)
            raise PortableInventoryValidationError(
                f"{path}.state has invalid value {item.state!r}; allowed: {allowed}"
            ) from exc
        if item.category_id is not None and item.category_id not in categories:
            raise PortableInventoryValidationError(
                f"{path}.category_id references missing category id={item.category_id}"
            )
        if item.location_id is not None and item.location_id not in locations:
            raise PortableInventoryValidationError(
                f"{path}.location_id references missing location id={item.location_id}"
            )
        _validate_portable_names(item.aliases, f"{path}.aliases")
        _validate_portable_names(item.tags, f"{path}.tags")
        for tag in item.tags:
            normalized = normalize_name(tag)
            previous = known_tags.setdefault(normalized, tag)
            if previous != tag:
                raise PortableInventoryValidationError(
                    f"tag {tag!r} conflicts with existing spelling {previous!r} "
                    f"for normalized name {normalized!r}"
                )

    for index, event in enumerate(document.history.events):
        path = f"history.events.{index}"
        _portable_name(event.event_type, f"{path}.event_type")
        _portable_datetime(event.created_at, f"{path}.created_at")
        if event.item_id is not None and event.item_id not in items:
            raise PortableInventoryValidationError(
                f"{path}.item_id references missing item id={event.item_id}"
            )
        for field_name, location_id in (
            ("from_location_id", event.from_location_id),
            ("to_location_id", event.to_location_id),
        ):
            if location_id is not None and location_id not in locations:
                raise PortableInventoryValidationError(
                    f"{path}.{field_name} references missing location id={location_id}"
                )


def _portable_ids(entries: list[Any], label: str) -> dict[int, Any]:
    by_id: dict[int, Any] = {}
    for entry in entries:
        if entry.id in by_id:
            raise PortableInventoryValidationError(
                f"duplicate {label} id={entry.id}"
            )
        by_id[entry.id] = entry
    return by_id


def _validate_portable_tree(
    nodes: dict[int, PortableTreeNode],
    label: str,
) -> None:
    siblings: dict[tuple[int | None, str], int] = {}
    for node in nodes.values():
        _portable_name(node.name, f"{label} id={node.id} name")
        _portable_created_updated(
            node.created_at,
            node.updated_at,
            f"{label} id={node.id}",
        )
        if node.parent_id == node.id:
            raise PortableInventoryValidationError(
                f"{label} id={node.id} cannot be its own parent"
            )
        if node.parent_id is not None and node.parent_id not in nodes:
            raise PortableInventoryValidationError(
                f"{label} id={node.id} references missing parent id={node.parent_id}"
            )
        key = (node.parent_id, normalize_name(node.name))
        previous = siblings.get(key)
        if previous is not None:
            raise PortableInventoryValidationError(
                f"duplicate sibling {label} names under parent {node.parent_id}: "
                f"ids {previous} and {node.id}"
            )
        siblings[key] = node.id

    for start_id in nodes:
        positions: dict[int, int] = {}
        chain: list[int] = []
        current_id: int | None = start_id
        while current_id is not None:
            if current_id in positions:
                cycle = chain[positions[current_id]:] + [current_id]
                raise PortableInventoryValidationError(
                    f"{label} hierarchy cycle: "
                    + " -> ".join(str(node_id) for node_id in cycle)
                )
            positions[current_id] = len(chain)
            chain.append(current_id)
            current_id = nodes[current_id].parent_id


def _validate_portable_names(values: list[str], path: str) -> None:
    seen: dict[str, str] = {}
    for value in values:
        normalized = _portable_name(value, path)
        previous = seen.get(normalized)
        if previous is not None:
            raise PortableInventoryValidationError(
                f"{path} contains duplicate normalized name {value!r}"
            )
        seen[normalized] = value


def _portable_name(value: str, path: str) -> str:
    normalized = normalize_name(value)
    if not normalized:
        raise PortableInventoryValidationError(f"{path} must not be blank")
    return normalized


def _portable_created_updated(created: str, updated: str, path: str) -> None:
    created_at = _portable_datetime(created, f"{path}.created_at")
    updated_at = _portable_datetime(updated, f"{path}.updated_at")
    if updated_at < created_at:
        raise PortableInventoryValidationError(
            f"{path}.updated_at precedes created_at"
        )


def _portable_datetime(value: str, path: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PortableInventoryValidationError(
            f"{path} is not a valid ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PortableInventoryValidationError(
            f"{path} must include a timezone offset"
        )
    return parsed.astimezone(timezone.utc)


class _DuplicateJsonKey(ValueError):
    pass


def _json_object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


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
    expected_revision: str = CURRENT_SCHEMA_REVISION,
) -> DatabaseValidation:
    database = Path(path).expanduser().resolve()
    if not database.is_file():
        raise DatabaseValidationError(f"database file does not exist: {database}")
    revision = expected_revision

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
        validation = validate_database(temporary)
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
) -> RestoreResult:
    target = sqlite_path_from_url(database_url)
    source = Path(candidate).expanduser().resolve()
    if not target.is_file():
        raise StorageError(f"active database does not exist: {target}")
    if source == target:
        raise StorageError("restore candidate must differ from the active database")

    candidate_validation = validate_database(source)
    safety = (
        Path(safety_backup).expanduser().resolve()
        if safety_backup is not None
        else _default_safety_backup(target)
    )
    create_backup(
        database_url,
        safety,
        overwrite=False,
    )

    replacement = _temporary_sibling(target, "restore")
    try:
        _copy_sqlite_snapshot(source, replacement)
        validate_database(replacement)
        _checkpoint_for_restore(target)
        _unlink_sidecars(target)
        os.replace(replacement, target)
        _fsync_path(target)
        _fsync_directory(target.parent)
        try:
            restored = validate_database(target)
        except Exception:
            rollback = _temporary_sibling(target, "rollback")
            try:
                _copy_sqlite_snapshot(safety, rollback)
                validate_database(rollback)
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
) -> dict[str, Any]:
    database = sqlite_path_from_url(database_url)
    validation = validate_database(database)
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


def import_portable_inventory(
    database_url: str,
    source: str | Path,
    destination: str | Path,
    *,
    alembic_ini: str | Path = "alembic.ini",
) -> PortableImportResult:
    """Reconstruct portable inventory/history into a brand-new migrated database."""
    document = load_portable_inventory(source)
    target = validate_portable_import_target(database_url, destination)
    target.parent.mkdir(parents=True, exist_ok=True)

    working = _temporary_sibling(target, "portable-work")
    publish = _temporary_sibling(target, "portable-final")
    try:
        _migrate_new_database(working, alembic_ini=alembic_ini)
        working_url = f"sqlite:///{working}"
        engine = create_db_engine(working_url)
        factory = create_session_factory(engine)
        try:
            with factory() as session:
                try:
                    _write_portable_inventory(session, document)
                    session.flush()
                    _validate_imported_search_state(session)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
        finally:
            engine.dispose()

        validate_database(working)
        _copy_sqlite_snapshot(working, publish)
        staged = validate_database(publish)
        # Re-check immediately before publication so a path created during the
        # longer migration/import work is never silently overwritten.
        validate_portable_import_target(database_url, target)
        _publish_new_file(publish, target)
        _fsync_path(target)
        _fsync_directory(target.parent)
        database = DatabaseValidation(
            path=str(target),
            size_bytes=target.stat().st_size,
            sha256=_sha256(target),
            alembic_revision=staged.alembic_revision,
            integrity_check=staged.integrity_check,
            foreign_key_violations=staged.foreign_key_violations,
        )
        return PortableImportResult(
            imported_path=str(target),
            format=document.format,
            source_alembic_revision=document.source.alembic_revision,
            categories=len(document.inventory.categories),
            locations=len(document.inventory.locations),
            items=len(document.inventory.items),
            events=len(document.history.events),
            database=database,
        )
    finally:
        _unlink_sqlite_files(working)
        _unlink_sqlite_files(publish)


def _migrate_new_database(path: Path, *, alembic_ini: str | Path) -> None:
    if path.exists():
        raise StorageError(f"portable import staging path already exists: {path}")
    config = Config(str(alembic_ini))
    database_url = f"sqlite:///{path}"
    config.set_main_option("sqlalchemy.url", database_url)
    # migrations/env.py normally permits AH_THERE_IT_IS_DATABASE_URL to
    # override alembic.ini. Portable import must be immune to that ambient
    # setting because its only legal migration target is this staging DB.
    config.attributes["database_url_override"] = database_url
    command.upgrade(config, "head")


def _write_portable_inventory(
    session: Session,
    document: PortableInventoryDocument,
) -> None:
    for node in _portable_tree_order(document.inventory.categories):
        session.add(
            Category(
                id=node.id,
                parent_id=node.parent_id,
                name=node.name,
                normalized_name=normalize_name(node.name),
                description=node.description,
                created_at=_portable_datetime(node.created_at, "category.created_at"),
                updated_at=_portable_datetime(node.updated_at, "category.updated_at"),
            )
        )
        session.flush()

    for node in _portable_tree_order(document.inventory.locations):
        session.add(
            Location(
                id=node.id,
                parent_id=node.parent_id,
                name=node.name,
                normalized_name=normalize_name(node.name),
                description=node.description,
                created_at=_portable_datetime(node.created_at, "location.created_at"),
                updated_at=_portable_datetime(node.updated_at, "location.updated_at"),
            )
        )
        session.flush()

    items = sorted(document.inventory.items, key=lambda item: item.id)
    for item in items:
        session.add(
            Item(
                id=item.id,
                name=item.name,
                normalized_name=normalize_name(item.name),
                description=item.description,
                state=item.state,
                category_id=item.category_id,
                current_location_id=item.location_id,
                quantity=item.quantity,
                attributes=item.attributes,
                created_at=_portable_datetime(item.created_at, "item.created_at"),
                updated_at=_portable_datetime(item.updated_at, "item.updated_at"),
            )
        )
    session.flush()

    for item in items:
        for alias in item.aliases:
            session.add(
                Alias(
                    item_id=item.id,
                    name=alias,
                    normalized_name=normalize_name(alias),
                )
            )
    session.flush()

    tags: dict[str, Tag] = {}
    for item in items:
        for tag_name in item.tags:
            normalized = normalize_name(tag_name)
            tag = tags.get(normalized)
            if tag is None:
                tag = Tag(name=tag_name, normalized_name=normalized)
                session.add(tag)
                session.flush()
                tags[normalized] = tag
            session.add(ItemTag(item_id=item.id, tag_id=tag.id))
    session.flush()

    for event in sorted(document.history.events, key=lambda event: event.id):
        session.add(
            Event(
                id=event.id,
                event_type=event.event_type,
                item_id=event.item_id,
                from_location_id=event.from_location_id,
                to_location_id=event.to_location_id,
                payload=event.payload,
                original_text=event.original_text,
                created_at=_portable_datetime(event.created_at, "event.created_at"),
            )
        )
    session.flush()


def _portable_tree_order(nodes: list[PortableTreeNode]) -> list[PortableTreeNode]:
    by_id = {node.id: node for node in nodes}
    depths: dict[int, int] = {}

    def depth(node_id: int) -> int:
        cached = depths.get(node_id)
        if cached is not None:
            return cached
        parent_id = by_id[node_id].parent_id
        value = 0 if parent_id is None else depth(parent_id) + 1
        depths[node_id] = value
        return value

    return sorted(nodes, key=lambda node: (depth(node.id), node.id))


def _validate_imported_search_state(session: Session) -> None:
    mismatches = list(
        session.scalars(
            text(
                """
                SELECT items.id
                FROM items
                LEFT JOIN item_search_fts ON item_search_fts.rowid = items.id
                WHERE item_search_fts.rowid IS NULL
                   OR item_search_fts.name != items.name
                   OR item_search_fts.description != COALESCE(items.description, '')
                   OR item_search_fts.aliases != COALESCE((
                        SELECT group_concat(aliases.name, ' ')
                        FROM aliases
                        WHERE aliases.item_id = items.id
                   ), '')
                   OR item_search_fts.tags != COALESCE((
                        SELECT group_concat(tags.name, ' ')
                        FROM item_tags
                        JOIN tags ON tags.id = item_tags.tag_id
                        WHERE item_tags.item_id = items.id
                   ), '')
                   OR item_search_fts.attributes != COALESCE(
                        CAST(items.attributes AS TEXT), ''
                   )
                ORDER BY items.id
                """
            )
        )
    )
    extras = list(
        session.scalars(
            text(
                """
                SELECT rowid
                FROM item_search_fts
                WHERE rowid NOT IN (SELECT id FROM items)
                ORDER BY rowid
                """
            )
        )
    )
    if mismatches or extras:
        raise StorageError(
            "portable import produced inconsistent FTS state: "
            f"mismatched_items={mismatches!r}, extra_rows={extras!r}"
        )


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


def _publish_new_file(source: Path, target: Path) -> None:
    """Atomically publish a same-filesystem file without overwrite semantics."""
    try:
        os.link(source, target)
    except FileExistsError as exc:
        raise StorageError(
            f"portable import destination appeared during import: {target}"
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"cannot atomically publish portable import to {target}: {exc}"
        ) from exc
    source.unlink()


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
