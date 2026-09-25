"""HTTP API and HTML routes for the first usable web MVP."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.agent.errors import AgentTurnFailedError
from ah_there_it_is.db.models import ItemMedia
from ah_there_it_is.domain.exceptions import EntityNotFoundError, InventoryError
from ah_there_it_is.services.activity import ActivityService
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.chat_requests import (
    ChatRequestNotFoundError,
    ChatRequestService,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyPreviousFailureError,
    IdempotencyRecoveryNotAllowedError,
)
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.experiments import ExperimentService
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.location_suggestions import LocationSuggestionService
from ah_there_it_is.web.dependencies import get_session
from ah_there_it_is.web.schemas import (
    ChatRequest,
    ChatRequestRecordResponse,
    ChatRequestRecoveryRequest,
    ChatRequestRecoveryResponse,
    ChatResponse,
    ConversationMessageResponse,
    ConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    ExperimentReviewRequest,
    ExperimentReviewResponse,
    ItemCreateRequest,
    ItemEditRequest,
    ItemMoveRequest,
    ItemMediaAttachRequest,
    ItemMediaResponse,
    ItemMediaUpdateRequest,
    ItemQuantityChangeRequest,
    ItemRemoveRequest,
    ItemRestoreRequest,
    ItemTakeRequest,
    ItemResponse,
    TreeCreateRequest,
    TreeEditRequest,
    TreeResponse,
)


_T = TypeVar("_T")


def _manual_mutation(session: Session, action: Callable[[], _T]) -> _T:
    """One HTTP request owns one inventory transaction, including movement."""
    try:
        result = action()
        session.commit()
        return result
    except EntityNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InventoryError, ValueError, IntegrityError) as exc:
        session.rollback()
        detail = "inventory identity conflict" if isinstance(exc, IntegrityError) else str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc


def _tree_response(node) -> TreeResponse:
    return TreeResponse(
        id=node.id,
        name=node.name,
        description=node.description,
        parent_id=node.parent_id,
        path=CatalogService.path(node),
    )


def _media_response(media: ItemMedia) -> ItemMediaResponse:
    return ItemMediaResponse(
        id=media.id,
        item_id=media.item_id,
        provider=media.provider,
        media_reference=media.media_reference,
        caption=media.caption,
        position=media.position,
        created_at=media.created_at,
        updated_at=media.updated_at,
    )


def _parent_choices(rows: list[dict], edited_id: int) -> list[dict]:
    by_id = {row["id"]: row for row in rows}
    choices = []
    for row in rows:
        current = row["id"]
        seen: set[int] = set()
        while current is not None and current in by_id and current not in seen:
            if current == edited_id:
                break
            seen.add(current)
            current = by_id[current]["parent_id"]
        else:
            choices.append(row)
    return choices


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"app_name": request.app.state.settings.app_name},
        )

    @router.post("/api/chat", response_model=ChatResponse)
    def chat(
        payload: ChatRequest,
        request: Request,
        session: Session = Depends(get_session),
    ) -> ChatResponse:
        settings = request.app.state.settings

        def execute_agent(commit_on_success: bool):
            llm = request.app.state.llm_factory()
            try:
                return AgentRunner(
                    session,
                    llm,
                    max_rounds=settings.agent_max_rounds,
                    system_prompt=request.app.state.system_prompt,
                    prompt_version=settings.prompt_version,
                ).run(
                    payload.message,
                    conversation_id=payload.conversation_id,
                    commit_on_success=commit_on_success,
                )
            finally:
                close = getattr(llm, "close", None)
                if callable(close):
                    close()

        try:
            execution = ChatRequestService(session).execute(
                request_key=payload.request_key,
                message=payload.message,
                conversation_id=payload.conversation_id,
                operation=execute_agent,
            )
        except IdempotencyInProgressError as exc:
            raise HTTPException(status_code=425, detail=str(exc)) from exc
        except (
            IdempotencyConflictError,
            IdempotencyPreviousFailureError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InventoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AgentTurnFailedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        result = execution.result
        return ChatResponse(
            conversation_id=result.conversation_id,
            run_id=result.run_id,
            content=result.content,
            rounds=result.rounds,
            replayed=execution.replayed,
            changes_applied=result.changes_applied,
            receipts=list(result.receipts),
        )

    def chat_request_response(
        record,
        session: Session,
    ) -> ChatRequestRecordResponse:
        recovered_from = (
            session.get(type(record), record.recovered_from_id)
            if record.recovered_from_id is not None
            else None
        )
        return ChatRequestRecordResponse(
            id=record.id,
            request_key=record.request_key,
            requested_conversation_id=record.requested_conversation_id,
            message=record.message,
            status=record.status,
            agent_run_id=record.agent_run_id,
            error=record.error,
            recovered_from_id=record.recovered_from_id,
            recovered_from_request_key=(
                recovered_from.request_key if recovered_from is not None else None
            ),
            recovery_note=record.recovery_note,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def chat_request_projection_response(record) -> ChatRequestRecordResponse:
        return ChatRequestRecordResponse(
            id=record.id,
            request_key=record.request_key,
            requested_conversation_id=record.requested_conversation_id,
            message=record.message,
            status=record.status,
            agent_run_id=record.agent_run_id,
            error=record.error,
            recovered_from_id=record.recovered_from_id,
            recovered_from_request_key=record.recovered_from_request_key,
            recovery_note=record.recovery_note,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @router.get(
        "/api/chat-requests",
        response_model=list[ChatRequestRecordResponse],
    )
    def chat_requests_api(
        limit: int = 100,
        session: Session = Depends(get_session),
    ) -> list[ChatRequestRecordResponse]:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
        service = ChatRequestService(session)
        return [
            chat_request_projection_response(record)
            for record in service.recent_projection(limit=limit)
        ]

    @router.get(
        "/api/chat-requests/{request_key}",
        response_model=ChatRequestRecordResponse,
    )
    def chat_request_api(
        request_key: str,
        session: Session = Depends(get_session),
    ) -> ChatRequestRecordResponse:
        record = ChatRequestService(session).get(request_key)
        if record is None:
            raise HTTPException(status_code=404, detail="chat request not found")
        return chat_request_response(record, session)

    @router.get("/chat-requests", response_class=HTMLResponse)
    def chat_requests_page(
        request: Request,
        page: int = 1,
        page_size: int = ChatRequestService.DEFAULT_PAGE_SIZE,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        service = ChatRequestService(session)
        try:
            request_page = service.page(page=page, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def page_url(target_page: int) -> str:
            return f"/chat-requests?{urlencode({'page': target_page, 'page_size': request_page.page_size})}"

        return templates.TemplateResponse(
            request=request,
            name="chat_requests.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "records": request_page.records,
                "request_page": request_page,
                "previous_url": page_url(request_page.page - 1),
                "next_url": page_url(request_page.page + 1),
            },
        )

    @router.post(
        "/api/chat-requests/{source_request_key}/recover",
        response_model=ChatRequestRecoveryResponse,
    )
    def recover_chat_request(
        source_request_key: str,
        payload: ChatRequestRecoveryRequest,
        request: Request,
        session: Session = Depends(get_session),
    ) -> ChatRequestRecoveryResponse:
        service = ChatRequestService(session)
        source = service.get(source_request_key)
        if source is None:
            raise HTTPException(status_code=404, detail="chat request not found")
        settings = request.app.state.settings

        def execute_agent(commit_on_success: bool):
            llm = request.app.state.llm_factory()
            try:
                return AgentRunner(
                    session,
                    llm,
                    max_rounds=settings.agent_max_rounds,
                    system_prompt=request.app.state.system_prompt,
                    prompt_version=settings.prompt_version,
                ).run(
                    source.message,
                    conversation_id=source.requested_conversation_id,
                    commit_on_success=commit_on_success,
                )
            finally:
                close = getattr(llm, "close", None)
                if callable(close):
                    close()

        try:
            execution = service.recover(
                source_request_key=source_request_key,
                new_request_key=payload.new_request_key,
                recovery_note=payload.note,
                operation=execute_agent,
            )
        except ChatRequestNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except IdempotencyInProgressError as exc:
            raise HTTPException(status_code=425, detail=str(exc)) from exc
        except (
            IdempotencyConflictError,
            IdempotencyPreviousFailureError,
            IdempotencyRecoveryNotAllowedError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AgentTurnFailedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        result = execution.result
        return ChatRequestRecoveryResponse(
            source_request_key=source_request_key,
            new_request_key=payload.new_request_key,
            conversation_id=result.conversation_id,
            run_id=result.run_id,
            content=result.content,
            rounds=result.rounds,
            replayed=execution.replayed,
            changes_applied=result.changes_applied,
            receipts=list(result.receipts),
        )

    @router.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
    def conversation(
        conversation_id: int,
        limit: int = ConversationService.DEFAULT_MESSAGE_WINDOW_LIMIT,
        before_id: int | None = None,
        session: Session = Depends(get_session),
    ) -> ConversationResponse:
        conversations = ConversationService(session)
        evaluations = EvaluationService(session)
        try:
            window = conversations.message_window(
                conversation_id, limit=limit, before_id=before_id
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        assistant_message_ids = [
            message.id for message in window.messages if message.role == "assistant"
        ]
        runs = evaluations.runs_for_assistant_messages(assistant_message_ids)
        by_assistant_message = {
            run.assistant_message_id: run
            for run in runs
            if run.assistant_message_id is not None
        }
        return ConversationResponse(
            id=conversation_id,
            messages=[
                ConversationMessageResponse(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    run_id=(run.id if (run := by_assistant_message.get(message.id)) else None),
                    rating=(run.feedback.rating if run and run.feedback else None),
                    comment=(run.feedback.comment if run and run.feedback else None),
                )
                for message in window.messages
            ],
            limit=window.limit,
            before_id=before_id,
            has_older=window.has_older,
            next_before_id=window.next_before_id,
        )

    @router.post("/api/runs/{run_id}/feedback", response_model=FeedbackResponse)
    def feedback(
        run_id: int,
        payload: FeedbackRequest,
        session: Session = Depends(get_session),
    ) -> FeedbackResponse:
        service = EvaluationService(session)
        try:
            result = service.set_feedback(
                run_id,
                rating=payload.rating,
                comment=payload.comment,
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FeedbackResponse(
            run_id=run_id,
            rating=result.rating,
            comment=result.comment,
        )

    @router.get("/activity", response_class=HTMLResponse)
    def activity(
        request: Request,
        event_type: str | None = None,
        item_id: int | None = None,
        page: int = 1,
        page_size: int = ActivityService.DEFAULT_PAGE_SIZE,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        selected_type = event_type if event_type != "" else None
        service = ActivityService(session)
        try:
            activity_page = service.page(
                page=page,
                page_size=page_size,
                event_type=selected_type,
                item_id=item_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def page_url(target_page: int) -> str:
            params = {"page": target_page, "page_size": activity_page.page_size}
            if selected_type is not None:
                params["event_type"] = selected_type
            if item_id is not None:
                params["item_id"] = item_id
            return "/activity?" + urlencode(params)

        return templates.TemplateResponse(
            request=request,
            name="activity.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "activity_page": activity_page,
                "event_type": selected_type or "",
                "item_id": item_id,
                "has_filters": selected_type is not None or item_id is not None,
                "previous_url": (
                    page_url(activity_page.previous_page)
                    if activity_page.previous_page is not None else None
                ),
                "next_url": (
                    page_url(activity_page.next_page)
                    if activity_page.next_page is not None else None
                ),
            },
        )

    @router.get("/activity/{event_id}", response_class=HTMLResponse)
    def activity_detail(
        event_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        try:
            detail = ActivityService(session).detail(event_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request,
            name="activity_detail.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "event": detail,
            },
        )

    @router.get("/items", response_class=HTMLResponse)
    def items(
        request: Request,
        q: str = "",
        lifecycle: str | None = None,
        location_status: str = "all",
        page: int = 1,
        page_size: int = CatalogService.DEFAULT_PAGE_SIZE,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        catalog = CatalogService(session)
        query = q.strip()
        selected_lifecycle = (
            lifecycle if lifecycle is not None else ("all" if query else "active")
        )
        try:
            if query:
                rows = catalog.search_items(
                    query,
                    lifecycle=selected_lifecycle,
                    location_status=location_status,
                )
                item_page = None
            else:
                item_page = catalog.item_page(
                    page=page,
                    page_size=page_size,
                    lifecycle=selected_lifecycle,
                    location_status=location_status,
                )
                rows = item_page.items
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request,
            name="items.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "items": rows,
                "item_page": item_page,
                "query": query,
                "search_limit": catalog.SEARCH_LIMIT,
                "lifecycle": selected_lifecycle,
                "location_status": location_status,
            },
        )

    @router.get("/items/new", response_class=HTMLResponse)
    def new_item(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        catalog = CatalogService(session)
        return templates.TemplateResponse(
            request=request,
            name="item_new.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "item": None,
                "locations": catalog.list_locations(),
                "categories": catalog.list_categories(),
            },
        )

    @router.get("/items/{item_id}", response_class=HTMLResponse)
    def item_detail(
        item_id: int,
        request: Request,
        page: int = 1,
        page_size: int = CatalogService.DEFAULT_PAGE_SIZE,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        catalog = CatalogService(session)
        try:
            item = catalog.item_detail(item_id, page=page, page_size=page_size)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        suggestions = (
            LocationSuggestionService(session).suggest_item_locations(item_id)
            if item["location_status"] == "unknown"
            else []
        )
        return templates.TemplateResponse(
            request=request,
            name="item_detail.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "item": item,
                "locations": catalog.list_locations(),
                "categories": catalog.list_categories(),
                "location_suggestions": suggestions,
            },
        )

    @router.post("/api/items", response_model=ItemResponse, status_code=201)
    def create_item(
        payload: ItemCreateRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.create_item(
                **payload.model_dump(mode="python"),
                original_text="[manual web create]",
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.patch("/api/items/{item_id}", response_model=ItemResponse)
    def edit_item(
        item_id: int,
        payload: ItemEditRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        patch = payload.model_dump(exclude_unset=True, mode="python")
        item = _manual_mutation(
            session,
            lambda: inventory.update_item(
                item_id, **patch, original_text="[manual web edit]"
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.get(
        "/api/items/{item_id}/media",
        response_model=list[ItemMediaResponse],
    )
    @router.get(
        "/api/items/{item_id}/photos",
        response_model=list[ItemMediaResponse],
        include_in_schema=False,
    )
    def list_item_media(
        item_id: int,
        session: Session = Depends(get_session),
    ) -> list[ItemMediaResponse]:
        try:
            media = InventoryService(session).list_item_photos(item_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [_media_response(photo) for photo in media]

    @router.post(
        "/api/items/{item_id}/media",
        response_model=ItemMediaResponse,
        status_code=201,
    )
    @router.post(
        "/api/items/{item_id}/photos",
        response_model=ItemMediaResponse,
        status_code=201,
        include_in_schema=False,
    )
    def attach_item_media(
        item_id: int,
        payload: ItemMediaAttachRequest,
        session: Session = Depends(get_session),
    ) -> ItemMediaResponse:
        inventory = InventoryService(session, autocommit=False)
        media = _manual_mutation(
            session,
            lambda: inventory.attach_item_photo(
                item_id,
                **payload.model_dump(mode="python"),
            ),
        )
        return _media_response(media)

    @router.patch(
        "/api/items/{item_id}/media/{media_id}",
        response_model=ItemMediaResponse,
    )
    @router.patch(
        "/api/items/{item_id}/photos/{media_id}",
        response_model=ItemMediaResponse,
        include_in_schema=False,
    )
    def update_item_media(
        item_id: int,
        media_id: int,
        payload: ItemMediaUpdateRequest,
        session: Session = Depends(get_session),
    ) -> ItemMediaResponse:
        inventory = InventoryService(session, autocommit=False)

        def update() -> ItemMedia:
            parent = inventory.get_item(item_id)
            media = session.get(ItemMedia, media_id)
            if media is None or media.item_id != parent.id:
                raise EntityNotFoundError(
                    f"item photo id={media_id} is not attached to item id={item_id}"
                )
            patch = payload.model_dump(exclude_unset=True, mode="python")
            if "position" in patch and patch["position"] is None:
                raise ValueError("position must be a non-negative integer when provided")
            return inventory.update_item_photo(media_id, **patch)

        media = _manual_mutation(session, update)
        return _media_response(media)

    @router.delete(
        "/api/items/{item_id}/media/{media_id}",
        response_model=ItemMediaResponse,
    )
    @router.delete(
        "/api/items/{item_id}/photos/{media_id}",
        response_model=ItemMediaResponse,
        include_in_schema=False,
    )
    def detach_item_media(
        item_id: int,
        media_id: int,
        session: Session = Depends(get_session),
    ) -> ItemMediaResponse:
        inventory = InventoryService(session, autocommit=False)

        def detach() -> ItemMedia:
            parent = inventory.get_item(item_id)
            media = session.get(ItemMedia, media_id)
            if media is None or media.item_id != parent.id:
                raise EntityNotFoundError(
                    f"item photo id={media_id} is not attached to item id={item_id}"
                )
            return inventory.detach_item_photo(media_id)

        media = _manual_mutation(session, detach)
        return _media_response(media)

    @router.post("/api/items/{item_id}/move", response_model=ItemResponse)
    def move_item(
        item_id: int,
        payload: ItemMoveRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.move_item(
                item_id,
                payload.location_id,
                portion=payload.portion.model_dump() if payload.portion else None,
                original_text="[manual web move]",
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.post("/api/items/{item_id}/take", response_model=ItemResponse)
    def take_item(
        item_id: int,
        payload: ItemTakeRequest | None = None,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.take_item(
                item_id,
                portion=(
                    payload.portion.model_dump()
                    if payload is not None and payload.portion is not None
                    else None
                ),
                original_text="[manual web take]",
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.post("/api/items/{item_id}/location-unknown", response_model=ItemResponse)
    def mark_item_location_unknown(
        item_id: int,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.mark_item_location_unknown(
                item_id, original_text="[manual web mark location unknown]"
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.post("/api/items/{item_id}/quantity", response_model=ItemResponse)
    def change_item_quantity(
        item_id: int,
        payload: ItemQuantityChangeRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.change_item_quantity(
                item_id,
                **payload.model_dump(mode="python"),
                original_text="[manual web quantity change]",
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.post("/api/items/{item_id}/remove", response_model=ItemResponse)
    def remove_item(
        item_id: int,
        payload: ItemRemoveRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.remove_item(
                item_id,
                portion=payload.portion.model_dump() if payload.portion else None,
                reason=payload.reason,
                reason_source=payload.reason_source,
                original_text="[manual web remove]",
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.post("/api/items/{item_id}/restore", response_model=ItemResponse)
    def restore_item(
        item_id: int,
        payload: ItemRestoreRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session, autocommit=False)
        item = _manual_mutation(
            session,
            lambda: inventory.restore_item(
                item_id,
                state=payload.state,
                location_id=payload.location_id,
                original_text="[manual web restore]",
            ),
        )
        return ItemResponse(**CatalogService(session).item_dict(item))

    @router.get("/locations", response_class=HTMLResponse)
    def locations(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="locations.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "locations": CatalogService(session).list_locations(),
            },
        )

    @router.get("/locations/{location_id}", response_class=HTMLResponse)
    def location_detail_page(
        location_id: int, request: Request,
        page: int = 1,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        try:
            detail = CatalogService(session).location_detail(location_id, page=page)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request, name="tree_detail.html",
            context={"app_name": request.app.state.settings.app_name,
                     "kind": "locations", "label": "Location", "detail": detail},
        )

    @router.get("/locations/{location_id}/edit", response_class=HTMLResponse)
    def location_edit_page(
        location_id: int, request: Request, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        rows = CatalogService(session).list_locations()
        node = next((row for row in rows if row["id"] == location_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"location id={location_id} does not exist")
        return templates.TemplateResponse(
            request=request,
            name="tree_edit.html",
            context={"app_name": request.app.state.settings.app_name, "kind": "locations",
                     "node": node, "choices": _parent_choices(rows, location_id)},
        )

    @router.post("/api/locations", response_model=TreeResponse, status_code=201)
    def create_location(payload: TreeCreateRequest, session: Session = Depends(get_session)) -> TreeResponse:
        inventory = InventoryService(session, autocommit=False)
        node = _manual_mutation(session, lambda: inventory.create_location(**payload.model_dump()))
        return _tree_response(node)

    @router.patch("/api/locations/{location_id}", response_model=TreeResponse)
    def edit_location(
        location_id: int, payload: TreeEditRequest, session: Session = Depends(get_session)
    ) -> TreeResponse:
        inventory = InventoryService(session, autocommit=False)
        node = _manual_mutation(
            session,
            lambda: inventory.update_location(location_id, **payload.model_dump(exclude_unset=True)),
        )
        return _tree_response(node)

    @router.get("/categories", response_class=HTMLResponse)
    def categories(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="categories.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "categories": CatalogService(session).list_categories(),
            },
        )

    @router.get("/categories/{category_id}", response_class=HTMLResponse)
    def category_detail_page(
        category_id: int, request: Request,
        page: int = 1,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        try:
            detail = CatalogService(session).category_detail(category_id, page=page)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request, name="tree_detail.html",
            context={"app_name": request.app.state.settings.app_name,
                     "kind": "categories", "label": "Category", "detail": detail},
        )

    @router.get("/categories/{category_id}/edit", response_class=HTMLResponse)
    def category_edit_page(
        category_id: int, request: Request, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        rows = CatalogService(session).list_categories()
        node = next((row for row in rows if row["id"] == category_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"category id={category_id} does not exist")
        return templates.TemplateResponse(
            request=request,
            name="tree_edit.html",
            context={"app_name": request.app.state.settings.app_name, "kind": "categories",
                     "node": node, "choices": _parent_choices(rows, category_id)},
        )

    @router.post("/api/categories", response_model=TreeResponse, status_code=201)
    def create_category(payload: TreeCreateRequest, session: Session = Depends(get_session)) -> TreeResponse:
        inventory = InventoryService(session, autocommit=False)
        node = _manual_mutation(session, lambda: inventory.create_category(**payload.model_dump()))
        return _tree_response(node)

    @router.patch("/api/categories/{category_id}", response_model=TreeResponse)
    def edit_category(
        category_id: int, payload: TreeEditRequest, session: Session = Depends(get_session)
    ) -> TreeResponse:
        inventory = InventoryService(session, autocommit=False)
        node = _manual_mutation(
            session,
            lambda: inventory.update_category(category_id, **payload.model_dump(exclude_unset=True)),
        )
        return _tree_response(node)


    @router.get("/experiments", response_class=HTMLResponse)
    def experiments(
        request: Request,
        page: int = 1,
        page_size: int = ExperimentService.DEFAULT_PAGE_SIZE,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        service = ExperimentService(session)
        try:
            run_page = service.run_page(page=page, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def page_url(target_page: int) -> str:
            return f"/experiments?{urlencode({'page': target_page, 'page_size': run_page.page_size})}"

        return templates.TemplateResponse(
            request=request,
            name="experiments.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "summaries": service.summaries(),
                "runs": run_page.runs,
                "run_page": run_page,
                "previous_url": page_url(run_page.page - 1),
                "next_url": page_url(run_page.page + 1),
            },
        )

    @router.get("/experiments/{experiment_run_id}", response_class=HTMLResponse)
    def experiment_detail(
        experiment_run_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        try:
            run = ExperimentService(session).get_run(experiment_run_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request,
            name="experiment_detail.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "run": run,
                "trace_json": json.dumps(run.tool_trace, ensure_ascii=False, indent=2),
                "config_json": json.dumps(run.llm_config, ensure_ascii=False, indent=2),
            },
        )

    @router.post(
        "/api/experiments/{experiment_run_id}/review",
        response_model=ExperimentReviewResponse,
    )
    def experiment_review(
        experiment_run_id: int,
        payload: ExperimentReviewRequest,
        session: Session = Depends(get_session),
    ) -> ExperimentReviewResponse:
        try:
            review = ExperimentService(session).set_review(
                experiment_run_id,
                choice=payload.choice,
                variant_rating=payload.variant_rating,
                comment=payload.comment,
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ExperimentReviewResponse(
            experiment_run_id=experiment_run_id,
            choice=review.choice,
            variant_rating=review.variant_rating,
            comment=review.comment,
        )

    @router.get("/evaluations", response_class=HTMLResponse)
    def evaluations(
        request: Request,
        page: int = 1,
        page_size: int = EvaluationService.DEFAULT_PAGE_SIZE,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        service = EvaluationService(session)
        try:
            run_page = service.run_page(page=page, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def page_url(target_page: int) -> str:
            return f"/evaluations?{urlencode({'page': target_page, 'page_size': run_page.page_size})}"

        return templates.TemplateResponse(
            request=request,
            name="evaluations.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "summaries": service.summaries(),
                "runs": run_page.runs,
                "run_page": run_page,
                "previous_url": page_url(run_page.page - 1),
                "next_url": page_url(run_page.page + 1),
            },
        )

    @router.get("/evaluations/{run_id}", response_class=HTMLResponse)
    def evaluation_detail(
        run_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        try:
            run = EvaluationService(session).get_run(run_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request,
            name="evaluation_detail.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "run": run,
                "input_json": json.dumps(run.input_messages, ensure_ascii=False, indent=2),
                "trace_json": json.dumps(run.tool_trace, ensure_ascii=False, indent=2),
                "config_json": json.dumps(run.llm_config, ensure_ascii=False, indent=2),
            },
        )

    return router
