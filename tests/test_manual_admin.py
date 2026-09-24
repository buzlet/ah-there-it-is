# test_manual_admin.py
from __future__ import annotations

import re

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.domain.exceptions import DuplicateEntityError, EntityNotFoundError
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService
from tests.scale_fixture import build_target_scale_inventory
from tests.test_app import build_test_app


@pytest.mark.parametrize('kind', ['category', 'location'])
def test_tree_update_validates_before_mutation_and_preserves_stable_references(
    session: Session, kind: str
) -> None:
    inventory = InventoryService(session)
    create = getattr(inventory, f'create_{kind}')
    update = getattr(inventory, f'update_{kind}')
    root = create('Root')
    child = create('Child', parent_id=root.id)
    grandchild = create('Grandchild', parent_id=child.id)
    sibling = create('Sibling', parent_id=root.id)
    other = create('Other')
    item = inventory.create_item('Stable item', **{f'{kind}_id' if kind == 'category' else 'location_id': child.id})
    original_events = [(event.id, event.event_type, event.to_location_id) for event in inventory.get_item_history(item.id)]

    updated = update(child.id, name='Renamed', description='Updated note', parent_id=other.id)
    assert updated.id == child.id
    assert updated.description == 'Updated note'
    assert CatalogService.path(updated) == 'Other / Renamed'
    update(child.id, name='Renamed')
    assert child.parent_id == other.id
    assert child.description == 'Updated note'
    assert getattr(item, 'category_id' if kind == 'category' else 'current_location_id') == child.id

    update(child.id, description=None, parent_id=None)
    assert child.description is None
    assert CatalogService.path(child) == 'Renamed'
    update(child.id, parent_id=root.id)
    assert CatalogService.path(child) == 'Root / Renamed'

    before = (child.name, child.parent_id, child.description)
    with pytest.raises(DuplicateEntityError):
        update(child.id, name='Sibling', description='must not persist')
    with pytest.raises(EntityNotFoundError):
        update(child.id, name='Missing parent', parent_id=999)
    assert (child.name, child.parent_id, child.description) == before

    with pytest.raises(ValueError, match='cycle'):
        update(root.id, name='Bad root', parent_id=root.id)
    with pytest.raises(ValueError, match='cycle'):
        update(root.id, name='Bad root', parent_id=grandchild.id)
    assert root.name == 'Root'
    assert root.parent_id is None
    assert [(event.id, event.event_type, event.to_location_id) for event in inventory.get_item_history(item.id)] == original_events
    assert sibling.parent_id == root.id


