"""Typed deterministic search results exposed to later LLM/tool adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

MatchType = Literal[
    "exact_name",
    "exact_alias",
    "exact_attribute",
    "exact_path",
    "normalized_name",
    "normalized_alias",
    "exact_tag",
    "contains",
    "fts",
]


class SearchCandidate(BaseModel):
    """Stable-ID candidate returned by deterministic retrieval."""

    model_config = ConfigDict(frozen=True)

    id: int
    entity_type: Literal["item", "location", "category", "tag"]
    name: str
    match_type: MatchType
    score: int
    path: str | None = None
    description: str | None = None


class ItemSearchCandidate(SearchCandidate):
    entity_type: Literal["item"] = "item"
    state: str
    location_id: int | None = None
    current_location_id: int | None = None
    location_status: str
    location_path: str | None = None
    category_id: int | None = None
    category_path: str | None = None
    fts_rank: float | None = None
