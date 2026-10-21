import types
from datetime import datetime
from typing import Any, Literal

import pytest
from pydantic import TypeAdapter, ValidationError

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.server.fastapi.factory import (
    _field_annotation,
    _security_requirements,
    create_pydantic_model,
    register_fastapi_routes,
)
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.server_context import (
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
) -> RuntimeIdentityDescriptor:
    providers = via or ["password"]
    return RuntimeIdentityDescriptor(
        name=name,
        bindings=tuple(IRProviderBinding(provider=p, identifier=identifier) for p in providers),
        id_field=id_field,
    )


# --- Model naming convention (documented spec: {Collection}{Op}Payload) ---


def test_model_naming_collection_capitalized_operation_payload():
    col = _make_collection("items", {"title": {"type": "string", "required": True}})
    model = create_pydantic_model(col, "create")
    assert model.__name__ == "ItemsCreatePayload"


def test_underscore_collection_naming():
    col = _make_collection("user_posts", {"title": {"type": "string", "required": True}})
    model = create_pydantic_model(col, "create")
    assert model.__name__ == "UserPostsCreatePayload"


# --- Model creation per operation ---


def test_write_operations_create_model():
    col = _make_collection("items", {"name": {"type": "string", "required": True}})
    for op in ("create", "update", "replace"):
        assert create_pydantic_model(col, op) is not None


def test_read_operations_return_none():
    col = _make_collection("items", {"name": {"type": "string"}})
    assert create_pydantic_model(col, "list") is None
    assert create_pydantic_model(col, "get") is None
    assert create_pydantic_model(col, "delete") is None


# --- Login model requires identifier + password ---


def test_login_model_requires_identifier_and_password():
    col = _make_collection("users", {"email": {"type": "string", "required": True}})
    identity = _make_identity(identifier="email", via=["password"])
    model = create_pydantic_model(col, "login", identity)
    model(email="a@b.com", password="secret")  # must succeed
    with pytest.raises(ValidationError):
        model(email="a@b.com")  # missing password
    with pytest.raises(ValidationError):
        model(password="secret")  # missing identifier


# --- Update operation: all fields optional ---


def test_update_operation_all_fields_optional():
    col = _make_collection("items", {
        "title": {"type": "string", "required": True},
        "count": {"type": "number", "required": True},
    })
    model = create_pydantic_model(col, "update")
    instance = model()  # must succeed with no fields
    assert model(title="x").model_dump(exclude_unset=True) == {"title": "x"}
    assert model().model_dump(exclude_unset=True) == {}


# --- Field type annotations ---


def test_field_type_mapping_string():
    assert _field_annotation({"type": "string"}) is str


@pytest.mark.parametrize("value", ["3", True])
def test_number_field_is_never_coerced(value):
    number = TypeAdapter(_field_annotation({"type": "number"}))
    assert number.validate_python(3) == 3.0
    with pytest.raises(ValidationError):
        number.validate_python(value)


@pytest.mark.parametrize("value", ["true", 1])
def test_boolean_field_is_never_coerced(value):
    boolean = TypeAdapter(_field_annotation({"type": "boolean"}))
    assert boolean.validate_python(True) is True
    with pytest.raises(ValidationError):
        boolean.validate_python(value)


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


# --- Constraints enforced at validation time ---


def test_constraints_min_max_enforced():
    col = _make_collection("items", {"score": {"type": "number", "min": 0, "max": 100}})
    model = create_pydantic_model(col, "create")
    model(score=50)   # valid
    model(score=0)    # boundary valid
    model(score=100)  # boundary valid
    with pytest.raises(ValidationError):
        model(score=-1)
    with pytest.raises(ValidationError):
        model(score=101)


def test_constraints_min_length_max_length_enforced():
    col = _make_collection("items", {"name": {"type": "string", "minLength": 2, "maxLength": 5}})
    model = create_pydantic_model(col, "create")
    model(name="hi")      # at min
    model(name="hello")   # at max
    with pytest.raises(ValidationError):
        model(name="x")   # too short
    with pytest.raises(ValidationError):
        model(name="toolong")  # too long


# --- Field exclusions ---