def test_manual_item_create_edit_search_and_history() -> None:
    app, factory, engine = build_test_app()
    try:
        with TestClient(app) as client:
            category = client.post('/api/categories', json={'name': 'Electronics', 'description': 'Parts'}).json()
            location = client.post('/api/locations', json={'name': 'Bench'}).json()
            created = client.post('/api/items', json={
                'name': 'Manual Probe', 'description': 'phosphor canoe marker',
                'state': 'working', 'quantity': 3,
                'category_id': category['id'], 'location_id': location['id'],
                'attributes': {'serial': 'SERIAL-121'},
                'aliases': ['Comma, alias'], 'tags': ['bench, tools'],
            })
            assert created.status_code == 201
            item = created.json()
            item_id = item['id']
            assert item['category_path'] == 'Electronics'
            assert item['location_path'] == 'Bench'
            assert item['attributes'] == {'serial': 'SERIAL-121'}
            assert item['aliases'] == ['Comma, alias']
            assert item['tags'] == ['bench, tools']

            with factory() as session:
                search = SearchService(session)
                for query in ('Manual Probe', 'Comma, alias', 'bench, tools', 'SERIAL-121', 'phosphor canoe'):
                    assert any(result.id == item_id for result in search.search_items(query)), query

            cleared = client.patch(f'/api/items/{item_id}', json={
                'name': 'Manual Probe Revised', 'description': None, 'state': 'used',
                'quantity': 2, 'category_id': None,
                'attributes': {}, 'aliases': [], 'tags': [],
            })
            assert cleared.status_code == 200
            assert cleared.json()['category_id'] is None
            assert cleared.json()['location_id'] == location['id']
            taken = client.post(f'/api/items/{item_id}/take')
            assert taken.status_code == 200
            assert taken.json()['location_id'] is None
            assert taken.json()['location_status'] == 'in_use'
            assert cleared.json()['description'] is None
            assert cleared.json()['attributes'] == {}
            assert cleared.json()['aliases'] == []
            assert cleared.json()['tags'] == []

            replaced = client.patch(f'/api/items/{item_id}', json={
                'description': 'replacement description marker',
                'category_id': category['id'],
                'attributes': {'model': 'REPLACEMENT-777'},
                'aliases': ['Replacement, alias'], 'tags': ['replacement tag'],
            })
            assert replaced.status_code == 200
            assert replaced.json()['location_status'] == 'in_use'
            assert replaced.json()['category_path'] == 'Electronics'
            assert replaced.json()['aliases'] == ['Replacement, alias']
            assert replaced.json()['tags'] == ['replacement tag']
            moved = client.post(
                f'/api/items/{item_id}/move', json={'location_id': location['id']}
            )
            assert moved.status_code == 200
            assert moved.json()['location_path'] == 'Bench'
            assert client.patch(f'/api/items/{item_id}', json={
                'description': 'replacement description marker',
                'category_id': category['id'],
                'attributes': {'model': 'REPLACEMENT-777'},
                'aliases': ['Replacement, alias'], 'tags': ['replacement tag'],
            }).status_code == 200

        with factory() as session:
            inventory = InventoryService(session)
            events = inventory.get_item_history(item_id)
            assert [event.event_type for event in events] == [
                'item_created', 'item_updated', 'item_taken', 'item_updated', 'item_moved'
            ]
            assert [event.original_text for event in events] == [
                '[manual web create]', '[manual web edit]', '[manual web take]',
                '[manual web edit]', '[manual web move]'
            ]
            search = SearchService(session)
            for query in ('Manual Probe Revised', 'Replacement, alias', 'replacement tag',
                          'REPLACEMENT-777', 'replacement description'):
                assert any(result.id == item_id for result in search.search_items(query)), query
            assert not any(result.id == item_id for result in search.search_items('Comma, alias'))
    finally:
        engine.dispose()


def test_manual_api_errors_and_atomicity() -> None:
    app, factory, engine = build_test_app()
    try:
        with TestClient(app) as client:
            root = client.post('/api/categories', json={'name': 'Root'}).json()
            child = client.post('/api/categories', json={'name': 'Child', 'parent_id': root['id']}).json()
            first = client.post('/api/items', json={'name': 'First', 'category_id': root['id']}).json()
            second = client.post('/api/items', json={'name': 'Second', 'category_id': root['id']}).json()

            assert client.post('/api/items', json={'name': 'First', 'category_id': root['id']}).status_code == 400
            assert client.patch(f"/api/items/{second['id']}", json={'name': 'First', 'description': 'partial'}).status_code == 400
            assert client.patch(f"/api/items/{second['id']}", json={'description': 'partial', 'location_id': 999}).status_code == 422
            assert client.patch(f"/api/items/{second['id']}", json={'location_id': None}).status_code == 422
            assert client.post(f"/api/items/{second['id']}/move", json={'location_id': 999}).status_code == 404
            assert client.patch(f"/api/items/{second['id']}", json={'attributes': []}).status_code == 422
            assert client.post('/api/items', json={'name': 'Invalid', 'state': 'not-a-state'}).status_code == 422
            assert client.post('/api/items', json={'name': 'Invalid', 'quantity': 0}).status_code == 422
            assert client.post('/api/items', json={'name': 'Invalid', 'unknown': True}).status_code == 422
            assert client.post('/api/items', json={'name': 'Invalid', 'allow_duplicate': True}).status_code == 422
            assert client.post('/api/items', json={'name': 'Invalid', 'attributes': []}).status_code == 422
            assert client.patch('/api/items/999', json={'description': 'missing'}).status_code == 404
            assert client.post('/api/locations', json={'name': 'Missing', 'parent_id': 999}).status_code == 404
            assert client.post('/api/categories', json={'name': 'Root'}).status_code == 400
            loc = client.post('/api/locations', json={'name': 'Shelf'}).json()
            assert client.post('/api/locations', json={'name': 'Shelf'}).status_code == 400
            assert client.patch(f"/api/locations/{loc['id']}", json={'parent_id': loc['id']}).status_code == 400
            assert client.patch('/api/locations/999', json={'name': 'Missing'}).status_code == 404
            assert client.patch(f"/api/categories/{root['id']}", json={'name': 'Mutated', 'parent_id': child['id']}).status_code == 400
            assert client.patch(f"/api/categories/{root['id']}", json={'parent_id': root['id']}).status_code == 400
            assert client.patch('/api/categories/999', json={'name': 'Missing'}).status_code == 404
            assert client.patch(f"/api/categories/{root['id']}", json={'parent_id': 999}).status_code == 404
            assert client.patch(f"/api/categories/{root['id']}", json={'unknown': True}).status_code == 422
            assert client.patch(f"/api/categories/{root['id']}", json={'name': None}).status_code == 422
            assert client.get(f"/categories/{root['id']}/edit").status_code == 200

        with factory() as session:
            inventory = InventoryService(session)
            assert inventory.get_category(root['id']).name == 'Root'
            assert inventory.get_item(second['id']).description is None
            assert [event.event_type for event in inventory.get_item_history(second['id'])] == ['item_created']
            assert inventory.get_item(first['id']).name == 'First'
    finally:
        engine.dispose()


