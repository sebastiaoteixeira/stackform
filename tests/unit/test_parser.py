import os

import pytest

from yaml_api_generator.parsers.yaml_parser import (
    ConfigErrors,
    ParseResult,
    _resolve_interpolation,
    load_and_generate_ir,
)
from tests.conftest import VALID_DIR, INVALID_DIR

EXAMPLES_DIR = __import__("pathlib").Path(__file__).parent.parent.parent / "examples"


# --- Existing tests (1: valid YAML loads) ---


def test_basic_crud_collections() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml"))
    ir = result.ir
    assert "posts" in ir.collections
    col = ir.collections["posts"]
    assert "title" in col.fields
    ops = {r.operation for r in ir.routes}
    assert "list" in ops
    assert "replace" not in ops


def test_basic_crud_routes() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml")).ir
    methods = {r.method for r in ir.routes}
    assert "GET" in methods
    assert "POST" in methods
    assert "DELETE" in methods
    ops = {r.operation for r in ir.routes}
    assert "login" not in ops
    assert "register" not in ops


def test_auth_password_identity() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "auth-password.yaml")).ir
    assert "users" in ir.identityCollections


def test_auth_password_has_login_register_routes() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "auth-password.yaml")).ir
    paths = {r.path for r in ir.routes}
    ops = {r.operation for r in ir.routes}
    assert "login" in ops
    assert any("register" in p for p in paths)


def test_entity_inheritance_fields_merged() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "entity-inheritance.yaml")).ir
    col = ir.collections["posts"]
    assert "id" in col.fields
    assert "createdAt" in col.fields
    assert "title" in col.fields


def test_abstract_entity_not_in_collections() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "entity-inheritance.yaml")).ir
    assert "base" not in ir.collections
    for col in ir.collections.values():
        assert col.entity_name != "base"


def test_roles_hierarchy_in_ir() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "roles-access.yaml")).ir
    assert "user" in ir.role_hierarchies
    user_h = ir.role_hierarchies["user"]
    assert "admin" in user_h
    assert "moderator" in user_h["admin"]


def test_access_rules_on_routes() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "roles-access.yaml")).ir
    delete_route = next(
        r for r in ir.routes if r.operation == "delete" and "posts" in r.path
    )
    assert delete_route.access_rules is not None
    assert any(r.required_role == "admin" for r in delete_route.access_rules)


def test_natural_pk() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "natural-pk.yaml")).ir
    col = ir.collections["countries"]
    assert col.idField == "code"


def test_mongo_from_yaml() -> None:
    ir = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml")).ir
    assert ir.mongo.database == "testdb"
    assert "27017" in ir.mongo.uri


# --- Test 2: Invalid YAML syntax → YAML_PARSE_ERROR ---


def test_yaml_syntax_error_raises_parse_error() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "malformed-yaml.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_PARSE_ERROR" in codes
    err = exc_info.value.errors[0]
    assert "line:" in err.path or "col:" in err.path


# --- Test 3: Empty file → treated as {} ---


def test_empty_file_treated_as_empty_dict() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "empty-file.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_PARSE_ERROR" not in codes
    assert "SCHEMA_VALIDATION_ERROR" in codes


# --- Test 4: File with only comments → treated as {} ---


def test_comments_only_file_treated_as_empty_dict() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "comments-only.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_PARSE_ERROR" not in codes
    assert "SCHEMA_VALIDATION_ERROR" in codes


# --- Test 5: YAML root is a list → YAML_ROOT_INVALID ---


def test_yaml_root_is_list_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "root-is-list.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_ROOT_INVALID" in codes


# --- Test 6: YAML root is a scalar → YAML_ROOT_INVALID ---


def test_yaml_root_is_scalar_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "root-is-scalar.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_ROOT_INVALID" in codes


# --- Test 7: File not found → OSError propagates ---


def test_file_not_found_raises_os_error() -> None:
    with pytest.raises(OSError):
        load_and_generate_ir("/nonexistent/path/to/file.yaml")


# --- Test 8: ${VAR} with env set → substituted ---


def test_env_var_substituted_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_MONGO_URI", "mongodb://custom:27017")
    result = load_and_generate_ir(str(VALID_DIR / "env-interpolation.yaml"))
    assert result.ir.mongo.uri == "mongodb://custom:27017"


