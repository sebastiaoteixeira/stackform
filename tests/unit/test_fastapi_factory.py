from datetime import datetime
from typing import Any, Literal, get_args

import pytest
from pydantic import BaseModel

from yaml_api_generator.runtime.fastapi_factory import (
    WRITE_OPERATIONS,
    create_pydantic_model,
    create_pydantic_model_fields,
    register_fastapi_routes,
    _field_annotation,
    _security_requirements,
    _openapi_security_schemes,
)
from yaml_api_generator.runtime.runtime_context import (
    RuntimeAccessRule,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)


def _make_collection(
    name: str = "items",
    fields: dict | None = None,
    type_: str = "data",
    id_field: str = "id",
    id_format: str = "uuidv7",
) -> RuntimeCollectionDescriptor:
    return RuntimeCollectionDescriptor(
        name=name,
        type=type_,
        id_field=id_field,
        id_format=id_format,
        fields=fields or {},
    )


def _make_identity(
    name: str = "users",
    identifier: str = "email",
    via: list[str] | None = None,
    id_field: str = "id",
    roles_field: str | None = None,
) -> RuntimeIdentityDescriptor:
    return RuntimeIdentityDescriptor(
        name=name,
        identifier=identifier,
        via=via or ["password"],
        id_field=id_field,
        roles_field=roles_field,
    )


def test_model_naming_collection_capitalized_operation_payload():
    col = _make_collection("items", {"title": {"type": "string", "required": True}})
    model = create_pydantic_model(col, "create")
    assert model is not None
    assert model.__name__ == "ItemsCreatePayload"


def test_underscore_collection_naming():
    col = _make_collection(
        "user_posts", {"title": {"type": "string", "required": True}}
    )
    model = create_pydantic_model(col, "create")
    assert model is not None
    assert model.__name__ == "UserPostsCreatePayload"


def test_write_operations_create_model():
    col = _make_collection("items", {"name": {"type": "string", "required": True}})
    for op in ("create", "update", "replace"):
        model = create_pydantic_model(col, op)
        assert model is not None


def test_read_operations_return_none():
    col = _make_collection("items", {"name": {"type": "string"}})
    assert create_pydantic_model(col, "list") is None
    assert create_pydantic_model(col, "get") is None
    assert create_pydantic_model(col, "delete") is None


def test_login_model_has_identifier_and_password():
    col = _make_collection("users", {"email": {"type": "string", "required": True}})
    identity = _make_identity(identifier="email", via=["password"])
    model = create_pydantic_model(col, "login", identity)
    assert model is not None
    assert model.__name__ == "UsersLoginPayload"
    assert "email" in model.model_fields
    assert "password" in model.model_fields


def test_update_operation_all_fields_optional():
    col = _make_collection(
        "items",
        {
            "title": {"type": "string", "required": True},
            "count": {"type": "number", "required": True},
        },
    )
    model = create_pydantic_model(col, "update")
    assert model is not None
    for field_info in model.model_fields.values():
        assert field_info.is_required() is False


def test_field_type_mapping_string():
    assert _field_annotation({"type": "string"}) is str


def test_field_type_mapping_number():
    assert _field_annotation({"type": "number"}) is float


def test_field_type_mapping_boolean():
    assert _field_annotation({"type": "boolean"}) is bool


def test_field_type_mapping_datetime():
    assert _field_annotation({"type": "datetime"}) is datetime


def test_field_type_mapping_enum():
    ann = _field_annotation({"type": "enum", "values": ["a", "b", "c"]})
    assert ann == Literal["a", "b", "c"]


def test_field_type_mapping_array():
    ann = _field_annotation({"type": "array", "items": {"type": "string"}})
    assert ann == list[str]


def test_field_type_mapping_object():
    ann = _field_annotation({"type": "object"})
    assert ann == dict[str, Any]


def test_field_type_mapping_ref():
    assert _field_annotation({"type": "ref", "ref": "user"}) is str


def test_constraints_min_max():
    col = _make_collection(
        "items",
        {"score": {"type": "number", "min": 0, "max": 100}},
    )
    model = create_pydantic_model(col, "create")
    assert model is not None
    field_info = model.model_fields["score"]
    assert field_info.metadata
    ge_found = any(
        hasattr(m, "ge") and getattr(m, "ge") == 0 for m in field_info.metadata
    )
    le_found = any(
        hasattr(m, "le") and getattr(m, "le") == 100 for m in field_info.metadata
    )
    assert ge_found
    assert le_found