def test_intentional_duplicate_edit_and_identity_conflicts() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            category = inventory.create_category('Parts')
            first = inventory.create_item('Adapter', category_id=category.id)
            duplicate = inventory.create_item('Adapter', category_id=category.id, allow_duplicate=True)
            target = inventory.create_item('Different', category_id=category.id)
            ids = (category.id, first.id, duplicate.id, target.id)
        with TestClient(app) as client:
            category_id, first_id, duplicate_id, target_id = ids
            okay = client.patch(f'/api/items/{duplicate_id}', json={'description': 'safe correction'})
            assert okay.status_code == 200
            assert client.post('/api/items', json={'name': 'Adapter', 'category_id': category_id}).status_code == 400
            assert client.patch(f'/api/items/{target_id}', json={'name': 'Adapter'}).status_code == 400
            assert client.patch(f'/api/items/{duplicate_id}', json={'category_id': None}).status_code == 200
            assert client.patch(f'/api/items/{duplicate_id}', json={'category_id': category_id}).status_code == 400
        with factory() as session:
            assert InventoryService(session).get_item(duplicate_id).category_id is None
            assert InventoryService(session).get_item(first_id).category_id == category_id
    finally:
        engine.dispose()


def test_tree_api_paths_search_and_parent_choices() -> None:
    app, factory, engine = build_test_app()
    try:
        with TestClient(app) as client:
            cat_root = client.post('/api/categories', json={'name': 'Old category'}).json()
            cat_child = client.post('/api/categories', json={'name': 'Category child', 'parent_id': cat_root['id']}).json()
            cat_grand = client.post('/api/categories', json={'name': 'Category grand', 'parent_id': cat_child['id']}).json()
            cat_other = client.post('/api/categories', json={'name': 'Category other'}).json()
            loc_root = client.post('/api/locations', json={'name': 'Old location'}).json()
            loc_child = client.post('/api/locations', json={'name': 'Location child', 'parent_id': loc_root['id']}).json()
            loc_grand = client.post('/api/locations', json={'name': 'Location grand', 'parent_id': loc_child['id']}).json()
            loc_other = client.post('/api/locations', json={'name': 'Location other'}).json()
            item = client.post('/api/items', json={
                'name': 'Path probe', 'category_id': cat_child['id'], 'location_id': loc_child['id']
            }).json()

            cat_page = client.get(f"/categories/{cat_child['id']}/edit")
            loc_page = client.get(f"/locations/{loc_child['id']}/edit")
            for page, child, grand, other_path in (
                (cat_page, cat_child, cat_grand, 'Category other'),
                (loc_page, loc_child, loc_grand, 'Location other'),
            ):
                assert page.status_code == 200
                selector = re.search(r'<select name="parent_id">(.*?)</select>', page.text, re.S).group(1)
                assert '— root —' in selector
                assert f'value="{child["id"]}"' not in selector
                assert f'value="{grand["id"]}"' not in selector
                assert other_path in selector

            assert client.patch(f"/api/categories/{cat_root['id']}", json={'name': 'New category'}).status_code == 200
            assert client.patch(f"/api/locations/{loc_root['id']}", json={'name': 'New location'}).status_code == 200
            moved_cat = client.patch(f"/api/categories/{cat_child['id']}", json={'parent_id': cat_other['id']})
            moved_loc = client.patch(f"/api/locations/{loc_child['id']}", json={'parent_id': loc_other['id']})
            assert moved_cat.status_code == 200
            assert moved_loc.status_code == 200
            assert moved_cat.json()['path'] == 'Category other / Category child'
            assert moved_loc.json()['path'] == 'Location other / Location child'
            assert 'Category other / Category child' in client.get('/categories').text
            assert 'Location other / Location child' in client.get('/locations').text
            detail = client.get(f"/items/{item['id']}")
            assert 'Category other / Category child' in detail.text
            assert 'Location other / Location child' in detail.text

        with factory() as session:
            search = SearchService(session)
            assert search.search_categories('Category other Category child')[0].id == cat_child['id']
            assert search.search_locations('Location other Location child')[0].id == loc_child['id']
            found = search.search_items('Path probe')[0]
            assert found.category_path == 'Category other / Category child'
            assert found.location_path == 'Location other / Location child'
            assert [event.event_type for event in InventoryService(session).get_item_history(item['id'])] == ['item_created']
    finally:
        engine.dispose()


