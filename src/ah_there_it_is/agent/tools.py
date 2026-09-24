"""LLM tool registry and safe dispatcher over application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
import json
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent.errors import ToolExecutionError, ToolPreconditionError
from ah_there_it_is.agent.protocol import ToolDefinition
from ah_there_it_is.agent.receipts import MutationReceipt
from ah_there_it_is.agent.write_resolution import WriteResolver
from ah_there_it_is.agent.schemas import (
    CreateCategoryInput,
    CreateItemInput,
    CreateLocationInput,
    IdInput,
    ItemIdInput,
    LocationIdInput,
    MoveItemInput,
    SearchInput,
    SuggestItemLocationsInput,
    UpdateItemInput,
)
from ah_there_it_is.db.models import Category, Event, Item, Location
from ah_there_it_is.domain.exceptions import InventoryError
from ah_there_it_is.domain.names import normalize_search_text
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.location_suggestions import LocationSuggestionService
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
    evidence: dict[str, dict[int, set[str]]] = field(
        default_factory=lambda: {key: {} for key in ("item", "location", "category")}
    )
    created: dict[str, set[int]] = field(
        default_factory=lambda: {key: set() for key in ("item", "location", "category")}
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

    ITEM_MUTATION_TOOLS = frozenset({
        "create_item", "update_item", "move_item", "take_item",
        "mark_item_location_unknown", "discard_item", "mark_item_sold", "reactivate_item",
    })
    LOCATION_MUTATION_TOOLS = frozenset({
        "move_item", "take_item", "mark_item_location_unknown", "discard_item",
        "mark_item_sold", "reactivate_item",
    })
    MUTATION_TOOLS = ITEM_MUTATION_TOOLS | frozenset({"create_location", "create_category"})

    def __init__(
        self,
        session: Session,
        *,
        original_text: str | None = None,
        state: ToolRunState | None = None,
        autocommit: bool = True,
    ) -> None:
        self.inventory = InventoryService(session, autocommit=autocommit)
        self.location_suggestions = LocationSuggestionService(session)
        self.search = SearchService(session)
        self.write_resolver = WriteResolver(session)
        self.original_text = original_text
        self.state = state or ToolRunState()
        self._round_seen: dict[str, set[int]] | None = None
        self._round_resolved: dict[str, set[int]] | None = None
        self._round_searches: dict[str, set[str]] | None = None
        self._round_evidence: dict[str, dict[int, set[str]]] | None = None
        self._round_created: dict[str, set[int]] | None = None
        self._specs = self._build_specs()
        self.receipts: list[MutationReceipt] = []


    def begin_round(self) -> None:
        """Freeze capabilities visible to the model before this tool-call batch."""
        self._round_seen = {key: set(values) for key, values in self.state.seen.items()}
        self._round_resolved = {
            key: set(values) for key, values in self.state.resolved.items()
        }
        self._round_searches = {
            key: set(values) for key, values in self.state.searches.items()
        }
        self._round_evidence = {
            key: {entity_id: set(queries) for entity_id, queries in values.items()}
            for key, values in self.state.evidence.items()
        }
        self._round_created = {
            key: set(values) for key, values in self.state.created.items()
        }

    def end_round(self) -> None:
        self._round_seen = None
        self._round_resolved = None
        self._round_searches = None
        self._round_evidence = None
        self._round_created = None

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
            names.update({"suggest_item_locations", "update_item"})
            # Preserve the v1 nullable argument adapter until the explicit
            # take_item tool is introduced; null only takes a located item.
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
            before = self._mutation_before(name, parsed) if name in self.MUTATION_TOOLS else None
            result = spec.handler(parsed)
            if name in self.MUTATION_TOOLS:
                receipt = self._mutation_receipt(name, parsed, result, before)
                self.receipts.append(receipt)
                return {
                    "ok": True, "result": result, "changed": receipt.changed,
                    "commit_state": "committed" if self.inventory.autocommit else "provisional",
                }
            return {"ok": True, "result": result}
        except ValidationError as exc:
            return self._error("invalid_arguments", exc.errors(include_url=False))
        except ToolExecutionError as exc:
            return self._error(type(exc).__name__, str(exc))
        except (InventoryError, ValueError, RuntimeError) as exc:
            return self._error(type(exc).__name__, str(exc))

    def _mutation_before(self, name: str, parsed: BaseModel) -> dict[str, Any]:
        if name not in self.ITEM_MUTATION_TOOLS or name == "create_item":
            return {}
        item_id = parsed.item_id  # type: ignore[attr-defined]
        item = self.inventory.session.get(Item, item_id)
        last_event_id = self.inventory.session.scalar(
            select(func.max(Event.id)).where(Event.item_id == item_id)
        ) or 0
        return {
            "last_event_id": last_event_id,
            "location_id": item.current_location_id if item else None,
            "category_id": item.category_id if item else None,
        }

    def _mutation_receipt(
        self, name: str, parsed: BaseModel, result: dict[str, Any],
        before: dict[str, Any] | None,
    ) -> MutationReceipt:
        entity_type = "item" if name in self.ITEM_MUTATION_TOOLS else name.removeprefix("create_")
        entity_id = result["id"]
        before = before or {}
        event_ids: tuple[int, ...] = ()
        before_ids: dict[str, int | None] = {}
        after_ids: dict[str, int | None] = {}
        if entity_type == "item":
            event_ids = tuple(self.inventory.session.scalars(
                select(Event.id).where(
                    Event.item_id == entity_id,
                    Event.id > before.get("last_event_id", 0),
                ).order_by(Event.id)
            ))
            if name in self.LOCATION_MUTATION_TOOLS:
                before_ids = {"location_id": before["location_id"]}
                after_ids = {"location_id": result["location_id"]}
            elif name == "update_item" and "category_id" in parsed.model_fields_set:
                before_ids = {"category_id": before["category_id"]}
                after_ids = {"category_id": result["category_id"]}
            elif name == "create_item":
                after_ids = {
                    "category_id": result["category_id"],
                    "location_id": result["location_id"],
                }
        elif name in {"create_location", "create_category"}:
            after_ids = {"parent_id": result["parent_id"]}
        changed = bool(event_ids) if name in self.ITEM_MUTATION_TOOLS - {"create_item"} else True
        return MutationReceipt(
            operation=name,
            entity_type=entity_type,
            entity_id=entity_id,
            changed=changed,
            before_ids=before_ids,
            after_ids=after_ids,
            event_ids=event_ids,
        )

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
            "suggest_item_locations": _ToolSpec(
                "Read-only location suggestions for an unambiguously resolved item. Suggestions are derived from last-known history and related current items; they are not the stored current location and do not authorize a move. Search and resolve a location separately before mutation.",
                SuggestItemLocationsInput,
                self._suggest_item_locations,
            ),
            "create_category": _ToolSpec(
                "Create a category only when the user explicitly asked for a new category, after search_categories for the same name. Do not invent taxonomy merely to create an item.",
                CreateCategoryInput,
                self._create_category,
            ),
            "create_location": _ToolSpec(
                "Create a location only after search_locations was called for this name.",
                CreateLocationInput,
                self._create_location,
            ),
            "create_item": _ToolSpec(
                "Create an item only after search_items for the exact same proposed name; reuse that searched name. Existing category/location IDs must be resolved. Persist only metadata stated by the user: leave optional category, tags, description, attributes, and state unset/default rather than inventing them.",
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

    def _list_location(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(LocationIdInput, raw)
        self._require_seen("location", args.location_id)
        result = self.inventory.list_location_page(
            args.location_id, page=args.page, page_size=args.page_size,
        )
        self._remember_seen("item", [item.id for item in result.items])
        return self._page_result(result, [self._item_dict(item) for item in result.items])

    def _get_item_history(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(ItemIdInput, raw)
        self._require_seen("item", args.item_id)
        result = self.inventory.get_item_history_page(
            args.item_id, page=args.page, page_size=args.page_size,
        )
        return self._page_result(result, [self._event_dict(event) for event in result.items])

    @staticmethod
    def _page_result(page: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "items": items, "total": page.total, "page": page.page,
            "page_size": page.page_size, "pages": page.pages,
            "has_previous": page.has_previous, "has_next": page.has_next,
            "previous_page": page.previous_page, "next_page": page.next_page,
        }

    def _suggest_item_locations(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(SuggestItemLocationsInput, raw)
        self._require_resolved("item", args.item_id)
        item = self.inventory.get_item(args.item_id)
        suggestions = self.location_suggestions.suggest_item_locations(
            args.item_id,
            limit=args.limit,
        )
        self._remember_seen(
            "location",
            [suggestion.location_id for suggestion in suggestions],
        )
        return {
            "item_id": item.id,
            "stored_current_location_id": item.current_location_id,
            "suggestions": [asdict(suggestion) for suggestion in suggestions],
            "note": (
                "These are evidence-based suggestions, not the stored current location. "
                "A suggested location must be searched/resolved separately before any move."
            ),
        }

    def _create_category(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(CreateCategoryInput, raw)
        self._require_prior_search("category", args.name)
        if args.parent_id is not None:
            self._require_resolved("category", args.parent_id)
        category = self._validated_write(
            [("category", args.parent_id)] if args.parent_id is not None else [],
            lambda: self.inventory.create_category(**args.model_dump()),
        )
        self._remember_created("category", category.id)
        return self._category_dict(category)

    def _create_location(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(CreateLocationInput, raw)
        self._require_prior_search("location", args.name)
        if args.parent_id is not None:
            self._require_resolved("location", args.parent_id)
        location = self._validated_write(
            [("location", args.parent_id)] if args.parent_id is not None else [],
            lambda: self.inventory.create_location(**args.model_dump()),
        )
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
        references = []
        if args.category_id is not None:
            references.append(("category", args.category_id))
        if args.location_id is not None:
            references.append(("location", args.location_id))
        item = self._validated_write(
            references, lambda: self.inventory.create_item(**kwargs)
        )
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
        references = [("item", item_id)]
        if "category_id" in payload and payload["category_id"] is not None:
            references.append(("category", payload["category_id"]))
        item = self._validated_write(
            references, lambda: self.inventory.update_item(item_id, **payload)
        )
        return self._item_dict(item)

    def _move_item(self, raw: BaseModel) -> dict[str, Any]:
        args = self._cast(MoveItemInput, raw)
        self._require_resolved("item", args.item_id)
        if args.location_id is not None:
            self._require_resolved("location", args.location_id)
        references = [("item", args.item_id)]
        if args.location_id is not None:
            references.append(("location", args.location_id))
        def apply_legacy_move() -> Item:
            if args.location_id is None:
                current = self.inventory.get_item(args.item_id)
                if current.current_location_id is None:
                    return current
                return self.inventory.take_item(
                    args.item_id, original_text=self.original_text
                )
            return self.inventory.move_item(
                args.item_id, args.location_id, original_text=self.original_text
            )

        item = self._validated_write(references, apply_legacy_move)
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
        prior = visible[entity_type]
        if key in prior:
            return
        signature = self._search_name_signature(key)
        if signature and any(
            self._search_name_signature(candidate) == signature
            for candidate in prior
        ):
            return
        raise ToolPreconditionError(
            f"search_{entity_type}s must be called for {name!r} before creation"
        )

    @staticmethod
    def _search_name_signature(value: str) -> tuple[str, ...]:
        return tuple(sorted(value.split()))

    def _remember_search(self, entity_type: str, query: str) -> None:
        key = normalize_search_text(query)
        if key:
            self.state.searches[entity_type].add(key)

    def _remember_seen(self, entity_type: str, ids: list[int]) -> None:
        self.state.seen[entity_type].update(ids)

    def _remember_created(self, entity_type: str, entity_id: int) -> None:
        self.state.seen[entity_type].add(entity_id)
        self.state.resolved[entity_type].add(entity_id)
        self.state.created[entity_type].add(entity_id)

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
        if entity_type not in self.state.evidence:
            return
        resolved_id = self.write_resolver.resolve(entity_type, query)
        if resolved_id in ids:
            self.state.resolved[entity_type].add(resolved_id)
            self.state.evidence[entity_type].setdefault(resolved_id, set()).add(query)

    def _validated_write(
        self,
        references: list[tuple[str, int]],
        operation: Callable[[], Any],
    ) -> Any:
        visible_evidence = self._round_evidence or self.state.evidence
        visible_created = self._round_created or self.state.created
        for entity_type, entity_id in references:
            self._require_resolved(entity_type, entity_id)
            if entity_id not in visible_created[entity_type] and not visible_evidence[entity_type].get(entity_id):
                raise ToolPreconditionError(f"{entity_type} id={entity_id} has no write resolution evidence")

        if references:
            session = self.inventory.session
            session.flush()
            # Acquire SQLite's write lock before checking the complete matching
            # set. A false predicate changes no row or event.
            session.connection().exec_driver_sql("UPDATE items SET id = id WHERE 0")
            session.expire_all()
            for entity_type, entity_id in references:
                if entity_id in visible_created[entity_type]:
                    continue
                queries = visible_evidence[entity_type][entity_id]
                if not any(
                    self.write_resolver.resolve(entity_type, query) == entity_id
                    for query in queries
                ):
                    raise ToolPreconditionError(
                        f"{entity_type} id={entity_id} resolution is stale or ambiguous; search again"
                    )
        return operation()

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
