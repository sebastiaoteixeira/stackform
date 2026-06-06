"""Resolve `$`-prefixed binding references inside custom-operation queries.

A reference like `$principal.id` is looked up in the request bindings
({"principal": ..., "params": ..., "body": ...}); plain values pass through.
"""

from typing import Any


def resolve(value: Any, bindings: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _resolve_ref(value, bindings) if value.startswith("$") else value
    if isinstance(value, dict):
        return {key: resolve(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, bindings) for item in value]
    return value


def _resolve_ref(value: str, bindings: dict[str, Any]) -> Any:
    current: Any = bindings
    for part in value[1:].split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current
