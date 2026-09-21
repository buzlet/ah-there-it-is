"""Versioned evaluation-corpus schema and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExpectedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["item_location", "item_exists", "no_mutation"]
    item_query: str | None = None
    location_query: str | None = None


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
