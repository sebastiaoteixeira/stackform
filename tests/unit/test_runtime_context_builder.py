import pytest

from yaml_api_generator.ir import (
    IRAccessRule,
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IRMongo,
    IRProviderBinding,
    IRRepository,
    IRRoute,
)
from yaml_api_generator.server.common.pipeline_builder import PipelineBuilder
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.ir import flatten_role_hierarchy
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.steps import ForbiddenError, UnauthorizedError
from tests.unit.support.repositories import InMemoryRepository


def _make_ir(
    collections: dict | None = None,
    identity: dict | None = None,
    routes: list | None = None,
) -> IRDocument:
    cols = collections or {
        "items": IRCollection(
            name="items",
            entity_name="item",
            type="data",
            idField="id",
            idFormat="uuidv7",
            fields={"name": {"type": "string", "required": True}},
        ),
    }
    return IRDocument(
        version="0.2",
        api=IRApi(basePath="/api", version="v1"),
        collections=cols,
        routes=routes or [],
        identityCollections=identity or {},
        mongo=IRMongo(),
        repositories={},
    )


def _users_collection():
    return IRCollection(
        name="users",
        entity_name="user",
        type="auth",
        idField="id",
        idFormat="uuidv7",
        fields={"email": {"type": "string", "required": True}},
    )


def _route(operation, collection="items", is_public=True, access_rules=None):
    paths = {
        "list": "/items", "get": "/items/{id}", "create": "/items",
        "update": "/items/{id}", "delete": "/items/{id}",
    }
    methods = {"list": "GET", "get": "GET", "create": "POST", "update": "PATCH", "delete": "DELETE"}
    return IRRoute(
        method=methods.get(operation, "GET"),
        path=paths.get(operation, "/items"),
        operation=operation,
        collection=collection,
        is_public=is_public,
        access_rules=access_rules,
    )


# --- flatten_role_hierarchy ---


def test_role_hierarchy_flattened_to_transitive_closure():
    result = flatten_role_hierarchy({"admin": ["moderator"], "moderator": ["user"]})
    assert result["admin"] == {"moderator", "user"}
    assert result["moderator"] == {"user"}


def test_role_hierarchy_non_included_role_not_upgraded():
    result = flatten_role_hierarchy({"admin": ["moderator"], "moderator": ["user"]})
    assert "admin" not in result.get("moderator", set())
    assert "admin" not in result.get("user", set())


# --- build_runtime_context → pipeline behavior ---


@pytest.mark.asyncio
async def test_collection_id_field_used_in_repository_operations():
    """Collections built with a custom idField must use it in create/get."""
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="itemId",
                idFormat="uuidv7",
                fields={"name": {"type": "string", "required": True}},
            ),
        },
        routes=[_route("create")],
    )
    rc = build_runtime_context(ir)
    repo = InMemoryRepository()
    route = rc.routes[0]
    pipeline = PipelineBuilder(rc, RepositoryRegistry.single(repo)).build_for_route(route)
    result = await pipeline.run(body={"name": "Widget"})
    assert "itemId" in result.response


@pytest.mark.asyncio
async def test_password_auth_collection_enables_login():
    """IR with password-auth identity collection must produce a working login pipeline."""
    from yaml_api_generator.server.common.auth.password import hash_password

    ir = _make_ir(
        collections={"users": _users_collection()},
        identity={"users": IRIdentityCollection(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),))},
        routes=[
            IRRoute(method="POST", path="/users/login", operation="login",
                    collection="users", is_public=True),
        ],
    )
    rc = build_runtime_context(ir)
    repo = InMemoryRepository({
        "users": [{"id": "u1", "email": "a@b.com", "_auth": {"passwordHash": hash_password("secret")}}]
    })
    repo.register_id_field("users", "id")
    route = rc.routes[0]
    pipeline = PipelineBuilder(rc, RepositoryRegistry.single(repo)).build_for_route(route)
    result = await pipeline.run(body={"email": "a@b.com", "password": "secret"})
    assert "token" in result.response


@pytest.mark.asyncio
async def test_non_public_route_from_ir_rejects_unauthenticated():
    """IR with a non-public route must produce a pipeline that rejects anonymous requests."""
    ir = _make_ir(
        collections={"users": _users_collection()},
        identity={"users": IRIdentityCollection(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),))},
        routes=[
            IRRoute(
                method="POST", path="/items", operation="create", collection="users",
                is_public=False,
                access_rules=[IRAccessRule(principal="*", effect="allow")],
            ),
        ],
    )
    rc = build_runtime_context(ir)
    repo = InMemoryRepository()
    route = rc.routes[0]
    pipeline = PipelineBuilder(rc, RepositoryRegistry.single(repo)).build_for_route(route)
    with pytest.raises(UnauthorizedError):
        await pipeline.run(headers={}, body={"email": "x@y.com"})


@pytest.mark.asyncio
async def test_role_based_access_rule_from_ir_is_enforced():
    """An access rule with required_role in the IR must be enforced in the pipeline."""
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"name": {"type": "string", "required": True}},
            ),
            "users": _users_collection(),
        },
        identity={"users": IRIdentityCollection(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),))},
        routes=[
            IRRoute(
                method="DELETE", path="/items/{id}", operation="delete", collection="items",
                is_public=False,
                access_rules=[IRAccessRule(principal="identity:users", required_role="admin", effect="allow")],
            ),
        ],
    )
    rc = build_runtime_context(ir)
    repo = InMemoryRepository({"items": [{"id": "item-1", "name": "Test"}]})
    repo.register_id_field("items", "id")
    route = rc.routes[0]
    pipeline = PipelineBuilder(rc, RepositoryRegistry.single(repo)).build_for_route(route)

    with pytest.raises(ForbiddenError):
        await pipeline.run(
            url_params={"id": "item-1"},
            principal={"sub": "u1", "identity_collection": "users", "roles": ["user"], "record": {}},
        )

def test_password_identity_without_declared_login_gets_one():
    """A controller need not declare the login operation: the generated project serves it, so
    the development server serves it too."""
    ir = _make_ir(
        collections={"users": _users_collection()},
        identity={"users": IRIdentityCollection(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),))},
        routes=[_route("create", collection="users")],
    )
    rc = build_runtime_context(ir)
    login = [route for route in rc.routes if route.operation == "login"]
    assert [(route.method, route.path, route.collection, route.is_public) for route in login] == [
        ("POST", "/api/v1/users/login", "users", True)
    ]


def test_declared_login_route_is_not_duplicated():
    ir = _make_ir(
        collections={"users": _users_collection()},
        identity={"users": IRIdentityCollection(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),))},
        routes=[
            IRRoute(method="POST", path="/api/v1/users/login", operation="login",
                    collection="users", is_public=True),
        ],
    )
    rc = build_runtime_context(ir)
    assert [route.path for route in rc.routes if route.operation == "login"] == ["/api/v1/users/login"]
