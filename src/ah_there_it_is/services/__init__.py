"""Services layer."""

from .catalog import CatalogService
from .conversations import ConversationService
from .evaluation import EvaluationService
from .inventory import InventoryService
from .location_suggestions import (
    LocationSuggestion,
    LocationSuggestionEvidence,
    LocationSuggestionService,
)
from .search import SearchService

__all__ = [
    "CatalogService",
    "ChatApplicationService",
    "ConversationService",
    "EvaluationService",
    "InventoryService",
    "LocationSuggestion",
    "LocationSuggestionEvidence",
    "LocationSuggestionService",
    "SearchService",
]


def __getattr__(name: str):
    if name == "ChatApplicationService":
        from .chat_application import ChatApplicationService

        return ChatApplicationService
    raise AttributeError(name)
