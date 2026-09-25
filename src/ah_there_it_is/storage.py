"""SQLite backup, validation, restore, and portable inventory export."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable, Iterator
from typing import Any, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import migration_heads, upgrade_database
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
from ah_there_it_is.domain.quantity import QuantityValue
from ah_there_it_is.domain.states import ItemState, LocationStatus
from ah_there_it_is.portable_stream import (
    PortableInputError,
    PortableInputWorkspace,
    SpoolMarker,
    read_portable_workspace,
)


PORTABLE_V1_VERSION = "inventory-portable-v1"
PORTABLE_V2_VERSION = "inventory-portable-v2"
PORTABLE_EXPORT_VERSION = "inventory-portable-v3"
CURRENT_SCHEMA_REVISION = "1a7c4e9d2b10"
_VALIDATION_SAMPLE_LIMIT = 20


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



class PortableItemV2(PortableItem):
    location_status: str


class PortableInventoryV2(_PortableModel):
    categories: list[PortableTreeNode]
    locations: list[PortableTreeNode]
    items: list[PortableItemV2]


class PortableInventoryDocumentV2(_PortableModel):
    format: str
    exported_at: str
    source: PortableSource
    inventory: PortableInventoryV2
    history: PortableHistory
    excluded: list[str]


class PortableItemV3(PortableItemV2):
    quantity_mode: str
    quantity: int | None = Field(ge=1)
    removal_reason: str | None


class PortableInventoryV3(_PortableModel):
    categories: list[PortableTreeNode]
    locations: list[PortableTreeNode]
    items: list[PortableItemV3]


class PortableInventoryDocumentV3(_PortableModel):
    format: str
    exported_at: str
    source: PortableSource
    inventory: PortableInventoryV3
    history: PortableHistory
    excluded: list[str]


PortableDocument = (
    PortableInventoryDocument | PortableInventoryDocumentV2 | PortableInventoryDocumentV3
)


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


@dataclass(frozen=True)
class PortableExportResult:
    destination: str
    format: str
    source_alembic_revision: str
    categories: int
    locations: int
    items: int
    events: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortableValidationSummary:
    format: str
    source_alembic_revision: str
    categories: int
    locations: int
    items: int
    events: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _PortableTreeProjection:
    id: int
    parent_id: int | None
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _PortableItemProjection:
    id: int
    name: str
    description: str | None
    state: str
    category_id: int | None
    location_id: int | None
    location_status: str
    quantity_mode: str
    quantity: int | None
    removal_reason: str | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _PortableEventProjection:
    id: int
    event_type: str
    item_id: int | None
    from_location_id: int | None
    to_location_id: int | None
    payload: dict[str, Any]
    original_text: str | None
    created_at: datetime


class _PortableStreamEnvelope(_PortableModel):
    format: str
    exported_at: str
    source: PortableSource
    inventory: dict[str, Any]
    history: dict[str, Any]
    excluded: list[str]


def parse_portable_inventory(data: Any) -> PortableDocument:
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
            f"expected {PORTABLE_V1_VERSION!r}, {PORTABLE_V2_VERSION!r}, "
            f"or {PORTABLE_EXPORT_VERSION!r}"
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


def _parse_portable_inventory_v2(
    data: dict[str, Any],
) -> PortableInventoryDocumentV2:
    """Validate the current inventory-portable-v2 contract."""
    try:
        document = PortableInventoryDocumentV2.model_validate(data)
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


def _parse_portable_inventory_v3(
    data: dict[str, Any],
) -> PortableInventoryDocumentV3:
    """Validate the current inventory-portable-v3 contract."""
    try:
        document = PortableInventoryDocumentV3.model_validate(data)
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
    PORTABLE_V1_VERSION: _parse_portable_inventory_v1,
    PORTABLE_V2_VERSION: _parse_portable_inventory_v2,
    PORTABLE_EXPORT_VERSION: _parse_portable_inventory_v3,
}


def load_portable_inventory(path: str | Path) -> PortableDocument:
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


def validate_portable_inventory(path: str | Path) -> PortableDocument:
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


def validate_portable_workspace(
    workspace: PortableInputWorkspace,
) -> PortableValidationSummary:
    """Validate a bounded workspace without constructing a PortableDocument."""
    envelope = _validate_portable_record(
        _PortableStreamEnvelope,
        workspace.structure,
        "<document>",
    )
    if envelope.format not in (
        PORTABLE_V1_VERSION, PORTABLE_V2_VERSION, PORTABLE_EXPORT_VERSION
    ):
        raise PortableInventoryValidationError(
            f"unsupported portable format {envelope.format!r}; "
            f"expected {PORTABLE_V1_VERSION!r}, {PORTABLE_V2_VERSION!r}, "
            f"or {PORTABLE_EXPORT_VERSION!r}"
        )
    _require_spool_members(
        envelope.inventory,
        {"categories", "locations", "items"},
        "inventory",
    )
    _require_spool_members(envelope.history, {"events"}, "history")
    _portable_datetime(envelope.exported_at, "exported_at")
    if not envelope.source.alembic_revision.strip():
        raise PortableInventoryValidationError(
            "source.alembic_revision must not be empty"
        )
    if len(envelope.excluded) != len(set(envelope.excluded)):
        raise PortableInventoryValidationError("excluded contains duplicate entries")

    category_ids, category_parents = _validate_stream_trees(
        workspace, "categories", "category"
    )
    location_ids, location_parents = _validate_stream_trees(
        workspace, "locations", "location"
    )
    _validate_stream_hierarchy(category_parents, "category")
    _validate_stream_hierarchy(location_parents, "location")
    item_ids = _validate_stream_items(
        workspace,
        version=envelope.format,
        category_ids=category_ids,
        location_ids=location_ids,
    )
    _validate_stream_events(workspace, item_ids=item_ids, location_ids=location_ids)
    return PortableValidationSummary(
        format=envelope.format,
        source_alembic_revision=envelope.source.alembic_revision,
        categories=workspace.counts["categories"],
        locations=workspace.counts["locations"],
        items=workspace.counts["items"],
        events=workspace.counts["events"],
    )


@contextmanager
def _validated_portable_workspace(
    source: str | Path,
) -> Iterator[tuple[PortableInputWorkspace, PortableValidationSummary]]:
    try:
        with read_portable_workspace(source) as workspace:
            yield workspace, validate_portable_workspace(workspace)
    except PortableInputError as exc:
        raise PortableInventoryValidationError(str(exc)) from exc


def _validate_portable_record(model: type[_PortableModel], value: Any, path: str):
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        details = []
        for error in exc.errors():
            suffix = ".".join(str(part) for part in error["loc"])
            location = f"{path}.{suffix}" if suffix else path
            details.append(f"{location}: {error['msg']}")
        raise PortableInventoryValidationError(
            "invalid portable document structure: " + "; ".join(details)
        ) from exc


def _require_spool_members(
    section: dict[str, Any],
    expected: set[str],
    path: str,
) -> None:
    actual = set(section)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise PortableInventoryValidationError(
            f"invalid portable document structure: {path} missing fields {missing!r}"
        )
    if extra:
        raise PortableInventoryValidationError(
            f"invalid portable document structure: {path} has extra fields {extra!r}"
        )
    for name in expected:
        marker = section[name]
        if not isinstance(marker, SpoolMarker) or marker.section != name:
            raise PortableInventoryValidationError(
                f"invalid portable document structure: {path}.{name} must be an array"
            )


def _validate_stream_trees(
    workspace: PortableInputWorkspace,
    section: str,
    label: str,
) -> tuple[set[int], dict[int, int | None]]:
    ids: set[int] = set()
    parents: dict[int, int | None] = {}
    siblings: dict[tuple[int | None, str], int] = {}
    for index, raw in enumerate(workspace.iter_records(section)):
        node = _validate_portable_record(
            PortableTreeNode, raw, f"inventory.{section}.{index}"
        )
        if node.id in ids:
            raise PortableInventoryValidationError(f"duplicate {label} id={node.id}")
        ids.add(node.id)
        parents[node.id] = node.parent_id
        normalized = _portable_name(node.name, f"{label} id={node.id} name")
        _portable_created_updated(
            node.created_at, node.updated_at, f"{label} id={node.id}"
        )
        if node.parent_id == node.id:
            raise PortableInventoryValidationError(
                f"{label} id={node.id} cannot be its own parent"
            )
        sibling = (node.parent_id, normalized)
        previous = siblings.get(sibling)
        if previous is not None:
            raise PortableInventoryValidationError(
                f"duplicate sibling {label} names under parent {node.parent_id}: "
                f"ids {previous} and {node.id}"
            )
        siblings[sibling] = node.id
    return ids, parents


def _validate_stream_hierarchy(
    parents: dict[int, int | None],
    label: str,
) -> None:
    for node_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in parents:
            raise PortableInventoryValidationError(
                f"{label} id={node_id} references missing parent id={parent_id}"
            )
    done: set[int] = set()
    for start_id in parents:
        positions: dict[int, int] = {}
        chain: list[int] = []
        current_id: int | None = start_id
        while current_id is not None and current_id not in done:
            if current_id in positions:
                cycle = chain[positions[current_id]:] + [current_id]
                raise PortableInventoryValidationError(
                    f"{label} hierarchy cycle: "
                    + " -> ".join(str(value) for value in cycle)
                )
            positions[current_id] = len(chain)
            chain.append(current_id)
            current_id = parents[current_id]
        done.update(chain)


def _validate_stream_items(
    workspace: PortableInputWorkspace,
    *,
    version: str,
    category_ids: set[int],
    location_ids: set[int],
) -> set[int]:
    model: type[PortableItem] | type[PortableItemV2] | type[PortableItemV3]
    if version == PORTABLE_EXPORT_VERSION:
        model = PortableItemV3
    elif version == PORTABLE_V2_VERSION:
        model = PortableItemV2
    else:
        model = PortableItem
    legacy = version != PORTABLE_EXPORT_VERSION
    allowed_states = {state.value for state in ItemState}
    if not legacy:
        allowed_states -= {ItemState.DISCARDED.value, ItemState.SOLD.value}
    terminal_states = (
        {ItemState.DISCARDED.value, ItemState.SOLD.value}
        if legacy else {ItemState.REMOVED.value}
    )
    allowed_location_statuses = {status.value for status in LocationStatus}
    item_ids: set[int] = set()
    known_tags: dict[str, str] = {}
    for index, raw in enumerate(workspace.iter_records("items")):
        path = f"inventory.items.{index}"
        item = _validate_portable_record(model, raw, path)
        if item.id in item_ids:
            raise PortableInventoryValidationError(f"duplicate item id={item.id}")
        item_ids.add(item.id)
        _portable_name(item.name, f"{path}.name")
        _portable_created_updated(item.created_at, item.updated_at, path)
        if item.state not in allowed_states:
            allowed = ", ".join(sorted(allowed_states))
            raise PortableInventoryValidationError(
                f"{path}.state has invalid value {item.state!r}; allowed: {allowed}"
            )
        location_status = (
            item.location_status
            if version != PORTABLE_V1_VERSION
            else _legacy_location_status(item.state, item.location_id)
        )
        if location_status not in allowed_location_statuses:
            raise PortableInventoryValidationError(
                f"{path}.location_status has invalid value {location_status!r}"
            )
        if (
            (location_status == LocationStatus.KNOWN.value)
            != (item.location_id is not None)
            or (item.state in terminal_states)
            != (location_status == LocationStatus.NOT_APPLICABLE.value)
        ):
            raise PortableInventoryValidationError(
                f"{path} has contradictory state, location_id, and location_status"
            )
        if isinstance(item, PortableItemV3):
            try:
                QuantityValue.coerce(item.quantity_mode, item.quantity)
            except ValueError as exc:
                raise PortableInventoryValidationError(
                    f"{path} has contradictory quantity_mode and quantity: {exc}"
                ) from exc
            if (item.state == ItemState.REMOVED.value) != (
                item.removal_reason is not None
            ):
                raise PortableInventoryValidationError(
                    f"{path} has contradictory state and removal_reason"
                )
            if item.removal_reason is not None and not item.removal_reason.strip():
                raise PortableInventoryValidationError(
                    f"{path}.removal_reason must not be blank"
                )
        if item.category_id is not None and item.category_id not in category_ids:
            raise PortableInventoryValidationError(
                f"{path}.category_id references missing category id={item.category_id}"
            )
        if item.location_id is not None and item.location_id not in location_ids:
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
    return item_ids


def _validate_stream_events(
    workspace: PortableInputWorkspace,
    *,
    item_ids: set[int],
    location_ids: set[int],
) -> None:
    event_ids: set[int] = set()
    for index, raw in enumerate(workspace.iter_records("events")):
        path = f"history.events.{index}"
        event = _validate_portable_record(PortableEvent, raw, path)
        if event.id in event_ids:
            raise PortableInventoryValidationError(f"duplicate event id={event.id}")
        event_ids.add(event.id)
        _portable_name(event.event_type, f"{path}.event_type")
        _portable_datetime(event.created_at, f"{path}.created_at")
        if event.item_id is not None and event.item_id not in item_ids:
            raise PortableInventoryValidationError(
                f"{path}.item_id references missing item id={event.item_id}"
            )
        for field_name, location_id in (
            ("from_location_id", event.from_location_id),
            ("to_location_id", event.to_location_id),
        ):
            if location_id is not None and location_id not in location_ids:
                raise PortableInventoryValidationError(
                    f"{path}.{field_name} references missing location id={location_id}"
                )


def _validate_portable_semantics(document: PortableDocument) -> None:
    legacy = document.format != PORTABLE_EXPORT_VERSION
    has_location_status = document.format != PORTABLE_V1_VERSION
    allowed_states = {state.value for state in ItemState}
    if not legacy:
        allowed_states -= {ItemState.DISCARDED.value, ItemState.SOLD.value}
    terminal_states = (
        {ItemState.DISCARDED.value, ItemState.SOLD.value}
        if legacy else {ItemState.REMOVED.value}
    )
    allowed_location_statuses = {status.value for status in LocationStatus}
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
        if item.state not in allowed_states:
            allowed = ", ".join(sorted(allowed_states))
            raise PortableInventoryValidationError(
                f"{path}.state has invalid value {item.state!r}; allowed: {allowed}"
            )
        location_status = (
            item.location_status
            if has_location_status
            else _legacy_location_status(item.state, item.location_id)
        )
        if location_status not in allowed_location_statuses:
            raise PortableInventoryValidationError(
                f"{path}.location_status has invalid value {location_status!r}"
            )
        if (
            (location_status == LocationStatus.KNOWN.value)
            != (item.location_id is not None)
            or (item.state in terminal_states)
            != (location_status == LocationStatus.NOT_APPLICABLE.value)
        ):
            raise PortableInventoryValidationError(
                f"{path} has contradictory state, location_id, and location_status"
            )
        if isinstance(item, PortableItemV3):
            try:
                QuantityValue.coerce(item.quantity_mode, item.quantity)
            except ValueError as exc:
                raise PortableInventoryValidationError(
                    f"{path} has contradictory quantity_mode and quantity: {exc}"
                ) from exc
            if (item.state == ItemState.REMOVED.value) != (
                item.removal_reason is not None
            ):
                raise PortableInventoryValidationError(
                    f"{path} has contradictory state and removal_reason"
                )
            if item.removal_reason is not None and not item.removal_reason.strip():
                raise PortableInventoryValidationError(
                    f"{path}.removal_reason must not be blank"
                )
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


def _legacy_location_status(state: str, location_id: int | None) -> str:
    if location_id is not None:
        return LocationStatus.KNOWN.value
    if state in {ItemState.DISCARDED.value, ItemState.SOLD.value}:
        return LocationStatus.NOT_APPLICABLE.value
    return LocationStatus.UNKNOWN.value


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


def expected_alembic_head() -> str:
    heads = migration_heads()
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
                for row in connection.execute(
                    f"PRAGMA integrity_check({_VALIDATION_SAMPLE_LIMIT})"
                )
            )
            foreign_key_count, foreign_keys = _foreign_key_summary(connection)
            versions = [
                str(row[0])
                for row in connection.execute(
                    "SELECT version_num FROM alembic_version"
                )
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
    if foreign_key_count:
        problems.append(
            f"foreign_key_check count={foreign_key_count} samples={foreign_keys!r}"
        )
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


def _foreign_key_summary(
    connection: sqlite3.Connection,
) -> tuple[int, tuple[tuple[Any, ...], ...]]:
    count = int(
        connection.execute(
            "SELECT count(*) FROM pragma_foreign_key_check"
        ).fetchone()[0]
    )
    samples = tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT * FROM pragma_foreign_key_check "
            "ORDER BY \"table\", rowid, parent, fkid LIMIT ?",
            (_VALIDATION_SAMPLE_LIMIT,),
        )
    )
    return count, samples


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
        try:
            _copy_sqlite_snapshot(source, temporary)
        except Exception as exc:
            raise StorageError(f"backup snapshot copy failed: {exc}") from exc
        try:
            validation = validate_database(temporary)
        except Exception as exc:
            raise StorageError(f"backup candidate validation failed: {exc}") from exc
        if target.exists() and not overwrite:
            raise StorageError(f"backup destination already exists: {target}")
        try:
            if overwrite:
                os.replace(temporary, target)
            else:
                _publish_backup_no_overwrite(temporary, target)
        except StorageError:
            raise
        except OSError as exc:
            raise StorageError(f"backup publication failed: {exc}") from exc
        try:
            _fsync_path(target)
            _fsync_directory(target.parent)
        except OSError as exc:
            try:
                validate_database(target)
                validation_detail = "published destination validates successfully"
            except Exception as validation_error:
                validation_detail = (
                    "published destination validation failed: "
                    f"{type(validation_error).__name__}: {validation_error}"
                )
            raise StorageError(
                f"backup was published but durability sync failed: {exc}; "
                f"{validation_detail}"
            ) from exc
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
    validate_database(safety)

    replacement = _temporary_sibling(target, "restore")
    try:
        try:
            _copy_sqlite_snapshot(source, replacement)
        except Exception as exc:
            raise StorageError(
                f"restore candidate staging copy failed: {exc}"
            ) from exc
        try:
            validate_database(replacement)
        except Exception as exc:
            raise StorageError(
                f"restore candidate staging validation failed: {exc}"
            ) from exc
        _checkpoint_for_restore(target)
        _unlink_sidecars(target)
        try:
            os.replace(replacement, target)
        except OSError as exc:
            raise StorageError(f"restore publication failed: {exc}") from exc
        try:
            _fsync_path(target)
            _fsync_directory(target.parent)
            restored = validate_database(target)
        except Exception as restore_error:
            try:
                _rollback_restore(target, safety)
            except Exception as rollback_error:
                raise StorageError(
                    "restore failed after active database publication: "
                    f"{type(restore_error).__name__}: {restore_error}; "
                    "rollback failed: "
                    f"{type(rollback_error).__name__}: {rollback_error}; "
                    f"safety backup retained at {safety}"
                ) from rollback_error
            raise StorageError(
                "restore failed after active database publication: "
                f"{type(restore_error).__name__}: {restore_error}; "
                f"rollback succeeded from safety backup {safety}"
            ) from restore_error
        return RestoreResult(
            restored_path=str(target),
            safety_backup_path=str(safety),
            candidate=candidate_validation,
            restored=restored,
        )
    finally:
        _unlink_sqlite_files(replacement)


def _rollback_restore(target: Path, safety: Path) -> DatabaseValidation:
    rollback = _temporary_sibling(target, "rollback")
    try:
        _copy_sqlite_snapshot(safety, rollback)
        validate_database(rollback)
        _unlink_sidecars(target)
        try:
            os.replace(rollback, target)
        except OSError as exc:
            raise StorageError(f"rollback publication failed: {exc}") from exc
        _fsync_path(target)
        _fsync_directory(target.parent)
        return validate_database(target)
    finally:
        _unlink_sqlite_files(rollback)


def rehearse_restore(database_url: str, candidate: str | Path) -> dict[str, Any]:
    """Exercise the real restore path on an isolated current-schema database.

    The configured active database is only resolved for identity comparison.
    No connection is opened to it, so its WAL and sidecars cannot be changed.
    """
    source = Path(candidate).expanduser().resolve()
    report: dict[str, Any] = {
        "ok": False,
        "candidate": str(source),
        "restore_mechanics": {"ok": None, "error": None},
        "physical_validation": {"ok": None, "error": None, "restored": None},
        "doctor": {"ok": None, "report": None, "error": None},
    }
    try:
        active = sqlite_path_from_url(database_url)
        if source == active:
            raise StorageError("restore rehearsal candidate must differ from active database")

        from ah_there_it_is.database_doctor import diagnose_database

        with tempfile.TemporaryDirectory(prefix="ah-restore-rehearsal-") as directory:
            fake_active = Path(directory) / "fake-active.db"
            fake_url = f"sqlite:///{fake_active}"
            # A newly migrated empty inventory is an equivalent valid active
            # target; the real configured active database is never opened.
            upgrade_database(fake_url)
            if not diagnose_database(fake_url).ok:
                raise StorageError("temporary current-schema active database is unhealthy")
            try:
                restore_backup(
                    fake_url, source,
                    safety_backup=Path(directory) / "pre-restore-safety.db",
                )
            except Exception as exc:
                report["restore_mechanics"] = {
                    "ok": False, "error": f"{type(exc).__name__}: {exc}",
                }
                try:
                    validate_database(source)
                except Exception as validation_error:
                    report["physical_validation"] = {
                        "ok": False,
                        "error": f"{type(validation_error).__name__}: {validation_error}",
                        "restored": None,
                    }
                return report

            report["restore_mechanics"] = {"ok": True, "error": None}
            try:
                physical = validate_database(fake_active)
            except Exception as exc:
                report["physical_validation"] = {
                    "ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "restored": None,
                }
                return report
            report["physical_validation"] = {
                "ok": True, "error": None, "restored": physical.as_dict(),
            }
            try:
                doctor = diagnose_database(fake_url)
                report["doctor"] = {
                    "ok": doctor.ok, "report": doctor.as_dict(), "error": None,
                }
            except Exception as exc:
                report["doctor"] = {
                    "ok": False, "report": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            report["ok"] = bool(report["doctor"]["ok"])
    except Exception as exc:
        report["restore_mechanics"] = {
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
        }
        report["ok"] = False
    return report


def export_portable_inventory(
    database_url: str,
    destination: str | Path,
) -> dict[str, Any]:
    """Compatibility helper returning the fully materialized document."""
    stream_portable_inventory(database_url, destination)
    target = Path(destination).expanduser().resolve()
    return json.loads(target.read_text(encoding="utf-8"))


def stream_portable_inventory(
    database_url: str,
    destination: str | Path,
) -> PortableExportResult:
    database = sqlite_path_from_url(database_url)
    validation = validate_database(database)
    engine = create_db_engine(database_url)
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_sibling(target, "json")
    try:
        factory = create_session_factory(engine)
        with factory() as session, temporary.open("w", encoding="utf-8") as handle:
            # SQLAlchemy's logical autobegin does not force pysqlite to open a
            # database read transaction for SELECT statements. An explicit
            # BEGIN makes all projection phases share one SQLite snapshot.
            session.connection().exec_driver_sql("BEGIN")
            counts = _write_portable_stream(
                handle, session, validation.alembic_revision
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_path(target)
        _fsync_directory(target.parent)
        return PortableExportResult(
            destination=str(target),
            format=PORTABLE_EXPORT_VERSION,
            source_alembic_revision=validation.alembic_revision,
            categories=counts[0],
            locations=counts[1],
            items=counts[2],
            events=counts[3],
        )
    finally:
        engine.dispose()
        temporary.unlink(missing_ok=True)


def _write_portable_stream(
    handle: TextIO,
    session: Session,
    alembic_revision: str,
) -> tuple[int, int, int, int]:
    encode = lambda value: json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    handle.write("{")
    handle.write(f'"format":{encode(PORTABLE_EXPORT_VERSION)},')
    handle.write(f'"exported_at":{encode(datetime.now(timezone.utc).isoformat())},')
    handle.write(f'"source":{{"alembic_revision":{encode(alembic_revision)}}},')
    handle.write('"inventory":{"categories":')
    categories = _write_json_array(
        handle, (_tree_projection_dict(row) for row in _stream_trees(session, Category))
    )
    handle.write(',"locations":')
    locations = _write_json_array(
        handle, (_tree_projection_dict(row) for row in _stream_trees(session, Location))
    )
    handle.write(',"items":')
    items = _write_json_array(handle, _stream_item_dicts(session))
    handle.write('},"history":{"events":')
    events = _write_json_array(
        handle, (_event_projection_dict(row) for row in _stream_events(session))
    )
    handle.write('},"excluded":')
    handle.write(encode(_portable_excluded()))
    handle.write("}\n")
    return categories, locations, items, events


def _write_json_array(handle: TextIO, rows: Iterable[dict[str, Any]]) -> int:
    handle.write("[")
    count = 0
    for row in rows:
        if count:
            handle.write(",")
        handle.write(json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        count += 1
    handle.write("]")
    return count


def _stream_trees(
    session: Session,
    model: type[Category] | type[Location],
) -> Iterator[_PortableTreeProjection]:
    statement = select(
        model.id, model.parent_id, model.name, model.description,
        model.created_at, model.updated_at,
    ).order_by(model.id).execution_options(yield_per=250)
    for row in session.execute(statement):
        yield _PortableTreeProjection(*row)


def _stream_item_dicts(session: Session) -> Iterator[dict[str, Any]]:
    after_id = 0
    while True:
        rows = [
            _PortableItemProjection(*row)
            for row in session.execute(
                select(
                    Item.id, Item.name, Item.description, Item.state,
                    Item.category_id, Item.current_location_id,
                    Item.location_status, Item.quantity_mode, Item.quantity,
                    Item.removal_reason, Item.attributes,
                    Item.created_at, Item.updated_at,
                )
                .where(Item.id > after_id)
                .order_by(Item.id)
                .limit(250)
            )
        ]
        if not rows:
            return
        item_ids = [row.id for row in rows]
        aliases: dict[int, list[str]] = {}
        for item_id, name in session.execute(
            select(Alias.item_id, Alias.name)
            .where(Alias.item_id.in_(item_ids))
            .order_by(Alias.item_id, Alias.id)
        ):
            aliases.setdefault(item_id, []).append(name)
        tags: dict[int, list[str]] = {}
        for item_id, name in session.execute(
            select(ItemTag.item_id, Tag.name)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(ItemTag.item_id.in_(item_ids))
            .order_by(ItemTag.item_id, ItemTag.tag_id)
        ):
            tags.setdefault(item_id, []).append(name)
        for row in rows:
            yield _item_projection_dict(
                row,
                aliases=aliases.get(row.id, []),
                tags=tags.get(row.id, []),
            )
        after_id = rows[-1].id


def _stream_events(session: Session) -> Iterator[_PortableEventProjection]:
    statement = select(
        Event.id, Event.event_type, Event.item_id, Event.from_location_id,
        Event.to_location_id, Event.payload, Event.original_text, Event.created_at,
    ).order_by(Event.id).execution_options(yield_per=250)
    for row in session.execute(statement):
        yield _PortableEventProjection(*row)


def import_portable_inventory(
    database_url: str,
    source: str | Path,
    destination: str | Path,
) -> PortableImportResult:
    """Reconstruct portable inventory/history into a brand-new migrated database."""
    target = validate_portable_import_target(database_url, destination)
    with _validated_portable_workspace(source) as (workspace, summary):
        target.parent.mkdir(parents=True, exist_ok=True)
        working = _temporary_sibling(target, "portable-work")
        publish = _temporary_sibling(target, "portable-final")
        try:
            _migrate_new_database(working)
            working_url = f"sqlite:///{working}"
            engine = create_db_engine(working_url)
            factory = create_session_factory(engine)
            try:
                with factory() as session:
                    try:
                        _write_portable_workspace_inventory(
                            session, workspace, summary
                        )
                        _write_portable_workspace_events(session, workspace)
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
            _publish_new_database(publish, target)
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
                format=summary.format,
                source_alembic_revision=summary.source_alembic_revision,
                categories=summary.categories,
                locations=summary.locations,
                items=summary.items,
                events=summary.events,
                database=database,
            )
        finally:
            _unlink_sqlite_files(working)
            _unlink_sqlite_files(publish)


def _migrate_new_database(path: Path) -> None:
    if path.exists():
        raise StorageError(f"portable import staging path already exists: {path}")
    database_url = f"sqlite:///{path}"
    # The packaged runner always pins Alembic to this explicit staging URL,
    # so ambient active-database configuration cannot hijack portable import.
    upgrade_database(database_url)


def _write_portable_inventory(
    session: Session,
    document: PortableDocument,
) -> None:
    for level in _portable_tree_levels(document.inventory.categories):
        session.add_all([
            Category(
                id=node.id,
                parent_id=node.parent_id,
                name=node.name,
                normalized_name=normalize_name(node.name),
                description=node.description,
                created_at=_portable_datetime(node.created_at, "category.created_at"),
                updated_at=_portable_datetime(node.updated_at, "category.updated_at"),
            ) for node in level
        ])
        session.flush()

    for level in _portable_tree_levels(document.inventory.locations):
        session.add_all([
            Location(
                id=node.id,
                parent_id=node.parent_id,
                name=node.name,
                normalized_name=normalize_name(node.name),
                description=node.description,
                created_at=_portable_datetime(node.created_at, "location.created_at"),
                updated_at=_portable_datetime(node.updated_at, "location.updated_at"),
            ) for node in level
        ])
        session.flush()

    items = sorted(document.inventory.items, key=lambda item: item.id)
    session.add_all([
            Item(
                id=item.id,
                name=item.name,
                normalized_name=normalize_name(item.name),
                description=item.description,
                state=_portable_import_truth(item)[0],
                category_id=item.category_id,
                current_location_id=item.location_id,
                location_status=_portable_import_truth(item)[1],
                quantity_mode=_portable_import_truth(item)[2],
                quantity=item.quantity,
                removal_reason=_portable_import_truth(item)[3],
                attributes=item.attributes,
                created_at=_portable_datetime(item.created_at, "item.created_at"),
                updated_at=_portable_datetime(item.updated_at, "item.updated_at"),
            ) for item in items
    ])
    session.flush()

    alias_rows = [
        {
            "item_id": item.id,
            "name": alias,
            "normalized_name": normalize_name(alias),
        }
        for item in items
        for alias in item.aliases
    ]
    if alias_rows:
        session.execute(Alias.__table__.insert(), alias_rows)

    tag_names: dict[str, str] = {}
    for item in items:
        for tag_name in item.tags:
            normalized = normalize_name(tag_name)
            tag_names.setdefault(normalized, tag_name)
    tag_ids = {
        normalized: index
        for index, normalized in enumerate(tag_names, start=1)
    }
    if tag_names:
        session.execute(
            Tag.__table__.insert(),
            [
                {
                    "id": tag_ids[normalized],
                    "name": name,
                    "normalized_name": normalized,
                }
                for normalized, name in tag_names.items()
            ],
        )
    item_tag_rows = [
        {
            "item_id": item.id,
            "tag_id": tag_ids[normalize_name(tag_name)],
        }
        for item in items
        for tag_name in item.tags
    ]
    if item_tag_rows:
        session.execute(ItemTag.__table__.insert(), item_tag_rows)

    session.add_all([
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
        for event in sorted(document.history.events, key=lambda event: event.id)
    ])
    session.flush()


def _write_portable_workspace_inventory(
    session: Session,
    workspace: PortableInputWorkspace,
    summary: PortableValidationSummary,
    *,
    batch_size: int = 250,
    _observe_batch: Any = None,
) -> None:
    """Replay validated inventory spools with bounded Core batches."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    _write_workspace_tree(
        session, workspace, "categories", Category, batch_size, _observe_batch
    )
    _write_workspace_tree(
        session, workspace, "locations", Location, batch_size, _observe_batch
    )
    if summary.format == PORTABLE_EXPORT_VERSION:
        item_model = PortableItemV3
    elif summary.format == PORTABLE_V2_VERSION:
        item_model = PortableItemV2
    else:
        item_model = PortableItem
    _execute_batched(
        session,
        Item.__table__,
        (
            {
                "id": item.id,
                "name": item.name,
                "normalized_name": normalize_name(item.name),
                "description": item.description,
                "state": _portable_import_truth(item)[0],
                "category_id": item.category_id,
                "current_location_id": item.location_id,
                "location_status": _portable_import_truth(item)[1],
                "quantity_mode": _portable_import_truth(item)[2],
                "quantity": item.quantity,
                "removal_reason": _portable_import_truth(item)[3],
                "attributes": item.attributes,
                "created_at": _portable_datetime(item.created_at, "item.created_at"),
                "updated_at": _portable_datetime(item.updated_at, "item.updated_at"),
            }
            for item in _workspace_records(workspace, "items", item_model)
        ),
        batch_size,
        "items",
        _observe_batch,
    )
    _execute_batched(
        session,
        Alias.__table__,
        (
            {
                "item_id": item.id,
                "name": alias,
                "normalized_name": normalize_name(alias),
            }
            for item in _workspace_records(workspace, "items", item_model)
            for alias in item.aliases
        ),
        batch_size,
        "aliases",
        _observe_batch,
    )
    tag_ids, tag_names = _workspace_tag_index(workspace, item_model)
    _execute_batched(
        session,
        Tag.__table__,
        (
            {
                "id": tag_id,
                "name": tag_names[normalized],
                "normalized_name": normalized,
            }
            for normalized, tag_id in tag_ids.items()
        ),
        batch_size,
        "tags",
        _observe_batch,
    )
    _execute_batched(
        session,
        ItemTag.__table__,
        (
            {
                "item_id": item.id,
                "tag_id": tag_ids[normalize_name(tag)],
            }
            for item in _workspace_records(workspace, "items", item_model)
            for tag in item.tags
        ),
        batch_size,
        "item_tags",
        _observe_batch,
    )


