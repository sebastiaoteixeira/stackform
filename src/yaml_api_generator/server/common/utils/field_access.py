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
