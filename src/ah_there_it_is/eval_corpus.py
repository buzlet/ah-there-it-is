"""Versioned evaluation-corpus schema and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CheckKind = Literal[
    "item_location",
    "item_exists",
    "no_mutation",
    "item_location_none",
    "item_state",
    "item_quantity",
    "item_description_contains",
    "item_attribute_equals",
    "item_category_none",
    "event_count_delta",
    "item_event",
]


class ExpectedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    item_query: str | None = None
    location_query: str | None = None
    state: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    text: str | None = None
    attribute_key: str | None = None
    expected_value: Any = None
    expected_delta: int | None = Field(default=None, ge=0)
    event_type: str | None = None
    from_location_query: str | None = None
    to_location_query: str | None = None
    min_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _required_fields_for_kind(self) -> "ExpectedCheck":
        required: dict[str, tuple[str, ...]] = {
            "item_location": ("item_query", "location_query"),
            "item_exists": ("item_query",),
            "item_location_none": ("item_query",),
            "item_state": ("item_query", "state"),
            "item_quantity": ("item_query", "quantity"),
            "item_description_contains": ("item_query", "text"),
            "item_attribute_equals": ("item_query", "attribute_key"),
            "item_category_none": ("item_query",),
            "event_count_delta": ("expected_delta",),
            "item_event": ("item_query", "event_type"),
        }
        missing = [
            name
            for name in required.get(self.kind, ())
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError(
                f"check {self.kind!r} requires: " + ", ".join(missing)
            )
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    group: str
    turns: list[str] = Field(min_length=1)
    focus: str
    checks: list[ExpectedCheck] = Field(default_factory=list)


class EvaluationCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    fixture: str
    cases: list[EvaluationCase]


def load_corpus(path: str | Path) -> EvaluationCorpus:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvaluationCorpus.model_validate(data)