def test_password_field_required_for_identity_create():
    col = _make_collection("users", {"email": {"type": "string", "required": True}})
    identity = _make_identity(via=["password"])
    model = create_pydantic_model(col, "create", identity)
    model(email="a@b.com", password="secret")  # must succeed
    with pytest.raises(ValidationError):
        model(email="a@b.com")  # missing password


def test_existing_password_field_not_duplicated():
    col = _make_collection("users", {
        "email": {"type": "string", "required": True},
        "password": {"type": "string", "required": True},
    })
    identity = _make_identity(via=["password"])
    model = create_pydantic_model(col, "create", identity)
    # If duplicated, Pydantic would error or behave oddly; just verify it works
    model(email="a@b.com", password="secret")


def test_id_type_field_not_required_in_create():
    """Auto-generated id fields must not appear in the create payload."""
    col = _make_collection("items", {
        "id": {"type": "id"},
        "name": {"type": "string", "required": True},
    })
    model = create_pydantic_model(col, "create")
    # Can create without providing id
    instance = model(name="Widget")
    assert "id" not in instance.model_dump(exclude_unset=True)


def test_auth_internal_field_not_accepted_in_create():
    """_auth fields must not appear in create payloads — they are internal."""
    col = _make_collection("items", {
        "name": {"type": "string", "required": True},
        "_auth": {"type": "object"},
    })
    model = create_pydantic_model(col, "create")
    instance = model(name="x")
    assert "_auth" not in instance.model_dump(exclude_unset=True)


# --- Route registration ---


def test_routes_registered_with_correct_methods_and_paths():
    from fastapi import FastAPI
    from yaml_api_generator.server.common.server_context import RuntimeAppConfig, RuntimeContext

    col = _make_collection("posts", {"title": {"type": "string", "required": True}})
    auth = RuntimeAuthConfig(
        enabled=False, identity_collections={}, identity_id_fields={},
        has_password_auth=False, has_api_key_auth=False,
    )
    route = RuntimeRouteDescriptor(
        method="POST", path="/api/v1/posts", operation="create",
        collection="posts", is_public=True,
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
    register_fastapi_routes(app, ctx, RepositoryRegistry.single(_DummyRepo()))
    registered = [(r.methods, r.path) for r in app.routes if hasattr(r, "methods")]
    assert any("POST" in methods and path == "/api/v1/posts" for methods, path in registered)


def test_all_crud_routes_registered():
    from fastapi import FastAPI
    from yaml_api_generator.server.common.server_context import RuntimeAppConfig, RuntimeContext

    col = _make_collection("items", {"name": {"type": "string", "required": True}})
    auth = RuntimeAuthConfig(
        enabled=False, identity_collections={}, identity_id_fields={},
        has_password_auth=False, has_api_key_auth=False,
    )
    routes = [
        RuntimeRouteDescriptor(method="GET",   path="/items",      operation="list",   collection="items", is_public=True),
        RuntimeRouteDescriptor(method="POST",  path="/items",      operation="create", collection="items", is_public=True),
        RuntimeRouteDescriptor(method="GET",   path="/items/{id}", operation="get",    collection="items", is_public=True),
        RuntimeRouteDescriptor(method="PATCH", path="/items/{id}", operation="update", collection="items", is_public=True),
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
    register_fastapi_routes(app, ctx, RepositoryRegistry.single(_DummyRepo()))
    registered_paths = {r.path for r in app.routes if hasattr(r, "path") and hasattr(r, "methods")}
    assert "/items" in registered_paths
    assert "/items/{id}" in registered_paths


# --- Pydantic model behavior ---


def test_payload_model_dump_exclude_unset_for_partial_updates():
    col = _make_collection("items", {
        "name": {"type": "string", "required": True},
        "desc": {"type": "string"},
    })
    model = create_pydantic_model(col, "update")
    instance = model(name="test")
    dumped = instance.model_dump(exclude_unset=True)
    assert "desc" not in dumped
    assert dumped["name"] == "test"


# --- Error → HTTP status mapping ---


@pytest.mark.anyio
async def test_error_mapping_unauthorized_401():
    from fastapi import FastAPI, HTTPException
    from yaml_api_generator.server.fastapi.factory import _run_pipeline
    from yaml_api_generator.server.common.pipeline import Pipeline
    from yaml_api_generator.server.common.steps import UnauthorizedError

    async def _raise(ctx):
        raise UnauthorizedError("nope")

    pipeline = Pipeline(steps=[_raise], method="GET", path="/", collection="items", operation="list")

    class _FakeRequest:
        path_params = {}
        headers = {}
        state = types.SimpleNamespace(principal=None)

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_error_mapping_forbidden_403():
    from fastapi import HTTPException
    from yaml_api_generator.server.fastapi.factory import _run_pipeline
    from yaml_api_generator.server.common.pipeline import Pipeline
    from yaml_api_generator.server.common.steps import ForbiddenError

    async def _raise(ctx):
        raise ForbiddenError("nope")

    pipeline = Pipeline(steps=[_raise], method="GET", path="/", collection="items", operation="list")

    class _FakeRequest:
        path_params = {}
        headers = {}
        state = types.SimpleNamespace(principal=None)

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_error_mapping_not_found_404():
    from fastapi import HTTPException
    from yaml_api_generator.server.fastapi.factory import _run_pipeline
    from yaml_api_generator.server.common.pipeline import Pipeline
    from yaml_api_generator.server.common.steps import NotFoundError

    async def _raise(ctx):
        raise NotFoundError("gone")

    pipeline = Pipeline(steps=[_raise], method="GET", path="/", collection="items", operation="get")

    class _FakeRequest:
        path_params = {}
        headers = {}
        state = types.SimpleNamespace(principal=None)

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_error_mapping_value_error_422():
    from fastapi import HTTPException
    from yaml_api_generator.server.fastapi.factory import _run_pipeline
    from yaml_api_generator.server.common.pipeline import Pipeline

    async def _raise(ctx):
        raise ValueError("bad input")

    pipeline = Pipeline(steps=[_raise], method="POST", path="/", collection="items", operation="create")

    class _FakeRequest:
        path_params = {}
        headers = {}
        state = types.SimpleNamespace(principal=None)

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(pipeline, _FakeRequest(), None, {})
    assert exc_info.value.status_code == 422


# --- OpenAPI security requirements ---


def test_public_route_no_security_requirements():
    route = RuntimeRouteDescriptor(
        method="GET", path="/posts", operation="list", collection="posts", is_public=True
    )
    auth = RuntimeAuthConfig(
        enabled=True, identity_collections={}, identity_id_fields={},
        has_password_auth=True, has_api_key_auth=False,
    )
    assert _security_requirements(route, auth) == []


def test_api_key_auth_includes_apikey_and_bearer_schemes():
    route = RuntimeRouteDescriptor(
        method="GET", path="/posts", operation="list", collection="posts", is_public=False
    )
    identity = RuntimeIdentityDescriptor(name="clients", bindings=(IRProviderBinding(provider="apiKey", identifier="clientId"),), id_field="id")
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


def test_password_auth_includes_basic_and_bearer_schemes():
    route = RuntimeRouteDescriptor(
        method="GET", path="/posts", operation="list", collection="posts", is_public=False
    )
    identity = RuntimeIdentityDescriptor(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),), id_field="id")
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


