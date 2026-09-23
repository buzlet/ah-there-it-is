"""Strict onboarding import for an empty current-schema inventory database."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Alias, Category, Event, Item, ItemTag, Location, Tag
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.states import ItemState
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.storage import (
    DatabaseValidationError,
    sqlite_path_from_url,
    validate_database,
)


BOOTSTRAP_FORMAT_VERSION = "inventory-bootstrap-v1"
BOOTSTRAP_PROVENANCE = "[inventory-bootstrap-v1 import]"
_INVENTORY_TABLES = (
    "categories",
    "locations",
    "items",
    "aliases",
    "tags",
    "item_tags",
    "events",
)


class BootstrapError(RuntimeError):
    """Bootstrap validation or application cannot be completed safely."""


class BootstrapValidationError(BootstrapError):
    """A bootstrap manifest is structurally or semantically invalid."""


class BootstrapPreflightError(BootstrapError):
    """The active database is not a safe bootstrap target."""


class _BootstrapModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BootstrapTreeEntry(_BootstrapModel):
    path: list[str]
    description: str | None


class BootstrapItem(_BootstrapModel):
    name: str
    description: str | None
    state: str
    category_path: list[str] | None
    location_path: list[str] | None
    quantity: int = Field(ge=1)
    attributes: dict[str, Any]
    aliases: list[str]
    tags: list[str]


class BootstrapManifest(_BootstrapModel):
    format: str
    locations: list[BootstrapTreeEntry]
    categories: list[BootstrapTreeEntry]
    items: list[BootstrapItem]


@dataclass(frozen=True)
class BootstrapPreflightResult:
    database_path: str
    alembic_revision: str
    format: str
    categories: int
    locations: int
    items: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BootstrapImportResult:
    database_path: str
    alembic_revision: str
    format: str
    categories: int
    locations: int
    items: int
    events: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_bootstrap_manifest(data: Any) -> BootstrapManifest:
    """Pure format dispatch and semantic validation for decoded bootstrap JSON."""
    if not isinstance(data, dict):
        raise BootstrapValidationError("bootstrap manifest must be a JSON object")
    if "format" not in data:
        raise BootstrapValidationError("bootstrap manifest is missing required format")
    if not isinstance(data["format"], str):
        raise BootstrapValidationError("bootstrap manifest format must be a string")

    parser = _BOOTSTRAP_FORMAT_PARSERS.get(data["format"])
    if parser is None:
        raise BootstrapValidationError(
            f"unsupported bootstrap format {data['format']!r}; "
            f"expected {BOOTSTRAP_FORMAT_VERSION!r}"
        )
    return parser(data)


def _parse_bootstrap_v1(data: dict[str, Any]) -> BootstrapManifest:
    try:
        manifest = BootstrapManifest.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        )
        raise BootstrapValidationError(
            "invalid bootstrap manifest structure: " + details
        ) from exc
    if manifest.format != BOOTSTRAP_FORMAT_VERSION:
        raise BootstrapValidationError(
            f"unsupported bootstrap format {manifest.format!r}; "
            f"expected {BOOTSTRAP_FORMAT_VERSION!r}"
        )
    _validate_bootstrap_semantics(manifest)
    return manifest


_BOOTSTRAP_FORMAT_PARSERS: dict[str, Callable[[dict[str, Any]], BootstrapManifest]] = {
    BOOTSTRAP_FORMAT_VERSION: _parse_bootstrap_v1,
}


class _DuplicateJsonKey(ValueError):
    pass


def _json_object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def load_bootstrap_manifest(path: str | Path) -> BootstrapManifest:
    """Read and purely validate a bootstrap manifest without database access."""
    source = Path(path).expanduser().resolve()
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise BootstrapError(f"cannot read bootstrap manifest: {source}: {exc}") from exc
    try:
        data = json.loads(raw, object_pairs_hook=_json_object_no_duplicates)
    except _DuplicateJsonKey as exc:
        raise BootstrapValidationError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise BootstrapValidationError(
            f"invalid bootstrap JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return parse_bootstrap_manifest(data)


def validate_bootstrap_manifest(path: str | Path) -> BootstrapManifest:
    """Pure file-level validation; never opens or mutates a database."""
    return load_bootstrap_manifest(path)


def preflight_bootstrap_import(
    database_url: str,
    source: str | Path,
) -> BootstrapPreflightResult:
    """Validate manifest plus current-schema/empty-domain target without mutation."""
    manifest = load_bootstrap_manifest(source)
    database = sqlite_path_from_url(database_url)
    try:
        validation = validate_database(database)
    except DatabaseValidationError as exc:
        raise BootstrapPreflightError(
            f"bootstrap target is not a valid current-schema database: {exc}"
        ) from exc
    counts = _readonly_inventory_counts(database)
    nonempty = {table: count for table, count in counts.items() if count}
    if nonempty:
        detail = ", ".join(f"{table}={count}" for table, count in nonempty.items())
        raise BootstrapPreflightError(
            f"bootstrap requires an empty inventory domain; found {detail}"
        )
    return BootstrapPreflightResult(
        database_path=str(database),
        alembic_revision=validation.alembic_revision,
        format=manifest.format,
        categories=len(manifest.categories),
        locations=len(manifest.locations),
        items=len(manifest.items),
    )


def apply_bootstrap_import(
    database_url: str,
    source: str | Path,
) -> BootstrapImportResult:
    """Apply a validated bootstrap manifest to an empty current-schema database."""
    manifest = load_bootstrap_manifest(source)
    preflight = preflight_bootstrap_import(database_url, source)

    engine = create_db_engine(database_url)
    try:
        with Session(engine) as session:
            try:
                _require_empty_inventory_session(session)
                _apply_manifest(session, manifest)
                event_count = int(session.scalar(select(func.count(Event.id))) or 0)
                session.commit()
            except Exception:
                session.rollback()
                raise
    finally:
        engine.dispose()

    return BootstrapImportResult(
        database_path=preflight.database_path,
        alembic_revision=preflight.alembic_revision,
        format=manifest.format,
        categories=len(manifest.categories),
        locations=len(manifest.locations),
        items=len(manifest.items),
        events=event_count,
    )


def _validate_bootstrap_semantics(manifest: BootstrapManifest) -> None:
    location_paths = _validate_tree_entries(manifest.locations, "locations", "location")
    category_paths = _validate_tree_entries(manifest.categories, "categories", "category")
    valid_states = {state.value for state in ItemState}
    identities: set[tuple[str, tuple[str, ...] | None]] = set()

    for index, item in enumerate(manifest.items):
        label = f"items[{index}]"
        item_name = normalize_name(item.name)
        if not item_name:
            raise BootstrapValidationError(f"{label}.name must not be blank")
        if item.state not in valid_states:
            raise BootstrapValidationError(
                f"{label}.state {item.state!r} is not a valid ItemState"
            )

        category_key = _optional_path_key(item.category_path, f"{label}.category_path")
        location_key = _optional_path_key(item.location_path, f"{label}.location_path")
        if category_key is not None and category_key not in category_paths:
            raise BootstrapValidationError(
                f"{label}.category_path does not reference a manifest category"
            )
        if location_key is not None and location_key not in location_paths:
            raise BootstrapValidationError(
                f"{label}.location_path does not reference a manifest location"
            )

        identity = (item_name, category_key)
        if identity in identities:
            raise BootstrapValidationError(
                f"duplicate item identity at {label}: normalized name/category already exists"
            )
        identities.add(identity)

        _validate_names(item.aliases, f"{label}.aliases")
        _validate_names(item.tags, f"{label}.tags")


def _validate_tree_entries(
    entries: list[BootstrapTreeEntry],
    label: str,
    entity_label: str,
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for index, entry in enumerate(entries):
        key = _path_key(entry.path, f"{label}[{index}].path")
        if key in paths:
            raise BootstrapValidationError(
                f"duplicate normalized {entity_label} path at {label}[{index}]"
            )
        paths.add(key)

    for index, entry in enumerate(entries):
        key = _path_key(entry.path, f"{label}[{index}].path")
        if len(key) > 1 and key[:-1] not in paths:
            raise BootstrapValidationError(
                f"{label}[{index}].path is missing its immediate parent path"
            )
    return paths


def _optional_path_key(
    path: list[str] | None,
    label: str,
) -> tuple[str, ...] | None:
    if path is None:
        return None
    return _path_key(path, label)


def _path_key(path: list[str], label: str) -> tuple[str, ...]:
    if not path:
        raise BootstrapValidationError(f"{label} must contain at least one component")
    normalized: list[str] = []
    for index, component in enumerate(path):
        value = normalize_name(component)
        if not value:
            raise BootstrapValidationError(
                f"{label}[{index}] must not be blank"
            )
        normalized.append(value)
    return tuple(normalized)


def _validate_names(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for index, value in enumerate(values):
        normalized = normalize_name(value)
        if not normalized:
            raise BootstrapValidationError(f"{label}[{index}] must not be blank")
        if normalized in seen:
            raise BootstrapValidationError(
                f"{label} contains duplicate normalized value {value!r}"
            )
        seen.add(normalized)


def _readonly_inventory_counts(database: Path) -> dict[str, int]:
    uri = database.as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise BootstrapPreflightError(
            f"cannot open bootstrap target read-only: {exc}"
        ) from exc
    try:
        return {
            table: int(
                connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            )
            for table in _INVENTORY_TABLES
        }
    except sqlite3.Error as exc:
        raise BootstrapPreflightError(
            f"cannot inspect bootstrap target inventory domain: {exc}"
        ) from exc
    finally:
        connection.close()


def _require_empty_inventory_session(session: Session) -> None:
    models = (Category, Location, Item, Alias, Tag, ItemTag, Event)
    nonempty: dict[str, int] = {}
    for model in models:
        count = int(session.scalar(select(func.count()).select_from(model)) or 0)
        if count:
            nonempty[model.__tablename__] = count
    if nonempty:
        detail = ", ".join(f"{table}={count}" for table, count in nonempty.items())
        raise BootstrapPreflightError(
            f"bootstrap requires an empty inventory domain; found {detail}"
        )


def _apply_manifest(session: Session, manifest: BootstrapManifest) -> None:
    inventory = InventoryService(session, autocommit=False)
    category_ids: dict[tuple[str, ...], int] = {}
    location_ids: dict[tuple[str, ...], int] = {}

    for entry in sorted(manifest.categories, key=lambda value: len(value.path)):
        key = _path_key(entry.path, "category.path")
        parent_id = category_ids.get(key[:-1]) if len(key) > 1 else None
        category = inventory.create_category(
            entry.path[-1],
            parent_id=parent_id,
            description=entry.description,
        )
        category_ids[key] = category.id

    for entry in sorted(manifest.locations, key=lambda value: len(value.path)):
        key = _path_key(entry.path, "location.path")
        parent_id = location_ids.get(key[:-1]) if len(key) > 1 else None
        location = inventory.create_location(
            entry.path[-1],
            parent_id=parent_id,
            description=entry.description,
        )
        location_ids[key] = location.id

    for item in manifest.items:
        category_key = _optional_path_key(item.category_path, "item.category_path")
        location_key = _optional_path_key(item.location_path, "item.location_path")
        inventory.create_item(
            item.name,
            description=item.description,
            state=item.state,
            category_id=category_ids.get(category_key) if category_key is not None else None,
            location_id=location_ids.get(location_key) if location_key is not None else None,
            quantity=item.quantity,
            attributes=item.attributes,
            aliases=item.aliases,
            tags=item.tags,
            original_text=BOOTSTRAP_PROVENANCE,
        )
