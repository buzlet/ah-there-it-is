"""Typed input contracts for tools exposed to an LLM."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ah_there_it_is.domain.states import ItemState


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
    limit: int = Field(default=5, ge=1, le=20)


class IdInput(_ToolInput):
    id: int = Field(gt=0)


class ItemIdInput(_ToolInput):
    item_id: int = Field(gt=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class ItemPhotoListInput(_ToolInput):
    item_id: int = Field(gt=0)


class AttachItemPhotoInput(_ToolInput):
    item_id: int = Field(gt=0)
    provider: str = Field(min_length=1, max_length=100)
    media_reference: str = Field(min_length=1, max_length=1000)
    caption: str | None = Field(default=None, max_length=20_000)
    position: int = Field(default=0, ge=0)


class UpdateItemPhotoInput(_ToolInput):
    media_id: int = Field(gt=0)
    caption: str | None = Field(default=None, max_length=20_000)
    position: int | None = Field(default=None, ge=0)


class ItemPhotoIdInput(_ToolInput):
    media_id: int = Field(gt=0)


class LocationIdInput(_ToolInput):
    location_id: int = Field(gt=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class SuggestItemLocationsInput(_ToolInput):
    item_id: int = Field(gt=0)
    limit: int = Field(default=5, ge=1, le=20)


class CreateCategoryInput(_ToolInput):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = Field(default=None, gt=0)
    description: str | None = None


class CreateLocationInput(_ToolInput):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = Field(default=None, gt=0)
    description: str | None = None


class CreateItemInput(_ToolInput):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    state: ItemState = ItemState.UNKNOWN
    category_id: int | None = Field(default=None, gt=0)
    location_id: int | None = Field(default=None, gt=0)
    quantity_mode: Literal["exact", "approximate", "unknown"] = "exact"
    quantity: int | None = Field(default=1, ge=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_quantity(self) -> "CreateItemInput":
        _validate_quantity(self.quantity_mode, self.quantity)
        return self


class UpdateItemInput(_ToolInput):
    item_id: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=300)
    description: str | None = None
    state: NonTerminalItemState | None = None
    category_id: int | None = Field(default=None, gt=0)
    attributes: dict[str, Any] | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None


class ItemMutationInput(_ToolInput):
    item_id: int = Field(gt=0)


class PortionInput(_ToolInput):
    mode: Literal["exact", "approximate", "unknown"]
    value: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_quantity(self) -> "PortionInput":
        _validate_quantity(self.mode, self.value)
        return self


class MoveItemInput(_ToolInput):
    item_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    portion: PortionInput | None = None


class PortionedItemInput(_ToolInput):
    item_id: int = Field(gt=0)
    portion: PortionInput | None = None


class ChangeItemQuantityInput(_ToolInput):
    item_id: int = Field(gt=0)
    quantity_mode: Literal["exact", "approximate", "unknown"]
    quantity: int | None = Field(default=None, ge=1)
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
    item_id: int = Field(gt=0)
    state: NonTerminalItemState
    location_id: int | None = Field(gt=0)


def _validate_quantity(mode: str, value: int | None) -> None:
    if mode == "unknown" and value is not None:
        raise ValueError("unknown quantity requires a null value")
    if mode != "unknown" and value is None:
        raise ValueError(f"{mode} quantity requires a value")
