"""LLM tool registry and safe dispatcher over application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ah_there_it_is.agent.errors import ToolExecutionError, ToolPreconditionError
from ah_there_it_is.agent.protocol import ToolDefinition
from ah_there_it_is.agent.schemas import (
    CreateCategoryInput,
    CreateItemInput,
    CreateLocationInput,
    IdInput,
    ItemIdInput,
    LocationIdInput,
    MoveItemInput,
    SearchInput,
    UpdateItemInput,
)
from ah_there_it_is.db.models import Category, Event, Item, Location
from ah_there_it_is.domain.exceptions import InventoryError
from ah_there_it_is.domain.names import normalize_search_text
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService


@dataclass
class ToolRunState:
    """Capabilities learned from actual tool results during one agent run."""

    seen: dict[str, set[int]] = field(
        default_factory=lambda: {
            "item": set(),
            "location": set(),
            "category": set(),
            "tag": set(),
        }
    )
    resolved: dict[str, set[int]] = field(
        default_factory=lambda: {
            "item": set(),
            "location": set(),
            "category": set(),
            "tag": set(),
        }
    )
    searches: dict[str, set[str]] = field(
        default_factory=lambda: {
            "item": set(),
            "location": set(),
            "category": set(),
            "tag": set(),
        }
    )
    empty_searches: dict[str, set[str]] = field(
        default_factory=lambda: {
            "item": set(),
            "location": set(),
            "category": set(),
            "tag": set(),
        }
    )


@dataclass(frozen=True)
class _ToolSpec:
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel], Any]


class ToolDispatcher:
    """Validate and execute the only operations an LLM can perform."""

    def __init__(
        self,
        session: Session,
        *,
        original_text: str | None = None,
        state: ToolRunState | None = None,
    ) -> None:
        self.inventory = InventoryService(session)
        self.search = SearchService(session)
        self.original_text = original_text
        self.state = state or ToolRunState()
        self._round_seen: dict[str, set[int]] | None = None
        self._round_resolved: dict[str, set[int]] | None = None
        self._round_searches: dict[str, set[str]] | None = None
        self._specs = self._build_specs()


    def begin_round(self) -> None:
        """Freeze capabilities visible to the model before this tool-call batch."""
        self._round_seen = {key: set(values) for key, values in self.state.seen.items()}
        self._round_resolved = {
            key: set(values) for key, values in self.state.resolved.items()
        }
        self._round_searches = {
            key: set(values) for key, values in self.state.searches.items()
        }

    def end_round(self) -> None:
        self._round_seen = None
        self._round_resolved = None
        self._round_searches = None

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return only tools whose preconditions can be useful in current state."""
        available = self._available_tool_names()
        return tuple(
            ToolDefinition(
                name=name,
                description=spec.description,
                input_schema=self._compact_schema(spec.input_model.model_json_schema()),
            )
            for name, spec in self._specs.items()
            if name in available
        )

    def _available_tool_names(self) -> set[str]:
        names = {
            "search_items",
            "search_locations",
            "search_categories",
            "search_tags",
        }
        if self.state.seen["item"]:
            names.update({"get_item", "get_item_history"})
        if self.state.seen["location"]:
            names.update({"get_location", "list_location"})
        if self.state.seen["category"]:
            names.add("get_category")

        if self.state.empty_searches["item"]:
            names.add("create_item")
        if self.state.empty_searches["location"]:
            names.add("create_location")
        if self.state.empty_searches["category"]:
            names.add("create_category")

        if self.state.resolved["item"]:
            names.add("update_item")
            # A move to a named location is useful only after the location is
            # resolved. With no location search yet, keep move_item available
            # so location_id=null can still represent "take/remove from storage".
            if not self.state.searches["location"] or self.state.resolved["location"]:
                names.add("move_item")
        return names

    @classmethod
    def _compact_schema(cls, value: Any) -> Any:
        """Remove model-irrelevant Pydantic decoration without changing validation."""
        if isinstance(value, dict):
            return {
                key: cls._compact_schema(item)
                for key, item in value.items()
                if key not in {"title", "default", "examples"}
            }
        if isinstance(value, list):
            return [cls._compact_schema(item) for item in value]
        return value

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            return self._error("unknown_tool", f"unknown tool: {name}")
        try:
            parsed = spec.input_model.model_validate(arguments)
            result = spec.handler(parsed)
            return {"ok": True, "result": result}
        except ValidationError as exc:
            return self._error("invalid_arguments", exc.errors(include_url=False))
        except ToolExecutionError as exc:
            return self._error(type(exc).__name__, str(exc))
        except (InventoryError, ValueError, RuntimeError) as exc:
            return self._error(type(exc).__name__, str(exc))

    @staticmethod
    def as_tool_message_content(result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)

    def _build_specs(self) -> dict[str, _ToolSpec]:
        return {
            "search_items": _ToolSpec(
                "Search existing items before referring to or creating an item.",
                SearchInput,
                self._search_items,
            ),
            "search_locations": _ToolSpec(
                "Search existing locations and inspect full paths before using or creating one.",
                SearchInput,
                self._search_locations,
            ),
            "search_categories": _ToolSpec(
                "Search existing categories before assigning or creating a category.",
                SearchInput,
                self._search_categories,
            ),
            "search_tags": _ToolSpec(
                "Search existing tags.", SearchInput, self._search_tags
            ),
            "get_item": _ToolSpec(
                "Read an item already returned by a search/read tool. Never guess an ID.",
                IdInput,
                self._get_item,
            ),
            "get_location": _ToolSpec(
                "Read a location already returned by a search/read tool. Never guess an ID.",
                IdInput,
                self._get_location,
            ),
            "get_category": _ToolSpec(
                "Read a category already returned by a search/read tool. Never guess an ID.",
                IdInput,
                self._get_category,
            ),
            "list_location": _ToolSpec(
                "List items directly in a location that has already been resolved.",
                LocationIdInput,
                self._list_location,
            ),
            "get_item_history": _ToolSpec(
                "Read history for an item that has already been resolved.",
                ItemIdInput,
                self._get_item_history,
            ),
            "create_category": _ToolSpec(
                "Create a category only after search_categories was called for this name.",
                CreateCategoryInput,
                self._create_category,
            ),
            "create_location": _ToolSpec(
                "Create a location only after search_locations was called for this name.",
                CreateLocationInput,
                self._create_location,
            ),
            "create_item": _ToolSpec(
                "Create an item only after search_items was called for this name; existing category/location IDs must be resolved first.",
                CreateItemInput,
                self._create_item,
            ),
            "update_item": _ToolSpec(
                "Update an already-resolved item by stable ID; any assigned category must also be resolved.",
                UpdateItemInput,
                self._update_item,
            ),
            "move_item": _ToolSpec(
                "Move/take an already-resolved item using a resolved location ID or null.",
                MoveItemInput,
                self._move_item,
            ),
        }

    def _search_items(self, raw: BaseModel) -> list[dict[str, Any]]:
        args = self._cast(SearchInput, raw)
        self._remember_search("item", args.query)
        results = self.search.search_items(args.query, limit=args.limit)
        self._remember_search_candidates("item", args.query, results)
        return [candidate.model_dump(mode="json") for candidate in results]

    def _search_locations(self, raw: BaseModel) -> list[dict[str, Any]]:
        args = self._cast(SearchInput, raw)
        self._remember_search("location", args.query)
        results = self.search.search_locations(args.query, limit=args.limit)
        self._remember_search_candidates("location", args.query, results)
        return [candidate.model_dump(mode="json") for candidate in results]

    def _search_categories(self, raw: BaseModel) -> list[dict[str, Any]]:
        args = self._cast(SearchInput, raw)
        self._remember_search("category", args.query)
        results = self.search.search_categories(args.query, limit=args.limit)
        self._remember_search_candidates("category", args.query, results)
        return [candidate.model_dump(mode="json") for candidate in results]

    def _search_tags(self, raw: BaseModel) -> list[dict[str, Any]]:
        args = self._cast(SearchInput, raw)
        self._remember_search("tag", args.query)
        results = self.search.search_tags(args.query, limit=args.limit)
        self._remember_search_candidates("tag", args.query, results)
        return [candidate.model_dump(mode="json") for candidate in results]

    def _get_item(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(IdInput, raw)
        self._require_seen("item", args.id)
        return self._item_dict(self.inventory.get_item(args.id))

    def _get_location(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(IdInput, raw)
        self._require_seen("location", args.id)
        return self._location_dict(self.inventory.get_location(args.id))

    def _get_category(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(IdInput, raw)
        self._require_seen("category", args.id)
        return self._category_dict(self.inventory.get_category(args.id))

    def _list_location(self, raw: BaseModel) -> list[dict[str, Any]]:
        args = self._cast(LocationIdInput, raw)
        self._require_seen("location", args.location_id)
        items = self.inventory.list_location(args.location_id)
        self._remember_seen("item", [item.id for item in items])
        return [self._item_dict(item) for item in items]

    def _get_item_history(self, raw: BaseModel) -> list[dict[str, Any]]:
        args = self._cast(ItemIdInput, raw)
        self._require_seen("item", args.item_id)
        return [self._event_dict(event) for event in self.inventory.get_item_history(args.item_id)]

    def _create_category(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(CreateCategoryInput, raw)
        self._require_prior_search("category", args.name)
        if args.parent_id is not None:
            self._require_resolved("category", args.parent_id)
        category = self.inventory.create_category(**args.model_dump())
        self._remember_created("category", category.id)
        return self._category_dict(category)

    def _create_location(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(CreateLocationInput, raw)
        self._require_prior_search("location", args.name)
        if args.parent_id is not None:
            self._require_resolved("location", args.parent_id)
        location = self.inventory.create_location(**args.model_dump())
        self._remember_created("location", location.id)
        return self._location_dict(location)

    def _create_item(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(CreateItemInput, raw)
        self._require_prior_search("item", args.name)
        if args.category_id is not None:
            self._require_resolved("category", args.category_id)
        if args.location_id is not None:
            self._require_resolved("location", args.location_id)
        kwargs = args.model_dump(mode="python")
        kwargs["original_text"] = self.original_text
        item = self.inventory.create_item(**kwargs)
        self._remember_created("item", item.id)
        return self._item_dict(item)

    def _update_item(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(UpdateItemInput, raw)
        self._require_resolved("item", args.item_id)
        payload = args.model_dump(mode="python", exclude_unset=True)
        item_id = payload.pop("item_id")
        if "category_id" in payload and payload["category_id"] is not None:
            self._require_resolved("category", payload["category_id"])
        payload["original_text"] = self.original_text
        item = self.inventory.update_item(item_id, **payload)
        return self._item_dict(item)

    def _move_item(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(MoveItemInput, raw)
        self._require_resolved("item", args.item_id)
        if args.location_id is not None:
            self._require_resolved("location", args.location_id)
        item = self.inventory.move_item(
            args.item_id, args.location_id, original_text=self.original_text
        )
        return self._item_dict(item)

    def _require_seen(self, entity_type: str, entity_id: int) -> None:
        visible = self._round_seen or self.state.seen
        if entity_id not in visible[entity_type]:
            raise ToolPreconditionError(
                f"{entity_type} id={entity_id} was not returned by a prior search/read tool in this run"
            )

    def _require_resolved(self, entity_type: str, entity_id: int) -> None:
        visible = self._round_resolved or self.state.resolved
        if entity_id not in visible[entity_type]:
            raise ToolPreconditionError(
                f"{entity_type} id={entity_id} is not unambiguously resolved in this run; refine the search or ask the user"
            )

    def _require_prior_search(self, entity_type: str, name: str) -> None:
        key = normalize_search_text(name)
        visible = self._round_searches or self.state.searches
        if key not in visible[entity_type]:
            raise ToolPreconditionError(
                f"search_{entity_type}s must be called for {name!r} before creation"
            )

    def _remember_search(self, entity_type: str, query: str) -> None:
        key = normalize_search_text(query)
        if key:
            self.state.searches[entity_type].add(key)

    def _remember_seen(self, entity_type: str, ids: list[int]) -> None:
        self.state.seen[entity_type].update(ids)

    def _remember_created(self, entity_type: str, entity_id: int) -> None:
        self.state.seen[entity_type].add(entity_id)
        self.state.resolved[entity_type].add(entity_id)

    def _remember_search_candidates(
        self,
        entity_type: str,
        query: str,
        candidates: list[Any],
    ) -> None:
        ids = [candidate.id for candidate in candidates]
        self._remember_seen(entity_type, ids)
        if not candidates:
            key = normalize_search_text(query)
            if key:
                self.state.empty_searches[entity_type].add(key)
            return
        if len(candidates) == 1:
            self.state.resolved[entity_type].add(candidates[0].id)
            return
        # Search scores are deterministic Stage 2 evidence. A clear score gap may
        # resolve the top candidate; tied/close candidates remain read-only until
        # the model refines the search or asks the user.
        if candidates[0].score - candidates[1].score >= 50:
            self.state.resolved[entity_type].add(candidates[0].id)

    @staticmethod
    def _cast(expected: type[BaseModel], raw: BaseModel):
        if not isinstance(raw, expected):
            raise TypeError(f"expected {expected.__name__}")
        return raw

    @staticmethod
    def _path(node: Location | Category | None) -> str | None:
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

    def _item_dict(self, item: Item) -> dict[str, Any]:
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
            "category_path": self._path(item.category),
            "location_id": item.current_location_id,
            "location_path": self._path(item.current_location),
        }

    def _location_dict(self, location: Location) -> dict[str, Any]:
        return {
            "id": location.id,
            "name": location.name,
            "path": self._path(location),
            "parent_id": location.parent_id,
            "description": location.description,
        }

    def _category_dict(self, category: Category) -> dict[str, Any]:
        return {
            "id": category.id,
            "name": category.name,
            "path": self._path(category),
            "parent_id": category.parent_id,
            "description": category.description,
        }

    @staticmethod
    def _event_dict(event: Event) -> dict[str, Any]:
        return {
            "id": event.id,
            "event_type": event.event_type,
            "item_id": event.item_id,
            "from_location_id": event.from_location_id,
            "to_location_id": event.to_location_id,
            "payload": event.payload,
            "original_text": event.original_text,
            "created_at": event.created_at.isoformat(),
        }

    @staticmethod
    def _error(error_type: str, detail: Any) -> dict[str, Any]:
        return {"ok": False, "error": {"type": error_type, "detail": detail}}
