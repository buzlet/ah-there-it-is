"""Deterministic inventory fixture for live model evaluation.

The fixture exists so prompt/model comparisons run against the same inventory
state instead of whatever happens to be in the user's live database.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ah_there_it_is.services.inventory import InventoryService


FIXTURE_VERSION = "inventory-fixture-v1"


@dataclass(frozen=True)
class FixtureIds:
    categories: dict[str, int]
    locations: dict[str, int]
    items: dict[str, int]


def seed_inventory_fixture(session: Session) -> FixtureIds:
    """Populate an empty database with a small realistic inventory graph."""

    inventory = InventoryService(session)

    categories: dict[str, int] = {}
    locations: dict[str, int] = {}
    items: dict[str, int] = {}

    electronics = inventory.create_category("Электроника")
    categories["electronics"] = electronics.id
    computers = inventory.create_category("Компьютеры", parent_id=electronics.id)
    categories["computers"] = computers.id
    components = inventory.create_category("Комплектующие", parent_id=computers.id)
    categories["components"] = components.id
    gpu = inventory.create_category("Видеокарты", parent_id=components.id)
    categories["gpu"] = gpu.id
    psu = inventory.create_category("Блоки питания", parent_id=components.id)
    categories["psu"] = psu.id
    adapters = inventory.create_category("Переходники", parent_id=electronics.id)
    categories["adapters"] = adapters.id
    cables = inventory.create_category("Кабели", parent_id=electronics.id)
    categories["cables"] = cables.id
    tools = inventory.create_category("Инструменты")
    categories["tools"] = tools.id
    measuring = inventory.create_category("Измерительные приборы", parent_id=tools.id)
    categories["measuring"] = measuring.id

    home = inventory.create_location("Квартира")
    locations["home"] = home.id
    study = inventory.create_location("Кабинет", parent_id=home.id)
    locations["study"] = study.id
    desk = inventory.create_location("Стол", parent_id=study.id)
    locations["desk"] = desk.id
    right_drawer = inventory.create_location("Правый ящик", parent_id=desk.id)
    locations["desk_right"] = right_drawer.id
    middle_drawer = inventory.create_location("Средний ящик", parent_id=desk.id)
    locations["desk_middle"] = middle_drawer.id
    study_cabinet = inventory.create_location("Шкаф", parent_id=study.id)
    locations["study_cabinet"] = study_cabinet.id
    study_shelf1 = inventory.create_location("Полка 1", parent_id=study_cabinet.id)
    locations["study_shelf1"] = study_shelf1.id

    balcony = inventory.create_location("Балкон", parent_id=home.id)
    locations["balcony"] = balcony.id
    rack = inventory.create_location("Стеллаж", parent_id=balcony.id)
    locations["rack"] = rack.id
    rack_shelf1 = inventory.create_location("Полка 1", parent_id=rack.id)
    locations["rack_shelf1"] = rack_shelf1.id
    rack_shelf2 = inventory.create_location("Полка 2", parent_id=rack.id)
    locations["rack_shelf2"] = rack_shelf2.id
    old_hw = inventory.create_location("Коробка старого железа", parent_id=rack_shelf2.id)
    locations["old_hw"] = old_hw.id
    balcony_cabinet = inventory.create_location("Шкаф", parent_id=balcony.id)
    locations["balcony_cabinet"] = balcony_cabinet.id

    item = inventory.create_item(
        "Gigabyte GTX 1070",
        description="Рабочая видеокарта, один вентилятор иногда шумит.",
        state="working",
        category_id=gpu.id,
        location_id=old_hw.id,
        attributes={"manufacturer": "Gigabyte", "model": "GTX 1070", "memory_gb": 8},
        aliases=["GTX 1070", "гигабайт 1070"],
        tags=["PCIe", "GPU", "computer"],
        original_text="fixture",
    )
    items["gtx1070"] = item.id

    item = inventory.create_item(
        "ASUS GTX 750 Ti",
        description="Старая рабочая видеокарта 2 GB.",
        state="used",
        category_id=gpu.id,
        location_id=rack_shelf1.id,
        attributes={"manufacturer": "ASUS", "model": "GTX 750 Ti", "memory_gb": 2},
        aliases=["GTX 750 Ti"],
        tags=["PCIe", "GPU"],
        original_text="fixture",
    )
    items["gtx750ti"] = item.id

    item = inventory.create_item(
        "Chieftec 750W PSU",
        description="Неисправный ATX блок питания; требуется проверить напряжения.",
        state="broken",
        category_id=psu.id,
        location_id=old_hw.id,
        attributes={"manufacturer": "Chieftec", "power_w": 750, "form_factor": "ATX"},
        aliases=["Chieftec 750W", "чифтек 750"],
        tags=["PSU", "12V", "repair"],
        original_text="fixture",
    )
    items["chieftec750"] = item.id

    item = inventory.create_item(
        "UNI-T UT61E+",
        description="Основной цифровой мультиметр.",
        state="working",
        category_id=measuring.id,
        location_id=study_cabinet.id,
        attributes={"manufacturer": "UNI-T", "model": "UT61E+"},
        aliases=["UNI-T", "основной мультиметр"],
        tags=["multimeter", "measurement"],
        original_text="fixture",
    )
    items["unit"] = item.id

    item = inventory.create_item(
        "DT-830B",
        description="Красный дешёвый мультиметр, щупы повреждены.",
        state="needs_test",
        category_id=measuring.id,
        location_id=balcony_cabinet.id,
        attributes={"model": "DT-830B", "color": "red"},
        aliases=["красный мультиметр", "дешёвый мультиметр"],
        tags=["multimeter", "repair"],
        original_text="fixture",
    )
    items["dt830b"] = item.id

    item = inventory.create_item(
        "ORICO USB 3.0 SATA adapter",
        description="Переходник для подключения SATA HDD/SSD по USB 3.0.",
        state="working",
        category_id=adapters.id,
        location_id=right_drawer.id,
        attributes={"manufacturer": "ORICO", "interface": "USB 3.0 to SATA"},
        aliases=["USB-SATA переходник", "переходник для SATA диска"],
        tags=["USB", "SATA", "HDD", "SSD"],
        original_text="fixture",
    )
    items["usb_sata"] = item.id

    item = inventory.create_item(
        "CH341A programmer",
        description="USB программатор SPI flash/BIOS, чёрная плата.",
        state="working",
        category_id=adapters.id,
        location_id=right_drawer.id,
        attributes={"model": "CH341A", "interface": "USB"},
        aliases=["CH341A", "программатор BIOS", "USB программатор"],
        tags=["BIOS", "SPI", "flash"],
        original_text="fixture",
    )
    items["ch341a"] = item.id

    item = inventory.create_item(
        "HDMI cable 2m",
        description="Обычные HDMI кабели длиной около двух метров.",
        state="used",
        category_id=cables.id,
        location_id=right_drawer.id,
        quantity=3,
        attributes={"length_m": 2, "connector": "HDMI"},
        aliases=["HDMI 2 метра"],
        tags=["HDMI", "cable"],
        original_text="fixture",
    )
    items["hdmi2m"] = item.id

    return FixtureIds(categories=categories, locations=locations, items=items)