# --- Test 9: ${VAR} with env not set, no default → INTERPOLATION_MISSING_VAR ---


def test_env_var_missing_no_default_raises() -> None:
    os.environ.pop("MISSING_VAR_NO_DEFAULT", None)
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "env-missing-var.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "INTERPOLATION_MISSING_VAR" in codes


# --- Test 10: ${VAR:-default} with env not set → uses "default" ---


def test_env_var_default_used_when_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_MONGO_URI", raising=False)
    monkeypatch.delenv("TEST_DB_NAME", raising=False)
    result = load_and_generate_ir(str(VALID_DIR / "env-interpolation.yaml"))
    assert result.ir.mongo.uri == "mongodb://localhost:27017"
    assert result.ir.mongo.database == "testdb"


# --- Test 11: ${VAR:-} with env not set → uses empty string ---


def test_env_var_empty_default_resolves_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMPTY_VAR", raising=False)
    errors: list = []
    result = _resolve_interpolation({"key": "${EMPTY_VAR:-}"}, tuple(), errors)
    assert result["key"] == ""


# --- Test 12: ${VAR:-default} with env set to empty string → uses empty string ---


def test_env_var_empty_string_wins_over_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_VAR", "")
    errors: list = []
    result = _resolve_interpolation({"key": "${MY_VAR:-fallback}"}, tuple(), errors)
    assert result["key"] == ""


# --- Test 13: Multiple vars in same string → all resolved ---


def test_multiple_vars_in_same_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "dbserver")
    monkeypatch.setenv("PORT", "5432")
    errors: list = []
    result = _resolve_interpolation({"uri": "${HOST}:${PORT}"}, tuple(), errors)
    assert result["uri"] == "dbserver:5432"


# --- Test 14: Vars in dict values → resolved ---


def test_vars_in_dict_values_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "resolved_value")
    errors: list = []
    result = _resolve_interpolation({"outer": {"inner": "${MY_KEY}"}}, tuple(), errors)
    assert result["outer"]["inner"] == "resolved_value"


# --- Test 15: Vars in list items → resolved ---


def test_vars_in_list_items_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ITEM_A", "alpha")
    monkeypatch.setenv("ITEM_B", "beta")
    errors: list = []
    result = _resolve_interpolation(
        {"items": ["${ITEM_A}", "${ITEM_B}"]}, tuple(), errors
    )
    assert result["items"] == ["alpha", "beta"]


# --- Test 16: Non-string values (int, bool, None) → unchanged ---


def test_non_string_values_unchanged() -> None:
    errors: list = []
    result = _resolve_interpolation(
        {"int_val": 42, "bool_val": True, "null_val": None}, tuple(), errors
    )
    assert result["int_val"] == 42
    assert result["bool_val"] is True
    assert result["null_val"] is None
    assert errors == []


# --- Test 17: Deeply nested vars → resolved ---


def test_deeply_nested_vars_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEP_VAR", "deep_value")
    errors: list = []
    result = _resolve_interpolation(
        {"a": {"b": {"c": {"d": "${DEEP_VAR}"}}}}, tuple(), errors
    )
    assert result["a"]["b"]["c"]["d"] == "deep_value"


# --- Test 17b: Nested reference inside a default resolves fully ---


def test_default_with_reference_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OUTER", raising=False)
    monkeypatch.setenv("INNER", "inner_value")
    errors: list = []
    result = _resolve_interpolation({"key": "${OUTER:-${INNER}}"}, tuple(), errors)
    assert result["key"] == "inner_value"
    assert errors == []


def test_default_with_reference_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OUTER", raising=False)
    monkeypatch.setenv("KEY", "dbkey")
    errors: list = []
    result = _resolve_interpolation(
        {"key": "prefix-${OUTER:-${KEY}}-suffix"}, tuple(), errors
    )
    assert result["key"] == "prefix-dbkey-suffix"
    assert errors == []


# --- Test 17c: Env value that itself contains a reference resolves ---


def test_env_value_containing_reference_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("A", "${B}")
    monkeypatch.setenv("B", "b_value")
    errors: list = []
    result = _resolve_interpolation({"key": "${A}"}, tuple(), errors)
    assert result["key"] == "b_value"
    assert errors == []


# --- Test 17d: Escaped braces in a default produce literal braces ---


