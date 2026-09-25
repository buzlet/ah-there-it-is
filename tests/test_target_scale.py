from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import re

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import Event, Item
from ah_there_it_is.services.activity import ActivityService
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.location_suggestions import LocationSuggestionService
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.services.inventory import InventoryService
from tests.scale_fixture import build_target_scale_inventory


@contextmanager
def _count_loaded_items(session: Session):
    count = 0

    def loaded(_session, instance) -> None:
        nonlocal count
        if isinstance(instance, Item):
            count += 1

    event.listen(session, "loaded_as_persistent", loaded)
    try:
        yield lambda: count
    finally:
        event.remove(session, "loaded_as_persistent", loaded)


@contextmanager
def _count_loaded_events(session: Session):
    count = 0

    def loaded(_session, instance) -> None:
        nonlocal count
        if isinstance(instance, Event):
            count += 1

    event.listen(session, "loaded_as_persistent", loaded)
    try:
        yield lambda: count
    finally:
        event.remove(session, "loaded_as_persistent", loaded)


@contextmanager
def _count_statements(session: Session):
    count = 0
    engine = session.get_bind()

    def before_cursor_execute(*_args) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield lambda: count
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def test_target_scale_search_semantics_and_bounded_item_loading(session: Session) -> None:
    scale = build_target_scale_inventory(session)
    search = SearchService(session)

    cases = [
        ("Scale Exact Name Target", scale.exact_name_id, "exact_name"),
        ("Scale Exact Alias", scale.alias_id, "exact_alias"),
        ("SCALE-ATTRIBUTE-777", scale.attribute_id, "exact_attribute"),
        ("scale-exact-tag", scale.tag_id, "exact_tag"),
        ("phosphor telescope", scale.description_id, "fts"),
    ]
    for query, expected_id, expected_match in cases:
        session.expunge_all()
        with _count_loaded_items(session) as loaded:
            results = search.search_items(query, limit=5)
        assert results[0].id == expected_id
        assert results[0].match_type == expected_match
        assert loaded() < 200

    session.expunge_all()
    duplicates = search.search_locations("Zone 00 Shelf 07", limit=5)
    assert duplicates[0].id == scale.duplicate_location_ids[0]


def test_target_scale_quantity_split_removed_and_equivalent_lots_are_bounded(
    session: Session,
) -> None:
    scale = build_target_scale_inventory(session)
    inventory = InventoryService(session)
    baseline_events = int(session.scalar(select(func.count(Event.id))) or 0)
    split_destination = inventory.create_location("Scale split destination")
    sources = list(session.scalars(select(Item).order_by(Item.id).limit(60)))
    for index, item in enumerate(sources):
        mode, value = (
            ("exact", 12) if index % 3 == 0
            else ("approximate", 12) if index % 3 == 1
            else ("unknown", None)
        )
        inventory.change_item_quantity(
            item.id,
            quantity_mode=mode,
            quantity=value,
            reason="scale fixture",
            reason_source="context",
        )
    for item in sources[:10]:
        inventory.move_item(
            item.id,
            split_destination.id,
            portion={"mode": "exact", "value": 2},
        )

    equivalent_ids = []
    for _ in range(40):
        equivalent_ids.append(inventory.create_item(
            "Equivalent Scale Lot",
            location_id=scale.suggestion_location_id,
            quantity=5,
            allow_duplicate=True,
        ).id)
    for item_id in equivalent_ids[:20]:
        inventory.remove_item(
            item_id, reason="scale retirement", reason_source="context"
        )

    session.expunge_all()
    with _count_loaded_items(session) as loaded:
        matches = SearchService(session).search_items("Equivalent Scale Lot", limit=5)
    assert [candidate.id for candidate in matches] == equivalent_ids[:5]
    assert loaded() < 100
    assert session.scalar(select(func.count(Item.id))) == 1050
    assert int(session.scalar(select(func.count(Event.id))) or 0) > baseline_events + 100


def test_target_scale_suggestions_do_not_load_unrelated_item_population(
    session: Session,
) -> None:
    scale = build_target_scale_inventory(session)
    session.expunge_all()

    with _count_loaded_items(session) as loaded:
        suggestions = LocationSuggestionService(session).suggest_item_locations(
            scale.suggestion_target_id,
            limit=5,
        )

    assert suggestions[0].location_id == scale.suggestion_location_id
    assert scale.suggestion_related_id in suggestions[0].evidence.supporting_item_ids
    assert suggestions[0].evidence.reasons == ("same_category", "shared_tag")
    assert loaded() < 20


