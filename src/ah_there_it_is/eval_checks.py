"""Provider-neutral postcondition checks for evaluation scenarios."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Event
from ah_there_it_is.eval_corpus import ExpectedCheck
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService


def event_count(session: Session) -> int:
    return int(session.scalar(select(func.count(Event.id))) or 0)


def evaluate_expected_check(
    session: Session,
    check: ExpectedCheck,
    *,
    events_before: int,
) -> dict[str, Any]:
    search = SearchService(session)
    inventory = InventoryService(session)

    if check.kind == "no_mutation":
        events_after = event_count(session)
        return {
            "kind": check.kind,
            "ok": events_after == events_before,
            "detail": f"events {events_before} -> {events_after}",
        }

    items = (
        search.search_items(check.item_query or "", limit=3)
        if check.item_query
        else []
    )

    if check.kind == "item_exists":
        return {
            "kind": check.kind,
            "ok": bool(items),
            "detail": [item.model_dump(mode="json") for item in items],
        }

    if not items:
        return {
            "kind": check.kind,
            "ok": False,
            "detail": {"item_query": check.item_query, "items": 0},
        }

    candidate = items[0]
    item = inventory.get_item(candidate.id)

    if check.kind == "item_location":
        locations = search.search_locations(check.location_query or "", limit=5)
        location_ids = {location.id for location in locations}
        return {
            "kind": check.kind,
            "ok": item.current_location_id in location_ids,
            "detail": {
                "item_id": item.id,
                "actual_location_id": item.current_location_id,
                "candidate_location_ids": sorted(location_ids),
            },
        }

    if check.kind == "item_location_none":
        return {
            "kind": check.kind,
            "ok": item.current_location_id is None,
            "detail": {
                "item_id": item.id,
                "actual_location_id": item.current_location_id,
            },
        }

    if check.kind == "item_state":
        return {
            "kind": check.kind,
            "ok": item.state == check.state,
            "detail": {
                "item_id": item.id,
                "actual": item.state,
                "expected": check.state,
            },
        }

    if check.kind == "item_quantity":
        return {
            "kind": check.kind,
            "ok": item.quantity == check.quantity,
            "detail": {
                "item_id": item.id,
                "actual": item.quantity,
                "expected": check.quantity,
            },
        }

    if check.kind == "item_description_contains":
        description = item.description or ""
        needle = check.text or ""
        return {
            "kind": check.kind,
            "ok": needle.casefold() in description.casefold(),
            "detail": {
                "item_id": item.id,
                "description": description,
                "expected_text": needle,
            },
        }

    if check.kind == "item_history_min_events":
        events = inventory.get_item_history(item.id)
        minimum = check.min_events or 0
        return {
            "kind": check.kind,
            "ok": len(events) >= minimum,
            "detail": {
                "item_id": item.id,
                "actual_events": len(events),
                "minimum": minimum,
            },
        }

    raise AssertionError(f"unsupported check kind: {check.kind}")
