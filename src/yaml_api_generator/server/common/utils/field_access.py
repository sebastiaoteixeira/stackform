from typing import Any


def get_nested_field(obj: dict[str, Any], path: str, default: Any = None) -> Any:
    """Navigate a nested dict using a dot-separated path, returning ``default`` if any key is absent."""
    if not path:
        return default

    parts = path.split(".")
    current: Any = obj

    for part in parts:
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default

    return current


def resolve_claim_path(claims: dict[str, Any], path: str) -> Any | None:
    """Navigate claims with dotted paths; a bare ``*`` segment selects the sole entry of a dict."""
    if not path or not path.strip():
        return None

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
