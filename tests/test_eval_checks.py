from __future__ import annotations

import pytest
from pydantic import ValidationError

from ah_there_it_is.eval_checks import event_count, evaluate_check, evaluate_checks
from ah_there_it_is.eval_corpus import ExpectedCheck
from ah_there_it_is.eval_fixture import seed_inventory_fixture
from ah_there_it_is.services.inventory import InventoryService


def test_extended_check_schema_requires_kind_specific_fields() -> None:
    with pytest.raises(ValidationError):
        ExpectedCheck(kind="item_state", item_query="GTX 1070")
    with pytest.raises(ValidationError):
        ExpectedCheck(kind="event_count_delta")
    with pytest.raises(ValidationError):
        ExpectedCheck(kind="item_event", item_query="GTX 1070")


def test_shared_oracle_reads_item_state_fields(session) -> None:
    seed_inventory_fixture(session)
    before = event_count(session)

    checks = [
        ExpectedCheck(
            kind="item_state",
            item_query="GTX 1070",
            state="working",
        ),
        ExpectedCheck(
            kind="item_quantity",
            item_query="HDMI 2 метра",
            quantity=3,
        ),
        ExpectedCheck(
            kind="item_description_contains",
            item_query="ORICO",
            text="SSD",
        ),
        ExpectedCheck(
            kind="item_attribute_equals",
            item_query="GTX 1070",
            attribute_key="memory_gb",
            expected_value=8,
        ),
    ]

    results = evaluate_checks(session, checks, events_before=before)

    assert all(result["ok"] for result in results)


def test_shared_oracle_checks_move_event_and_event_delta(session) -> None:
    ids = seed_inventory_fixture(session)
    inventory = InventoryService(session)
    before = event_count(session)

    inventory.move_item(
        ids.items["ch341a"],
        ids.locations["desk_middle"],
        original_text="test move",
    )

    checks = [
        ExpectedCheck(
            kind="item_location",
            item_query="CH341A",
            location_query="Средний ящик",
        ),
        ExpectedCheck(kind="event_count_delta", expected_delta=1),
        ExpectedCheck(
            kind="item_event",
            item_query="CH341A",
            event_type="item_moved",
            from_location_query="Правый ящик",
            to_location_query="Средний ящик",
        ),
    ]

    results = evaluate_checks(session, checks, events_before=before)

    assert all(result["ok"] for result in results)
    assert results[2]["detail"]["matching"][0]["original_text"] == "test move"


def test_shared_oracle_checks_taken_location_and_category_none(session) -> None:
    ids = seed_inventory_fixture(session)
    inventory = InventoryService(session)
    before = event_count(session)

    inventory.move_item(ids.items["dt830b"], None, original_text="take")
    loose = inventory.create_item("Loose adapter", original_text="create")

    taken = evaluate_check(
        session,
        ExpectedCheck(
            kind="item_location_none",
            item_query="красный мультиметр",
        ),
        events_before=before,
    )
    category = evaluate_check(
        session,
        ExpectedCheck(
            kind="item_category_none",
            item_query=loose.name,
        ),
        events_before=before,
    )

    assert taken["ok"] is True
    assert category["ok"] is True
