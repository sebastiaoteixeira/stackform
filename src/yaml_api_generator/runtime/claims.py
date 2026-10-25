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


_CONVERTERS: dict[str, Callable[[Any], Any]] = {"number": float, "boolean": _boolean}


def claim_value(value: Any, field_type: str | None) -> Any | None:
    """``value`` as the field type expects it; ``None`` when absent, multi-valued or not convertible."""
    if value is None or isinstance(value, (list, dict)):
        return None
    try:
        return _CONVERTERS.get(field_type, str)(value)
    except ValueError:
        return None
