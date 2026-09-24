from __future__ import annotations

from sqlalchemy.orm import Session

from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.location_suggestions import LocationSuggestionService

def test_known_current_location_returns_no_suggestions(session: Session) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Шкаф")
    category = inventory.create_category("Адаптеры")
    item = inventory.create_item(
        "Known adapter",
        category_id=category.id,
        location_id=location.id,
    )
    inventory.create_item(
        "Related adapter",
        category_id=category.id,
        location_id=location.id,
    )

    assert LocationSuggestionService(session).suggest_item_locations(item.id) == []

def test_in_use_item_suppresses_last_known_suggestions(session: Session) -> None:
    inventory = InventoryService(session)
    room = inventory.create_location("Комната")
    drawer = inventory.create_location("Ящик", parent_id=room.id)
    item = inventory.create_item("Meter", location_id=drawer.id)
    inventory.take_item(item.id)

    suggestions = LocationSuggestionService(session).suggest_item_locations(item.id)

    assert suggestions == []

def test_related_same_category_evidence(session: Session) -> None:
    inventory = InventoryService(session)
    category = inventory.create_category("Кабели")
    location = inventory.create_location("Правый ящик")
    target = inventory.create_item("Unknown cable", category_id=category.id)
    related = inventory.create_item(
        "Known cable",
        category_id=category.id,
        location_id=location.id,
    )

    suggestion = LocationSuggestionService(session).suggest_item_locations(target.id)[0]

    assert suggestion.location_id == location.id
    assert suggestion.evidence.reasons == ("same_category",)
    assert suggestion.evidence.supporting_item_ids == (related.id,)
    assert suggestion.evidence.same_category_item_ids == (related.id,)
    assert suggestion.evidence.shared_tag_item_ids == ()

def test_related_shared_tag_evidence(session: Session) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Полка")
    target = inventory.create_item("Unknown tester", tags=["USB"])
    related = inventory.create_item(
        "Known adapter",
        tags=["USB"],
        location_id=location.id,
    )

    suggestion = LocationSuggestionService(session).suggest_item_locations(target.id)[0]

    assert suggestion.location_id == location.id
    assert suggestion.evidence.reasons == ("shared_tag",)
    assert suggestion.evidence.supporting_item_ids == (related.id,)
    assert suggestion.evidence.same_category_item_ids == ()
    assert suggestion.evidence.shared_tag_item_ids == (related.id,)

def test_combines_last_known_category_and_tag_at_same_location(session: Session) -> None:
    inventory = InventoryService(session)
    category = inventory.create_category("Мультиметры")
    location = inventory.create_location("Шкаф")
    target = inventory.create_item(
        "Unknown meter",
        category_id=category.id,
        location_id=location.id,
        tags=["measurement"],
    )
    related = inventory.create_item(
        "Known meter",
        category_id=category.id,
        location_id=location.id,
        tags=["measurement"],
    )
    inventory.mark_item_location_unknown(target.id)

    suggestions = LocationSuggestionService(session).suggest_item_locations(target.id)

    assert len(suggestions) == 1
    evidence = suggestions[0].evidence
    assert evidence.reasons == ("last_known", "same_category", "shared_tag")
    assert evidence.supporting_item_ids == (related.id,)
    assert evidence.same_category_item_ids == (related.id,)
    assert evidence.shared_tag_item_ids == (related.id,)