# --- BUG 1: field defaults materialized on create ---


def test_create_model_dump_includes_defaults_when_field_absent():
    col = _make_collection("posts", {"published": {"type": "boolean", "default": False}})
    model = create_pydantic_model(col, "create")
    instance = model()
    dumped = instance.model_dump(mode="json")
    assert "published" in dumped
    assert dumped["published"] is False


# --- BUG 1: update keeps exclude_unset so unset fields are not clobbered ---


def test_update_model_dump_exclude_unset_does_not_include_defaults():
    col = _make_collection("posts", {
        "title": {"type": "string", "required": True},
        "published": {"type": "boolean", "default": False},
    })
    model = create_pydantic_model(col, "update")
    instance = model(title="hello")
    dumped = instance.model_dump(mode="json", exclude_unset=True)
    assert "title" in dumped
    assert "published" not in dumped


# --- BUG 2: datetime model_dump with mode='json' produces ISO string ---


def test_create_model_dump_json_mode_serializes_datetime_to_iso_string():
    col = _make_collection("events", {"starts_at": {"type": "datetime"}})
    model = create_pydantic_model(col, "create")
    instance = model(starts_at=datetime(2025, 1, 15, 10, 30, 0))
    dumped = instance.model_dump(mode="json")
    assert isinstance(dumped["starts_at"], str)
    assert dumped["starts_at"].startswith("2025-01-15")