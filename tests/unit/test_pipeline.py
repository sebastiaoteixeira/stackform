import pytest

from yaml_api_generator.runtime.context import RequestContext
from yaml_api_generator.runtime.pipeline import Pipeline
from yaml_api_generator.runtime.pipeline_builder import PipelineBuilder
from yaml_api_generator.runtime.repositories.base import BaseRepository
from yaml_api_generator.ir import IRDocumentBinding
from yaml_api_generator.runtime.runtime_context import (
    RuntimeAccessRule,
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)
from yaml_api_generator.when_ast import Equals, FieldRef, StringLiteral
from .test_repository_steps import InMemoryRepository


def _make_ctx(**overrides) -> RequestContext:
    defaults = dict(
        method="GET",
        path="/items",
        api_version=None,
        collection="items",
        operation="list",
        headers={},
        url_params={},
        repository=None,
        principal=None,
        body=None,
        response=None,
    )
    defaults.update(overrides)
    return RequestContext(**defaults)


def _make_runtime_context(
    collections=None,
    identity_collections=None,
    routes=None,
    has_password_auth=False,
    has_api_key_auth=False,
    role_hierarchies=None,
) -> tuple:
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
    ctx = type(
        "RC",
        (),
        {
            "app": RuntimeAppConfig(base_path="/api", api_version="v1"),
            "collections": cols,
            "routes": rts,
            "auth": auth,
        },
    )()
    return ctx


# --- Pipeline Execution (304-308) ---


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


# --- Pipeline Builder (309-317) ---


@pytest.mark.asyncio
async def test_builder_custom_handler_route():
    import types

    mod = types.ModuleType("myapp.handlers.items")
    mod.custom_handler = lambda ctx: ctx  # type: ignore
    import sys

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
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    assert len(pipeline.steps) == 1
    assert pipeline.steps[0] is mod.custom_handler

    del sys.modules["myapp.handlers.items"]


def test_builder_login_route():
    identity = RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
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
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    step_names = [s.__name__ for s in pipeline.steps]
    assert "step" in step_names[0]
    assert len(pipeline.steps) == 2


def test_builder_standard_crud_has_validation_and_repo():
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items",
        operation="create",
        collection="items",
        is_public=True,
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    assert len(pipeline.steps) >= 2


def test_builder_non_public_route_has_auth_steps():
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/items",
        operation="create",
        collection="items",
        is_public=False,
        access_rules=[RuntimeAccessRule(principal="*", effect="allow")],
    )
    identity = RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
    )
    rc = _make_runtime_context(
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    step_names = [type(s).__name__ for s in pipeline.steps]
    assert len(pipeline.steps) >= 3


def test_builder_public_route_no_auth_steps():
    route = RuntimeRouteDescriptor(
        method="GET",
        path="/items",
        operation="list",
        collection="items",
        is_public=True,
    )
    rc = _make_runtime_context(routes=[route])
    repo = InMemoryRepository()
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    assert len(pipeline.steps) == 2


def test_builder_update_with_document_rules_has_prefetch():
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
                principal="identity:user",
                when=when_expr,
                document_symbols={"document": IRDocumentBinding(collection="items")},
                effect="allow",
            ),
        ],
    )
    identity = RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
    )
    rc = _make_runtime_context(
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    assert len(pipeline.steps) >= 4


def test_builder_get_with_document_rules_repo_then_post_fetch():
    when_expr = Equals(
        left=FieldRef(root="principal", path=("sub",)),
        right=FieldRef(root="document", path=("authorId",)),
    )
    route = RuntimeRouteDescriptor(
        method="GET",
        path="/items/{id}",
        operation="get",
        collection="items",
        is_public=False,
        access_rules=[
            RuntimeAccessRule(
                principal="identity:user",
                when=when_expr,
                document_symbols={"document": IRDocumentBinding(collection="items")},
                effect="allow",
            ),
        ],
    )
    identity = RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
    )
    rc = _make_runtime_context(
        identity_collections={"users": identity},
        routes=[route],
        has_password_auth=True,
    )
    repo = InMemoryRepository()
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    assert len(pipeline.steps) >= 4


def test_builder_identity_create_has_validate_identity_step():
    identity = RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
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
    builder = PipelineBuilder(rc, repo)
    pipeline = builder.build_for_route(route)
    assert len(pipeline.steps) >= 3


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
    builder = PipelineBuilder(rc, repo)
    with pytest.raises(ValueError, match="Unsupported operation"):
        builder.build_for_route(route)