def test_constraints_min_length_max_length():
    col = _make_collection(
        "items",
        {"name": {"type": "string", "minLength": 1, "maxLength": 255}},
    )
    model = create_pydantic_model(col, "create")
    assert model is not None
    field_info = model.model_fields["name"]
    assert field_info.metadata
    min_found = any(
        hasattr(m, "min_length") and getattr(m, "min_length") == 1
        for m in field_info.metadata
    )
    max_found = any(
        hasattr(m, "max_length") and getattr(m, "max_length") == 255
        for m in field_info.metadata
    )
    assert min_found
    assert max_found


def test_password_field_injection_for_identity_create():
    col = _make_collection("users", {"email": {"type": "string", "required": True}})
    identity = _make_identity(via=["password"])
    model = create_pydantic_model(col, "create", identity)
    assert model is not None
    assert "password" in model.model_fields


def test_existing_password_field_no_duplicate():
    col = _make_collection(
        "users",
        {
            "email": {"type": "string", "required": True},
            "password": {"type": "string", "required": True},
        },
    )
    identity = _make_identity(via=["password"])
    model = create_pydantic_model(col, "create", identity)
    assert model is not None
    password_count = sum(1 for f in model.model_fields if f == "password")
    assert password_count == 1


def test_id_type_fields_excluded():
    col = _make_collection(
        "items", {"id": {"type": "id"}, "name": {"type": "string", "required": True}}
    )
    model = create_pydantic_model(col, "create")
    assert model is not None
    assert "id" not in model.model_fields


def test_auth_field_excluded():
    col = _make_collection(
        "items",
        {"name": {"type": "string", "required": True}, "_auth": {"type": "object"}},
    )
    model = create_pydantic_model(col, "create")
    assert model is not None
    assert "_auth" not in model.model_fields


def test_routes_registered_with_correct_methods_and_paths():
    from fastapi import FastAPI

    col = _make_collection("posts", {"title": {"type": "string", "required": True}})
    auth = RuntimeAuthConfig(
        enabled=False,
        identity_collections={},
        identity_id_fields={},
        has_password_auth=False,
        has_api_key_auth=False,
    )
    route = RuntimeRouteDescriptor(
        method="POST",
        path="/api/v1/posts",
        operation="create",
        collection="posts",
        is_public=True,
    )
    from yaml_api_generator.runtime.runtime_context import (
        RuntimeAppConfig,
        RuntimeContext,
    )

    ctx = RuntimeContext(
        app=RuntimeAppConfig(base_path="/api", api_version="v1"),
        collections={"posts": col},
        routes=[route],
        auth=auth,
    )

    class _DummyRepo:
        def register_id_field(self, *a, **kw):
            pass

    app = FastAPI()
    pipelines = register_fastapi_routes(app, ctx, _DummyRepo())
    assert ("POST", "/api/v1/posts") in pipelines
    registered = [(r.methods, r.path) for r in app.routes if hasattr(r, "methods")]
    assert any(
        "POST" in methods and path == "/api/v1/posts" for methods, path in registered
    )


def test_four_endpoint_variants():
    from fastapi import FastAPI
    from yaml_api_generator.runtime.runtime_context import (
        RuntimeAppConfig,
        RuntimeContext,
    )

    col = _make_collection("items", {"name": {"type": "string", "required": True}})
    auth = RuntimeAuthConfig(
        enabled=False,
        identity_collections={},
        identity_id_fields={},
        has_password_auth=False,
        has_api_key_auth=False,
    )
    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/items",
            operation="list",
            collection="items",
            is_public=True,
        ),
        RuntimeRouteDescriptor(
            method="POST",
            path="/items",
            operation="create",
            collection="items",
            is_public=True,
        ),
        RuntimeRouteDescriptor(
            method="GET",
            path="/items/{id}",
            operation="get",
            collection="items",
            is_public=True,
        ),
        RuntimeRouteDescriptor(
            method="PUT",
            path="/items/{id}",
            operation="update",
            collection="items",
            is_public=True,
        ),
    ]
    ctx = RuntimeContext(
        app=RuntimeAppConfig(base_path="/api", api_version="v1"),
        collections={"items": col},
        routes=routes,
        auth=auth,
    )

    class _DummyRepo:
        def register_id_field(self, *a, **kw):
            pass

    app = FastAPI()
    register_fastapi_routes(app, ctx, _DummyRepo())
    registered_paths = {
        r.path for r in app.routes if hasattr(r, "path") and hasattr(r, "methods")
    }
    assert "/items" in registered_paths
    assert "/items/{id}" in registered_paths


