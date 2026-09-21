"""Transactional domain services for inventory mutations and reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Alias, Category, Event, Item, Location, Tag, utc_now
from ah_there_it_is.domain.exceptions import DuplicateEntityError, EntityNotFoundError
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.states import ItemState


class _Unset:
    pass


_UNSET = _Unset()


class InventoryService:
    """Own inventory validation and transaction boundaries for one DB session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_category(
        self,
        name: str,
        *,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> Category:
        normalized = normalize_name(name)
        parent = self._get_optional_parent(Category, parent_id, "category")
        self._ensure_tree_name_available(Category, normalized, parent_id, "category")

        category = Category(
            name=name.strip(),
            normalized_name=normalized,
            parent=parent,
            description=description,
        )
        self.session.add(category)
        self._commit(category)
        return category

    def create_location(
        self,
        name: str,
        *,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> Location:
        normalized = normalize_name(name)
        parent = self._get_optional_parent(Location, parent_id, "location")
        self._ensure_tree_name_available(Location, normalized, parent_id, "location")

        location = Location(
            name=name.strip(),
            normalized_name=normalized,
            parent=parent,
            description=description,
        )
        self.session.add(location)
        self._commit(location)
        return location

    def create_item(
        self,
        name: str,
        *,
        description: str | None = None,
        state: ItemState | str = ItemState.UNKNOWN,
        category_id: int | None = None,
        location_id: int | None = None,
        quantity: int = 1,
        attributes: Mapping[str, Any] | None = None,
        aliases: Sequence[str] = (),
        tags: Sequence[str] = (),
        original_text: str | None = None,
        allow_duplicate: bool = False,
    ) -> Item:
        if quantity < 1:
            raise ValueError("quantity must be >= 1")

        normalized = normalize_name(name)
        category = self._get_optional(Category, category_id, "category")
        location = self._get_optional(Location, location_id, "location")
        if not allow_duplicate:
            self._ensure_item_name_available(normalized, category_id)

        item = Item(
            name=name.strip(),
            normalized_name=normalized,
            description=description,
            state=self._coerce_state(state),
            category=category,
            current_location=location,
            quantity=quantity,
            attributes=dict(attributes or {}),
        )
        self.session.add(item)
        self.session.flush()

        self._replace_aliases(item, aliases)
        self._replace_tags(item, tags)
        self.session.add(
            Event(
                event_type="item_created",
                item=item,
                to_location=location,
                payload={"name": item.name, "quantity": quantity},
                original_text=original_text,
            )
        )
        self._commit(item)
        return item

    def update_item(
        self,
        item_id: int,
        *,
        name: str | None = None,
        description: str | None | _Unset = _UNSET,
        state: ItemState | str | None = None,
        category_id: int | None | _Unset = _UNSET,
        quantity: int | None = None,
        attributes: Mapping[str, Any] | None = None,
        aliases: Sequence[str] | None = None,
        tags: Sequence[str] | None = None,
        original_text: str | None = None,
        allow_duplicate: bool = False,
    ) -> Item:
        item = self.get_item(item_id)

        # Validate the full requested patch before mutating the persistent object.
        target_name = name.strip() if name is not None else item.name
        target_normalized_name = normalize_name(target_name)
        target_category_id = (
            item.category_id if isinstance(category_id, _Unset) else category_id
        )
        target_category = (
            item.category
            if isinstance(category_id, _Unset)
            else self._get_optional(Category, category_id, "category")
        )
        target_state = self._coerce_state(state) if state is not None else item.state
        if quantity is not None and quantity < 1:
            raise ValueError("quantity must be >= 1")
        if not allow_duplicate and (
            target_normalized_name != item.normalized_name
            or target_category_id != item.category_id
        ):
            self._ensure_item_name_available(
                target_normalized_name, target_category_id, exclude_item_id=item.id
            )

        changes: dict[str, Any] = {}
        if target_name != item.name:
            changes["name"] = {"from": item.name, "to": target_name}
            item.name = target_name
            item.normalized_name = target_normalized_name
        if not isinstance(description, _Unset) and description != item.description:
            changes["description"] = {"from": item.description, "to": description}
            item.description = description
        if target_state != item.state:
            changes["state"] = {"from": item.state, "to": target_state}
            item.state = target_state
        if target_category_id != item.category_id:
            changes["category_id"] = {
                "from": item.category_id,
                "to": target_category_id,
            }
            item.category = target_category
        if quantity is not None and quantity != item.quantity:
            changes["quantity"] = {"from": item.quantity, "to": quantity}
            item.quantity = quantity
        if attributes is not None and dict(attributes) != item.attributes:
            changes["attributes"] = {"from": item.attributes, "to": dict(attributes)}
            item.attributes = dict(attributes)
        if aliases is not None:
            current_aliases = {alias.normalized_name for alias in item.aliases}
            new_aliases = {normalize_name(value) for value in aliases if normalize_name(value)}
            if current_aliases != new_aliases:
                changes["aliases"] = list(aliases)
                self._replace_aliases(item, aliases)
        if tags is not None:
            current_tags = {link.tag.normalized_name for link in item.tag_links}
            new_tags = {normalize_name(value) for value in tags if normalize_name(value)}
            if current_tags != new_tags:
                changes["tags"] = list(tags)
                self._replace_tags(item, tags)

        if changes:
            item.updated_at = utc_now()
            self.session.add(
                Event(
                    event_type="item_updated",
                    item=item,
                    payload=changes,
                    original_text=original_text,
                )
            )
            self._commit(item)
        return item

    def move_item(
        self,
        item_id: int,
        location_id: int | None,
        *,
        original_text: str | None = None,
    ) -> Item:
        item = self.get_item(item_id)
        destination = self._get_optional(Location, location_id, "location")
        if item.current_location_id == location_id:
            return item

        old_location = item.current_location
        item.current_location = destination
        self.session.add(
            Event(
                event_type="item_moved" if destination is not None else "item_taken",
                item=item,
                from_location=old_location,
                to_location=destination,
                payload={},
                original_text=original_text,
            )
        )
        self._commit(item)
        return item

    def get_item(self, item_id: int) -> Item:
        return self._get_required(Item, item_id, "item")

    def get_location(self, location_id: int) -> Location:
        return self._get_required(Location, location_id, "location")

    def get_category(self, category_id: int) -> Category:
        return self._get_required(Category, category_id, "category")

    def get_item_history(self, item_id: int) -> list[Event]:
        self.get_item(item_id)
        stmt = (
            select(Event)
            .where(Event.item_id == item_id)
            .order_by(Event.created_at.asc(), Event.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_location(self, location_id: int) -> list[Item]:
        self._get_required(Location, location_id, "location")
        stmt = select(Item).where(Item.current_location_id == location_id).order_by(Item.id)
        return list(self.session.scalars(stmt))

    def _replace_aliases(self, item: Item, aliases: Sequence[str]) -> None:
        item.aliases.clear()
        seen: set[str] = set()
        for value in aliases:
            normalized = normalize_name(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            item.aliases.append(Alias(name=value.strip(), normalized_name=normalized))

    def _replace_tags(self, item: Item, tags: Sequence[str]) -> None:
        item.tag_links.clear()
        seen: set[str] = set()
        for value in tags:
            normalized = normalize_name(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            tag = self.session.scalar(select(Tag).where(Tag.normalized_name == normalized))
            if tag is None:
                tag = Tag(name=value.strip(), normalized_name=normalized)
                self.session.add(tag)
                self.session.flush()
            item.tag_links.append(tag_link := self._new_item_tag(tag))

    @staticmethod
    def _new_item_tag(tag: Tag):
        from ah_there_it_is.db.models import ItemTag

        return ItemTag(tag=tag)


    def _ensure_item_name_available(
        self,
        normalized_name: str,
        category_id: int | None,
        *,
        exclude_item_id: int | None = None,
    ) -> None:
        stmt = select(Item.id).where(
            Item.normalized_name == normalized_name,
            Item.category_id == category_id,
        )
        if exclude_item_id is not None:
            stmt = stmt.where(Item.id != exclude_item_id)
        if self.session.scalar(stmt) is not None:
            raise DuplicateEntityError(
                "item with this normalized name already exists in this category; "
                "use the existing item or explicitly allow a duplicate"
            )

    def _ensure_tree_name_available(
        self,
        model: type[Category] | type[Location],
        normalized_name: str,
        parent_id: int | None,
        label: str,
    ) -> None:
        stmt: Select[tuple[Category]] | Select[tuple[Location]] = select(model).where(
            model.normalized_name == normalized_name,
            model.parent_id == parent_id,
        )
        if self.session.scalar(stmt) is not None:
            raise DuplicateEntityError(
                f"{label} with this name already exists under the same parent"
            )

    def _get_optional_parent(self, model, entity_id: int | None, label: str):
        return self._get_optional(model, entity_id, label)

    def _get_optional(self, model, entity_id: int | None, label: str):
        if entity_id is None:
            return None
        return self._get_required(model, entity_id, label)

    def _get_required(self, model, entity_id: int, label: str):
        entity = self.session.get(model, entity_id)
        if entity is None:
            raise EntityNotFoundError(f"{label} id={entity_id} does not exist")
        return entity

    def _commit(self, entity: Any) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(entity)

    @staticmethod
    def _coerce_state(value: ItemState | str) -> str:
        try:
            return ItemState(value).value
        except ValueError as exc:
            allowed = ", ".join(state.value for state in ItemState)
            raise ValueError(f"invalid item state {value!r}; allowed: {allowed}") from exc
