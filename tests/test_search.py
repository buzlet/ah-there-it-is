from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from ah_there_it_is.domain.names import normalize_name, normalize_search_text
from ah_there_it_is.services import InventoryService, SearchService


def test_search_normalization_does_not_change_identity_normalization() -> None:
    assert normalize_name("USB-SATA") == "usb-sata"
    assert normalize_name("USB/SATA") == "usb/sata"
    assert normalize_search_text(" USB-SATA / adapter ") == "usb sata adapter"


def test_exact_name_and_alias_outrank_fts(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    category = inventory.create_category("Комплектующие")
    exact = inventory.create_item(
        "Chieftec 750W",
        category_id=category.id,
        description="Старый компьютерный блок питания",
    )
    alias = inventory.create_item(
        "Chieftec GPS-750C",
        category_id=category.id,
        aliases=["Chieftec PSU"],
        allow_duplicate=True,
    )
    inventory.create_item(
        "Seasonic 650W",
        category_id=category.id,
        description="Похожий Chieftec блок питания лежал рядом",
    )

    exact_results = search.search_items("chieftec 750w")
    assert exact_results[0].id == exact.id
    assert exact_results[0].match_type == "exact_name"

    alias_results = search.search_items("Chieftec PSU")
    assert alias_results[0].id == alias.id
    assert alias_results[0].match_type == "exact_alias"
    assert alias_results[0].score > next(
        result.score for result in alias_results if result.match_type == "fts"
    )


def test_search_name_separator_variants_without_merging_identity(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    item = inventory.create_item("USB-SATA adapter")

    results = search.search_items("usb/sata adapter")

    assert results[0].id == item.id
    assert results[0].match_type == "normalized_name"


def test_item_search_uses_attributes_description_tags_and_updates_fts(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    item = inventory.create_item(
        "Gigabyte video card",
        description="Запасная видеокарта для старого компьютера",
        attributes={"model": "GV-N75TOC-2GI", "chip": "GTX 750 Ti"},
        tags=["PCIe", "NVIDIA"],
    )

    model_results = search.search_items("GV-N75TOC-2GI")
    assert model_results[0].id == item.id
    assert model_results[0].match_type == "exact_attribute"

    assert search.search_items("запасная")[0].id == item.id
    assert search.search_items("nvidia")[0].id == item.id

    inventory.update_item(
        item.id,
        description="Рабочая карта; средний вентилятор иногда шумит",
        aliases=["старая GTX"],
        tags=["PCIe", "graphics"],
    )

    assert search.search_items("вентилятор")[0].id == item.id
    assert search.search_items("старая GTX")[0].match_type == "exact_alias"
    assert search.search_items("graphics")[0].id == item.id
    assert search.search_items("nvidia") == []


def test_duplicate_location_leaf_names_are_returned_with_paths(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    desk = inventory.create_location("Стол")
    cabinet = inventory.create_location("Шкаф")
    desk_drawer = inventory.create_location("Ящик", parent_id=desk.id)
    cabinet_drawer = inventory.create_location("Ящик", parent_id=cabinet.id)

    results = search.search_locations("ящик")

    assert [result.id for result in results] == [desk_drawer.id, cabinet_drawer.id]
    assert {result.path for result in results} == {"Стол / Ящик", "Шкаф / Ящик"}
    assert all(result.match_type == "exact_name" for result in results)


def test_tree_search_can_use_ancestry_to_disambiguate(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    balcony = inventory.create_location("Балкон")
    office = inventory.create_location("Кабинет")
    balcony_shelf = inventory.create_location("Полка 2", parent_id=balcony.id)
    inventory.create_location("Полка 2", parent_id=office.id)

    results = search.search_locations("балкон полка 2")

    assert len(results) == 1
    assert results[0].id == balcony_shelf.id
    assert results[0].path == "Балкон / Полка 2"


def test_tree_search_exact_path_outranks_descendant_with_same_ancestry(
    session: Session,
) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)

    home = inventory.create_location("Квартира")
    office = inventory.create_location("Кабинет", parent_id=home.id)
    cabinet = inventory.create_location("Шкаф", parent_id=office.id)
    inventory.create_location("Полка 1", parent_id=cabinet.id)

    balcony = inventory.create_location("Балкон", parent_id=home.id)
    inventory.create_location("Шкаф", parent_id=balcony.id)

    results = search.search_locations("Кабинет Шкаф")

    assert results[0].id == cabinet.id
    assert results[0].path == "Квартира / Кабинет / Шкаф"
    assert results[0].match_type == "exact_path"
    assert results[0].score == SearchService.EXACT_PATH
    assert len(results) >= 2
    assert results[0].score - results[1].score >= 50


def test_tree_search_prefers_specific_leaf_inside_natural_phrase(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    home = inventory.create_location("Квартира")
    office = inventory.create_location("Кабинет", parent_id=home.id)
    desk = inventory.create_location("Стол", parent_id=office.id)
    middle = inventory.create_location("Средний ящик", parent_id=desk.id)

    results = search.search_locations("средний ящик стола")

    assert results[0].id == middle.id
    assert results[0].path == "Квартира / Кабинет / Стол / Средний ящик"
    assert results[0].score - results[1].score >= 50


def test_category_candidates_include_full_path(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    computers = inventory.create_category("Компьютеры")
    electronics = inventory.create_category("Электроника")
    pc_adapters = inventory.create_category("Переходники", parent_id=computers.id)
    inventory.create_category("Переходники", parent_id=electronics.id)

    results = search.search_categories("компьютеры переходники")

    assert len(results) == 1
    assert results[0].id == pc_adapters.id
    assert results[0].path == "Компьютеры / Переходники"


def test_tags_are_searchable_by_stable_id(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    inventory.create_item("Cable", tags=["USB-C", "spare"])

    result = search.search_tags("usb-c")[0]

    assert result.entity_type == "tag"
    assert result.name == "USB-C"
    assert isinstance(result.id, int)


def test_item_candidates_expose_context_ids_and_paths(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    balcony = inventory.create_location("Балкон")
    box = inventory.create_location("Старое железо", parent_id=balcony.id)
    computers = inventory.create_category("Компьютеры")
    gpu = inventory.create_category("Видеокарты", parent_id=computers.id)
    item = inventory.create_item("ASUS GTX 1070", category_id=gpu.id, location_id=box.id)

    result = search.search_items("GTX 1070")[0]

    assert result.id == item.id
    assert result.location_id == box.id
    assert result.location_path == "Балкон / Старое железо"
    assert result.category_id == gpu.id
    assert result.category_path == "Компьютеры / Видеокарты"


def test_fts_table_is_trigger_maintained(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item(
        "DT-830B", description="Красный мультиметр", aliases=["cheap meter"], tags=["repair"]
    )

    row = session.execute(
        text(
            "SELECT name, aliases, description, tags FROM item_search_fts WHERE rowid=:id"
        ),
        {"id": item.id},
    ).one()
    assert row.name == "DT-830B"
    assert "cheap meter" in row.aliases
    assert "Красный мультиметр" in row.description
    assert "repair" in row.tags


def test_long_fts_query_filters_single_token_noise(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    target = inventory.create_item("Gigabyte GTX 1070")
    inventory.create_item("ASUS GTX 750 Ti")
    inventory.create_item("USB programmer", description="USB device for BIOS")

    results = search.search_items("GeForce GTX 1070")
    assert [result.id for result in results] == [target.id]

    assert search.search_items("USB-C hub Anker 7-в-1") == []


def test_search_handles_fts_operator_punctuation_as_plain_text(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    item = inventory.create_item("USB-C adapter", description="adapter for test bench")

    results = search.search_items('USB-C OR "adapter"*')

    assert any(result.id == item.id for result in results)


def test_search_limit_and_tie_order_are_deterministic(session: Session) -> None:
    inventory = InventoryService(session)
    search = SearchService(session)
    category = inventory.create_category("Кабели")
    first = inventory.create_item("HDMI cable", category_id=category.id)
    second = inventory.create_item(
        "HDMI cable", category_id=category.id, allow_duplicate=True
    )
    inventory.create_item("HDMI cable", category_id=category.id, allow_duplicate=True)

    results = search.search_items("HDMI cable", limit=2)

    assert [result.id for result in results] == [first.id, second.id]
    assert all(result.match_type == "exact_name" for result in results)
