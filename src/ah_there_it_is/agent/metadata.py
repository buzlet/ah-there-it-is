# metadata.py
"""Safe, stable provider metadata for persisted evaluation traces."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit


def safe_trace_base_url(base_url: str) -> str:
    """Keep endpoint identity without URL credentials or request-only suffixes."""
    parsed = urlsplit(base_url.strip())
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def provider_sensitive_values(
    *, api_key: str | None, base_url: str, extra_body: dict[str, Any] | None
) -> tuple[str, ...]:
    """Return configured request-only values that must never enter durable errors."""
    parsed = urlsplit(base_url.strip())
    values: list[str] = []
    for value in (api_key, parsed.username, parsed.password, parsed.fragment):
        if isinstance(value, str) and value:
            values.append(value)
    if parsed.query:
        values.append(parsed.query)
        values.extend(
            value
            for _key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if value
        )

    def collect(value: Any) -> None:
        if isinstance(value, str):
            if value:
                values.append(value)
        elif isinstance(value, dict):
            for nested in value.values():
                collect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                collect(nested)

    if extra_body:
        collect(extra_body)
    return tuple(sorted(set(values), key=len, reverse=True))


def redact_sensitive_text(value: object, secrets: Iterable[str]) -> str:
    """Redact configured secret/request-only values from an exception detail."""
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text
