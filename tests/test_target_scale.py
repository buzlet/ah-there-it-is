from __future__ import annotations

from contextlib import contextmanager
import re

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import Item
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.location_suggestions import LocationSuggestionService
from ah_there_it_is.services.search import SearchService
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