def test_escaped_braces_in_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("J", raising=False)
    errors: list = []
    result = _resolve_interpolation({"key": r"${J:-foo\}bar}"}, tuple(), errors)
    assert result["key"] == "foo}bar"
    assert errors == []


def test_escaped_braces_outside_tokens_preserved() -> None:
    errors: list = []
    result = _resolve_interpolation({"key": r"a \{ b \} c"}, tuple(), errors)
    assert result["key"] == "a { b } c"
    assert errors == []


# --- Test 17e: Malformed tokens flagged rather than emitted verbatim ---


def test_malformed_token_empty_var_flagged() -> None:
    errors: list = []
    _resolve_interpolation({"key": "x${}y"}, tuple(), errors)
    assert [e.code for e in errors] == ["INTERPOLATION_MALFORMED_TOKEN"]


# --- Trust: idp warning channel ---


def test_idp_minimal_produces_audience_defaulted_warning() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "auth-oidc-idp-minimal.yaml"))
    warning_codes = {w.code for w in result.warnings}
    assert "TRUST_IDP_AUDIENCE_DEFAULTED" in warning_codes
    assert all(w.severity == "warning" for w in result.warnings)


def test_idp_with_explicit_audiences_produces_no_warning() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "auth-oidc-idp.yaml"))
    warning_codes = {w.code for w in result.warnings}
    assert "TRUST_IDP_AUDIENCE_DEFAULTED" not in warning_codes


def test_idp_audiences_stored_in_ir() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "auth-oidc-idp.yaml"))
    provider = result.ir.providers["keycloak"]
    assert provider.audiences == ("my-app",)  # type: ignore[union-attr]


def test_idp_minimal_audiences_empty_in_ir() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "auth-oidc-idp-minimal.yaml"))
    provider = result.ir.providers["keycloak"]
    assert provider.audiences == ()  # type: ignore[union-attr]


def test_warning_does_not_raise_and_build_succeeds() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "auth-oidc-idp-minimal.yaml"))
    assert result.ir is not None
    assert any(w.code == "TRUST_IDP_AUDIENCE_DEFAULTED" for w in result.warnings)


def test_malformed_token_with_space_flagged() -> None:
    errors: list = []
    _resolve_interpolation({"key": "${MY VAR}"}, tuple(), errors)
    assert [e.code for e in errors] == ["INTERPOLATION_MALFORMED_TOKEN"]


def test_missing_var_reported_once_with_resolved_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRESENT", "ok")
    monkeypatch.delenv("ABSENT", raising=False)
    errors: list = []
    _resolve_interpolation({"key": "${PRESENT}:${ABSENT}"}, tuple(), errors)
    assert [e.code for e in errors] == ["INTERPOLATION_MISSING_VAR"]


# --- Test 18: Interpolation errors halt pipeline ---


def test_interpolation_errors_halt_before_schema_validation() -> None:
    os.environ.pop("MISSING_VAR_NO_DEFAULT", None)
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "env-missing-var.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "INTERPOLATION_MISSING_VAR" in codes
    assert "SCHEMA_VALIDATION_ERROR" not in codes


# --- providers.*.client_secret is now plain build-time interpolation ---


def test_provider_secret_is_build_time_interpolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_SECRET", "s3cr3t")
    errors: list = []
    node = {"providers": {"keycloak": {"client_secret": "${PROVIDER_SECRET}"}}}
    result = _resolve_interpolation(node, tuple(), errors)
    assert result["providers"]["keycloak"]["client_secret"] == "s3cr3t"
    assert errors == []


def test_provider_secret_unset_raises_missing_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROVIDER_SECRET", raising=False)
    errors: list = []
    node = {"providers": {"keycloak": {"client_secret": "${PROVIDER_SECRET}"}}}
    _resolve_interpolation(node, tuple(), errors)
    assert [e.code for e in errors] == ["INTERPOLATION_MISSING_VAR"]


# --- Test 19: No version key → defaults to "0.1" ---


def test_no_version_defaults_to_v01() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(VALID_DIR / "v01-no-version.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "UNSUPPORTED_VERSION" not in codes


# --- Test 20: Version "0.1" → v01 transformer ---


def test_version_01_uses_v01_transformer() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "blog.yaml"))
    assert result.ir.version == "0.1"
    assert "posts" in result.ir.collections
    assert "users" in result.ir.collections