def test_related_aggregation_ranking_and_ties_are_stable(session: Session) -> None:
    inventory = InventoryService(session)
    target_category = inventory.create_category("Target category")
    other_category = inventory.create_category("Other category")
    location_a = inventory.create_location("A")
    location_b = inventory.create_location("B")
    location_c = inventory.create_location("C")
    target = inventory.create_item(
        "Unknown target",
        category_id=target_category.id,
        tags=["shared"],
    )

    inventory.create_item("A1", category_id=target_category.id, location_id=location_a.id)
    inventory.create_item("A2", category_id=target_category.id, location_id=location_a.id)

    inventory.create_item("B1", category_id=target_category.id, location_id=location_b.id)
    inventory.create_item(
        "B2",
        category_id=other_category.id,
        location_id=location_b.id,
        tags=["shared"],
    )

    inventory.create_item("C1", category_id=target_category.id, location_id=location_c.id)
    inventory.create_item(
        "C2",
        category_id=other_category.id,
        location_id=location_c.id,
        tags=["shared"],
    )

    service = LocationSuggestionService(session)
    first = service.suggest_item_locations(target.id)
    second = service.suggest_item_locations(target.id)

    assert first == second
    assert [item.location_id for item in first] == [
        location_b.id,
        location_c.id,
        location_a.id,
    ]
    assert [len(item.evidence.supporting_item_ids) for item in first] == [2, 2, 2]
    assert first[0].evidence.reasons == ("same_category", "shared_tag")
    assert first[1].evidence.reasons == ("same_category", "shared_tag")
    assert first[2].evidence.reasons == ("same_category",)

    assert [item.location_id for item in service.suggest_item_locations(target.id, limit=2)] == [
        location_b.id,
        location_c.id,
    ]

def test_no_evidence_returns_empty_result(session: Session) -> None:
    item = InventoryService(session).create_item("Unknown singleton")

    assert LocationSuggestionService(session).suggest_item_locations(item.id) == []

def test_last_known_always_ranks_before_more_related_support(session: Session) -> None:
    inventory = InventoryService(session)
    category = inventory.create_category("Adapters")
    last_known = inventory.create_location("Last known")
    related_location = inventory.create_location("Many related")
    target = inventory.create_item(
        "Unknown adapter",
        category_id=category.id,
        location_id=last_known.id,
    )
    for index in range(3):
        inventory.create_item(
            f"Related {index}",
            category_id=category.id,
            location_id=related_location.id,
        )
    inventory.mark_item_location_unknown(target.id)

    suggestions = LocationSuggestionService(session).suggest_item_locations(target.id)

    assert [item.location_id for item in suggestions[:2]] == [
        last_known.id,
        related_location.id,
    ]
    assert suggestions[0].evidence.reasons == ("last_known",)
    assert len(suggestions[1].evidence.supporting_item_ids) == 3

def test_last_known_skips_unusable_events_and_prefers_to_location(
    session: Session,
) -> None:
    from ah_there_it_is.db.models import Event

    inventory = InventoryService(session)
    source = inventory.create_location("Source")
    destination = inventory.create_location("Destination")
    item = inventory.create_item("Unknown routed item")
    movement = Event(
        event_type="item_moved",
        item_id=item.id,
        from_location_id=source.id,
        to_location_id=destination.id,
        payload={},
    )
    session.add(movement)
    session.commit()
    inventory.update_item(item.id, description="newer event without location evidence")

    suggestion = LocationSuggestionService(session).suggest_item_locations(item.id)[0]

    assert suggestion.location_id == destination.id
    assert suggestion.evidence.reasons == ("last_known",)
    assert suggestion.evidence.last_known_event_id == movement.id
    assert suggestion.evidence.last_known_event_type == "item_moved"


def test_suggestions_are_eligible_only_for_unknown_location_truth(session: Session) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Bench")
    related = inventory.create_item("Related meter", location_id=location.id)
    in_use = inventory.create_item("In use meter", location_id=location.id)
    terminal = inventory.create_item("Discarded meter", state="discarded")

    inventory.take_item(in_use.id)
    inventory.discard_item(terminal.id)
    suggestions = LocationSuggestionService(session)

    assert suggestions.suggest_item_locations(related.id) == []
    assert suggestions.suggest_item_locations(in_use.id) == []
    assert suggestions.suggest_item_locations(terminal.id) == []


def test_unknown_status_suggestions_can_use_unknown_transition_history(
    session: Session,
) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Drawer")
    item = inventory.create_item("Moved meter", location_id=location.id)
    inventory.mark_item_location_unknown(item.id)

    result = LocationSuggestionService(session).suggest_item_locations(item.id)

    assert len(result) == 1
    assert result[0].location_id == location.id
    assert result[0].evidence.last_known_event_type == "item_location_unknown"
