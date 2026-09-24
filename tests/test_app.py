from __future__ import annotations

from fastapi.testclient import TestClient

from ah_there_it_is.agent import HeuristicLLMClient, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.experiments import ExperimentRunner
from ah_there_it_is.app import create_app
from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import AgentRunLog, Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.conversations import ConversationService
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
        assert body["changes_applied"] is True
        assert body["receipts"][0]["operation"] == "create_item"
        assert body["receipts"][0]["changed"] is True
        assert len(body["receipts"][0]["event_ids"]) == 1

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
            assert run.mutation_receipts == body["receipts"]
            assert len(run.prompt_hash) == 64
            assert run.tool_trace
    finally:
        engine.dispose()


def test_chat_api_replays_completed_request_without_new_llm() -> None:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    calls = 0

    def counted_llm():
        nonlocal calls
        calls += 1
        return HeuristicLLMClient()

    app = create_app(
        Settings(app_name="Test Inventory"),
        session_factory=factory,
        llm_factory=counted_llm,
    )
    try:
        with factory() as session:
            inventory = InventoryService(session)
            desk = inventory.create_location("Стол")
            inventory.create_location("правый ящик", parent_id=desk.id)

        payload = {
            "message": "Положил USB тестер в правый ящик",
            "conversation_id": None,
            "request_key": "api-retry-key-0001",
        }
        with TestClient(app) as client:
            first = client.post("/api/chat", json=payload)
            second = client.post("/api/chat", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["replayed"] is False
        assert second.json()["replayed"] is True
        assert second.json()["run_id"] == first.json()["run_id"]
        assert second.json()["conversation_id"] == first.json()["conversation_id"]
        assert second.json()["changes_applied"] is True
        assert second.json()["receipts"] == first.json()["receipts"]
        assert calls == 1

        with factory() as session:
            items = [
                item
                for item in CatalogService(session).list_items()
                if item["name"] == "USB тестер"
            ]
            assert len(items) == 1
            assert len(InventoryService(session).get_item_history(items[0]["id"])) == 1
    finally:
        engine.dispose()


def test_chat_api_rejects_conflicting_request_key() -> None:
    app, _, engine = build_test_app()
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/chat",
                json={
                    "message": "Где CH341A?",
                    "request_key": "api-conflict-key-0001",
                },
            )
            conflict = client.post(
                "/api/chat",
                json={
                    "message": "Где GTX 1070?",
                    "request_key": "api-conflict-key-0001",
                },
            )

        assert first.status_code == 200
        assert conflict.status_code == 409
        assert "different chat content" in conflict.json()["detail"]
    finally:
        engine.dispose()


def test_chat_api_returns_425_for_processing_idempotency_key() -> None:
    from ah_there_it_is.db.models import ChatRequestRecord

    app, factory, engine = build_test_app()
    calls = 0

    def forbidden_llm():
        nonlocal calls
        calls += 1
        raise AssertionError("processing replay must not construct an LLM")

    app.state.llm_factory = forbidden_llm
    try:
        with factory() as session:
            session.add(
                ChatRequestRecord(
                    request_key="api-processing-key-0001",
                    requested_conversation_id=None,
                    message="same",
                    status="processing",
                )
            )
            session.commit()

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "message": "same",
                    "request_key": "api-processing-key-0001",
                },
            )

        assert response.status_code == 425
        assert "still processing" in response.json()["detail"]
        assert calls == 0
    finally:
        engine.dispose()


