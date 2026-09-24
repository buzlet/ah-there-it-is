"""HTTP request/response schemas for the text-only MVP."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ah_there_it_is.domain.states import ItemState
from ah_there_it_is.agent.receipts import MutationReceipt


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
    changes_applied: bool = False
    receipts: list[MutationReceipt] = Field(default_factory=list)


class ChatRequestRecordResponse(BaseModel):
    id: int
    request_key: str
    requested_conversation_id: int | None
    message: str
    status: str
    agent_run_id: int | None
    error: str | None
    recovered_from_id: int | None
    recovered_from_request_key: str | None
    recovery_note: str | None
    created_at: datetime
    updated_at: datetime


class ChatRequestRecoveryRequest(BaseModel):
    new_request_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    note: str = Field(min_length=3, max_length=2_000)
    acknowledge_duplicate_risk: Literal[True]


class ChatRequestRecoveryResponse(BaseModel):
    source_request_key: str
    new_request_key: str
    conversation_id: int
    run_id: int
    content: str
    rounds: int
    replayed: bool
    changes_applied: bool = False
    receipts: list[MutationReceipt] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


class FeedbackResponse(BaseModel):
    run_id: int
    rating: int
    comment: str | None


AliasName = Annotated[str, Field(min_length=1, max_length=300)]
TagName = Annotated[str, Field(min_length=1, max_length=100)]


class ItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    state: ItemState = ItemState.UNKNOWN
    quantity: int = Field(default=1, ge=1)
    category_id: int | None = Field(default=None, gt=0)
    location_id: int | None = Field(default=None, gt=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[AliasName] = Field(default_factory=list)
    tags: list[TagName] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value

    @field_validator("aliases", "tags")
    @classmethod
    def nonblank_entries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("aliases and tags must not contain blank entries")
        return values


class ItemEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    state: ItemState | None = None
    quantity: int | None = Field(default=None, ge=1)
    category_id: int | None = Field(default=None, gt=0)
    attributes: dict[str, Any] | None = None
    aliases: list[AliasName] | None = None
    tags: list[TagName] | None = None

    @model_validator(mode="after")
    def require_nonnull_fields(self) -> "ItemEditRequest":
        for key in ("name", "state", "quantity", "attributes", "aliases", "tags"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        if self.name is not None and not self.name.strip():
            raise ValueError("name must not be blank")
        for values in (self.aliases, self.tags):
            if values is not None and any(not value.strip() for value in values):
                raise ValueError("aliases and tags must not contain blank entries")
        return self


class ItemMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: int = Field(gt=0)


class ItemReactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ItemState
    location_id: int | None = Field(gt=0)

    @field_validator("state")
    @classmethod
    def require_nonterminal_state(cls, value: ItemState) -> ItemState:
        if value in {ItemState.DISCARDED, ItemState.SOLD}:
            raise ValueError("reactivation requires a non-terminal state")
        return value


class TreeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class TreeEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    parent_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_name_when_provided(self) -> "TreeEditRequest":
        if "name" in self.model_fields_set and (self.name is None or not self.name.strip()):
            raise ValueError("name must not be blank")
        return self


class TreeResponse(BaseModel):
    id: int
    name: str
    description: str | None
    parent_id: int | None
    path: str


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
    current_location_id: int | None
    location_status: str
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
    limit: int
    before_id: int | None = None
    has_older: bool
    next_before_id: int | None


class ExperimentReviewRequest(BaseModel):
    choice: str = Field(pattern="^(baseline|variant|tie|both_bad)$")
    variant_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


class ExperimentReviewResponse(BaseModel):
    experiment_run_id: int
    choice: str
    variant_rating: int | None
    comment: str | None
