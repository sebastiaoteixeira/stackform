import pytest

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.server.request_context import RequestContext
from yaml_api_generator.server.server_context import (
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
)
from yaml_api_generator.server.steps.validation import ValidateBodyStep
from .test_repository_steps import _make_ctx


def _make_collection(fields: dict | None = None) -> RuntimeCollectionDescriptor:
    return RuntimeCollectionDescriptor(
        name="items",
        type="standard",
        id_field="id",
        id_format="uuidv7",
        fields=fields or {},
    )


def _make_identity(
    identifier="email",
    via=("password",),
) -> RuntimeIdentityDescriptor:
    return RuntimeIdentityDescriptor(
        name="users",
        bindings=tuple(IRProviderBinding(provider=p, identifier=identifier) for p in via),
        id_field="id",
    )


# --- NO_BODY_OPS (275) ---


@pytest.mark.parametrize("op", ["list", "get", "delete"])
def test_validate_body_no_body_ops_pass(op):
    collection = _make_collection({"title": {"type": "string", "required": True}})
    step = ValidateBodyStep(collection, op)
    ctx = _make_ctx(operation=op, body=None)
    result = step(ctx)
    assert result.response is None


# --- Non-dict body (276) ---


def test_validate_body_non_dict_body():
    collection = _make_collection({"title": {"type": "string"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body="not a dict")
    with pytest.raises(ValueError, match="Request body must be a JSON object"):
        step(ctx)


# --- Unknown fields (277) ---


def test_validate_body_unknown_fields():
    collection = _make_collection({"title": {"type": "string"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"title": "ok", "extra": "bad"})
    with pytest.raises(ValueError, match="Unknown fields"):
        step(ctx)


# --- Missing required (278) ---


def test_validate_body_missing_required():
    collection = _make_collection({"title": {"type": "string", "required": True}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={})
    with pytest.raises(ValueError, match="Missing required fields"):
        step(ctx)


# --- Update makes all optional (279) ---


def test_validate_body_update_all_optional():
    collection = _make_collection({"title": {"type": "string", "required": True}})
    step = ValidateBodyStep(collection, "update")
    ctx = _make_ctx(operation="update", body={})
    result = step(ctx)
    assert result is not None


# --- String field (280-283) ---


def test_validate_body_string_valid():
    collection = _make_collection({"name": {"type": "string"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"name": "hello"})
    result = step(ctx)
    assert result.body["name"] == "hello"


def test_validate_body_string_non_string():
    collection = _make_collection({"name": {"type": "string"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"name": 123})
    with pytest.raises(ValueError, match="must be a string"):
        step(ctx)


def test_validate_body_string_min_length():
    collection = _make_collection({"name": {"type": "string", "minLength": 3}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"name": "ab"})
    with pytest.raises(ValueError, match="at least 3 characters"):
        step(ctx)


def test_validate_body_string_max_length():
    collection = _make_collection({"name": {"type": "string", "maxLength": 5}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"name": "abcdef"})
    with pytest.raises(ValueError, match="at most 5 characters"):
        step(ctx)


# --- Number field (284-288) ---


def test_validate_body_number_int():
    collection = _make_collection({"count": {"type": "number"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"count": 42})
    result = step(ctx)
    assert result.body["count"] == 42


def test_validate_body_number_float():
    collection = _make_collection({"count": {"type": "number"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"count": 3.14})
    result = step(ctx)
    assert result.body["count"] == 3.14


def test_validate_body_number_bool_rejected():
    collection = _make_collection({"count": {"type": "number"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"count": True})
    with pytest.raises(ValueError, match="must be a number"):
        step(ctx)


def test_validate_body_number_min():
    collection = _make_collection({"count": {"type": "number", "min": 0}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"count": -1})
    with pytest.raises(ValueError, match="must be >= 0"):
        step(ctx)


def test_validate_body_number_max():
    collection = _make_collection({"count": {"type": "number", "max": 100}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"count": 200})
    with pytest.raises(ValueError, match="must be <= 100"):
        step(ctx)


# --- Boolean field (289-290) ---


def test_validate_body_boolean_valid():
    collection = _make_collection({"active": {"type": "boolean"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"active": True})
    result = step(ctx)
    assert result.body["active"] is True


def test_validate_body_boolean_non_bool():
    collection = _make_collection({"active": {"type": "boolean"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"active": "yes"})
    with pytest.raises(ValueError, match="must be a boolean"):
        step(ctx)


# --- Datetime field (291-292) ---


def test_validate_body_datetime_valid_iso():
    collection = _make_collection({"ts": {"type": "datetime"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"ts": "2025-01-15T10:30:00"})
    result = step(ctx)
    assert result.body["ts"] == "2025-01-15T10:30:00"


def test_validate_body_datetime_invalid_iso():
    collection = _make_collection({"ts": {"type": "datetime"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"ts": "not-a-date"})
    with pytest.raises(ValueError, match="not a valid ISO datetime"):
        step(ctx)


# --- Enum field (293-294) ---


def test_validate_body_enum_valid():
    collection = _make_collection(
        {"role": {"type": "enum", "values": ["admin", "user"]}}
    )
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"role": "admin"})
    result = step(ctx)
    assert result.body["role"] == "admin"


def test_validate_body_enum_invalid():
    collection = _make_collection(
        {"role": {"type": "enum", "values": ["admin", "user"]}}
    )
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"role": "superadmin"})
    with pytest.raises(ValueError, match="must be one of"):
        step(ctx)


# --- Array field (295-296) ---


def test_validate_body_array_valid():
    collection = _make_collection({"tags": {"type": "array"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"tags": [1, 2, 3]})
    result = step(ctx)
    assert result.body["tags"] == [1, 2, 3]


def test_validate_body_array_non_list():
    collection = _make_collection({"tags": {"type": "array"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"tags": "not-a-list"})
    with pytest.raises(ValueError, match="must be an array"):
        step(ctx)


# --- Object field (297-298) ---


def test_validate_body_object_valid():
    collection = _make_collection({"meta": {"type": "object"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"meta": {"key": "val"}})
    result = step(ctx)
    assert result.body["meta"] == {"key": "val"}


def test_validate_body_object_non_dict():
    collection = _make_collection({"meta": {"type": "object"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"meta": [1, 2]})
    with pytest.raises(ValueError, match="must be an object"):
        step(ctx)


# --- Login without identity collection (299) ---


def test_validate_body_login_without_identity_raises():
    collection = _make_collection()
    with pytest.raises(ValueError, match="identity collection"):
        ValidateBodyStep(collection, "login", identity_collection=None)


# --- Login validation (300) ---


def test_validate_body_login_identifier_and_password_required():
    identity = _make_identity()
    collection = _make_collection()
    step = ValidateBodyStep(collection, "login", identity)
    ctx = _make_ctx(body={})
    with pytest.raises(ValueError, match="Missing required fields"):
        step(ctx)


# --- Password injected for identity create (301) ---


def test_validate_body_password_injected_for_identity_create():
    identity = _make_identity()
    collection = _make_collection({"email": {"type": "string", "required": True}})
    step = ValidateBodyStep(collection, "create", identity)
    ctx = _make_ctx(body={"email": "a@b.com", "password": "secret"})
    result = step(ctx)
    assert result.body["password"] == "secret"


def test_validate_body_identity_create_missing_password():
    identity = _make_identity()
    collection = _make_collection({"email": {"type": "string", "required": True}})
    step = ValidateBodyStep(collection, "create", identity)
    ctx = _make_ctx(body={"email": "a@b.com"})
    with pytest.raises(ValueError, match="Missing required fields"):
        step(ctx)


# --- id type fields skipped (302) ---


def test_validate_body_id_type_fields_skipped():
    collection = _make_collection({"id": {"type": "id"}, "title": {"type": "string"}})
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"title": "hello"})
    result = step(ctx)
    assert result.body["title"] == "hello"


# --- _auth field skipped (303) ---


def test_validate_body_auth_field_skipped():
    collection = _make_collection(
        {"_auth": {"type": "object"}, "title": {"type": "string"}}
    )
    step = ValidateBodyStep(collection, "create")
    ctx = _make_ctx(body={"title": "hello"})
    result = step(ctx)
    assert result.body["title"] == "hello"
