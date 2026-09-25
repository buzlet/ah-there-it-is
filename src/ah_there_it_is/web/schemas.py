"""HTTP request/response schemas for the text-only MVP."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ah_there_it_is.domain.states import ItemState
from ah_there_it_is.agent.receipts import MutationReceipt


PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
CountInt = Annotated[int, Field(strict=True, ge=1)]
RatingInt = Annotated[int, Field(strict=True, ge=1, le=5)]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: PositiveInt | None = None
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
    source_identity: str | None = None
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
    rating: RatingInt
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
    quantity_mode: Literal["exact", "approximate", "unknown"] = "exact"
    quantity: CountInt | None = 1
    category_id: PositiveInt | None = None
    location_id: PositiveInt | None = None
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

    @model_validator(mode="after")
    def valid_quantity(self) -> "ItemCreateRequest":
        _validate_quantity(self.quantity_mode, self.quantity)
        return self


class ItemEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    state: ItemState | None = None
    category_id: PositiveInt | None = None
    attributes: dict[str, Any] | None = None
    aliases: list[AliasName] | None = None
    tags: list[TagName] | None = None

    @model_validator(mode="after")
    def require_nonnull_fields(self) -> "ItemEditRequest":
        for key in ("name", "state", "attributes", "aliases", "tags"):
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

    location_id: PositiveInt
    portion: "ItemPortionRequest | None" = None


class ItemPortionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["exact", "approximate", "unknown"]
    value: CountInt | None = None

    @model_validator(mode="after")
    def valid_quantity(self) -> "ItemPortionRequest":
        _validate_quantity(self.mode, self.value)
        return self


class ItemTakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portion: ItemPortionRequest | None = None


class ItemQuantityChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity_mode: Literal["exact", "approximate", "unknown"]
    quantity: CountInt | None = None
    reason: str = Field(min_length=1, max_length=500)
    reason_source: Literal["explicit", "context"]

    @model_validator(mode="after")
    def valid_quantity(self) -> "ItemQuantityChangeRequest":
        _validate_quantity(self.quantity_mode, self.quantity)
        return self


class ItemRemoveRequest(ItemTakeRequest):
    reason: str = Field(min_length=1, max_length=500)
    reason_source: Literal["explicit", "context"]


class ItemRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ItemState
    location_id: PositiveInt | None

    @field_validator("state")
    @classmethod
    def require_nonterminal_state(cls, value: ItemState) -> ItemState:
        if value in {ItemState.REMOVED, ItemState.DISCARDED, ItemState.SOLD}:
            raise ValueError("restore requires a non-terminal state")
        return value


def _validate_quantity(mode: str, value: int | None) -> None:
    if mode == "unknown" and value is not None:
        raise ValueError("unknown quantity requires a null value")
    if mode != "unknown" and value is None:
        raise ValueError(f"{mode} quantity requires a value")


class TreeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    parent_id: PositiveInt | None = None

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
    parent_id: PositiveInt | None = None

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


class ItemMediaResponse(BaseModel):
    id: int
    item_id: int
    provider: str
    media_reference: str
    caption: str | None
    position: int
    created_at: datetime
    updated_at: datetime


class ItemMediaAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    media_reference: str = Field(min_length=1, max_length=1000)
    caption: str | None = Field(default=None, max_length=20_000)
    position: NonNegativeInt = 0


class ItemMediaUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caption: str | None = Field(default=None, max_length=20_000)
    position: NonNegativeInt | None = None


class ItemResponse(BaseModel):
    id: int
    name: str
    description: str | None
    state: str
    quantity_mode: str
    quantity: int | None
    removal_reason: str | None
    attributes: dict[str, Any]
    aliases: list[str]
    tags: list[str]
    category_id: int | None
    category_path: str | None
    location_id: int | None
    current_location_id: int | None
    location_status: str
    location_path: str | None
    media: list[ItemMediaResponse] = Field(default_factory=list)


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
    variant_rating: RatingInt | None = None
    comment: str | None = Field(default=None, max_length=2_000)


class ExperimentReviewResponse(BaseModel):
    experiment_run_id: int
    choice: str
    variant_rating: int | None
    comment: str | None
