# receipts.py
"""Backend-owned compact receipts for completed agent mutations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MutationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal[
        "create_item", "create_location", "create_category", "update_item", "move_item"
    ]
    entity_type: Literal["item", "location", "category"]
    entity_id: int = Field(gt=0)
    changed: bool
    before_ids: dict[str, int | None] = Field(default_factory=dict)
    after_ids: dict[str, int | None] = Field(default_factory=dict)
    event_ids: tuple[int, ...] = ()