def test_chat_request_admin_api_and_page_show_recovery_audit() -> None:
    from ah_there_it_is.db.models import ChatRequestRecord

    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            source = ChatRequestRecord(
                request_key="admin-source-0001",
                requested_conversation_id=None,
                message="same",
                status="failed",
                error="provider failed",
            )
            session.add(source)
            session.commit()

        app.state.llm_factory = lambda: ScriptedLLMClient(
            [LLMResponse(content="Recovered safely after inspection.")]
        )
        with TestClient(app) as client:
            listing = client.get("/api/chat-requests")
            detail = client.get("/api/chat-requests/admin-source-0001")
            page = client.get("/chat-requests")
            recovered = client.post(
                "/api/chat-requests/admin-source-0001/recover",
                json={
                    "new_request_key": "admin-recovery-0001",
                    "note": "Operator verified the prior attempt did not commit.",
                    "acknowledge_duplicate_risk": True,
                },
            )
            new_detail = client.get("/api/chat-requests/admin-recovery-0001")

        assert listing.status_code == 200
        assert "Page 1" in listing.text
        assert listing.json()[0]["request_key"] == "admin-source-0001"
        assert detail.status_code == 200
        assert detail.json()["status"] == "failed"
        assert page.status_code == 200
        assert "Recovery warning" in page.text
        assert "admin-source-0001" in page.text
        assert "/static/chat_requests.js" in page.text

        assert recovered.status_code == 200
        body = recovered.json()
        assert body["source_request_key"] == "admin-source-0001"
        assert body["new_request_key"] == "admin-recovery-0001"
        assert body["replayed"] is False
        assert body["content"] == "Recovered safely after inspection."

        assert new_detail.status_code == 200
        new_body = new_detail.json()
        assert new_body["status"] == "completed"
        assert new_body["recovered_from_request_key"] == "admin-source-0001"
        assert new_body["recovery_note"] == (
            "Operator verified the prior attempt did not commit."
        )

        with factory() as session:
            source = session.query(ChatRequestRecord).filter_by(
                request_key="admin-source-0001"
            ).one()
            attempt = session.query(ChatRequestRecord).filter_by(
                request_key="admin-recovery-0001"
            ).one()
            assert source.status == "failed"
            assert attempt.recovered_from_id == source.id
    finally:
        engine.dispose()


def test_chat_request_recovery_requires_explicit_risk_acknowledgement() -> None:
    from ah_there_it_is.db.models import ChatRequestRecord

    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            session.add(
                ChatRequestRecord(
                    request_key="ack-source-0001",
                    requested_conversation_id=None,
                    message="same",
                    status="processing",
                )
            )
            session.commit()

        with TestClient(app) as client:
            response = client.post(
                "/api/chat-requests/ack-source-0001/recover",
                json={
                    "new_request_key": "ack-recovery-0001",
                    "note": "I inspected the request.",
                    "acknowledge_duplicate_risk": False,
                },
            )

        assert response.status_code == 422
        with factory() as session:
            assert (
                session.query(ChatRequestRecord)
                .filter_by(request_key="ack-recovery-0001")
                .one_or_none()
                is None
            )
    finally:
        engine.dispose()


def test_completed_chat_request_cannot_be_recovered_via_api() -> None:
    app, _, engine = build_test_app()
    try:
        with TestClient(app) as client:
            completed = client.post(
                "/api/chat",
                json={
                    "message": "Где CH341A?",
                    "request_key": "completed-admin-0001",
                },
            )
            recovery = client.post(
                "/api/chat-requests/completed-admin-0001/recover",
                json={
                    "new_request_key": "completed-admin-recovery-0001",
                    "note": "Should replay instead.",
                    "acknowledge_duplicate_risk": True,
                },
            )

        assert completed.status_code == 200
        assert recovery.status_code == 409
        assert "must be replayed" in recovery.json()["detail"]
    finally:
        engine.dispose()


def test_browser_keeps_blocked_request_key_for_manual_recovery() -> None:
    app, _, engine = build_test_app()
    try:
        with TestClient(app) as client:
            script = client.get("/static/chat.js")
        assert script.status_code == 200
        assert "response.status === 425 || response.status === 409" in script.text
        assert "Inspect Requests before creating a new attempt." in script.text
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
        assert restored.json()["limit"] == 50
        assert restored.json()["has_older"] is False
        assistant = restored.json()["messages"][-1]
        assert assistant["run_id"] == first["run_id"]
        assert assistant["rating"] == 5
        assert assistant["comment"] == "точно"
        assert second.status_code == 200
        assert second.json()["conversation_id"] == first["conversation_id"]
    finally:
        engine.dispose()


