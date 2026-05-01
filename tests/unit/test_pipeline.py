import pytest

from yaml_api_generator.ir import IRDocumentBinding
from yaml_api_generator.server.request_context import RequestContext
from yaml_api_generator.server.pipeline import Pipeline
from yaml_api_generator.server.pipeline_builder import PipelineBuilder
from yaml_api_generator.server.server_context import (
    RuntimeAccessRule,
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)
from yaml_api_generator.server.steps import ForbiddenError, UnauthorizedError
from yaml_api_generator.ir.when import Equals, FieldRef
from .test_repository_steps import InMemoryRepository


def _make_runtime_context(
    collections=None,
    identity_collections=None,
    routes=None,
    has_password_auth=False,
    has_api_key_auth=False,
    role_hierarchies=None,
):
    cols = collections or {
        "items": RuntimeCollectionDescriptor(
            name="items",
            type="standard",
            id_field="id",
            id_format="uuidv7",
            fields={"title": {"type": "string", "required": True}},
        ),
    }
    identities = identity_collections or {}
    auth = RuntimeAuthConfig(
        enabled=bool(identities),
        identity_collections=identities,
        identity_id_fields={n: i.id_field for n, i in identities.items()},
        has_password_auth=has_password_auth,
        has_api_key_auth=has_api_key_auth,
        role_hierarchies=role_hierarchies or {},
    )
    rts = routes or [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=True,
        ),
    ]
    return type(
        "RC",
        (),
        {
            "app": RuntimeAppConfig(base_path="/api", api_version="v1"),
            "collections": cols,
            "routes": rts,
            "auth": auth,
        },
    )()


# --- Pipeline Execution ---


@pytest.mark.asyncio
async def test_pipeline_steps_executed_sequentially():
    order = []

    def step_a(ctx):
        order.append("a")
        ctx.response = "a"
        return ctx

    async def step_b(ctx):
        order.append("b")
        ctx.response = "b"
        return ctx

    p = Pipeline(steps=[step_a, step_b], method="GET", path="/")
    result = await p.run()
    assert order == ["a", "b"]
    assert result.response == "b"


@pytest.mark.asyncio
async def test_pipeline_async_steps_awaited():
    async def async_step(ctx):
        ctx.response = "async_done"
        return ctx

    p = Pipeline(steps=[async_step], method="GET", path="/")
    result = await p.run()
    assert result.response == "async_done"


@pytest.mark.asyncio
async def test_pipeline_context_cloned_between_runs():
    def mutate(ctx):
        ctx.response = "mutated"
        return ctx

    p = Pipeline(steps=[mutate], method="GET", path="/", body={"key": "val"})
    r1 = await p.run()
    r2 = await p.run()
    assert r1 is not r2


@pytest.mark.asyncio
async def test_pipeline_override_params_replace_base():
    def echo(ctx):
        ctx.response = ctx.body
        return ctx

    p = Pipeline(steps=[echo], method="POST", path="/", body={"original": True})
    result = await p.run(body={"overridden": True})
    assert result.body == {"overridden": True}


@pytest.mark.asyncio
async def test_pipeline_exception_propagates():
    def fail_step(ctx):
        raise RuntimeError("boom")

    p = Pipeline(steps=[fail_step], method="GET", path="/")
    with pytest.raises(RuntimeError, match="boom"):
        await p.run()


# --- Pipeline Builder (behavioral) ---


@pytest.mark.asyncio
async def test_builder_custom_handler_route_calls_handler():
    import sys
    import types

    mod = types.ModuleType("myapp.handlers.items")

    def custom_handler(ctx):
        ctx.response = {"handled": True}
        return ctx

    mod.custom_handler = custom_handler
    sys.modules["myapp.handlers.items"] = mod

    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items/{id}/custom",
        operation="custom",
        collection="items",
        is_public=True,
        handler="myapp.handlers.items.custom_handler",
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    result = await pipeline.run()
    assert result.response == {"handled": True}

    del sys.modules["myapp.handlers.items"]


