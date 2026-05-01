from copy import deepcopy
from inspect import isawaitable
from typing import Any, Mapping, Sequence

from .request_context import RequestContext
from .steps import Step


class Pipeline:
    def __init__(
        self,
        steps: Sequence[Step],
        method: str,
        path: str,
        api_version: str | None = None,
        collection: str | None = None,
        operation: str | None = None,
        headers: Mapping[str, str] | None = None,
        url_params: Mapping[str, str] | None = None,
        repository: Any | None = None,
        principal: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        response: Any | None = None,
    ) -> None:
        self.steps = list(steps)
        self._base_ctx = RequestContext(
            method=method,
            path=path,
            api_version=api_version,
            collection=collection,
            operation=operation,
            headers=dict(headers or {}),
            url_params=dict(url_params or {}),
            repository=repository,
            principal=deepcopy(principal) if principal is not None else None,
            body=deepcopy(body) if body is not None else None,
            response=deepcopy(response) if response is not None else None,
        )

    def _clone_context(self, ctx: RequestContext) -> RequestContext:
        return RequestContext(
            method=ctx.method,
            path=ctx.path,
            api_version=ctx.api_version,
            collection=ctx.collection,
            operation=ctx.operation,
            headers=dict(ctx.headers),
            url_params=dict(ctx.url_params),
            repository=ctx.repository,
            principal=deepcopy(ctx.principal) if ctx.principal is not None else None,
            body=deepcopy(ctx.body) if ctx.body is not None else None,
            response=deepcopy(ctx.response) if ctx.response is not None else None,
        )

    async def run(
        self,
        *,
        context: RequestContext | None = None,
        method: str | None = None,
        path: str | None = None,
        api_version: str | None = None,
        collection: str | None = None,
        operation: str | None = None,
        headers: Mapping[str, str] | None = None,
        url_params: Mapping[str, str] | None = None,
        repository: Any | None = None,
        principal: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        response: Any | None = None,
    ) -> RequestContext:
        current_ctx = (
            self._clone_context(context)
            if context is not None
            else self._clone_context(self._base_ctx)
        )

        if method is not None:
            current_ctx.method = method
        if path is not None:
            current_ctx.path = path
        if api_version is not None:
            current_ctx.api_version = api_version
        if collection is not None:
            current_ctx.collection = collection
        if operation is not None:
            current_ctx.operation = operation
        if headers is not None:
            current_ctx.headers = dict(headers)
        if url_params is not None:
            current_ctx.url_params = dict(url_params)
        if repository is not None:
            current_ctx.repository = repository
        if principal is not None:
            current_ctx.principal = deepcopy(principal)
        if body is not None:
            current_ctx.body = deepcopy(body)
        if response is not None:
            current_ctx.response = deepcopy(response)

        for step in self.steps:
            result = step(current_ctx)
            current_ctx = await result if isawaitable(result) else result

        return current_ctx
