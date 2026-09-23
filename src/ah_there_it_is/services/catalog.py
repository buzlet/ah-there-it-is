"""Read-oriented inventory projections for the web UI."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import Category, Item, ItemTag, Location
from ah_there_it_is.services.inventory import InventoryService


@dataclass(frozen=True)
class ItemPage:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int
    has_previous: bool
    has_next: bool
    previous_page: int | None
    next_page: int | None


class CatalogService:
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100

    def __init__(self, session: Session) -> None:
        self.session = session
        self.inventory = InventoryService(session)

    def item_page(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ItemPage:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1 or page_size > self.MAX_PAGE_SIZE:
            raise ValueError(
                f"page_size must be between 1 and {self.MAX_PAGE_SIZE}"
            )

        total = int(self.session.scalar(select(func.count(Item.id))) or 0)
        pages = ceil(total / page_size) if total else 0
        stmt = (
            select(Item)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links).selectinload(ItemTag.tag),
                selectinload(Item.category),
                selectinload(Item.current_location),
            )
            .order_by(Item.normalized_name, Item.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [self.item_dict(item) for item in self.session.scalars(stmt)]
        has_previous = page > 1
        has_next = page * page_size < total
        return ItemPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            has_previous=has_previous,
            has_next=has_next,
            previous_page=page - 1 if has_previous else None,
            next_page=page + 1 if has_next else None,
        )

    def list_items(self) -> list[dict[str, Any]]:
        stmt = (
            select(Item)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links).selectinload(ItemTag.tag),
                selectinload(Item.category),
                selectinload(Item.current_location),
            )
            .order_by(Item.normalized_name, Item.id)
        )
        return [self.item_dict(item) for item in self.session.scalars(stmt)]

    def list_locations(self) -> list[dict[str, Any]]:
        locations = list(self.session.scalars(select(Location).order_by(Location.id)))
        counts = dict(
            self.session.execute(
                select(Item.current_location_id, func.count(Item.id))
                .where(Item.current_location_id.is_not(None))
                .group_by(Item.current_location_id)
            ).all()
        )
        by_id = {location.id: location for location in locations}
        rows = [
            {
                "id": location.id,
                "name": location.name,
                "path": self._path_from_loaded(location, by_id),
                "description": location.description,
                "parent_id": location.parent_id,
                "item_count": int(counts.get(location.id, 0)),
            }
            for location in locations
        ]
        return sorted(rows, key=lambda row: (row["path"].casefold(), row["id"]))

    def list_categories(self) -> list[dict[str, Any]]:
        categories = list(self.session.scalars(select(Category).order_by(Category.id)))
        counts = dict(
            self.session.execute(
                select(Item.category_id, func.count(Item.id))
                .where(Item.category_id.is_not(None))
                .group_by(Item.category_id)
            ).all()
        )
        by_id = {category.id: category for category in categories}
        rows = [
            {
                "id": category.id,
                "name": category.name,
                "path": self._path_from_loaded(category, by_id),
                "description": category.description,
                "parent_id": category.parent_id,
                "item_count": int(counts.get(category.id, 0)),
            }
            for category in categories
        ]
        return sorted(rows, key=lambda row: (row["path"].casefold(), row["id"]))

    def item_detail(self, item_id: int) -> dict[str, Any]:
        item = self.inventory.get_item(item_id)
        result = self.item_dict(item)
        result["history"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "from_location": self.path(event.from_location),
                "to_location": self.path(event.to_location),
                "payload": event.payload,
                "original_text": event.original_text,
                "created_at": event.created_at,
            }
            for event in self.inventory.get_item_history(item_id)
        ]
        return result

    def item_dict(self, item: Item) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "state": item.state,
            "quantity": item.quantity,
            "attributes": item.attributes,
            "aliases": [alias.name for alias in item.aliases],
            "tags": [link.tag.name for link in item.tag_links],
            "category_id": item.category_id,
            "category_path": self.path(item.category),
            "location_id": item.current_location_id,
            "location_path": self.path(item.current_location),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    @staticmethod
    def _path_from_loaded(
        node: Location | Category,
        by_id: dict[int, Location] | dict[int, Category],
    ) -> str:
        names: list[str] = []
        seen: set[int] = set()
        current: Location | Category | None = node
        while current is not None:
            if current.id in seen:
                raise RuntimeError("cycle detected in hierarchy")
            seen.add(current.id)
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id is not None else None
        return " / ".join(reversed(names))

    @staticmethod
    def path(node: Location | Category | None) -> str | None:
        if node is None:
            return None
        names: list[str] = []
        seen: set[int] = set()
        current: Location | Category | None = node
        while current is not None:
            if current.id in seen:
                raise RuntimeError("cycle detected in hierarchy")
            seen.add(current.id)
            names.append(current.name)
            current = current.parent
        return " / ".join(reversed(names))
