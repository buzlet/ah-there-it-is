"""Name normalization shared by domain services and search."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_SEARCH_SEPARATOR_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


def normalize_name(value: str) -> str:
    """Return a stable, human-friendly key for identity comparisons."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return _WHITESPACE_RE.sub(" ", normalized)


def normalize_search_text(value: str) -> str:
    """Normalize punctuation/separators for retrieval without changing identity rules."""
    normalized = normalize_name(value)
    normalized = _SEARCH_SEPARATOR_RE.sub(" ", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()
