"""Read-oriented inventory projections for the web UI."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import Category, Item, Location
from ah_there_it_is.services.inventory import InventoryService


class CatalogService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.inventory = InventoryService(session)

    def list_items(self) -> list[dict[str, Any]]:
        stmt = (
            select(Item)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links),
                selectinload(Item.category),
                selectinload(Item.current_location),
            )
            .order_by(Item.normalized_name, Item.id)
        )
        return [self.item_dict(item) for item in self.session.scalars(stmt)]

    def list_locations(self) -> list[dict[str, Any]]:
        locations = list(self.session.scalars(select(Location).order_by(Location.id)))
        rows = [
            {
                "id": location.id,
                "name": location.name,
                "path": self.path(location),
                "description": location.description,
                "parent_id": location.parent_id,
                "item_count": len(location.items),
            }
            for location in locations
        ]
        return sorted(rows, key=lambda row: (row["path"].casefold(), row["id"]))

    def list_categories(self) -> list[dict[str, Any]]:
        categories = list(self.session.scalars(select(Category).order_by(Category.id)))
        rows = [
            {
                "id": category.id,
                "name": category.name,
                "path": self.path(category),
                "description": category.description,
                "parent_id": category.parent_id,
                "item_count": len(category.items),
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
