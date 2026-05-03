from typing import Any


def get_nested_field(obj: dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Navigate nested dictionary using dot-separated path.

    Args:
        obj: Dictionary to navigate
        path: Dot-separated path (e.g., "user.profile.email")
        default: Default value if path doesn't exist

    Returns:
        Value at the path, or default if not found

    Examples:
        >>> get_nested_field({"user": {"name": "Alice"}}, "user.name")
        'Alice'
        >>> get_nested_field({"user": {"name": "Alice"}}, "user.email", "unknown")
        'unknown'
    """
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