def test_target_scale_catalog_pagination_and_web_page_slice(
    session: Session,
) -> None:
    build_target_scale_inventory(session)
    catalog = CatalogService(session)

    first = catalog.item_page()
    third = catalog.item_page(page=3)
    expected = list(
        session.scalars(
            select(Item.id).order_by(Item.normalized_name, Item.id).offset(100).limit(50)
        )
    )
    assert first.total == 1000
    assert first.page_size == 50
    assert len(first.items) == 50
    assert [row["id"] for row in third.items] == expected
    assert first.has_previous is False
    assert first.next_page == 2
    assert third.previous_page == 2

    factory = lambda: session

    class _Factory:
        def __call__(self):
            return _SessionContext(session)

    app = create_app(
        Settings(app_name="Scale Inventory"),
        session_factory=_Factory(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        response = client.get("/items?page=1&page_size=50")
        invalid = client.get("/items?page=0")
        too_large = client.get("/items?page_size=101")

    assert response.status_code == 200
    assert "Total: 1000" in response.text
    assert 'href="/items/new"' in response.text
    assert len(re.findall(r'href="/items/\d+"', response.text)) == 50
    assert first.items[0]["name"] in response.text
    assert third.items[0]["name"] not in response.text
    assert invalid.status_code == 400
    assert too_large.status_code == 400


def test_target_scale_lifecycle_and_location_filters_preserve_pages(
    session: Session,
) -> None:
    scale = build_target_scale_inventory(session)
    InventoryService(session).mark_item_sold(scale.exact_name_id)

    catalog = CatalogService(session)
    active = catalog.item_page(lifecycle="active")
    terminal = catalog.item_page(lifecycle="terminal")
    unknown_first = catalog.item_page(
        lifecycle="active",
        location_status="unknown",
        page=1,
        page_size=2,
    )
    unknown_second = catalog.item_page(
        lifecycle="active",
        location_status="unknown",
        page=2,
        page_size=2,
    )
    assert active.total == 999
    assert terminal.total == 1
    assert terminal.items[0]["state"] == "sold"
    assert unknown_first.total == 4
    assert unknown_first.next_page == 2
    assert len(unknown_first.items) == 2
    assert len(unknown_second.items) == 2
    assert all(row["location_status"] == "unknown" for row in unknown_first.items + unknown_second.items)

    app = create_app(
        Settings(app_name="Scale Inventory"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        default_catalog = client.get("/items?page_size=2")
        unknown_page = client.get("/items", params={
            "lifecycle": "active",
            "location_status": "unknown",
            "page": 1,
            "page_size": 2,
        })
        unknown_page_two = client.get("/items?lifecycle=active&location_status=unknown&page=2&page_size=2")
        terminal_catalog = client.get("/items", params={"lifecycle": "terminal"})
        terminal_search = client.get("/items", params={"q": "Scale Exact Name Target"})
        active_search = client.get("/items", params={
            "q": "Scale Exact Name Target",
            "lifecycle": "active",
        })

    assert "Total: 999" in default_catalog.text
    assert "Scale Exact Name Target" not in default_catalog.text
    assert "Total: 4" in unknown_page.text
    assert "Location unknown" in unknown_page.text
    assert 'href="/items?lifecycle=active&amp;location_status=unknown&amp;page=2&amp;page_size=2"' in unknown_page.text
    assert "Page 2" in unknown_page_two.text
    assert "Scale Exact Name Target" in terminal_catalog.text
    assert "Scale Exact Name Target" in terminal_search.text
    assert "sold" in terminal_search.text and "Not applicable" in terminal_search.text
    assert f'href="/items/{scale.exact_name_id}"' not in active_search.text


class _SessionContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *_args) -> None:
        return None


def test_target_scale_tree_catalog_counts_use_bounded_statement_count(
    session: Session,
) -> None:
    build_target_scale_inventory(session)
    catalog = CatalogService(session)

    session.expunge_all()
    with _count_statements(session) as location_statements:
        locations = catalog.list_locations()
    assert len(locations) == 200
    assert location_statements() <= 3

    session.expunge_all()
    with _count_statements(session) as category_statements:
        categories = catalog.list_categories()
    assert len(categories) == 31
    assert category_statements() <= 3


def test_target_scale_browser_search_and_tree_detail_stay_bounded(session: Session) -> None:
    scale = build_target_scale_inventory(session)
    app = create_app(
        Settings(app_name="Scale Inventory"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        session.expunge_all()
        with _count_loaded_items(session) as loaded, _count_statements(session) as statements:
            search = client.get("/items", params={"q": "Inventory Item"})
        assert search.status_code == 200
        assert len(re.findall(r'href="/items/\d+"', search.text)) == 100
        assert "Up to 100 ranked matches after filters" in search.text
        assert "Total:" not in search.text
        assert loaded() < 500
        assert statements() < 250

        session.expunge_all()
        with _count_loaded_items(session) as loaded, _count_statements(session) as statements:
            location = client.get(f"/locations/{scale.duplicate_location_ids[0]}")
        assert location.status_code == 200
        assert "Zone 00 / Shelf 07" in location.text
        assert loaded() == 0
        assert statements() <= 8

        session.expunge_all()
        with _count_loaded_items(session) as loaded, _count_statements(session) as statements:
            category = client.get("/categories/1")
        assert category.status_code == 200
        assert "Direct items" in category.text
        assert loaded() == 0
        assert statements() <= 8

@contextmanager
def _capture_sql(session: Session):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield lambda: statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_target_scale_activity_page_filters_and_bounded_reads(
    session: Session,
) -> None:
    scale = build_target_scale_inventory(session)
    instant = datetime(2024, 1, 1, tzinfo=timezone.utc)
    session.execute(Event.__table__.insert(), [
        {
            "event_type": "scale-tie",
            "item_id": scale.exact_name_id,
            "created_at": instant,
            "payload": {"tie": index},
        }
        for index in range(3)
    ])
    session.commit()
    tie_ids = list(session.scalars(
        select(Event.id)
        .where(Event.event_type == "scale-tie")
        .order_by(Event.id)
    ))
    session.expunge_all()
    with (
        _count_loaded_events(session) as loaded,
        _count_statements(session) as statements,
        _capture_sql(session) as sql,
    ):
        page = ActivityService(session).page(page_size=50)
    assert page.total == 1003
    assert page.pages == 21 and len(page.items) == 50
    assert loaded() <= 50
    assert statements() <= 3
    assert any(
        "FROM EVENTS" in statement.upper() and "LIMIT" in statement.upper()
        for statement in sql()
    )

    tied = ActivityService(session).page(
        event_type="scale-tie",
        item_id=scale.exact_name_id,
        page_size=2,
    )

    assert tied.total == 3 and tied.next_page == 2
    assert [row["id"] for row in tied.items] == tie_ids[::-1][:2]
    filtered_page = ActivityService(session).page(
        event_type="scale-tie",
        item_id=scale.exact_name_id,
        page=2,
        page_size=2,
    )
    assert [row["id"] for row in filtered_page.items] == tie_ids[:1]
    assert ActivityService(session).page(item_id=999999).total == 0

    app = create_app(
        Settings(app_name="Scale Inventory"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        session.expunge_all()
        with _count_loaded_events(session) as loaded, _count_statements(session) as statements:
            overview = client.get("/activity")
        filtered = client.get("/activity", params={
            "event_type": "scale-tie",
            "item_id": scale.exact_name_id,
            "page_size": 2,
        })
        empty = client.get("/activity", params={"item_id": 999999})
        too_large = client.get("/activity?page_size=101")

    assert overview.status_code == 200 and "Total: 1003" in overview.text
    assert 'href="/activity">Activity</a>' in overview.text
    assert len(re.findall(r'href="/activity/\d+"', overview.text)) == 50
    assert loaded() <= 50
    assert statements() <= 3
    assert filtered.status_code == 200
    assert f'href="/activity?page=2&amp;page_size=2&amp;event_type=scale-tie&amp;item_id={scale.exact_name_id}"' in filtered.text
    assert f"Event #{tie_ids[-1]}" in filtered.text
    assert "Total: 0" in empty.text
    assert too_large.status_code == 400