def test_payload_model_dump_exclude_unset_for_partial_updates():
    col = _make_collection(
        "items",
        {"name": {"type": "string", "required": True}, "desc": {"type": "string"}},
    )
    model = create_pydantic_model(col, "update")
    assert model is not None
    instance = model(name="test")
    dumped = instance.model_dump(exclude_unset=True)
    assert "desc" not in dumped
    assert dumped["name"] == "test"


@pytest.mark.anyio
async def test_error_mapping_unauthorized_401():
    from yaml_api_generator.runtime.steps import UnauthorizedError
    from yaml_api_generator.runtime.fastapi_factory import _run_pipeline
    from yaml_api_generator.runtime.pipeline import Pipeline
    from fastapi import HTTPException

    async def _raise_unauth(ctx):
        raise UnauthorizedError("nope")

    pipeline = Pipeline(
        steps=[_raise_unauth],
        method="GET",
        path="/",
        collection="items",
        operation="list",
    )

    class _FakeRequest:
        path_params = {}
        headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_error_mapping_forbidden_403():
    from yaml_api_generator.runtime.steps import ForbiddenError
    from yaml_api_generator.runtime.pipeline import Pipeline
    from yaml_api_generator.runtime.fastapi_factory import _run_pipeline
    from fastapi import HTTPException

    async def _raise_forbidden(ctx):
        raise ForbiddenError("nope")

    pipeline = Pipeline(
        steps=[_raise_forbidden],
        method="GET",
        path="/",
        collection="items",
        operation="list",
    )

    class _FakeRequest:
        path_params = {}
        headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_error_mapping_not_found_404():
    from yaml_api_generator.runtime.steps import NotFoundError
    from yaml_api_generator.runtime.pipeline import Pipeline
    from yaml_api_generator.runtime.fastapi_factory import _run_pipeline
    from fastapi import HTTPException

    async def _raise_notfound(ctx):
        raise NotFoundError("gone")

    pipeline = Pipeline(
        steps=[_raise_notfound],
        method="GET",
        path="/",
        collection="items",
        operation="get",
    )

    class _FakeRequest:
        path_params = {}
        headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_error_mapping_value_error_422():
    from yaml_api_generator.runtime.pipeline import Pipeline
    from yaml_api_generator.runtime.fastapi_factory import _run_pipeline
    from fastapi import HTTPException

    async def _raise_value(ctx):
        raise ValueError("bad input")

    pipeline = Pipeline(
        steps=[_raise_value],
        method="POST",
        path="/",
        collection="items",
        operation="create",
    )

    class _FakeRequest:
        path_params = {}
        headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 422


def test_public_route_no_security_requirements():
    route = RuntimeRouteDescriptor(
        method="GET",
        path="/posts",
        operation="list",
        collection="posts",
        is_public=True,
    )
    auth = RuntimeAuthConfig(
        enabled=True,
        identity_collections={},
        identity_id_fields={},
        has_password_auth=True,
        has_api_key_auth=False,
    )
    assert _security_requirements(route, auth) == []


def test_api_key_auth_produces_apikey_and_bearer():
    route = RuntimeRouteDescriptor(
        method="GET",
        path="/posts",
        operation="list",
        collection="posts",
        is_public=False,
    )
    identity = RuntimeIdentityDescriptor(
        name="clients",
        identifier="clientId",
        via=["apiKey"],
        id_field="id",
    )
    auth = RuntimeAuthConfig(
        enabled=True,
        identity_collections={"clients": identity},
        identity_id_fields={"clients": "id"},
        has_password_auth=False,
        has_api_key_auth=True,
    )
    reqs = _security_requirements(route, auth)
    assert {"ApiKeyAuth": []} in reqs
    assert {"BearerAuth": []} in reqs


def test_password_auth_produces_basic_and_bearer():
    route = RuntimeRouteDescriptor(
        method="GET",
        path="/posts",
        operation="list",
        collection="posts",
        is_public=False,
    )
    identity = RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
    )
    auth = RuntimeAuthConfig(
        enabled=True,
        identity_collections={"users": identity},
        identity_id_fields={"users": "id"},
        has_password_auth=True,
        has_api_key_auth=False,
    )
    reqs = _security_requirements(route, auth)
    assert {"BasicAuth": []} in reqs
    assert {"BearerAuth": []} in reqs
