"""The request every backend passes to a user handler or a repository operation.

A handler is a sync or async callable that receives one ``HandlerRequest`` and
returns the JSON response body. Raising ``ValueError`` answers 422. A repository
operation resolves its query's ``$`` references against ``bindings``.

Every backend hands over the same view: a repeated query key keeps its last
value, an empty or non-JSON body is ``{}``, and the principal's record never
carries the stored id or credentials.
"""

import json
from dataclasses import dataclass, field
from importlib import import_module
from inspect import isawaitable
from typing import Any

_UNEXPOSED_RECORD_FIELDS = frozenset({"_id", "_auth", "password"})


def _last_values(query: dict[str, Any]) -> dict[str, Any]:
    return {key: value[-1] if isinstance(value, list) else value for key, value in query.items()}


def _principal_view(principal: dict[str, Any] | None) -> dict[str, Any] | None:
    if principal is None:
        return None
    record = principal.get("record")
    return {
        **principal,
        "roles": list(principal.get("roles", ())),
        "record": record and {key: value for key, value in record.items() if key not in _UNEXPOSED_RECORD_FIELDS},
    }


@dataclass(frozen=True)
class HandlerRequest:
    params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: Any = None
    principal: dict[str, Any] | None = None
    inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _last_values(self.query))
        object.__setattr__(self, "body", self.body or {})
        object.__setattr__(self, "principal", _principal_view(self.principal))

    @property
    def bindings(self) -> dict[str, Any]:
        params = {**self.params, **self.inputs}
        return {**params, "principal": self.principal or {}, "params": params, "body": self.body}


def json_body(raw: bytes) -> Any:
    """The JSON value a raw request body holds, or None when it holds none."""
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def invoke(handler: str, request: HandlerRequest) -> Any:
    module_path, name = handler.rsplit(".", 1)
    result = getattr(import_module(module_path), name)(request)
    return await result if isawaitable(result) else result
