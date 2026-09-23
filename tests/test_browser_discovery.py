# test_browser_discovery.py
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService
from tests.test_app import build_test_app


@pytest.mark.parametrize(
    ("query", "expected_match"),
    [
        ("Beacon reader", "exact name"),
        ("Handheld beacon", "exact alias"),
        ("beacon-tag", "exact tag"),
        ("BEACON-ATTRIBUTE-7", "exact attribute"),
        ("phosphor telescope", "fts"),
    ],
)
def test_browser_search_uses_existing_ranking_and_links(
    query: str, expected_match: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            category = inventory.create_category("Instruments")
            location = inventory.create_location("Bench")
            item = inventory.create_item(
                "Beacon reader",
                aliases=["Handheld beacon"],
                tags=["beacon-tag"],
                attributes={"model": "BEACON-ATTRIBUTE-7"},
                description="Unique phosphor telescope marker",
                category_id=category.id,
                location_id=location.id,
            )
            ids = item.id, category.id, location.id

        calls: list[tuple[str, int]] = []
        original = SearchService.search_items

        def traced(self: SearchService, value: str, *, limit: int = 5):
            calls.append((value, limit))
            return original(self, value, limit=limit)

        monkeypatch.setattr(SearchService, "search_items", traced)
        with TestClient(app) as client:
            response = client.get("/items", params={"q": f"  {query}  "})
            item_detail = client.get(f"/items/{ids[0]}")

        assert response.status_code == 200
        assert calls == [(query, 100)]
        assert f'href="/items/{ids[0]}"' in response.text
        assert f'href="/categories/{ids[1]}"' in response.text
        assert f'href="/locations/{ids[2]}"' in response.text
        assert f"Results for “{query}”" in response.text
        assert f'value="{query}"' in response.text
        assert expected_match in response.text
        assert "Clear search" in response.text
        assert "Total:" not in response.text
        assert f'href="/categories/{ids[1]}"' in item_detail.text
        assert f'href="/locations/{ids[2]}"' in item_detail.text
    finally:
        engine.dispose()


def test_blank_query_keeps_paged_catalog_and_reset() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            for index in range(3):
                inventory.create_item(f"Item {index}")
        with TestClient(app) as client:
            first = client.get("/items", params={"q": "  ", "page_size": 2})
            second = client.get("/items", params={"page": 2, "page_size": 2})
            empty = client.get("/items", params={"q": "absent"})
            invalid = client.get("/items", params={"q": " ", "page": 0})
        assert first.status_code == 200
        assert "Total: 3" in first.text
        assert len(re.findall(r'href="/items/\d+"', first.text)) == 2
        assert 'href="/items?page=2&page_size=2"' in first.text
        assert second.status_code == 200
        assert len(re.findall(r'href="/items/\d+"', second.text)) == 1
        assert empty.status_code == 200
        assert "No matching items." in empty.text
        assert 'href="/items">Clear search</a>' in empty.text
        assert "Total:" not in empty.text
        assert invalid.status_code == 400
    finally:
        engine.dispose()


def test_tree_detail_paths_direct_membership_links_and_404s() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            room_a = inventory.create_location("Room A")
            room_b = inventory.create_location("Room B")
            shelf_a = inventory.create_location("Shelf", parent_id=room_a.id, description="First shelf")
            shelf_b = inventory.create_location("Shelf", parent_id=room_b.id)
            bin_a = inventory.create_location("Bin", parent_id=shelf_a.id)
            category = inventory.create_category("Electronics")
            subcategory = inventory.create_category("Adapters", parent_id=category.id, description="Direct adapters")
            child_category = inventory.create_category("USB", parent_id=subcategory.id)
            direct = inventory.create_item("Direct adapter", category_id=subcategory.id, location_id=shelf_a.id)
            descendant = inventory.create_item("Descendant adapter", category_id=child_category.id, location_id=bin_a.id)
            other = inventory.create_item("Other adapter", category_id=category.id, location_id=shelf_b.id)
            ids = (room_a.id, room_b.id, shelf_a.id, shelf_b.id, bin_a.id,
                   category.id, subcategory.id, child_category.id,
                   direct.id, descendant.id, other.id)
        a, b, shelf_a, shelf_b, bin_a, cat, sub, child, direct, descendant, other = ids
        with TestClient(app) as client:
            loc_root = client.get(f"/locations/{a}")
            loc_a = client.get(f"/locations/{shelf_a}")
            loc_b = client.get(f"/locations/{shelf_b}")
            cat_parent = client.get(f"/categories/{cat}")
            cat_sub = client.get(f"/categories/{sub}")
            listing = client.get("/locations")
            category_listing = client.get("/categories")
            missing_loc = client.get("/locations/999999")
            missing_cat = client.get("/categories/999999")
            invalid_page = client.get(f"/locations/{shelf_a}?page=0")
            edit = client.get(f"/locations/{shelf_a}/edit")
        assert all(r.status_code == 200 for r in (loc_root, loc_a, loc_b, cat_parent, cat_sub, edit))
        assert f'href="/locations/{shelf_a}"' in loc_root.text
        assert f'href="/locations/{a}">Room A</a>' in loc_a.text
        assert "Room A / Shelf" in loc_a.text
        assert "Room B / Shelf" in loc_b.text
        assert "First shelf" in loc_a.text
        assert f'href="/locations/{bin_a}"' in loc_a.text
        assert f'href="/items/{direct}"' in loc_a.text
        assert f'href="/items/{descendant}"' not in loc_a.text
        assert f'href="/items/{other}"' not in loc_a.text
        assert f'href="/categories/{sub}"' in cat_parent.text
        assert f'href="/categories/{cat}">Electronics</a>' in cat_sub.text
        assert f'href="/categories/{child}"' in cat_sub.text
        assert "Direct adapters" in cat_sub.text
        assert f'href="/items/{direct}"' in cat_sub.text
        assert f'href="/items/{descendant}"' not in cat_sub.text
        assert f'href="/locations/{shelf_a}"' in listing.text
        assert f'href="/categories/{sub}"' in category_listing.text
        assert missing_loc.status_code == 404
        assert missing_cat.status_code == 404
        assert invalid_page.status_code == 400
    finally:
        engine.dispose()


def test_tree_direct_items_are_paged_without_subtree_membership() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            category = inventory.create_category("Bulk")
            child = inventory.create_category("Child", parent_id=category.id)
            direct_ids = [
                inventory.create_item(f"Direct {index:02d}", category_id=category.id).id
                for index in range(51)
            ]
            descendant = inventory.create_item("Descendant", category_id=child.id)
            category_id, descendant_id = category.id, descendant.id
        with TestClient(app) as client:
            first = client.get(f"/categories/{category_id}")
            second = client.get(f"/categories/{category_id}?page=2")
        assert first.status_code == second.status_code == 200
        assert "Total: 51" in first.text
        assert len(re.findall(r'href="/items/\d+"', first.text)) == 50
        assert f'href="/categories/{category_id}?page=2"' in first.text
        assert len(re.findall(r'href="/items/\d+"', second.text)) == 1
        assert f'href="/items/{direct_ids[-1]}"' in second.text
        assert f'href="/items/{descendant_id}"' not in first.text + second.text
    finally:
        engine.dispose()
