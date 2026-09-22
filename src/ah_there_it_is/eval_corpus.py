"""Versioned evaluation-corpus schema and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpectedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "item_location",
        "item_location_none",
        "item_exists",
        "item_state",
        "item_quantity",
        "item_description_contains",
        "item_history_min_events",
        "no_mutation",
    ]
    item_query: str | None = None
    location_query: str | None = None
    state: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    text: str | None = None
    min_events: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> "ExpectedCheck":
        item_kinds = {
            "item_location",
            "item_location_none",
            "item_exists",
            "item_state",
            "item_quantity",
            "item_description_contains",
            "item_history_min_events",
        }
        if self.kind in item_kinds and not self.item_query:
            raise ValueError(f"{self.kind} requires item_query")
        if self.kind == "item_location" and not self.location_query:
            raise ValueError("item_location requires location_query")
        if self.kind == "item_state" and self.state is None:
            raise ValueError("item_state requires state")
        if self.kind == "item_quantity" and self.quantity is None:
            raise ValueError("item_quantity requires quantity")
        if self.kind == "item_description_contains" and not self.text:
            raise ValueError("item_description_contains requires text")
        if self.kind == "item_history_min_events" and self.min_events is None:
            raise ValueError("item_history_min_events requires min_events")
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
