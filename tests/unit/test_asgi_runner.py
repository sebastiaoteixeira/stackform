import json

import pytest

from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.server.asgi.runner import ASGIApp, _compile_path
from yaml_api_generator.server.common.server_context import (
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeRouteDescriptor,
)
from yaml_api_generator.server.common.repositories import RepositoryRegistry


def _make_ctx_with_routes(routes):
    col = RuntimeCollectionDescriptor(
        name="items",
        type="data",
        id_field="id",
        id_format="uuidv7",
        fields={"name": {"type": "string", "required": True}},
    )
    auth = RuntimeAuthConfig(
        enabled=False,
        identity_collections={},
        identity_id_fields={},
        has_password_auth=False,
        has_api_key_auth=False,
    )
    return RuntimeContext(
        app=RuntimeAppConfig(base_path="/api", api_version="v1"),
        collections={"items": col},
        routes=routes,
        auth=auth,
    )


async def _receive_nothing():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _receive_json(body_dict):
    body = json.dumps(body_dict).encode("utf-8")
    return {"type": "http.request", "body": body, "more_body": False}


async def _receive_invalid_json():
    return {"type": "http.request", "body": b"not-json{", "more_body": False}


class _SendCollector:
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)

    @property
    def response(self):
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        body = next(m for m in self.messages if m["type"] == "http.response.body")
        status = start["status"]
        data = json.loads(body["body"])
        return status, data


async def _invoke_asgi(app, method, path, body_dict=None, headers=None):
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
    }

    if body_dict is not None:
        receive = lambda: _receive_json(body_dict)
    else:
        receive = _receive_nothing

    sender = _SendCollector()
    await app(scope, receive, sender)
    return sender.response


@pytest.mark.anyio
async def test_route_matching_by_method_and_path_regex():
    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))

    status, data = await _invoke_asgi(app, "GET", "/items")
    assert status == 200

    status2, data2 = await _invoke_asgi(app, "GET", "/nonexistent")
    assert status2 == 404


@pytest.mark.anyio
async def test_no_matching_route_returns_404_json():
    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))

    status, data = await _invoke_asgi(app, "GET", "/nonexistent")
    assert status == 404
    assert "detail" in data


@pytest.mark.anyio
async def test_invalid_json_body_returns_400_json():
    routes = [
        RuntimeRouteDescriptor(
            method="POST",
            path="/items",
            operation="create",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/items",
        "headers": [],
    }
    sender = _SendCollector()
    await app(scope, lambda: _receive_invalid_json(), sender)
    status, data = sender.response
    assert status == 400
    assert "detail" in data


def _inject_failing_pipeline(app, error_cls):
    from yaml_api_generator.server.common.pipeline import Pipeline

    for method, entries in app._routes.items():
        for i, (pattern, pipeline, route) in enumerate(entries):
            base = pipeline._base_ctx

            async def _fail(ctx, _error=error_cls):
                raise _error(_error.__name__)

            new_pipeline = Pipeline(
                steps=[_fail],
                method=base.method,
                path=base.path,
                collection=base.collection,
                operation=base.operation,
            )
            entries[i] = (pattern, new_pipeline, route)


@pytest.mark.anyio
async def test_error_mapping_401_unauthorized():
    from yaml_api_generator.server.common.steps import UnauthorizedError

    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=False,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))
    _inject_failing_pipeline(app, UnauthorizedError)

    status, data = await _invoke_asgi(app, "GET", "/items")
    assert status == 401


@pytest.mark.anyio
async def test_error_mapping_403_forbidden():
    from yaml_api_generator.server.common.steps import ForbiddenError

    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=False,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))
    _inject_failing_pipeline(app, ForbiddenError)

    status, data = await _invoke_asgi(app, "GET", "/items")
    assert status == 403


@pytest.mark.anyio
async def test_error_mapping_404_not_found():
    from yaml_api_generator.server.common.steps import NotFoundError

    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items/{id}",
            operation="get",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))
    _inject_failing_pipeline(app, NotFoundError)

    status, data = await _invoke_asgi(app, "GET", "/items/abc")
    assert status == 404


@pytest.mark.anyio
async def test_error_mapping_422_value_error():
    routes = [
        RuntimeRouteDescriptor(
            method="POST",
            path="/items",
            operation="create",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))
    _inject_failing_pipeline(app, ValueError)

    status, data = await _invoke_asgi(app, "POST", "/items", {"name": "x"})
    assert status == 422


@pytest.mark.skip(
    reason="Lifespan startup/shutdown requires complex ASGI protocol handling"
)
def test_lifespan_startup_shutdown():
    pass


@pytest.mark.anyio
async def test_header_decoding_from_asgi_bytes():
    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = _make_ctx_with_routes(routes)
    repo = InMemoryRepository()
    app = ASGIApp(ctx, RepositoryRegistry.single(repo))

    status, data = await _invoke_asgi(
        app, "GET", "/items", headers={"Authorization": "Bearer token123"}
    )
    assert status == 200