# --- Test 22: Version "9.9" → UNSUPPORTED_VERSION ---


def test_version_unsupported_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "version-unsupported.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "UNSUPPORTED_VERSION" in codes


# --- Test 23: Empty string version → UNSUPPORTED_VERSION ---


def test_version_empty_string_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "version-empty.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "UNSUPPORTED_VERSION" in codes


# --- Test 24: Explicit schema path → used directly ---


def test_explicit_schema_path_used() -> None:
    schema_path = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "src"
        / "yaml_api_generator"
        / "parsers"
        / "schemas"
        / "yaml-spec-v0.1.schema.json"
    )
    result = load_and_generate_ir(
        str(EXAMPLES_DIR / "blog.yaml"), schema_file=str(schema_path)
    )
    assert result.ir.version == "0.1"


# --- Test 25: Schema file unreadable → SCHEMA_LOAD_ERROR ---


def test_schema_file_unreadable_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(
            str(EXAMPLES_DIR / "blog.yaml"),
            schema_file="/nonexistent/schema.json",
        )
    codes = {e.code for e in exc_info.value.errors}
    assert "SCHEMA_LOAD_ERROR" in codes


# --- Test 26: Schema root not dict → SCHEMA_LOAD_ERROR ---


def test_schema_root_not_dict_raises() -> None:
    schema_path = str(INVALID_DIR / "schema-not-dict.json")
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(EXAMPLES_DIR / "blog.yaml"), schema_file=schema_path)
    codes = {e.code for e in exc_info.value.errors}
    assert "SCHEMA_LOAD_ERROR" in codes


# --- Test 27: Schema validation failure → SCHEMA_VALIDATION_ERROR (multiple) ---


def test_schema_validation_failure_multiple_errors() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "schema-validation-fail.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "SCHEMA_VALIDATION_ERROR" in codes
    assert len(exc_info.value.errors) >= 1


# --- Test 28: UI block extracted and preserved ---


def test_ui_block_extracted_and_preserved() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "ui-block.yaml"))
    assert result.ui_block is not None
    assert "dashboard" in result.ui_block
    assert result.ui_block["theme"] == "dark"


# --- Test 29: No UI block → ui_block=None ---


def test_no_ui_block_returns_none() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml"))
    assert result.ui_block is None


# --- Binding relations validation ---


def test_binding_relation_unknown_collection_raises() -> None:
    from yaml_api_generator.parsers.transformers.binding_validation import (
        validate_spec_bindings,
    )

    spec = {
        "entities": {
            "user": {
                "type": "auth",
                "auth": {
                    "bindings": [
                        {
                            "provider": "keycloak",
                            "relations": {
                                "organizationId": {
                                    "collection": "totally_unknown_collection",
                                    "match": {"keycloakOrgId": "organization.*.id"},
                                }
                            },
                        }
                    ]
                },
            },
            "organization": {
                "fields": {"id": {"type": "id"}},
            },
        },
        "repositories": {
            "organizations": {"entity": "organization"},
        },
    }
    errors = validate_spec_bindings(spec)
    assert any(e.code == "BINDING_RELATION_COLLECTION_NOT_FOUND" for e in errors)


def test_binding_relation_known_collection_parses_cleanly() -> None:
    from yaml_api_generator.parsers.transformers.binding_validation import (
        validate_spec_bindings,
    )
    from yaml_api_generator.ir import IRProviderRelation

    spec = {
        "entities": {
            "user": {
                "type": "auth",
                "auth": {
                    "bindings": [
                        {
                            "provider": "keycloak",
                            "relations": {
                                "organizationId": {
                                    "collection": "organizations",
                                    "match": {"keycloakOrgId": "organization.*.id"},
                                }
                            },
                        }
                    ]
                },
            },
            "organization": {
                "fields": {"id": {"type": "id"}},
            },
        },
        "repositories": {
            "organizations": {"entity": "organization"},
        },
    }
    errors = validate_spec_bindings(spec)
    assert errors == []

    relation = IRProviderRelation(
        collection="organizations",
        match={"keycloakOrgId": "organization.*.id"},
    )
    assert relation.collection == "organizations"
    assert relation.match == {"keycloakOrgId": "organization.*.id"}