def test_conversation_api_pages_history_and_browser_exposes_load_older() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            conversations = ConversationService(session)
            conversation_id = conversations.create().id
            for index in range(105):
                conversations.add_message(
                    conversation_id,
                    "assistant" if index % 2 else "user",
                    f"history-{index:03d}",
                )
        with TestClient(app) as client:
            latest = client.get(f"/api/conversations/{conversation_id}?limit=50")
            cursor = latest.json()["next_before_id"]
            older = client.get(
                f"/api/conversations/{conversation_id}?limit=50&before_id={cursor}"
            )
            invalid_limit = client.get(f"/api/conversations/{conversation_id}?limit=101")
            invalid_cursor = client.get(f"/api/conversations/{conversation_id}?before_id=0")
            missing_cursor = client.get(
                f"/api/conversations/{conversation_id}?before_id=999999"
            )
            page = client.get("/")
            script = client.get("/static/chat.js")

        assert latest.status_code == 200 and latest.json()["has_older"] is True
        assert len(latest.json()["messages"]) == 50
        assert len(older.json()["messages"]) == 50
        assert not (
            {row["id"] for row in latest.json()["messages"]}
            & {row["id"] for row in older.json()["messages"]}
        )
        assert invalid_limit.status_code == 400
        assert invalid_cursor.status_code == 400
        assert missing_cursor.status_code == 400
        assert 'id="load-older"' in page.text
        assert "before_id=${nextBeforeId}" in script.text
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
                },
            )
            taken = client.post(f"/api/items/{item_id}/take")

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
        assert edited.json()["location_id"] == shelf.id
        assert taken.status_code == 200
        assert taken.json()["location_id"] is None
        assert taken.json()["location_status"] == "in_use"

        with factory() as session:
            history = InventoryService(session).get_item_history(item_id)
            assert [event.event_type for event in history][-2:] == [
                "item_updated",
                "item_taken",
            ]
            assert history[-1].original_text == "[manual web take]"
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
        assert "Page 1" in summary.text
    finally:
        engine.dispose()


def test_evaluation_page_navigation_and_validation() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            conversation_id = ConversationService(session).create().id
            session.add_all(
                AgentRunLog(
                    conversation_id=conversation_id,
                    prompt_version="page-v1",
                    prompt_hash="b" * 64,
                    system_prompt="page",
                    llm_provider="test",
                    llm_model="page",
                    llm_config={},
                    input_messages=[],
                    tool_trace=[],
                    mutation_receipts=[],
                    final_content=f"response-{index}",
                    rounds=1,
                    status="completed",
                )
                for index in range(55)
            )
            session.commit()
        with TestClient(app) as client:
            first = client.get("/evaluations?page=1&page_size=50")
            second = client.get("/evaluations?page=2&page_size=50")
            invalid = client.get("/evaluations?page_size=101")
        assert first.status_code == 200 and "Next" in first.text
        assert second.status_code == 200 and "Previous" in second.text
        assert "response-0" in second.text
        assert invalid.status_code == 400
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


def test_experiment_pages_show_side_by_side_and_accept_review() -> None:
    app, factory, engine = build_test_app()
    try:
        with factory() as session:
            inventory = InventoryService(session)
            balcony = inventory.create_location("Балкон")
            inventory.create_item("CH341A", location_id=balcony.id)
            source_result = AgentRunner(
                session,
                ScriptedLLMClient(
                    [
                        LLMResponse(tool_calls=(ToolCall(id="1", name="search_items", arguments={"query": "CH341A"}),)),
                        LLMResponse(content="На балконе."),
                    ]
                ),
            ).run("Где CH341A?")
            EvaluationService(session).set_feedback(source_result.run_id, rating=4)
            source = EvaluationService(session).get_run(source_result.run_id)
            experiment = ExperimentRunner(
                session,
                ScriptedLLMClient(
                    [
                        LLMResponse(tool_calls=(ToolCall(id="2", name="search_items", arguments={"query": "CH341A"}),)),
                        LLMResponse(content="CH341A: Балкон."),
                    ]
                ),
            ).run(
                source,
                experiment_name="strict-v2",
                system_prompt="variant prompt",
                prompt_version="v2",
            )

        with TestClient(app) as client:
            listing = client.get("/experiments")
            detail = client.get(f"/experiments/{experiment.experiment_run_id}")
            review = client.post(
                f"/api/experiments/{experiment.experiment_run_id}/review",
                json={"choice": "variant", "variant_rating": 5, "comment": "лучше"},
            )

        assert listing.status_code == 200
        assert "strict-v2" in listing.text
        assert detail.status_code == 200
        assert "Baseline" in detail.text and "Variant" in detail.text
        assert review.status_code == 200
        assert review.json()["choice"] == "variant"
        assert review.json()["variant_rating"] == 5
    finally:
        engine.dispose()
