from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.domain.quantity import QuantityValue
from ah_there_it_is.domain.states import QuantityMode
from ah_there_it_is.services import InventoryService


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        (QuantityMode.EXACT, 1),
        (QuantityMode.APPROXIMATE, 50),
        (QuantityMode.UNKNOWN, None),
    ],
)
def test_quantity_value_accepts_valid_truth(mode: QuantityMode, value: int | None) -> None:
    assert QuantityValue.coerce(mode, value) == QuantityValue(mode, value)


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        ("exact", 0),
        ("exact", -1),
        ("exact", None),
        ("approximate", 0),
        ("unknown", 1),
        ("invalid", 1),
        ("exact", True),
    ],
)
def test_quantity_value_rejects_contradictory_truth(mode: str, value: object) -> None:
    with pytest.raises(ValueError):
        QuantityValue.coerce(mode, value)  # type: ignore[arg-type]


def test_quantity_creation_defaults_and_explicit_modes(session: Session) -> None:
    service = InventoryService(session)
    default = service.create_item("Default")
    approximate = service.create_item(
        "Approximate", quantity_mode="approximate", quantity=50
    )
    unknown = service.create_item("Unknown", quantity_mode="unknown", quantity=None)

    assert (default.quantity_mode, default.quantity) == ("exact", 1)
    assert (approximate.quantity_mode, approximate.quantity) == ("approximate", 50)
    assert (unknown.quantity_mode, unknown.quantity) == ("unknown", None)
    assert service.get_item_history(unknown.id)[0].payload["quantity"] == {
        "mode": "unknown",
        "value": None,
    }


def test_semantic_quantity_change_records_before_after_reason_and_text(
    session: Session,
) -> None:
    service = InventoryService(session)
    item = service.create_item("Screws", quantity=20)

    service.change_item_quantity(
        item.id,
        quantity_mode="approximate",
        quantity=15,
        reason="  пересчитал не полностью  ",
        reason_source="explicit",
        original_text="Теперь примерно 15 шурупов",
    )

    changed = service.get_item_history(item.id)[-1]
    assert (item.quantity_mode, item.quantity) == ("approximate", 15)
    assert changed.event_type == "item_quantity_changed"
    assert changed.payload == {
        "quantity": {
            "before": {"mode": "exact", "value": 20},
            "after": {"mode": "approximate", "value": 15},
        },
        "reason": "пересчитал не полностью",
        "reason_source": "explicit",
    }
    assert changed.original_text == "Теперь примерно 15 шурупов"


def test_semantic_quantity_change_supports_all_precision_transitions(
    session: Session,
) -> None:
    service = InventoryService(session)
    item = service.create_item("Fasteners", quantity=20)
    transitions = [
        ("exact", 15),
        ("unknown", None),
        ("approximate", 50),
        ("exact", 47),
        ("unknown", None),
    ]
    for mode, value in transitions:
        service.change_item_quantity(
            item.id,
            quantity_mode=mode,
            quantity=value,
            reason="inventory correction",
            reason_source="context",
        )
        assert (item.quantity_mode, item.quantity) == (mode, value)


def test_quantity_noop_creates_no_event_and_invalid_request_is_atomic(
    session: Session,
) -> None:
    service = InventoryService(session)
    item = service.create_item("Washers", quantity=12)
    before_events = len(service.get_item_history(item.id))

    service.change_item_quantity(
        item.id,
        quantity_mode="exact",
        quantity=12,
        reason="same count",
        reason_source="context",
    )
    assert len(service.get_item_history(item.id)) == before_events

    with pytest.raises(ValueError):
        service.change_item_quantity(
            item.id,
            quantity_mode="unknown",
            quantity=0,
            reason="invalid",
            reason_source="explicit",
        )
    assert (item.quantity_mode, item.quantity) == ("exact", 12)
    assert len(service.get_item_history(item.id)) == before_events


def test_generic_update_no_longer_accepts_quantity(session: Session) -> None:
    service = InventoryService(session)
    item = service.create_item("Cable")

    with pytest.raises(TypeError, match="quantity"):
        service.update_item(item.id, quantity=2)  # type: ignore[call-arg]


@pytest.mark.parametrize("reason", ["", "   "])
def test_quantity_change_requires_nonblank_reason(session: Session, reason: str) -> None:
    service = InventoryService(session)
    item = service.create_item("Nuts")

    with pytest.raises(ValueError, match="reason"):
        service.change_item_quantity(
            item.id,
            quantity_mode="exact",
            quantity=2,
            reason=reason,
            reason_source="explicit",
        )


def test_quantity_above_sqlite_integer_range_fails_at_domain_boundary(
    session: Session,
) -> None:
    with pytest.raises(ValueError, match="quantity must be an integer"):
        InventoryService(session).create_item("Impossible count", quantity=2**63)