def test_manual_pages_expose_complete_forms() -> None:
    app, factory, engine = build_test_app()
    try:
        with TestClient(app) as client:
            category = client.post('/api/categories', json={'name': 'Root'}).json()
            location = client.post('/api/locations', json={'name': 'Shelf'}).json()
            item = client.post('/api/items', json={
                'name': 'Form probe', 'aliases': ['Alias, with comma'],
                'tags': ['Tag, with comma'], 'attributes': {'serial': 'A-1'},
                'category_id': category['id'], 'location_id': location['id'],
            }).json()
            items = client.get('/items')
            new = client.get('/items/new')
            detail = client.get(f"/items/{item['id']}")
            categories = client.get('/categories')
            locations = client.get('/locations')
        assert '/items/new' in items.text and 'Add item' in items.text
        assert new.status_code == 200 and '/static/item.js' in new.text
        for field in ('name', 'description', 'state', 'quantity', 'category_id', 'location_id',
                      'attributes', 'aliases', 'tags'):
            assert f'name="{field}"' in new.text
            assert f'name="{field}"' in detail.text
        assert 'Alias, with comma' in detail.text
        assert 'Tag, with comma' in detail.text
        assert '"serial"' in detail.text
        for page, kind in ((categories, 'categories'), (locations, 'locations')):
            assert page.status_code == 200
            assert f'data-kind="{kind}"' in page.text
            assert f'/{kind}/' in page.text and '/edit' in page.text
            assert '— root —' in page.text
            assert '/static/tree.js' in page.text
    finally:
        engine.dispose()


