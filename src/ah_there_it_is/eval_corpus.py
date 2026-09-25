"""Versioned evaluation-corpus schema and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpectedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "item_location",
        "item_location_none",
        "item_location_status",
        "item_exists",
        "item_state",
        "item_quantity",
        "item_quantity_truth",
        "item_description_contains",
        "item_history_min_events",
        "item_attribute_equals",
        "item_category_none",
        "event_count_delta",
        "item_event",
        "no_mutation",
    ]
    item_query: str | None = None
    location_query: str | None = None
    location_status: str | None = None
    state: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    quantity_mode: Literal["exact", "approximate", "unknown"] | None = None
    text: str | None = None
    min_events: int | None = Field(default=None, ge=0)
    attribute_key: str | None = None
    expected_value: Any = None
    expected_delta: int | None = Field(default=None, ge=0)
    event_type: str | None = None
    from_location_query: str | None = None
    to_location_query: str | None = None
    min_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> "ExpectedCheck":
        item_kinds = {
            "item_location",
            "item_location_none",
            "item_location_status",
            "item_exists",
            "item_state",
            "item_quantity",
            "item_quantity_truth",
            "item_description_contains",
            "item_history_min_events",
            "item_attribute_equals",
            "item_category_none",
            "item_event",
        }
        if self.kind in item_kinds and not self.item_query:
            raise ValueError(f"{self.kind} requires item_query")
        if self.kind == "item_location" and not self.location_query:
            raise ValueError("item_location requires location_query")
        if self.kind == "item_location_status" and self.location_status is None:
            raise ValueError("item_location_status requires location_status")
        if self.kind == "item_state" and self.state is None:
            raise ValueError("item_state requires state")
        if self.kind == "item_quantity" and self.quantity is None:
            raise ValueError("item_quantity requires quantity")
        if self.kind == "item_quantity_truth" and self.quantity_mode is None:
            raise ValueError("item_quantity_truth requires quantity_mode")
        if self.kind == "item_description_contains" and not self.text:
            raise ValueError("item_description_contains requires text")
        if self.kind == "item_history_min_events" and self.min_events is None:
            raise ValueError("item_history_min_events requires min_events")
        if self.kind == "item_attribute_equals" and not self.attribute_key:
            raise ValueError("item_attribute_equals requires attribute_key")
        if self.kind == "event_count_delta" and self.expected_delta is None:
            raise ValueError("event_count_delta requires expected_delta")
        if self.kind == "item_event" and not self.event_type:
            raise ValueError("item_event requires event_type")
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    group: str
    turns: list[str] = Field(min_length=1)
    focus: str
    checks: list[ExpectedCheck] = Field(default_factory=list)
    unsupported_facts: list[str] = Field(default_factory=list)
    expected_error: str | None = None

    @model_validator(mode="after")
    def _validate_unsupported_facts(self) -> "EvaluationCase":
        normalized = [value.strip() for value in self.unsupported_facts]
        if any(not value for value in normalized):
            raise ValueError("unsupported_facts entries must be nonblank")
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("unsupported_facts entries must be unique")
        self.unsupported_facts = normalized
        return self


class EvaluationCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    fixture: str
    cases: list[EvaluationCase]


def load_corpus(path: str | Path) -> EvaluationCorpus:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvaluationCorpus.model_validate(data)
