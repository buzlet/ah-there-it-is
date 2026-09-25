"""Transactional domain services for inventory mutations and reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import Alias, Category, Event, Item, ItemTag, Location, Tag, utc_now
from ah_there_it_is.domain.exceptions import DuplicateEntityError, EntityNotFoundError
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.quantity import QuantityValue, ReasonSource, validated_reason
from ah_there_it_is.domain.states import ItemState, LocationStatus, QuantityMode


_Row = TypeVar("_Row")


@dataclass(frozen=True)
class ReadPage(Generic[_Row]):
    items: list[_Row]
    total: int
    page: int
    page_size: int
    pages: int
    has_previous: bool
    has_next: bool
    previous_page: int | None
    next_page: int | None

    @classmethod
    def create(cls, items: list[_Row], total: int, page: int, page_size: int) -> "ReadPage[_Row]":
        has_previous = page > 1
        has_next = page * page_size < total
        return cls(
            items=items, total=total, page=page, page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
            has_previous=has_previous, has_next=has_next,
            previous_page=page - 1 if has_previous else None,
            next_page=page + 1 if has_next else None,
        )


class _Unset:
    pass


_UNSET = _Unset()


class InventoryService:
    """Own inventory validation for one DB session.

    Standalone callers keep the historical autocommit behavior. AgentRunner
    constructs the service with autocommit=False so all mutations in one user
    turn are flushed for tool visibility but committed only with the completed
    turn. The runner owns rollback on failure in that mode.
    """

    def __init__(self, session: Session, *, autocommit: bool = True) -> None:
        self.session = session
        self.autocommit = autocommit

    def create_category(
        self,
        name: str,
        *,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> Category:
        normalized = self._normalized_nonblank(name)
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
        normalized = self._normalized_nonblank(name)
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

    def update_category(
        self,
        category_id: int,
        *,
        name: str | None = None,
        description: str | None | _Unset = _UNSET,
        parent_id: int | None | _Unset = _UNSET,
    ) -> Category:
        return self._update_tree_node(
            self.get_category(category_id), Category, "category",
            name=name, description=description, parent_id=parent_id,
        )

    def update_location(
        self,
        location_id: int,
        *,
        name: str | None = None,
        description: str | None | _Unset = _UNSET,
        parent_id: int | None | _Unset = _UNSET,
    ) -> Location:
        return self._update_tree_node(
            self.get_location(location_id), Location, "location",
            name=name, description=description, parent_id=parent_id,
        )

    def _update_tree_node(
        self,
        node: Category | Location,
        model: type[Category] | type[Location],
        label: str,
        *,
        name: str | None,
        description: str | None | _Unset,
        parent_id: int | None | _Unset,
    ) -> Category | Location:
        # Resolve every reference and conflict before changing the persistent node.
        target_name = name.strip() if name is not None else node.name
        normalized = self._normalized_nonblank(target_name)
        target_description = node.description if isinstance(description, _Unset) else description
        target_parent_id = node.parent_id if isinstance(parent_id, _Unset) else parent_id
        parent = self._get_optional(model, target_parent_id, label)
        seen: set[int] = set()
        ancestor = parent
        while ancestor is not None:
            if ancestor.id == node.id or ancestor.id in seen:
                raise ValueError(f"{label} parent would create a cycle")
            seen.add(ancestor.id)
            ancestor = self._get_optional(model, ancestor.parent_id, label)
        if normalized != node.normalized_name or target_parent_id != node.parent_id:
            self._ensure_tree_name_available(
                model, normalized, target_parent_id, label, exclude_node_id=node.id
            )
        if (
            target_name == node.name
            and target_description == node.description
            and target_parent_id == node.parent_id
        ):
            return node
        node.name = target_name
        node.normalized_name = normalized
        node.description = target_description
        if target_parent_id != node.parent_id:
            node.parent = parent
        node.updated_at = utc_now()
        self._commit(node)
        return node

    def create_item(
        self,
        name: str,
        *,
        description: str | None = None,
        state: ItemState | str = ItemState.UNKNOWN,
        category_id: int | None = None,
        location_id: int | None = None,
        quantity_mode: QuantityMode | str = QuantityMode.EXACT,
        quantity: int | None = 1,
        attributes: Mapping[str, Any] | None = None,
        aliases: Sequence[str] = (),
        tags: Sequence[str] = (),
        original_text: str | None = None,
        allow_duplicate: bool = False,
    ) -> Item:
        quantity_value = QuantityValue.coerce(quantity_mode, quantity)

        normalized = self._normalized_nonblank(name)
        category = self._get_optional(Category, category_id, "category")
        location = self._get_optional(Location, location_id, "location")
        if not allow_duplicate:
            self._ensure_item_name_available(normalized, category_id)

        item_state = self._coerce_state(state)
        terminal_states = {ItemState.DISCARDED.value, ItemState.SOLD.value}
        if item_state in terminal_states and location is not None:
            raise ValueError("terminal items cannot have a current location")
        if item_state in terminal_states:
            location_status = LocationStatus.NOT_APPLICABLE
        elif location is not None:
            location_status = LocationStatus.KNOWN
        else:
            location_status = LocationStatus.UNKNOWN
        item = Item(
            name=name.strip(),
            normalized_name=normalized,
            description=description,
            state=item_state,
            category=category,
            current_location=location,
            location_status=location_status.value,
            quantity_mode=quantity_value.mode.value,
            quantity=quantity_value.value,
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
                payload={
                    "name": item.name,
                    "quantity": quantity_value.as_dict(),
                    "_history_evidence": self._history_evidence(
                        to_location_path=self._history_path(location, "location_id"),
                        to_category_path=self._history_path(category, "category_id"),
                    ),
                },
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
        attributes: Mapping[str, Any] | None = None,
        aliases: Sequence[str] | None = None,
        tags: Sequence[str] | None = None,
        original_text: str | None = None,
        allow_duplicate: bool = False,
    ) -> Item:
        item = self.get_item(item_id)

        # Validate the full requested patch before mutating the persistent object.
        target_name = name.strip() if name is not None else item.name
        target_normalized_name = self._normalized_nonblank(target_name)
        target_category_id = (
            item.category_id if isinstance(category_id, _Unset) else category_id
        )
        target_category = (
            item.category
            if isinstance(category_id, _Unset)
            else self._get_optional(Category, category_id, "category")
        )
        target_state = self._coerce_state(state) if state is not None else item.state
        terminal_states = {ItemState.DISCARDED.value, ItemState.SOLD.value}
        if item.state in terminal_states and target_state != item.state:
            raise ValueError("terminal state changes require explicit reactivation")
        if target_state == ItemState.SOLD.value and target_state != item.state:
            raise ValueError("sold transitions must use mark_item_sold")
        if target_state == ItemState.DISCARDED.value and target_state != item.state:
            raise ValueError("discard transitions must use discard_item")
        if not allow_duplicate and (
            target_normalized_name != item.normalized_name
            or target_category_id != item.category_id
        ):
            self._ensure_item_name_available(
                target_normalized_name, target_category_id, exclude_item_id=item.id
            )

        category_evidence = (
            self._history_evidence(
                from_category_path=self._history_path(item.category, "category_id"),
                to_category_path=self._history_path(target_category, "category_id"),
            )
            if target_category_id != item.category_id
            else None
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
            if target_state in terminal_states:
                if item.current_location_id is not None:
                    changes["current_location_id"] = {
                        "from": item.current_location_id,
                        "to": None,
                    }
                    item.current_location = None
                item.location_status = LocationStatus.NOT_APPLICABLE.value
        if target_category_id != item.category_id:
            changes["category_id"] = {
                "from": item.category_id,
                "to": target_category_id,
            }
            item.category = target_category
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
                    payload={
                        **changes,
                        **(
                            {"_history_evidence": category_evidence}
                            if category_evidence is not None
                            else {}
                        ),
                    },
                    original_text=original_text,
                )
            )
            self._commit(item)
        return item

    def change_item_quantity(
        self,
        item_id: int,
        *,
        quantity_mode: QuantityMode | str,
        quantity: int | None,
        reason: str,
        reason_source: ReasonSource | str,
        original_text: str | None = None,
    ) -> Item:
        after = QuantityValue.coerce(quantity_mode, quantity)
        compact_reason, source = validated_reason(reason, reason_source)
        item = self.get_item(item_id)
        before = QuantityValue.coerce(item.quantity_mode, item.quantity)
        if before == after:
            return item

        item.quantity_mode = after.mode.value
        item.quantity = after.value
        item.updated_at = utc_now()
        self.session.add(
            Event(
                event_type="item_quantity_changed",
                item=item,
                payload={
                    "quantity": {
                        "before": before.as_dict(),
                        "after": after.as_dict(),
                    },
                    "reason": compact_reason,
                    "reason_source": source.value,
                },
                original_text=original_text,
            )
        )
        self._commit(item)
        return item

    def move_item(
        self,
        item_id: int,
        location_id: int,
        *,
        original_text: str | None = None,
    ) -> Item:
        if location_id is None:
            raise ValueError("move_item requires a Location; use take_item to mark in-use")
        item = self.get_item(item_id)
        if item.state in {ItemState.DISCARDED.value, ItemState.SOLD.value}:
            raise ValueError("terminal items cannot be moved")
        destination = self._get_optional(Location, location_id, "location")
        if item.current_location_id == destination.id:
            return item

        old_location = item.current_location
        old_status = item.location_status
        item.current_location = destination
        item.location_status = LocationStatus.KNOWN.value
        self._record_location_transition(
            item,
            event_type="item_moved",
            from_location=old_location,
            to_location=destination,
            from_status=old_status,
            to_status=LocationStatus.KNOWN.value,
            original_text=original_text,
        )
        self._commit(item)
        return item

    def take_item(self, item_id: int, *, original_text: str | None = None) -> Item:
        item = self.get_item(item_id)
        self._ensure_nonterminal(item, "take")
        if item.location_status == LocationStatus.IN_USE.value:
            return item

        old_location = item.current_location
        old_status = item.location_status
        item.current_location = None
        item.location_status = LocationStatus.IN_USE.value
        self._record_location_transition(
            item,
            event_type="item_taken",
            from_location=old_location,
            to_location=None,
            from_status=old_status,
            to_status=LocationStatus.IN_USE.value,
            original_text=original_text,
        )
        self._commit(item)
        return item

    def mark_item_location_unknown(
        self, item_id: int, *, original_text: str | None = None
    ) -> Item:
        item = self.get_item(item_id)
        self._ensure_nonterminal(item, "change location")
        if item.location_status == LocationStatus.UNKNOWN.value:
            return item

        old_location = item.current_location
        old_status = item.location_status
        item.current_location = None
        item.location_status = LocationStatus.UNKNOWN.value
        self._record_location_transition(
            item,
            event_type="item_location_unknown",
            from_location=old_location,
            to_location=None,
            from_status=old_status,
            to_status=LocationStatus.UNKNOWN.value,
            original_text=original_text,
        )
        self._commit(item)
        return item

    def discard_item(self, item_id: int, *, original_text: str | None = None) -> Item:
        return self._mark_terminal(
            item_id, ItemState.DISCARDED, "item_discarded", original_text=original_text
        )

    def mark_item_sold(self, item_id: int, *, original_text: str | None = None) -> Item:
        return self._mark_terminal(
            item_id, ItemState.SOLD, "item_sold", original_text=original_text
        )

    def _mark_terminal(
        self,
        item_id: int,
        target_state: ItemState,
        event_type: str,
        *,
        original_text: str | None,
    ) -> Item:
        item = self.get_item(item_id)
        terminal_states = {ItemState.DISCARDED.value, ItemState.SOLD.value}
        if item.state in terminal_states:
            if item.state == target_state.value:
                return item
            raise ValueError("terminal items must be reactivated before another terminal transition")

        old_location = item.current_location
        old_state = item.state
        old_status = item.location_status
        item.state = target_state.value
        item.current_location = None
        item.location_status = LocationStatus.NOT_APPLICABLE.value
        self._record_location_transition(
            item,
            event_type=event_type,
            from_location=old_location,
            to_location=None,
            from_status=old_status,
            to_status=LocationStatus.NOT_APPLICABLE.value,
            state_change={"from": old_state, "to": target_state.value},
            original_text=original_text,
        )
        self._commit(item)
        return item

    def reactivate_item(
        self,
        item_id: int,
        *,
        state: ItemState | str,
        location_id: int | None,
        original_text: str | None = None,
    ) -> Item:
        item = self.get_item(item_id)
        if item.state not in {ItemState.DISCARDED.value, ItemState.SOLD.value}:
            raise ValueError("only sold or discarded items can be reactivated")
        target_state = self._coerce_state(state)
        if target_state in {ItemState.DISCARDED.value, ItemState.SOLD.value}:
            raise ValueError("reactivation requires a non-terminal target state")
        destination = self._get_optional(Location, location_id, "location")

        old_state = item.state
        old_status = item.location_status
        item.state = target_state
        item.current_location = destination
        item.location_status = (
            LocationStatus.KNOWN.value
            if destination is not None
            else LocationStatus.UNKNOWN.value
        )
        self._record_location_transition(
            item,
            event_type="item_reactivated",
            from_location=None,
            to_location=destination,
            from_status=old_status,
            to_status=item.location_status,
            state_change={"from": old_state, "to": target_state},
            original_text=original_text,
        )
        self._commit(item)
        return item

    def _ensure_nonterminal(self, item: Item, operation: str) -> None:
        if item.state in {ItemState.DISCARDED.value, ItemState.SOLD.value}:
            raise ValueError(f"terminal items cannot {operation}; reactivate first")

    def _record_location_transition(
        self,
        item: Item,
        *,
        event_type: str,
        from_location: Location | None,
        to_location: Location | None,
        from_status: str,
        to_status: str,
        original_text: str | None,
        state_change: dict[str, str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "_history_evidence": self._history_evidence(
                from_location_path=self._history_path(from_location, "location_id"),
                to_location_path=self._history_path(to_location, "location_id"),
            ),
        }
        if state_change is not None:
            payload["state"] = state_change
            payload["location_status"] = {"from": from_status, "to": to_status}
        self.session.add(
            Event(
                event_type=event_type,
                item=item,
                from_location=from_location,
                to_location=to_location,
                payload=payload,
                original_text=original_text,
            )
        )

    @staticmethod
    def _history_path(
        node: Category | Location | None, entity_id_key: str
    ) -> list[dict[str, Any]] | None:
        if node is None:
            return None
        components: list[dict[str, Any]] = []
        seen: set[int] = set()
        current = node
        while current is not None:
            if current.id in seen:
                raise ValueError("tree hierarchy contains a cycle")
            seen.add(current.id)
            components.append({entity_id_key: current.id, "name": current.name})
            current = current.parent
        components.reverse()
        return components

    @staticmethod
    def _history_evidence(
        **paths: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            **{name: path for name, path in paths.items() if path is not None},
        }

    def get_item(self, item_id: int) -> Item:
        return self._get_required(Item, item_id, "item")

    def get_location(self, location_id: int) -> Location:
        return self._get_required(Location, location_id, "location")

    def get_category(self, category_id: int) -> Category:
        return self._get_required(Category, category_id, "category")

    DEFAULT_READ_PAGE_SIZE = 50
    MAX_READ_PAGE_SIZE = 100

    @classmethod
    def _validate_read_page(cls, page: int, page_size: int) -> None:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1 or page_size > cls.MAX_READ_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {cls.MAX_READ_PAGE_SIZE}")

    def get_item_history_page(
        self, item_id: int, *, page: int = 1, page_size: int = DEFAULT_READ_PAGE_SIZE,
    ) -> ReadPage[Event]:
        self._validate_read_page(page, page_size)
        self.get_item(item_id)
        total = int(self.session.scalar(
            select(func.count(Event.id)).where(Event.item_id == item_id)
        ) or 0)
        events = list(self.session.scalars(
            select(Event).where(Event.item_id == item_id)
            .order_by(Event.created_at.asc(), Event.id.asc())
            .offset((page - 1) * page_size).limit(page_size)
        ))
        return ReadPage.create(events, total, page, page_size)

    def list_location_page(
        self, location_id: int, *, page: int = 1, page_size: int = DEFAULT_READ_PAGE_SIZE,
    ) -> ReadPage[Item]:
        self._validate_read_page(page, page_size)
        self.get_location(location_id)
        total = int(self.session.scalar(
            select(func.count(Item.id)).where(Item.current_location_id == location_id)
        ) or 0)
        items = list(self.session.scalars(
            select(Item).where(Item.current_location_id == location_id)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links).selectinload(ItemTag.tag),
                selectinload(Item.category),
                selectinload(Item.current_location),
            )
            .order_by(Item.id.asc())
            .offset((page - 1) * page_size).limit(page_size)
        ))
        return ReadPage.create(items, total, page, page_size)

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
        *,
        exclude_node_id: int | None = None,
    ) -> None:
        stmt = select(model.id).where(
            model.normalized_name == normalized_name,
            model.parent_id == parent_id,
        )
        if exclude_node_id is not None:
            stmt = stmt.where(model.id != exclude_node_id)
        if self.session.scalar(stmt) is not None:
            raise DuplicateEntityError(
                f"{label} with this name already exists under the same parent"
            )

    @staticmethod
    def _normalized_nonblank(name: str) -> str:
        normalized = normalize_name(name)
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

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
            if self.autocommit:
                self.session.commit()
            else:
                self.session.flush()
        except Exception:
            if self.autocommit:
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
