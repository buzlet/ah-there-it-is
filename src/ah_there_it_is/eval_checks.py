"""Shared deterministic postcondition evaluator for evaluation pipelines."""

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


def _item_detail(session: Session, query: str) -> tuple[Any | None, list[Any]]:
    search = SearchService(session)
    candidates = search.search_items(query, limit=10)
    if not candidates:
        return None, candidates
    item = InventoryService(session).get_item(candidates[0].id)
    return item, candidates


def _location_ids(session: Session, query: str | None) -> set[int]:
    if not query:
        return set()
    return {
        candidate.id
        for candidate in SearchService(session).search_locations(query, limit=10)
    }


def _event_dict(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "item_id": event.item_id,
        "from_location_id": event.from_location_id,
        "to_location_id": event.to_location_id,
        "payload": event.payload,
        "original_text": event.original_text,
    }


def evaluate_check(
    session: Session,
    check: ExpectedCheck,
    *,
    events_before: int,
) -> dict[str, Any]:
    search = SearchService(session)

    if check.kind == "no_mutation":
        after = event_count(session)
        return {
            "kind": check.kind,
            "ok": after == events_before,
            "detail": {"before": events_before, "after": after},
        }

    if check.kind == "event_count_delta":
        after = event_count(session)
        actual = after - events_before
        return {
            "kind": check.kind,
            "ok": actual == check.expected_delta,
            "detail": {
                "before": events_before,
                "after": after,
                "actual_delta": actual,
                "expected_delta": check.expected_delta,
            },
        }

    if check.kind == "item_exists":
        candidates = search.search_items(check.item_query or "", limit=10)
        return {
            "kind": check.kind,
            "ok": bool(candidates),
            "detail": [
                candidate.model_dump(mode="json")
                for candidate in candidates
            ],
        }

    item, candidates = _item_detail(session, check.item_query or "")
    if item is None:
        return {
            "kind": check.kind,
            "ok": False,
            "detail": {
                "item_query": check.item_query,
                "candidates": [],
            },
        }

    candidate_detail = [
        candidate.model_dump(mode="json") for candidate in candidates
    ]

    if check.kind == "item_location":
        location_ids = _location_ids(session, check.location_query)
        return {
            "kind": check.kind,
            "ok": item.current_location_id in location_ids,
            "detail": {
                "item_id": item.id,
                "actual_location_id": item.current_location_id,
                "candidate_location_ids": sorted(location_ids),
                "item_candidates": candidate_detail,
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
                "description": item.description,
                "contains": needle,
            },
        }

    if check.kind == "item_attribute_equals":
        actual = item.attributes.get(check.attribute_key or "")
        return {
            "kind": check.kind,
            "ok": actual == check.expected_value,
            "detail": {
                "item_id": item.id,
                "attribute": check.attribute_key,
                "actual": actual,
                "expected": check.expected_value,
            },
        }

    if check.kind == "item_category_none":
        return {
            "kind": check.kind,
            "ok": item.category_id is None,
            "detail": {
                "item_id": item.id,
                "actual_category_id": item.category_id,
            },
        }

    if check.kind == "item_event":
        stmt = (
            select(Event)
            .where(Event.item_id == item.id)
            .order_by(Event.id.asc())
        )
        if check.event_type is not None:
            stmt = stmt.where(Event.event_type == check.event_type)
        events = list(session.scalars(stmt))
        from_ids = _location_ids(session, check.from_location_query)
        to_ids = _location_ids(session, check.to_location_query)
        matching = [
            event
            for event in events
            if (
                not check.from_location_query
                or event.from_location_id in from_ids
            )
            and (
                not check.to_location_query
                or event.to_location_id in to_ids
            )
        ]
        return {
            "kind": check.kind,
            "ok": len(matching) >= check.min_count,
            "detail": {
                "item_id": item.id,
                "event_type": check.event_type,
                "min_count": check.min_count,
                "matching": [_event_dict(event) for event in matching],
                "all_matching_type": [_event_dict(event) for event in events],
            },
        }

    raise AssertionError(f"unsupported check kind: {check.kind}")


def evaluate_checks(
    session: Session,
    checks: list[ExpectedCheck],
    *,
    events_before: int,
) -> list[dict[str, Any]]:
    return [
        evaluate_check(session, check, events_before=events_before)
        for check in checks
    ]
