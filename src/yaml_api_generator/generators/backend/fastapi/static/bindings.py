from typing import Any


def resolve_filter(value: Any, bindings: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _resolve_ref(value, bindings) if value.startswith("$") else value
    if isinstance(value, dict):
        return {key: resolve_filter(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_filter(item, bindings) for item in value]
    return value


def _resolve_ref(ref: str, bindings: dict[str, Any]) -> Any:
    current: Any = bindings
    for part in ref[1:].split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current
