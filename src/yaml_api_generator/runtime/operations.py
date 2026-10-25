"""Bind and present declared repository operations.

A query value starting with ``$`` is a reference into ``HandlerRequest.bindings``
(``{**params, "principal", "params", "body"}``); every other value passes
through unchanged. Results are presented the way CRUD responses are: the
datastore's own ``_id`` becomes the canonical id field, credential fields
are hidden and timestamps read as ISO 8601 UTC strings.
"""

from datetime import UTC, datetime
from typing import Any

_HIDDEN_FIELDS = ("_auth", "password", "apiKey")


def resolve(value: Any, bindings: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _lookup(value[1:].split("."), bindings)
    if isinstance(value, dict):
        return {key: resolve(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, bindings) for item in value]
    return value


def _lookup(path: list[str], current: Any) -> Any:
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def present_value(value: Any) -> Any:
    """`value` as a response shows it: a stored timestamp, naive in UTC, as an ISO 8601 UTC string."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return value


def present_document(document: dict[str, Any] | None, id_field: str) -> dict[str, Any] | None:
    if document is None:
        return None
    presented = {key: present_value(value) for key, value in document.items()}
    if id_field not in presented and presented.get("_id") is not None:
        presented[id_field] = str(presented["_id"])
    if id_field != "_id":
        presented.pop("_id", None)
    for field in _HIDDEN_FIELDS:
        presented.pop(field, None)
    return presented


def present(result: Any, id_field: str) -> Any:
    if isinstance(result, list):
        return [present(item, id_field) for item in result]
    if isinstance(result, dict):
        return present_document(result, id_field)
    return result