def _write_portable_workspace_events(
    session: Session,
    workspace: PortableInputWorkspace,
    *,
    batch_size: int = 250,
    _observe_batch: Any = None,
) -> None:
    """Replay validated history without retaining the complete Event stream."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    _execute_batched(
        session,
        Event.__table__,
        (
            {
                "id": event.id,
                "event_type": event.event_type,
                "item_id": event.item_id,
                "from_location_id": event.from_location_id,
                "to_location_id": event.to_location_id,
                "payload": event.payload,
                "original_text": event.original_text,
                "created_at": _portable_datetime(event.created_at, "event.created_at"),
            }
            for event in _workspace_records(workspace, "events", PortableEvent)
        ),
        batch_size,
        "events",
        _observe_batch,
    )


def _workspace_records(
    workspace: PortableInputWorkspace,
    section: str,
    model: type[_PortableModel],
) -> Iterator[Any]:
    for index, raw in enumerate(workspace.iter_records(section)):
        yield _validate_portable_record(model, raw, f"{section}.{index}")


def _write_workspace_tree(
    session: Session,
    workspace: PortableInputWorkspace,
    section: str,
    table_model: type[Category] | type[Location],
    batch_size: int,
    observer: Any,
) -> None:
    parents: dict[int, int | None] = {}
    for node in _workspace_records(workspace, section, PortableTreeNode):
        parents[node.id] = node.parent_id
    depths: dict[int, int] = {}

    def depth(node_id: int) -> int:
        trail: list[int] = []
        current = node_id
        while current not in depths:
            trail.append(current)
            parent = parents[current]
            if parent is None:
                value = 0
                break
            current = parent
        else:
            value = depths[current] + 1
        for candidate in reversed(trail):
            depths[candidate] = value
            value += 1
        return depths[node_id]

    for node_id in parents:
        depth(node_id)
    for level in range(max(depths.values(), default=-1) + 1):
        _execute_batched(
            session,
            table_model.__table__,
            (
                {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "name": node.name,
                    "normalized_name": normalize_name(node.name),
                    "description": node.description,
                    "created_at": _portable_datetime(node.created_at, f"{section}.created_at"),
                    "updated_at": _portable_datetime(node.updated_at, f"{section}.updated_at"),
                }
                for node in _workspace_records(workspace, section, PortableTreeNode)
                if depths[node.id] == level
            ),
            batch_size,
            section,
            observer,
        )


def _workspace_tag_index(
    workspace: PortableInputWorkspace,
    item_model: type[PortableItem] | type[PortableItemV2] | type[PortableItemV3],
) -> tuple[dict[str, int], dict[str, str]]:
    order: dict[str, tuple[int, int]] = {}
    names: dict[str, str] = {}
    for item in _workspace_records(workspace, "items", item_model):
        for position, tag in enumerate(item.tags):
            normalized = normalize_name(tag)
            names.setdefault(normalized, tag)
            candidate = (item.id, position)
            if normalized not in order or candidate < order[normalized]:
                order[normalized] = candidate
    normalized_order = sorted(order, key=lambda name: (*order[name], name))
    return (
        {name: tag_id for tag_id, name in enumerate(normalized_order, start=1)},
        names,
    )


def _portable_import_truth(
    item: PortableItem | PortableItemV2 | PortableItemV3,
) -> tuple[str, str, str, str | None]:
    if isinstance(item, PortableItemV3):
        return (
            item.state,
            item.location_status,
            item.quantity_mode,
            item.removal_reason,
        )
    state = item.state
    removal_reason = None
    if state in {ItemState.SOLD.value, ItemState.DISCARDED.value}:
        removal_reason = state
        state = ItemState.REMOVED.value
    location_status = (
        item.location_status
        if isinstance(item, PortableItemV2)
        else _legacy_location_status(item.state, item.location_id)
    )
    return state, location_status, "exact", removal_reason


def _execute_batched(
    session: Session,
    table: Any,
    rows: Iterable[dict[str, Any]],
    batch_size: int,
    section: str,
    observer: Any,
) -> None:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            session.execute(table.insert(), batch)
            if observer is not None:
                observer(section, len(batch))
            batch.clear()
    if batch:
        session.execute(table.insert(), batch)
        if observer is not None:
            observer(section, len(batch))


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


def _portable_tree_levels(
    nodes: list[PortableTreeNode],
) -> list[list[PortableTreeNode]]:
    levels: list[list[PortableTreeNode]] = []
    by_id = {candidate.id: candidate for candidate in nodes}
    for node in _portable_tree_order(nodes):
        node_depth = 0
        parent_id = node.parent_id
        while parent_id is not None:
            node_depth += 1
            parent_id = by_id[parent_id].parent_id
        while len(levels) <= node_depth:
            levels.append([])
        levels[node_depth].append(node)
    return levels


def _validate_imported_search_state(session: Session) -> None:
    from ah_there_it_is.db.search_consistency import search_consistency

    result = search_consistency(session.connection())
    if not result.ok:
        raise StorageError(
            "portable import produced inconsistent FTS state: "
            f"missing={result.missing_count}, mismatched={result.mismatched_count}, "
            f"extra={result.extra_count}"
        )


def _portable_document(session: Session, alembic_revision: str) -> dict[str, Any]:
    categories = [
        _PortableTreeProjection(*row)
        for row in session.execute(
            select(
                Category.id, Category.parent_id, Category.name,
                Category.description, Category.created_at, Category.updated_at,
            ).order_by(Category.id)
        )
    ]
    locations = [
        _PortableTreeProjection(*row)
        for row in session.execute(
            select(
                Location.id, Location.parent_id, Location.name,
                Location.description, Location.created_at, Location.updated_at,
            ).order_by(Location.id)
        )
    ]
    items = [
        _PortableItemProjection(*row)
        for row in session.execute(
            select(
                Item.id, Item.name, Item.description, Item.state,
                Item.category_id, Item.current_location_id, Item.location_status,
                Item.quantity_mode, Item.quantity, Item.removal_reason,
                Item.attributes, Item.created_at, Item.updated_at,
            ).order_by(Item.id)
        )
    ]
    aliases: dict[int, list[str]] = {}
    for item_id, name in session.execute(
        select(Alias.item_id, Alias.name).order_by(Alias.item_id, Alias.id)
    ):
        aliases.setdefault(item_id, []).append(name)
    tags: dict[int, list[str]] = {}
    for item_id, name in session.execute(
        select(ItemTag.item_id, Tag.name)
        .join(Tag, Tag.id == ItemTag.tag_id)
        .order_by(ItemTag.item_id, ItemTag.tag_id)
    ):
        tags.setdefault(item_id, []).append(name)
    events = [
        _PortableEventProjection(*row)
        for row in session.execute(
            select(
                Event.id, Event.event_type, Event.item_id,
                Event.from_location_id, Event.to_location_id, Event.payload,
                Event.original_text, Event.created_at,
            ).order_by(Event.id)
        )
    ]

    return {
        "format": PORTABLE_EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "alembic_revision": alembic_revision,
        },
        "inventory": {
            "categories": [
                _tree_projection_dict(node)
                for node in categories
            ],
            "locations": [
                _tree_projection_dict(node)
                for node in locations
            ],
            "items": [
                _item_projection_dict(
                    item,
                    aliases=aliases.get(item.id, []),
                    tags=tags.get(item.id, []),
                )
                for item in items
            ],
        },
        "history": {
            "events": [
                _event_projection_dict(event)
                for event in events
            ]
        },
        "excluded": _portable_excluded(),
    }


def _tree_projection_dict(node: _PortableTreeProjection) -> dict[str, Any]:
    return {
        "id": node.id, "parent_id": node.parent_id, "name": node.name,
        "description": node.description, "created_at": _iso(node.created_at),
        "updated_at": _iso(node.updated_at),
    }


def _item_projection_dict(
    item: _PortableItemProjection,
    *,
    aliases: list[str],
    tags: list[str],
) -> dict[str, Any]:
    return {
        "id": item.id, "name": item.name, "description": item.description,
        "state": item.state, "category_id": item.category_id,
        "location_id": item.location_id, "location_status": item.location_status,
        "quantity_mode": item.quantity_mode, "quantity": item.quantity,
        "removal_reason": item.removal_reason, "attributes": item.attributes,
        "aliases": aliases, "tags": tags, "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def _event_projection_dict(event: _PortableEventProjection) -> dict[str, Any]:
    return {
        "id": event.id, "event_type": event.event_type,
        "item_id": event.item_id, "from_location_id": event.from_location_id,
        "to_location_id": event.to_location_id, "payload": event.payload,
        "original_text": event.original_text, "created_at": _iso(event.created_at),
    }


def _portable_excluded() -> list[str]:
    return [
        "agent_run_logs", "agent_feedback", "experiment_runs",
        "experiment_reviews", "provider_metadata",
    ]


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


def _publish_new_database(source: Path, target: Path) -> None:
    """Publish a new local SQLite database without replacing any path.

    POSIX has no atomic operation spanning the main file and both SQLite
    sidecars. We check sidecars before and after atomically reserving the main
    path with ``link``. This relies on the supported local-filesystem rule that
    SQLite sidecars are created by opening an existing main database, not as
    unrelated orphan files after another process loses the main-file race.
    """
    occupied_sidecar = next(
        (path for path in _sqlite_sidecars(target) if path.exists()),
        None,
    )
    if occupied_sidecar is not None:
        raise StorageError(
            f"portable import destination sidecar appeared during import: "
            f"{occupied_sidecar}"
        )
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
    occupied_sidecar = next(
        (path for path in _sqlite_sidecars(target) if path.exists()),
        None,
    )
    if occupied_sidecar is not None:
        try:
            target.unlink()
            _fsync_directory(target.parent)
        except OSError as cleanup_error:
            raise StorageError(
                f"portable import sidecar race at {occupied_sidecar}; "
                f"failed to remove reserved destination {target}: {cleanup_error}"
            ) from cleanup_error
        raise StorageError(
            f"portable import destination sidecar appeared during publication: "
            f"{occupied_sidecar}"
        )
    source.unlink()


def _publish_backup_no_overwrite(source: Path, target: Path) -> None:
    """Atomically publish a same-filesystem backup without replacement."""
    try:
        os.link(source, target)
    except FileExistsError as exc:
        raise StorageError(
            f"backup destination appeared during backup: {target}"
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"cannot atomically publish backup to {target}: {exc}"
        ) from exc
    source.unlink()


def _sqlite_sidecars(path: Path) -> tuple[Path, Path]:
    return Path(str(path) + "-wal"), Path(str(path) + "-shm")


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
