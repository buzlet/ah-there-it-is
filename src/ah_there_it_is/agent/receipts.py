# receipts.py
"""Backend-owned compact receipts for completed agent mutations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MutationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal[
        "create_item", "create_location", "create_category", "update_item", "move_item",
        "take_item", "mark_item_location_unknown", "change_item_quantity",
        "remove_item", "restore_item", "undo_last_action",
        "attach_item_photo", "update_item_photo", "detach_item_photo",
    ]
    entity_type: Literal["item", "location", "category", "media"]
    entity_id: int = Field(gt=0)
    changed: bool
    before_ids: dict[str, int | None] = Field(default_factory=dict)
    after_ids: dict[str, int | None] = Field(default_factory=dict)
    event_ids: tuple[int, ...] = ()
    affected_item_ids: tuple[int, ...] = ()
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    split: dict[str, Any] | None = None
    compensation: dict[str, Any] = Field(default_factory=dict)
    undo_of_run_id: int | None = Field(default=None, gt=0)
