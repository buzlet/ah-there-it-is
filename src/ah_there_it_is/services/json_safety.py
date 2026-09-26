"""Deterministic, bounded conversion for values persisted in JSON columns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any


_MAX_DEPTH = 24
_MAX_STRING = 8_000
_MAX_ITEMS = 2_000
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"password|secret|credential|authorization)\b[\"']?\s*[:=]\s*)"
    r"(\"[^\"]*\"?|'[^']*'?|[^\s,;\"']+)"
)
_BEARER = re.compile(r"(?i)(\bbearer\s+)([^\s,;\"']+)")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,}")


def _type_name(value: Any) -> str:
    try:
        name = type.__getattribute__(type(value), "__name__")
    except Exception:
        return "object"
    return name[:120] if type(name) is str else "object"


def _safe_text(value: str) -> str:
    sanitized = _BEARER.sub(r"\1[redacted]", value[:_MAX_STRING])
    sanitized = _SECRET_ASSIGNMENT.sub(r"\1[redacted]", sanitized)
    sanitized = _ADDRESS.sub("[address]", sanitized)
    return sanitized[:_MAX_STRING]


def _exception_message(value: BaseException) -> str:
    try:
        args = BaseException.args.__get__(value, type(value))
    except Exception:
        return "<message unavailable>"
    parts: list[str] = []
    for arg in args[:32]:
        if arg is None or type(arg) in (bool, int, float, str):
            try:
                parts.append(str(arg))
            except Exception:
                parts.append("[message unavailable]")
        else:
            parts.append(f"[unsupported {_type_name(arg)}]")
    if len(args) > 32:
        parts.append("[truncated]")
    return ", ".join(parts)


def json_safe(value: Any, *, _depth: int = 0) -> Any:
    """Preserve JSON data shape while excluding arbitrary object serialization."""
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if type(value) is str:
        return _safe_text(value)
    if isinstance(value, BaseException):
        return {
            "exception_type": _safe_text(_type_name(value)),
            "message": _safe_text(_exception_message(value)),
        }
    if _depth >= _MAX_DEPTH:
        return "[maximum depth]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        try:
            for index, (key, child) in enumerate(value.items()):
                if index >= _MAX_ITEMS:
                    result["[truncated]"] = True
                    break
                safe_key = (
                    _safe_text(key)
                    if type(key) is str
                    else f"[key:{_type_name(key)}]"
                )
                result[safe_key] = json_safe(child, _depth=_depth + 1)
        except Exception:
            return f"[unsupported {_type_name(value)}]"
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            values = [
                json_safe(value[index], _depth=_depth + 1)
                for index in range(min(len(value), _MAX_ITEMS))
            ]
            if len(value) > _MAX_ITEMS:
                values.append("[truncated]")
            return values
        except Exception:
            return f"[unsupported {_type_name(value)}]"
    return f"[unsupported {_type_name(value)}]"


def safe_exception_diagnostic(exc: BaseException) -> str:
    """Render a bounded, sanitized diagnostic while preserving exception identity."""
    value = json_safe(exc)
    assert isinstance(value, dict)
    return f"{value['exception_type']}: {value['message']}"
