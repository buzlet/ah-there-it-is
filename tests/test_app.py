from __future__ import annotations

from fastapi.testclient import TestClient

from ah_there_it_is.agent import HeuristicLLMClient
from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.inventory import InventoryService


def build_test_app():
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    app = create_app(
        Settings(app_name="Test Inventory"),
        session_factory=factory,
        llm_factory=HeuristicLLMClient,
    )
    return app, factory, engine


def test_health() -> None:
    app, _, engine = build_test_app()
    try:
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "app": "Test Inventory",
            "llm_provider": "heuristic",
        }
    finally:
        engine.dispose()


def test_index_renders_usable_chat_shell() -> None:
    app, _, engine = build_test_app()
    try:
        with TestClient(app) as client:
            response = client.get("/")
        assert response.status_code == 200
        assert "Test Inventory" in response.text
        assert "Inventory chat" in response.text
        assert "/static/chat.js" in response.text
    finally:
        engine.dispose()


def test_chat_api_mutates_inventory_and_persists_evaluation_log() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            desk = inventory.create_location("Стол")
            drawer = inventory.create_location("правый ящик", parent_id=desk.id)
            drawer_id = drawer.id

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={"message": "Положил USB тестер в правый ящик"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["conversation_id"] > 0
        assert body["run_id"] > 0
        assert "Стол / правый ящик" in body["content"]

        with factory() as session:
            item = next(
                item for item in CatalogService(session).list_items() if item["name"] == "USB тестер"
            )
            assert item["location_id"] == drawer_id
            run = EvaluationService(session).get_run(body["run_id"])
            assert run.status == "completed"
            assert run.llm_provider == "offline"
            assert run.llm_model == "heuristic-v1"
            assert run.prompt_version == "inventory-v1"
            assert len(run.prompt_hash) == 64
            assert run.tool_trace
    finally:
        engine.dispose()


def test_conversation_can_continue_and_be_restored_with_rating() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            inventory.create_location("Балкон")
            inventory.create_item("CH341A", location_id=1)

        with TestClient(app) as client:
            first = client.post("/api/chat", json={"message": "Где CH341A?"}).json()
            feedback = client.post(
                f"/api/runs/{first['run_id']}/feedback",
                json={"rating": 5, "comment": "точно"},
            )
            restored = client.get(f"/api/conversations/{first['conversation_id']}")
            second = client.post(
                "/api/chat",
                json={
                    "message": "Где CH341A?",
                    "conversation_id": first["conversation_id"],
                },
            )

        assert feedback.status_code == 200
        assert feedback.json()["rating"] == 5
        assert restored.status_code == 200
        assistant = restored.json()["messages"][-1]
        assert assistant["run_id"] == first["run_id"]
        assert assistant["rating"] == 5
        assert assistant["comment"] == "точно"
        assert second.status_code == 200
        assert second.json()["conversation_id"] == first["conversation_id"]
    finally:
        engine.dispose()


def test_inventory_views_and_manual_correction_use_service_layer() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            shelf = inventory.create_location("Полка")
            category = inventory.create_category("Измерительные приборы")
            item = inventory.create_item(
                "DT-830B",
                description="старое описание",
                location_id=shelf.id,
                category_id=category.id,
            )
            item_id = item.id

        with TestClient(app) as client:
            items_page = client.get("/items")
            detail_page = client.get(f"/items/{item_id}")
            locations_page = client.get("/locations")
            categories_page = client.get("/categories")
            edited = client.patch(
                f"/api/items/{item_id}",
                json={
                    "description": "исправленное описание",
                    "state": "working",
                    "quantity": 2,
                    "location_id": None,
                },
            )

        assert all(
            response.status_code == 200
            for response in (items_page, detail_page, locations_page, categories_page)
        )
        assert "DT-830B" in items_page.text
        assert "старое описание" in detail_page.text
        assert edited.status_code == 200
        assert edited.json()["description"] == "исправленное описание"
        assert edited.json()["state"] == "working"
        assert edited.json()["quantity"] == 2
        assert edited.json()["location_id"] is None

        with factory() as session:
            history = InventoryService(session).get_item_history(item_id)
            assert [event.event_type for event in history][-2:] == [
                "item_updated",
                "item_taken",
            ]
            assert history[-1].original_text == "[manual web edit]"
    finally:
        engine.dispose()


def test_evaluation_pages_show_variant_summary_and_trace() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            inventory.create_location("Балкон")
            inventory.create_item("CH341A", location_id=1)

        with TestClient(app) as client:
            run = client.post("/api/chat", json={"message": "Где CH341A?"}).json()
            client.post(f"/api/runs/{run['run_id']}/feedback", json={"rating": 4})
            summary = client.get("/evaluations")
            detail = client.get(f"/evaluations/{run['run_id']}")

        assert summary.status_code == 200
        assert "inventory-v1" in summary.text
        assert "4.00" in summary.text
        assert detail.status_code == 200
        assert "Tool trace" in detail.text
        assert "search_items" in detail.text
    finally:
        engine.dispose()


def test_prompt_file_is_loaded_as_exact_experiment_prompt(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("experimental prompt\n", encoding="utf-8")
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    try:
        app = create_app(
            Settings(
                app_name="Test Inventory",
                prompt_version="exp-2",
                prompt_file=str(prompt),
            ),
            session_factory=factory,
            llm_factory=HeuristicLLMClient,
        )
        assert app.state.system_prompt == "experimental prompt\n"
    finally:
        engine.dispose()
