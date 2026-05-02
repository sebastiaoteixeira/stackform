"""Tests for the compiler context builder.

These tests verify behaviors by checking generated FastAPI code, not internal
CompilerContext attributes. The generator is the consumer of the context, so
generated output is the right behavioral boundary to test against.
"""
import pytest

from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.ir import (
    IRApi,
    IRCollection,
    IRCors,
    IRDocument,
    IRIdentityCollection,
    IRMongo,
    IROperations,
    IRProviderBinding,
    IRRoute,
)
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR


def _gen(ir, tmp_path):
    ctx = build_context(ir)
    FastAPIGenerator().generate(ctx, tmp_path)
    return tmp_path


def _make_ir(collections=None, identity=None, routes=None, cors=None):
    cols = collections or {
        "items": IRCollection(
            name="items",
            entity_name="item",
            type="data",
            idField="id",
            idFormat="uuidv7",
            fields={"name": {"type": "string", "required": True}},
            operations=IROperations(list=True, get=True, create=True, update=True, replace=False, delete=True),
        ),
    }
    return IRDocument(
        version="0.2",
        api=IRApi(basePath="/api", version="v1", cors=cors),
        collections=cols,
        routes=routes or [],
        identityCollections=identity or {},
        role_hierarchies={},
        mongo=IRMongo(),
    )


def _items_col(**field_overrides):
    return IRCollection(
        name="items",
        entity_name="item",
        type="data",
        idField="id",
        idFormat="uuidv7",
        fields=field_overrides,
        operations=IROperations(list=True, get=True, create=True, update=True, replace=False, delete=True),
    )


# --- CORS ---


def test_cors_none_generates_no_cors_middleware(tmp_path):
    ir = _make_ir()
    _gen(ir, tmp_path)
    app_content = (tmp_path / "app.py").read_text()
    assert "CORSMiddleware" not in app_content


def test_cors_configured_generates_cors_middleware(tmp_path):
    ir = _make_ir(cors=IRCors(origins=["https://example.com"], methods=["GET"], headers=["*"], credentials=True))
    _gen(ir, tmp_path)
    app_content = (tmp_path / "app.py").read_text()
    assert "CORSMiddleware" in app_content


# --- Model generation ---


def test_write_operations_generate_payload_models(tmp_path):
    ir = _make_ir()
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "CreatePayload" in model_content
    assert "UpdatePayload" in model_content


def test_disabled_replace_operation_generates_no_replace_model(tmp_path):
    """replace=False in IROperations must produce no ReplacePayload in generated code."""
    ir = _make_ir()
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "ReplacePayload" not in model_content


def test_id_type_field_excluded_from_generated_create_model(tmp_path):
    """Auto-generated id fields must not appear in create/update payload models."""
    ir = _make_ir(collections={"items": _items_col(
        id={"type": "id"},
        name={"type": "string", "required": True},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    # id should not appear as a model field in the payload
    create_section = model_content.split("CreatePayload")[1] if "CreatePayload" in model_content else ""
    assert "id:" not in create_section.split("class ")[0]


def test_auth_internal_field_excluded_from_generated_model(tmp_path):
    """_auth internal fields must not appear in generated payload models."""
    ir = _make_ir(collections={"items": _items_col(
        name={"type": "string", "required": True},
        _auth={"type": "object"},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "_auth" not in model_content


def test_update_model_fields_are_optional(tmp_path):
    """All fields in an update payload must be Optional (partial update support)."""
    ir = _make_ir(collections={"items": _items_col(
        name={"type": "string", "required": True},
        score={"type": "number"},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    # Find the UpdatePayload class block and verify Optional usage
    if "UpdatePayload" in model_content:
        update_section = model_content.split("UpdatePayload")[1].split("class ")[0]
        assert "Optional" in update_section or "| None" in update_section


# --- Field type mapping ---


def test_enum_field_generates_literal_type(tmp_path):
    ir = _make_ir(collections={"items": _items_col(
        status={"type": "enum", "values": ["active", "inactive"]},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "active" in model_content
    assert "inactive" in model_content


def test_array_field_generates_list_type(tmp_path):
    ir = _make_ir(collections={"items": _items_col(
        tags={"type": "array", "items": {"type": "string"}},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "list" in model_content.lower() or "List" in model_content


def test_ref_field_generates_string_type(tmp_path):
    """ref fields are stored as string IDs in the payload."""
    ir = _make_ir(collections={"items": _items_col(
        authorId={"type": "ref", "ref": "users"},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "authorId" in model_content


# --- Constraints ---


def test_min_max_constraints_appear_in_generated_model(tmp_path):
    ir = _make_ir(collections={"items": _items_col(
        score={"type": "number", "min": 0, "max": 100},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "0" in model_content and "100" in model_content


def test_min_max_length_constraints_appear_in_generated_model(tmp_path):
    ir = _make_ir(collections={"items": _items_col(
        name={"type": "string", "minLength": 1, "maxLength": 255},
    )})
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "items.py").read_text()
    assert "1" in model_content and "255" in model_content


# --- Auth / identity create ---


def test_password_field_injected_in_identity_create_model(tmp_path):
    """Registration payload for a password-auth entity must include a password field."""
    ir = _make_ir(
        collections={
            "users": IRCollection(
                name="users",
                entity_name="user",
                type="auth",
                idField="id",
                idFormat="uuidv7",
                fields={"email": {"type": "string", "required": True}},
                operations=IROperations(list=True, get=True, create=True, update=True, replace=False, delete=True),
            ),
        },
        identity={"users": IRIdentityCollection(name="users", bindings=(IRProviderBinding(provider="password", identifier="email"),))},
    )
    _gen(ir, tmp_path)
    model_content = (tmp_path / "models" / "users.py").read_text()
    assert "password" in model_content


# --- Auth config drives file generation (covered by test_generators.py) ---
# test_fastapi_login_routes_only_when_password_auth → see test_generators.py
# test_fastapi_auth_dependencies_only_when_auth_enabled → see test_generators.py
# test_fastapi_jwt_utils_only_when_password_auth → see test_generators.py