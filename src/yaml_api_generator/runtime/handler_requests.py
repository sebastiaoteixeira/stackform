"""The request every backend passes to a user handler or a repository operation.

A handler is a sync or async callable that receives one ``HandlerRequest`` and
returns the JSON response body. Raising ``ValueError`` answers 422. A repository
operation resolves its query's ``$`` references against ``bindings``.
"""

from dataclasses import dataclass, field
from importlib import import_module
from inspect import isawaitable
from typing import Any


@dataclass(frozen=True)
class HandlerRequest:
    params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: Any = None
    principal: dict[str, Any] | None = None
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def bindings(self) -> dict[str, Any]:
        params = {**self.params, **self.inputs}
        return {**params, "principal": self.principal or {}, "params": params, "body": self.body or {}}


async def invoke(handler: str, request: HandlerRequest) -> Any:
    module_path, name = handler.rsplit(".", 1)
    result = getattr(import_module(module_path), name)(request)
    return await result if isawaitable(result) else result