@pytest.mark.asyncio
async def test_builder_login_route_validates_and_returns_token():
    from yaml_api_generator.server.auth.password import hash_password

    identity = RuntimeIdentityDescriptor(
        name="users", identifier="email", via=["password"], id_field="id"
    )
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/users/login",
        operation="login",
        collection="users",
        is_public=True,
    )
    rc = _make_runtime_context(
        collections={
            "users": RuntimeCollectionDescriptor(
                name="users",
                type="auth",
                id_field="id",
                id_format="uuidv7",
                fields={"email": {"type": "string"}, "password": {"type": "string"}},
            ),
        },
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    repo._data["users"] = {
        "u1": {"id": "u1", "email": "a@b.com", "_auth": {"passwordHash": hash_password("secret")}}
    }

    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    result = await pipeline.run(body={"email": "a@b.com", "password": "secret"})
    assert "token" in result.response


@pytest.mark.asyncio
async def test_builder_login_route_missing_body_raises():
    identity = RuntimeIdentityDescriptor(
        name="users", identifier="email", via=["password"], id_field="id"
    )
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/users/login",
        operation="login",
        collection="users",
        is_public=True,
    )
    rc = _make_runtime_context(
        collections={
            "users": RuntimeCollectionDescriptor(
                name="users",
                type="auth",
                id_field="id",
                id_format="uuidv7",
                fields={"email": {"type": "string"}},
            ),
        },
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    with pytest.raises(ValueError):
        await pipeline.run(body={"email": "a@b.com"})  # missing password


@pytest.mark.asyncio
async def test_builder_standard_crud_invalid_body_raises_validation_error():
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items",
        operation="create",
        collection="items",
        is_public=True,
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    with pytest.raises(ValueError):
        await pipeline.run(body={})  # missing required "title"


@pytest.mark.asyncio
async def test_builder_standard_crud_valid_body_creates_item():
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items",
        operation="create",
        collection="items",
        is_public=True,
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    result = await pipeline.run(body={"title": "My Item"})
    assert result.response is not None
    assert result.response.get("title") == "My Item"


@pytest.mark.asyncio
async def test_builder_non_public_route_rejects_unauthenticated():
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items",
        operation="create",
        collection="items",
        is_public=False,
        access_rules=[RuntimeAccessRule(principal="*", effect="allow")],
    )
    identity = RuntimeIdentityDescriptor(
        name="users", identifier="email", via=["password"], id_field="id"
    )
    rc = _make_runtime_context(
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    with pytest.raises(UnauthorizedError):
        await pipeline.run(body={"title": "x"}, headers={})  # no auth header


@pytest.mark.asyncio
async def test_builder_public_route_succeeds_without_auth():
    route = RuntimeRouteDescriptor(
        method="GET",
        path="/items",
        operation="list",
        collection="items",
        is_public=True,
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    result = await pipeline.run(headers={})
    assert result.response == []  # empty list, no auth error


@pytest.mark.asyncio
async def test_builder_update_with_document_rule_allows_matching_principal():
    when_expr = Equals(
        left=FieldRef(root="principal", path=("sub",)),
        right=FieldRef(root="document", path=("authorId",)),
    )
    route = RuntimeRouteDescriptor(
        method="PATCH",
        path="/items/{id}",
        operation="update",
        collection="items",
        is_public=False,
        access_rules=[
            RuntimeAccessRule(
                principal="identity:users",
                when=when_expr,
                document_symbols={"document": IRDocumentBinding(collection="items")},
                effect="allow",
            ),
        ],
    )
    identity = RuntimeIdentityDescriptor(
        name="users", identifier="email", via=["password"], id_field="id"
    )
    rc = _make_runtime_context(
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {"item-1": {"id": "item-1", "title": "Old", "authorId": "user-1"}}
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    result = await pipeline.run(
        url_params={"id": "item-1"},
        body={"title": "New"},
        principal={"sub": "user-1", "identity_collection": "users", "roles": [], "record": {}},
    )
    assert result.response is not None


@pytest.mark.asyncio
async def test_builder_update_with_document_rule_denies_non_matching_principal():
    when_expr = Equals(
        left=FieldRef(root="principal", path=("sub",)),
        right=FieldRef(root="document", path=("authorId",)),
    )
    route = RuntimeRouteDescriptor(
        method="PATCH",
        path="/items/{id}",
        operation="update",
        collection="items",
        is_public=False,
        access_rules=[
            RuntimeAccessRule(
                principal="identity:users",
                when=when_expr,
                document_symbols={"document": IRDocumentBinding(collection="items")},
                effect="allow",
            ),
        ],
    )
    identity = RuntimeIdentityDescriptor(
        name="users", identifier="email", via=["password"], id_field="id"
    )
    rc = _make_runtime_context(
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {"item-1": {"id": "item-1", "title": "Old", "authorId": "user-1"}}
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    with pytest.raises(ForbiddenError):
        await pipeline.run(
            url_params={"id": "item-1"},
            body={"title": "New"},
            principal={"sub": "user-2", "identity_collection": "users", "roles": [], "record": {}},
        )


@pytest.mark.asyncio
async def test_builder_identity_create_without_password_raises():
    identity = RuntimeIdentityDescriptor(
        name="users", identifier="email", via=["password"], id_field="id"
    )
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/users",
        operation="create",
        collection="users",
        is_public=True,
    )
    rc = _make_runtime_context(
        collections={
            "users": RuntimeCollectionDescriptor(
                name="users",
                type="auth",
                id_field="id",
                id_format="uuidv7",
                fields={"email": {"type": "string", "required": True}},
            ),
        },
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    pipeline = PipelineBuilder(rc, repo).build_for_route(route)
    with pytest.raises(ValueError):
        await pipeline.run(body={"email": "a@b.com"})  # missing password


def test_builder_unsupported_operation_raises():
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items",
        operation="custom_op",
        collection="items",
        is_public=True,
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    with pytest.raises(ValueError, match="Unsupported operation"):
        PipelineBuilder(rc, repo).build_for_route(route)