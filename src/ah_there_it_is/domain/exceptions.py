"""Domain-level exceptions exposed by the service layer."""

from __future__ import annotations


class InventoryError(Exception):
    """Base error for inventory-domain failures."""


class EntityNotFoundError(InventoryError):
    """Requested entity does not exist."""


class DuplicateEntityError(InventoryError):
    """Creation would silently duplicate an existing entity."""
