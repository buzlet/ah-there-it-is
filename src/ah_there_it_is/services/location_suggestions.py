"""Deterministic read-only location suggestions from inventory evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import Event, Item, ItemTag, Location
from ah_there_it_is.domain.exceptions import EntityNotFoundError
from ah_there_it_is.domain.states import LocationStatus


SuggestionReason = Literal["last_known", "same_category", "shared_tag"]


@dataclass(frozen=True)
class LocationSuggestionEvidence:
    reasons: tuple[SuggestionReason, ...]
    last_known_event_id: int | None
    last_known_event_type: str | None
    supporting_item_ids: tuple[int, ...]
    same_category_item_ids: tuple[int, ...]
    shared_tag_item_ids: tuple[int, ...]


@dataclass(frozen=True)
class LocationSuggestion:
    location_id: int
    location_path: str
    evidence: LocationSuggestionEvidence


@dataclass
class _Evidence:
    last_known_event_id: int | None = None
    last_known_event_type: str | None = None
    supporting_item_ids: set[int] = field(default_factory=set)
    same_category_item_ids: set[int] = field(default_factory=set)
    shared_tag_item_ids: set[int] = field(default_factory=set)


class LocationSuggestionService:
    """Derive explainable candidate locations without changing inventory state."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def suggest_item_locations(
        self,
        item_id: int,
        *,
        limit: int = 5,
    ) -> list[LocationSuggestion]:
        item = self.session.scalar(
            select(Item)
            .options(selectinload(Item.tag_links))
            .where(Item.id == item_id)
        )
        if item is None:
            raise EntityNotFoundError(f"item id={item_id} does not exist")
        if item.location_status != LocationStatus.UNKNOWN.value or limit < 1:
            return []

        evidence_by_location: dict[int, _Evidence] = {}
        last_known = self._last_known_event(item.id)
        if last_known is not None:
            event, location_id = last_known
            bucket = evidence_by_location.setdefault(location_id, _Evidence())
            bucket.last_known_event_id = event.id
            bucket.last_known_event_type = event.event_type

        target_tag_ids = {link.tag_id for link in item.tag_links}
        shared_tag_exists = (
            exists(
                select(ItemTag.item_id).where(
                    ItemTag.item_id == Item.id,
                    ItemTag.tag_id.in_(target_tag_ids),
                )
            )
            if target_tag_ids
            else None
        )
        relevance = []
        if item.category_id is not None:
            relevance.append(Item.category_id == item.category_id)
        if shared_tag_exists is not None:
            relevance.append(shared_tag_exists)

        if relevance:
            related_stmt = (
                select(
                    Item.id,
                    Item.current_location_id,
                    Item.category_id,
                    (
                        shared_tag_exists
                        if shared_tag_exists is not None
                        else (Item.id != Item.id)
                    ).label("shared_tag"),
                )
                .where(
                    Item.id != item.id,
                    Item.current_location_id.is_not(None),
                    or_(*relevance),
                )
                .order_by(Item.id)
            )
            for related in self.session.execute(related_stmt):
                same_category = (
                    item.category_id is not None
                    and related.category_id == item.category_id
                )
                shared_tag = bool(related.shared_tag)
                location_id = related.current_location_id
                if location_id is None:
                    continue
                bucket = evidence_by_location.setdefault(location_id, _Evidence())
                bucket.supporting_item_ids.add(related.id)
                if same_category:
                    bucket.same_category_item_ids.add(related.id)
                if shared_tag:
                    bucket.shared_tag_item_ids.add(related.id)

        suggestions = [
            self._suggestion(location_id, evidence)
            for location_id, evidence in evidence_by_location.items()
        ]
        suggestions.sort(key=self._rank_key)
        return suggestions[:limit]

    def _last_known_event(self, item_id: int) -> tuple[Event, int] | None:
        events = self.session.scalars(
            select(Event)
            .where(Event.item_id == item_id)
            .order_by(Event.created_at.desc(), Event.id.desc())
        )
        for event in events:
            if event.event_type == "item_taken":
                location_id = event.from_location_id
            else:
                location_id = event.to_location_id or event.from_location_id
            if location_id is not None:
                return event, location_id
        return None

    def _suggestion(self, location_id: int, evidence: _Evidence) -> LocationSuggestion:
        location = self.session.get(Location, location_id)
        if location is None:
            raise RuntimeError(f"location id={location_id} referenced by evidence is missing")

        reasons: list[SuggestionReason] = []
        if evidence.last_known_event_id is not None:
            reasons.append("last_known")
        if evidence.same_category_item_ids:
            reasons.append("same_category")
        if evidence.shared_tag_item_ids:
            reasons.append("shared_tag")

        return LocationSuggestion(
            location_id=location_id,
            location_path=self._path(location),
            evidence=LocationSuggestionEvidence(
                reasons=tuple(reasons),
                last_known_event_id=evidence.last_known_event_id,
                last_known_event_type=evidence.last_known_event_type,
                supporting_item_ids=tuple(sorted(evidence.supporting_item_ids)),
                same_category_item_ids=tuple(sorted(evidence.same_category_item_ids)),
                shared_tag_item_ids=tuple(sorted(evidence.shared_tag_item_ids)),
            ),
        )

    @staticmethod
    def _rank_key(suggestion: LocationSuggestion) -> tuple[int, int, int, int]:
        evidence = suggestion.evidence
        has_last_known = "last_known" in evidence.reasons
        related_count = len(evidence.supporting_item_ids)
        has_both_related = (
            "same_category" in evidence.reasons
            and "shared_tag" in evidence.reasons
        )
        return (
            0 if has_last_known else 1,
            -related_count,
            0 if has_both_related else 1,
            suggestion.location_id,
        )

    @staticmethod
    def _path(location: Location) -> str:
        names: list[str] = []
        seen: set[int] = set()
        current: Location | None = location
        while current is not None:
            if current.id in seen:
                raise RuntimeError("cycle detected in location hierarchy")
            seen.add(current.id)
            names.append(current.name)
            current = current.parent
        return " / ".join(reversed(names))
