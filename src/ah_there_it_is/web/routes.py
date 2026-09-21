"""HTTP API and HTML routes for the first usable web MVP."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.domain.exceptions import EntityNotFoundError, InventoryError
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.experiments import ExperimentService
from ah_there_it_is.web.dependencies import get_session
from ah_there_it_is.web.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationMessageResponse,
    ConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    ExperimentReviewRequest,
    ExperimentReviewResponse,
    ItemEditRequest,
    ItemResponse,
)


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
        llm = request.app.state.llm_factory()
        settings = request.app.state.settings
        runner = AgentRunner(
            session,
            llm,
            max_rounds=settings.agent_max_rounds,
            system_prompt=request.app.state.system_prompt,
            prompt_version=settings.prompt_version,
        )
        try:
            result = runner.run(
                payload.message,
                conversation_id=payload.conversation_id,
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InventoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ChatResponse(
            conversation_id=result.conversation_id,
            run_id=result.run_id,
            content=result.content,
            rounds=result.rounds,
        )

    @router.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
    def conversation(
        conversation_id: int,
        session: Session = Depends(get_session),
    ) -> ConversationResponse:
        conversations = ConversationService(session)
        evaluations = EvaluationService(session)
        try:
            messages = conversations.list_messages(conversation_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        runs = evaluations.conversation_runs(conversation_id)
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
                for message in messages
            ],
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

    @router.get("/items", response_class=HTMLResponse)
    def items(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        catalog = CatalogService(session)
        return templates.TemplateResponse(
            request=request,
            name="items.html",
            context={"app_name": request.app.state.settings.app_name, "items": catalog.list_items()},
        )

    @router.get("/items/{item_id}", response_class=HTMLResponse)
    def item_detail(
        item_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        catalog = CatalogService(session)
        try:
            item = catalog.item_detail(item_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request,
            name="item_detail.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "item": item,
                "locations": catalog.list_locations(),
                "categories": catalog.list_categories(),
            },
        )

    @router.patch("/api/items/{item_id}", response_model=ItemResponse)
    def edit_item(
        item_id: int,
        payload: ItemEditRequest,
        session: Session = Depends(get_session),
    ) -> ItemResponse:
        inventory = InventoryService(session)
        patch = payload.model_dump(exclude_unset=True, mode="python")
        location_provided = "location_id" in patch
        location_id = patch.pop("location_id", None)
        try:
            if patch:
                inventory.update_item(
                    item_id,
                    **patch,
                    original_text="[manual web edit]",
                )
            if location_provided:
                inventory.move_item(
                    item_id,
                    location_id,
                    original_text="[manual web edit]",
                )
            item = CatalogService(session).item_detail(item_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InventoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ItemResponse(**{key: item[key] for key in ItemResponse.model_fields})

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


    @router.get("/experiments", response_class=HTMLResponse)
    def experiments(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        service = ExperimentService(session)
        return templates.TemplateResponse(
            request=request,
            name="experiments.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "summaries": service.summaries(),
                "runs": service.recent_runs(limit=100),
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
    def evaluations(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        service = EvaluationService(session)
        return templates.TemplateResponse(
            request=request,
            name="evaluations.html",
            context={
                "app_name": request.app.state.settings.app_name,
                "summaries": service.summaries(),
                "runs": service.recent_runs(limit=100),
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
