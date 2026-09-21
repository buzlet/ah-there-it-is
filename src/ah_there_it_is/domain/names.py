"""Name normalization shared by domain services and search."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(value: str) -> str:
    """Return a stable, human-friendly key for identity comparisons."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return _WHITESPACE_RE.sub(" ", normalized)
