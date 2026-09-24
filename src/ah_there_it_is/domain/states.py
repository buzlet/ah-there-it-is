"""Controlled item state values used by the initial domain model."""

from __future__ import annotations

from enum import StrEnum


class ItemState(StrEnum):
    UNKNOWN = "unknown"
    NEW = "new"
    WORKING = "working"
    USED = "used"
    BROKEN = "broken"
    NEEDS_TEST = "needs_test"
    FOR_PARTS = "for_parts"
    FOR_SALE = "for_sale"
    DISCARDED = "discarded"
    SOLD = "sold"


class LocationStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    IN_USE = "in_use"
    NOT_APPLICABLE = "not_applicable"
