"""Read identity-provider claims and coerce them to the types of the fields they fill."""

from collections.abc import Callable
from typing import Any

_BOOLEANS = {"true": True, "false": False}


def resolve_claim_path(claims: dict[str, Any], path: str) -> Any | None:
    """Read a claim by its exact name, else navigate a dotted path; a bare ``*`` segment selects the sole entry of a dict."""
    if not path or not path.strip():
        return None
    if path in claims:
        return claims[path]

    current: Any = claims
    for segment in path.split("."):
        if segment == "*":
            if not isinstance(current, dict) or len(current) != 1:
                return None
            current = next(iter(current.values()))
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(segment)
            if current is None:
                return None

    return current


def _boolean(value: Any) -> bool:
    try:
        return _BOOLEANS[str(value).lower()]
    except KeyError:
        raise ValueError(value) from None


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(value)
    return value


_STRUCTURED: dict[str, Callable[[Any], Any]] = {"array": _items, "object": _mapping}
_SCALARS: dict[str, Callable[[Any], Any]] = {"number": float, "boolean": _boolean}


def _fitted(value: Any, field_type: str | None) -> Any:
    if field_type in _STRUCTURED:
        return _STRUCTURED[field_type](value)
    if isinstance(value, (list, dict)):
        raise ValueError(value)
    return _SCALARS.get(field_type, str)(value)


def claim_value(value: Any, field_type: str | None) -> Any | None:
    """``value`` as a field of ``field_type`` holds it; ``None`` when absent or it does not fit."""
    if value is None:
        return None
    try:
        return _fitted(value, field_type)
    except ValueError:
        return None
