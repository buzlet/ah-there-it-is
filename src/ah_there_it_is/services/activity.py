# activity.py
"""Read-only bounded projections for browsing Item Event history."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Event, Item, Location
from ah_there_it_is.domain.exceptions import EntityNotFoundError


@dataclass(frozen=True)
class ActivityPage:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int
    has_previous: bool
    has_next: bool
    previous_page: int | None
    next_page: int | None


class ActivityService:
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100
    EVENT_LABELS = {
        "item_created": "Item created",
        "item_updated": "Item details updated",
        "item_moved": "Moved to a known Location",
        "item_taken": "Taken from storage / in use",
        "item_location_unknown": "Location marked unknown",
        "item_discarded": "Item discarded",
        "item_sold": "Item sold",
        "item_reactivated": "Item reactivated",
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    @classmethod
    def _validate_page(cls, page: int, page_size: int) -> None:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1 or page_size > cls.MAX_PAGE_SIZE:
            raise ValueError(
                f"page_size must be between 1 and {cls.MAX_PAGE_SIZE}"
            )

    @staticmethod
    def _filters(event_type: str | None, item_id: int | None) -> list[Any]:
        filters: list[Any] = []
        if event_type is not None:
            filters.append(Event.event_type == event_type)
        if item_id is not None:
            filters.append(Event.item_id == item_id)
        return filters

    def page(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        event_type: str | None = None,
        item_id: int | None = None,
    ) -> ActivityPage:
        self._validate_page(page, page_size)
        filters = self._filters(event_type, item_id)
        total = int(
            self.session.scalar(
                select(func.count(Event.id)).where(*filters)
            ) or 0
        )
        stmt = (
            select(
                Event.id,
                Event.event_type,
                Event.created_at,
                Event.item_id,
                Item.name,
            )
            .outerjoin(Item, Item.id == Event.item_id)
            .where(*filters)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        events = [
            {
                "id": event_id,
                "event_type": event_type,
                "event_label": self._event_label(event_type),
                "created_at": created_at,
                "item_id": item_id,
                "item_name": item_name,
            }
            for event_id, event_type, created_at, item_id, item_name
            in self.session.execute(stmt)
        ]
        has_previous = page > 1
        has_next = page * page_size < total
        return ActivityPage(
            items=events,
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
            has_previous=has_previous,
            has_next=has_next,
            previous_page=page - 1 if has_previous else None,
            next_page=page + 1 if has_next else None,
        )

    def detail(self, event_id: int) -> dict[str, Any]:
        row = self.session.execute(
            select(Event, Item.name)
            .outerjoin(Item, Item.id == Event.item_id)
            .where(Event.id == event_id)
        ).first()
        if row is None:
            raise EntityNotFoundError(f"event id={event_id} does not exist")
        event, item_name = row
        evidence = self._evidence(event)
        current_ids = {
            location_id
            for direction, location_id in (
                ("from", event.from_location_id),
                ("to", event.to_location_id),
            )
            if location_id is not None
            and self._snapshot_path(
                evidence, f"{direction}_location_path"
            ) is None
        }
        current_paths = self._current_location_paths(current_ids)
        return self._detail_projection(event, item_name, current_paths)

    def item_history(self, events: Sequence[Event]) -> list[dict[str, Any]]:
        needed: set[int] = set()
        for event in events:
            evidence = self._evidence(event)
            for direction, location_id in (
                ("from", event.from_location_id),
                ("to", event.to_location_id),
            ):
                if location_id is not None and self._snapshot_path(
                    evidence, f"{direction}_location_path"
                ) is None:
                    needed.add(location_id)
        current_paths = self._current_location_paths(needed)
        return [
            {
                "id": event.id,
                "event_type": event.event_type,
                "event_label": self._event_label(event.event_type),
                "created_at": event.created_at,
                "event_url": f"/activity/{event.id}",
                "from_path": self._location_path_projection(
                    event, "from", current_paths
                ),
                "to_path": self._location_path_projection(
                    event, "to", current_paths
                ),
            }
            for event in events
        ]

    def _detail_projection(
        self,
        event: Event,
        item_name: str | None,
        current_paths: dict[int, str],
    ) -> dict[str, Any]:
        evidence = self._evidence(event)
        category_paths = []
        for direction in ("from", "to"):
            components = self._snapshot_path(
                evidence, f"{direction}_category_path"
            )
            if components is not None:
                category_paths.append({
                    "direction": direction,
                    "components": components,
                    "text": " / ".join(part["name"] for part in components),
                })
        return {
            "id": event.id,
            "event_type": event.event_type,
            "event_label": self._event_label(event.event_type),
            "created_at": event.created_at,
            "item_id": event.item_id,
            "item_name": item_name,
            "from_location_id": event.from_location_id,
            "to_location_id": event.to_location_id,
            "from_path": self._location_path_projection(
                event, "from", current_paths
            ),
            "to_path": self._location_path_projection(
                event, "to", current_paths
            ),
            "category_paths": category_paths,
            "payload": event.payload,
            "original_text": event.original_text,
        }

    @classmethod
    def _event_label(cls, event_type: str) -> str:
        return cls.EVENT_LABELS.get(event_type, event_type)

    @staticmethod
    def _evidence(event: Event) -> dict[str, Any] | None:
        payload = event.payload
        evidence = payload.get("_history_evidence") if isinstance(payload, dict) else None
        if not isinstance(evidence, dict) or evidence.get("version") != 1:
            return None
        return evidence

    @staticmethod
    def _snapshot_path(
        evidence: dict[str, Any] | None, key: str
    ) -> list[dict[str, Any]] | None:
        raw = evidence.get(key) if evidence is not None else None
        if not isinstance(raw, list) or not raw:
            return None
        id_key = "location_id" if "location" in key else "category_id"
        components: list[dict[str, Any]] = []
        for component in raw:
            if not isinstance(component, dict):
                return None
            entity_id = component.get(id_key)
            name = component.get("name")
            if (
                not isinstance(entity_id, int)
                or isinstance(entity_id, bool)
                or not isinstance(name, str)
            ):
                return None
            components.append({"id": entity_id, "name": name})
        return components

    def _location_path_projection(
        self,
        event: Event,
        direction: str,
        current_paths: dict[int, str],
    ) -> dict[str, Any] | None:
        location_id = (
            event.from_location_id if direction == "from" else event.to_location_id
        )
        if location_id is None:
            return None
        components = self._snapshot_path(
            self._evidence(event), f"{direction}_location_path"
        )
        if components is not None:
            return {
                "label": "Historical path at event time",
                "text": " / ".join(part["name"] for part in components),
                "components": components,
                "source": "snapshot",
            }
        current_path = current_paths.get(location_id)
        return {
            "label": "Current path; historical path unavailable",
            "text": current_path,
            "components": [],
            "source": "current",
        }

    def _current_location_paths(self, location_ids: set[int]) -> dict[int, str]:
        if not location_ids:
            return {}
        records: dict[int, tuple[str, int | None]] = {}
        frontier = set(location_ids)
        while frontier:
            rows = self.session.execute(
                select(Location.id, Location.name, Location.parent_id)
                .where(Location.id.in_(frontier))
            ).all()
            frontier = set()
            for location_id, name, parent_id in rows:
                records[location_id] = (name, parent_id)
                if parent_id is not None and parent_id not in records:
                    frontier.add(parent_id)
        paths: dict[int, str] = {}
        for location_id in location_ids:
            names: list[str] = []
            seen: set[int] = set()
            current: int | None = location_id
            while current is not None and current in records:
                if current in seen:
                    raise RuntimeError("cycle detected in location hierarchy")
                seen.add(current)
                name, current = records[current]
                names.append(name)
            if current is None:
                paths[location_id] = " / ".join(reversed(names))
        return paths