def test_browser_location_truth_actions_lifecycle_and_suggestions() -> None:
    app, factory, engine = build_test_app()
    try:
        with TestClient(app) as client:
            location = client.post('/api/locations', json={'name': 'Test shelf'}).json()
            created = client.post('/api/items', json={
                'name': 'Truth workflow item',
                'location_id': location['id'],
            })
            assert created.status_code == 201
            item_id = created.json()['id']
            assert created.json()['state'] == 'unknown'
            assert created.json()['location_status'] == 'known'

            known_page = client.get(f'/items/{item_id}')
            assert 'Condition/state unknown' in known_page.text
            assert f'href="/locations/{location["id"]}"' in known_page.text
            assert 'Location suggestions' not in known_page.text
            assert 'Choose a Location' in known_page.text
            assert 'unknown / taken' not in known_page.text

            taken = client.post(f'/api/items/{item_id}/take')
            assert taken.status_code == 200
            assert taken.json()['state'] == 'unknown'
            assert taken.json()['location_status'] == 'in_use'
            in_use_page = client.get(f'/items/{item_id}')
            assert 'In use / taken from storage' in in_use_page.text
            assert 'Location suggestions' not in in_use_page.text

            unknown = client.post(f'/api/items/{item_id}/location-unknown')
            assert unknown.status_code == 200
            assert unknown.json()['location_status'] == 'unknown'
            unknown_page = client.get(f'/items/{item_id}')
            assert 'Location unknown' in unknown_page.text
            assert 'inferences, not confirmed current locations' in unknown_page.text
            assert 'data-transition-kind="location-unknown"' in unknown_page.text
            assert client.post(f'/api/items/{item_id}/move', json={}).status_code == 422
            assert client.post(
                f'/api/items/{item_id}/move', json={'location_id': None}
            ).status_code == 422

            moved = client.post(
                f'/api/items/{item_id}/move',
                json={'location_id': location['id']},
            )
            assert moved.status_code == 200
            assert moved.json()['location_status'] == 'known'
            assert moved.json()['current_location_id'] == location['id']

            discarded = client.post(f'/api/items/{item_id}/discard')
            assert discarded.status_code == 200
            assert discarded.json()['state'] == 'discarded'
            assert discarded.json()['location_status'] == 'not_applicable'
            terminal_page = client.get(f'/items/{item_id}')
            assert 'Not applicable' in terminal_page.text
            assert 'Reactivate terminal Item' in terminal_page.text
            assert 'data-transition-kind="move"' not in terminal_page.text
            assert 'data-transition-kind="discard"' not in terminal_page.text
            assert 'Location suggestions' not in terminal_page.text
            assert client.post(f'/api/items/{item_id}/take').status_code == 400
            assert client.post(
                f'/api/items/{item_id}/move', json={'location_id': location['id']}
            ).status_code == 400

            assert client.post(
                f'/api/items/{item_id}/reactivate',
                json={'state': 'working'},
            ).status_code == 422
            assert client.post(
                f'/api/items/{item_id}/reactivate',
                json={'state': 'sold', 'location_id': location['id']},
            ).status_code == 422
            reactivated = client.post(
                f'/api/items/{item_id}/reactivate',
                json={'state': 'working', 'location_id': location['id']},
            )
            assert reactivated.status_code == 200
            assert reactivated.json()['state'] == 'working'
            assert reactivated.json()['location_status'] == 'known'
            sold = client.post(f'/api/items/{item_id}/sold')
            assert sold.status_code == 200
            assert sold.json()['state'] == 'sold'
            assert sold.json()['location_status'] == 'not_applicable'

            unknown_terminal = client.post('/api/items', json={'name': 'Unknown reactivation'})
            unknown_id = unknown_terminal.json()['id']
            assert client.post(f'/api/items/{unknown_id}/sold').status_code == 200
            reactivated_unknown = client.post(
                f'/api/items/{unknown_id}/reactivate',
                json={'state': 'unknown', 'location_id': None},
            )
            assert reactivated_unknown.status_code == 200
            assert reactivated_unknown.json()['state'] == 'unknown'
            assert reactivated_unknown.json()['location_status'] == 'unknown'

            terminal_search = client.get('/items', params={'q': 'Truth workflow item'})
            assert 'Truth workflow item' in terminal_search.text
            assert '>sold<' in terminal_search.text
            assert 'Not applicable' in terminal_search.text
            terminal_only = client.get('/items', params={'lifecycle': 'terminal'})
            assert 'Truth workflow item' in terminal_only.text
            default_catalog = client.get('/items')
            assert 'Truth workflow item' not in default_catalog.text
            unknown_filter = client.get('/items', params={
                'lifecycle': 'active', 'location_status': 'unknown',
            })
            assert 'Unknown reactivation' in unknown_filter.text
            assert 'Truth workflow item' not in unknown_filter.text

            activity = client.get('/activity')
            assert 'Item discarded' in activity.text
            assert 'Item sold' in activity.text
            history = client.get(f'/items/{item_id}')
            assert 'Location marked unknown' in history.text

        with factory() as session:
            history = InventoryService(session).get_item_history(item_id)
            assert [event.event_type for event in history] == [
                'item_created', 'item_taken', 'item_location_unknown', 'item_moved',
                'item_discarded', 'item_reactivated', 'item_sold',
            ]
            moved_event_id = next(
                event.id for event in history if event.event_type == 'item_moved'
            )
        with TestClient(app) as client:
            movement_detail = client.get(f'/activity/{moved_event_id}')
        assert movement_detail.status_code == 200
        assert 'Moved to a known Location' in movement_detail.text
        assert 'Historical path at event time' in movement_detail.text
        assert 'Test shelf' in movement_detail.text
    finally:
        engine.dispose()
