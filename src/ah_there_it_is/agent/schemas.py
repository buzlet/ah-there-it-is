"""Typed input contracts for tools exposed to an LLM."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class SearchInput(_ToolInput):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class IdInput(_ToolInput):
    id: int = Field(gt=0)


class ItemIdInput(_ToolInput):
    item_id: int = Field(gt=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


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
    quantity: int = Field(default=1, ge=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class UpdateItemInput(_ToolInput):
    item_id: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=300)
    description: str | None = None
    state: NonTerminalItemState | None = None
    category_id: int | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, ge=1)
    attributes: dict[str, Any] | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None


class ItemMutationInput(_ToolInput):
    item_id: int = Field(gt=0)


class MoveItemInput(_ToolInput):
    item_id: int = Field(gt=0)
    location_id: int = Field(gt=0)


class ReactivateItemInput(_ToolInput):
    item_id: int = Field(gt=0)
    state: NonTerminalItemState
    location_id: int | None = Field(gt=0)
