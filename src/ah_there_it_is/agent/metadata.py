# metadata.py
"""Safe, stable provider metadata for persisted evaluation traces."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def safe_trace_base_url(base_url: str) -> str:
    """Keep endpoint identity without URL credentials or request-only suffixes."""
    parsed = urlsplit(base_url.strip())
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))
