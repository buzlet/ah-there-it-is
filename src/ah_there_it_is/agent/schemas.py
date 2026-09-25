"""Typed input contracts for tools exposed to an LLM."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ah_there_it_is.domain.states import ItemState
from ah_there_it_is.domain.quantity import MAX_SQLITE_INTEGER


PositiveInt = Annotated[int, Field(strict=True, gt=0, le=MAX_SQLITE_INTEGER)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0, le=MAX_SQLITE_INTEGER)]
CountInt = Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_INTEGER)]
PageInt = Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_INTEGER // 100)]
Limit20Int = Annotated[int, Field(strict=True, ge=1, le=20)]
PageSize100Int = Annotated[int, Field(strict=True, ge=1, le=100)]


NonTerminalItemState = Literal[
    "unknown",
    "new",
    "working",
    "used",
    "broken",
    "needs_test",
    "for_parts",
    "for_sale",
]


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoInput(_ToolInput):
    pass


class SearchInput(_ToolInput):
    query: str = Field(min_length=1)
    limit: Limit20Int = 5


class IdInput(_ToolInput):
    id: PositiveInt


class ItemIdInput(_ToolInput):
    item_id: PositiveInt
    page: PageInt = 1
    page_size: PageSize100Int = 50


class ItemPhotoListInput(_ToolInput):
    item_id: PositiveInt


class AttachItemPhotoInput(_ToolInput):
    item_id: PositiveInt
    provider: str = Field(min_length=1, max_length=100)
    media_reference: str = Field(min_length=1, max_length=1000)
    caption: str | None = Field(default=None, max_length=20_000)
    position: NonNegativeInt = 0


class UpdateItemPhotoInput(_ToolInput):
    media_id: PositiveInt
    caption: str | None = Field(default=None, max_length=20_000)
    position: NonNegativeInt | None = None


class ItemPhotoIdInput(_ToolInput):
    media_id: PositiveInt


class LocationIdInput(_ToolInput):
    location_id: PositiveInt
    page: PageInt = 1
    page_size: PageSize100Int = 50


class SuggestItemLocationsInput(_ToolInput):
    item_id: PositiveInt
    limit: Limit20Int = 5


class CreateCategoryInput(_ToolInput):
    name: str = Field(min_length=1, max_length=200)
    parent_id: PositiveInt | None = None
    description: str | None = None


class CreateLocationInput(_ToolInput):
    name: str = Field(min_length=1, max_length=200)
    parent_id: PositiveInt | None = None
    description: str | None = None


class CreateItemInput(_ToolInput):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    state: ItemState = ItemState.UNKNOWN
    category_id: PositiveInt | None = None
    location_id: PositiveInt | None = None
    quantity_mode: Literal["exact", "approximate", "unknown"] = "exact"
    quantity: CountInt | None = 1
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_quantity(self) -> "CreateItemInput":
        _validate_quantity(self.quantity_mode, self.quantity)
        return self


class UpdateItemInput(_ToolInput):
    item_id: PositiveInt
    name: str | None = Field(default=None, max_length=300)
    description: str | None = None
    state: NonTerminalItemState | None = None
    category_id: PositiveInt | None = None
    attributes: dict[str, Any] | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None


class ItemMutationInput(_ToolInput):
    item_id: PositiveInt


class PortionInput(_ToolInput):
    mode: Literal["exact", "approximate", "unknown"]
    value: CountInt | None = None

    @model_validator(mode="after")
    def validate_quantity(self) -> "PortionInput":
        _validate_quantity(self.mode, self.value)
        return self


class MoveItemInput(_ToolInput):
    item_id: PositiveInt
    location_id: PositiveInt
    portion: PortionInput | None = None


class PortionedItemInput(_ToolInput):
    item_id: PositiveInt
    portion: PortionInput | None = None


class ChangeItemQuantityInput(_ToolInput):
    item_id: PositiveInt
    quantity_mode: Literal["exact", "approximate", "unknown"]
    quantity: CountInt | None = None
    reason: str = Field(min_length=1, max_length=500)
    reason_source: Literal["explicit", "context"]

    @model_validator(mode="after")
    def validate_quantity(self) -> "ChangeItemQuantityInput":
        _validate_quantity(self.quantity_mode, self.quantity)
        return self


class RemoveItemInput(PortionedItemInput):
    reason: str = Field(min_length=1, max_length=500)
    reason_source: Literal["explicit", "context"]


class RestoreItemInput(_ToolInput):
    item_id: PositiveInt
    state: NonTerminalItemState
    location_id: PositiveInt | None


def _validate_quantity(mode: str, value: int | None) -> None:
    if mode == "unknown" and value is not None:
        raise ValueError("unknown quantity requires a null value")
    if mode != "unknown" and value is None:
        raise ValueError(f"{mode} quantity requires a value")
