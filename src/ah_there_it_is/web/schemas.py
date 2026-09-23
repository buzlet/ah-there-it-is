"""HTTP request/response schemas for the text-only MVP."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ah_there_it_is.domain.states import ItemState


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: int | None = Field(default=None, gt=0)
    request_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class ChatResponse(BaseModel):
    conversation_id: int
    run_id: int
    content: str
    rounds: int
    replayed: bool = False


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


class FeedbackResponse(BaseModel):
    run_id: int
    rating: int
    comment: str | None


class ItemEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    state: ItemState | None = None
    quantity: int | None = Field(default=None, ge=1)
    category_id: int | None = None
    location_id: int | None = None


class ItemResponse(BaseModel):
    id: int
    name: str
    description: str | None
    state: str
    quantity: int
    attributes: dict[str, Any]
    aliases: list[str]
    tags: list[str]
    category_id: int | None
    category_path: str | None
    location_id: int | None
    location_path: str | None


class ConversationMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    run_id: int | None = None
    rating: int | None = None
    comment: str | None = None


class ConversationResponse(BaseModel):
    id: int
    messages: list[ConversationMessageResponse]


class ExperimentReviewRequest(BaseModel):
    choice: str = Field(pattern="^(baseline|variant|tie|both_bad)$")
    variant_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


class ExperimentReviewResponse(BaseModel):
    experiment_run_id: int
    choice: str
    variant_rating: int | None
    comment: str | None
