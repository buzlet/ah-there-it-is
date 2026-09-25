"""Validated quantity truth shared by inventory mutation surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ah_there_it_is.domain.states import QuantityMode


class ReasonSource(StrEnum):
    EXPLICIT = "explicit"
    CONTEXT = "context"


@dataclass(frozen=True)
class QuantityValue:
    mode: QuantityMode
    value: int | None

    def __post_init__(self) -> None:
        if self.mode is QuantityMode.UNKNOWN:
            if self.value is not None:
                raise ValueError("unknown quantity must not have a numeric value")
            return
        if (
            not isinstance(self.value, int)
            or isinstance(self.value, bool)
            or self.value < 1
        ):
            raise ValueError("exact and approximate quantity must be an integer >= 1")

    @classmethod
    def coerce(
        cls, mode: QuantityMode | str, value: int | None
    ) -> "QuantityValue":
        try:
            quantity_mode = QuantityMode(mode)
        except ValueError as exc:
            allowed = ", ".join(candidate.value for candidate in QuantityMode)
            raise ValueError(
                f"invalid quantity mode {mode!r}; allowed: {allowed}"
            ) from exc
        return cls(quantity_mode, value)

    def as_dict(self) -> dict[str, str | int | None]:
        return {"mode": self.mode.value, "value": self.value}


@dataclass(frozen=True)
class Portion:
    """An explicitly supplied nonempty part of a lot; absence means whole lot."""

    quantity: QuantityValue

    @classmethod
    def coerce(
        cls,
        value: "Portion | QuantityValue | dict[str, object]",
    ) -> "Portion":
        if isinstance(value, cls):
            return value
        if isinstance(value, QuantityValue):
            return cls(value)
        if not isinstance(value, dict):
            raise ValueError("portion must be an object with mode and value")
        extra = set(value) - {"mode", "value"}
        if extra or "mode" not in value or "value" not in value:
            raise ValueError("portion must contain exactly mode and value")
        return cls(QuantityValue.coerce(value["mode"], value["value"]))  # type: ignore[arg-type]


def validated_reason(
    reason: str, reason_source: ReasonSource | str
) -> tuple[str, ReasonSource]:
    compact = reason.strip()
    if not compact:
        raise ValueError("reason must not be blank")
    if len(compact) > 500:
        raise ValueError("reason must be at most 500 characters")
    try:
        source = ReasonSource(reason_source)
    except ValueError as exc:
        raise ValueError("reason_source must be explicit or context") from exc
    return compact, source
