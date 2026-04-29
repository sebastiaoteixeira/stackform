import pytest

from yaml_api_generator.parsing.parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.parsing.transformers.v02 import (
    V02Transformer,
    _normalize_auth_via,
    _normalize_operations,
    _parse_access_rule_object,
    _parse_access_string,
    _parse_access_value,
    _resolve_id_format,
    _validate_roles_field,
)
from tests.conftest import INVALID_DIR, VALID_DIR


_AUTH_ENTITIES = {"user"}
_ENTITY_TO_COLLECTION = {"user": "users"}


def _transform_minimal(**overrides):
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {},
        "controllers": {},
        "mongo": {},
    }
    config.update(overrides)
    return V02Transformer().transform(config)


# ---- Collection Building (71-78) ----


def test_71_no_id_field_no_pk_id_field_missing():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "no-id-field.yaml"))
    assert any(e.code == "ID_FIELD_MISSING" for e in exc_info.value.errors)


def test_72_multiple_id_fields_id_field_multiple():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "multiple-id-fields.yaml"))
    assert any(e.code == "ID_FIELD_MULTIPLE" for e in exc_info.value.errors)


def test_73_id_field_config_not_dict_id_field_invalid():
    _, errors = _resolve_id_format("testEntity", "id", {"id": "not-a-dict"})
    assert len(errors) == 1
    assert errors[0].code == "ID_FIELD_INVALID"


def test_74_id_format_uuidv4_valid():
    ir = load_and_generate_ir(str(VALID_DIR / "uuidv4-id.yaml")).ir
    col = ir.collections["posts"]
    assert col.idFormat == "uuidv4"


def test_77_id_format_invalid_string():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "invalid-id-format.yaml"))
    assert any(e.code == "ID_FORMAT_INVALID" for e in exc_info.value.errors)


def test_78_operations_normalization_defaults_and_repo_overrides():
    defaults = {
        "list": True,
        "get": True,
        "create": True,
        "update": True,
        "replace": False,
        "delete": True,
    }
    repo_ops = {"replace": True, "delete": False}
    result = _normalize_operations(defaults, repo_ops)
    assert result.replace is True
    assert result.delete is False
    assert result.list is True
    assert result.get is True
    assert result.create is True
    assert result.update is True


# ---- PK Handling (80) ----


def test_80_pk_field_not_found_in_entity():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "pk-field-not-found.yaml"))
    assert any(e.code == "PK_FIELD_NOT_FOUND" for e in exc_info.value.errors)


# ---- Identity Collection Building (82-89) ----


def test_82_non_auth_entity_no_identity_collection():
    ir = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml")).ir
    assert len(ir.identityCollections) == 0


def test_83_via_string_normalized_to_list():
    assert _normalize_auth_via("password") == ["password"]


def test_84_via_list_preserved():
    assert _normalize_auth_via(["password", "apiKey"]) == ["password", "apiKey"]


def test_85_via_other_type_empty_list():
    assert _normalize_auth_via(42) == []
    assert _normalize_auth_via(None) == []


def test_86_auth_data_not_dict_safe_defaults():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "user": {
                "type": "auth",
                "auth": "not-a-dict",
                "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
            }
        },
        "repositories": {"users": {"entity": "user"}},
        "services": {},
        "controllers": {},
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    ic = ir.identityCollections["users"]
    assert ic.identifier is None
    assert ic.via == []


def test_87_roles_field_valid_stored():
    ir = load_and_generate_ir(str(VALID_DIR / "roles-access.yaml")).ir
    ic = ir.identityCollections["users"]
    assert ic.roles_field == "role"


def test_88_roles_field_not_found_in_entity():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "auth-roles-field-not-found.yaml"))
    assert any(e.code == "AUTH_ROLES_FIELD_NOT_FOUND" for e in exc_info.value.errors)


def test_89_roles_field_not_enum_type():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "auth-roles-field-not-enum.yaml"))
    assert any(e.code == "AUTH_ROLES_FIELD_NOT_ENUM" for e in exc_info.value.errors)


# ---- Implicit Auth Field Validation (90-92) ----


def test_90_password_field_forbidden_with_password_auth():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "auth-password-field-forbidden.yaml"))
    assert any(e.code == "AUTH_PASSWORD_FIELD_FORBIDDEN" for e in exc_info.value.errors)


def test_91_password_hash_field_forbidden_with_password_auth():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(
            str(INVALID_DIR / "auth-password-hash-field-forbidden.yaml")
        )
    assert any(
        e.code == "AUTH_PASSWORD_HASH_FIELD_FORBIDDEN" for e in exc_info.value.errors
    )


def test_92_no_password_in_via_no_validation():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "client": {
                "type": "auth",
                "auth": {"identifier": "clientId", "via": "apiKey"},
                "fields": {
                    "id": {"type": "id"},
                    "clientId": {"type": "string", "required": True},
                    "password": {"type": "string"},
                },
            }
        },
        "repositories": {"clients": {"entity": "client"}},
        "services": {},
        "controllers": {},
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    assert "clients" in ir.identityCollections


# ---- Access Rule Parsing (93-111) ----


def test_93_none_access_is_public():
    is_public, rules, errors = _parse_access_value(
        None, "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is True
    assert rules is None
    assert errors == []


def test_94_public_string_is_public():
    is_public, rules, errors = _parse_access_value(
        "public", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is True
    assert rules is None


def test_95_star_is_authenticated_no_rules():
    is_public, rules, errors = _parse_access_value(
        "*", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is False
    assert rules is None


def test_96_authenticated_legacy_compat():
    is_public, rules, errors = _parse_access_value(
        "authenticated", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is False
    assert rules is None


def test_97_identity_entity_resolves_to_collection():
    rule, errors = _parse_access_string(
        "identity:user", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert errors == []
    assert rule is not None
    assert rule.principal == "identity:users"


def test_98_identity_unknown_entity_error():
    rule, errors = _parse_access_string(
        "identity:nonexistent", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert len(errors) == 1
    assert errors[0].code == "ACCESS_UNKNOWN_ENTITY"


def test_99_entity_role_parsed():
    rule, errors = _parse_access_string(
        "user:admin", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert errors == []
    assert rule is not None
    assert rule.principal == "identity:users"
    assert rule.required_role == "admin"


def test_100_entity_star_no_role():
    rule, errors = _parse_access_string(
        "user:*", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert errors == []
    assert rule is not None
    assert rule.principal == "identity:users"
    assert rule.required_role is None


def test_101_unscoped_role_single_auth_resolved():
    rule, errors = _parse_access_string(
        "admin", "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert errors == []
    assert rule is not None
    assert rule.principal == "identity:users"
    assert rule.required_role == "admin"


def test_102_unscoped_role_no_auth_entities():
    rule, errors = _parse_access_string("admin", "path", set(), {})
    assert len(errors) == 1
    assert errors[0].code == "ACCESS_NO_AUTH_ENTITY"


def test_103_unscoped_role_multiple_auth_ambiguous():
    multi_auth = {"user", "apiClient"}
    multi_map = {"user": "users", "apiClient": "clients"}
    rule, errors = _parse_access_string("admin", "path", multi_auth, multi_map)
    assert len(errors) == 1
    assert errors[0].code == "ACCESS_AMBIGUOUS_ROLE"


def test_104_list_of_strings_multiple_rules():
    access = ["user:admin", "user:moderator"]
    is_public, rules, errors = _parse_access_value(
        access, "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is False
    assert errors == []
    assert rules is not None
    assert len(rules) == 2
    assert rules[0].required_role == "admin"
    assert rules[1].required_role == "moderator"


def test_105_list_of_dicts_rule_objects():
    access = [{"given": {"principal": "identity:user"}, "then": "allow"}]
    is_public, rules, errors = _parse_access_value(
        access, "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is False
    assert errors == []
    assert rules is not None
    assert len(rules) == 1
    assert rules[0].effect == "allow"


def test_106_empty_list_no_rules():
    is_public, rules, errors = _parse_access_value(
        [], "path", _AUTH_ENTITIES, _ENTITY_TO_COLLECTION
    )
    assert is_public is False
    assert rules is None


def test_107_rule_object_given_principal_resolved():
    rule, errors = _parse_access_rule_object(
        {"given": {"principal": "identity:user"}, "then": "allow"},
        "path",
        _AUTH_ENTITIES,
        _ENTITY_TO_COLLECTION,
    )
    assert errors == []
    assert rule is not None
    assert rule.principal == "identity:users"


def test_108_rule_object_when_expression_parsed():
    rule, errors = _parse_access_rule_object(
        {
            "given": {"principal": "identity:user"},
            "when": "principal.sub equals document.authorId",
        },
        "path",
        _AUTH_ENTITIES,
        _ENTITY_TO_COLLECTION,
    )
    assert errors == []
    assert rule is not None
    assert rule.when is not None


def test_109_rule_object_then_deny():
    rule, errors = _parse_access_rule_object(
        {"given": {"principal": "identity:user"}, "then": "deny"},
        "path",
        _AUTH_ENTITIES,
        _ENTITY_TO_COLLECTION,
    )
    assert errors == []
    assert rule is not None
    assert rule.effect == "deny"


def test_110_rule_object_then_allow_default():
    rule, errors = _parse_access_rule_object(
        {"given": {"principal": "identity:user"}},
        "path",
        _AUTH_ENTITIES,
        _ENTITY_TO_COLLECTION,
    )
    assert errors == []
    assert rule is not None
    assert rule.effect == "allow"


def test_111_rule_object_document_binding_parsed():
    rule, errors = _parse_access_rule_object(
        {
            "given": {
                "principal": "identity:user",
                "document": "posts",
            },
            "when": "principal.sub equals document.authorId",
        },
        "path",
        _AUTH_ENTITIES,
        _ENTITY_TO_COLLECTION,
    )
    assert errors == []
    assert rule is not None
    assert rule.document_symbols
    assert rule.document_symbols["document"].collection == "posts"


# ---- Role Hierarchy (113-114) ----


def test_113_roles_hierarchy_unknown_entity():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "roles-unknown-entity.yaml"))
    assert any(e.code == "ROLES_UNKNOWN_ENTITY" for e in exc_info.value.errors)


def test_114_empty_roles_section_empty_hierarchies():
    ir = _transform_minimal(roles={})
    assert ir.role_hierarchies == {}


# ---- Route Building (115-118) ----


def test_115_base_path_version_controller_base_route_path():
    config = {
        "version": "0.2",
        "api": {
            "basePath": "/api",
            "version": "v1",
            "operations": {"defaults": {}},
        },
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {
            "list-posts": {"repository": "posts", "operation": "list"},
        },
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "list": {
                        "service": "list-posts",
                        "method": "GET",
                        "path": "",
                        "access": "public",
                    },
                },
            },
        },
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    assert len(ir.routes) == 1
    assert ir.routes[0].path == "/api/v1/posts"


def test_116_no_version_no_version_segment():
    config = {
        "version": "0.2",
        "api": {"basePath": "/api", "operations": {"defaults": {}}},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {
            "list-posts": {"repository": "posts", "operation": "list"},
        },
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "list": {
                        "service": "list-posts",
                        "method": "GET",
                        "path": "",
                        "access": "public",
                    },
                },
            },
        },
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    assert ir.routes[0].path == "/api/posts"


def test_117_service_lookup_collection_handler_operation():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {
            "get-posts": {"repository": "posts", "operation": "get"},
        },
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "get": {
                        "service": "get-posts",
                        "method": "GET",
                        "path": "/{id}",
                        "access": "public",
                    },
                },
            },
        },
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    route = ir.routes[0]
    assert route.collection == "posts"
    assert route.operation == "get"
    assert route.service == "get-posts"


def test_118_service_not_found_none_values():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {},
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "list": {
                        "service": "nonexistent",
                        "method": "GET",
                        "path": "",
                        "access": "public",
                    },
                },
            },
        },
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    route = ir.routes[0]
    assert route.collection is None
    assert route.handler is None


# ---- API & Mongo Config (120-124) ----


def test_120_cors_config_parsing_with_defaults():
    ir = _transform_minimal(
        api={
            "cors": {"origins": ["https://example.com"]},
            "operations": {"defaults": {}},
        }
    )
    assert ir.api.cors is not None
    assert ir.api.cors.origins == ["https://example.com"]
    assert ir.api.cors.methods == ["*"]
    assert ir.api.cors.headers == ["*"]
    assert ir.api.cors.credentials is False


def test_121_cors_non_dict_returns_none():
    ir = _transform_minimal(api={"cors": "invalid", "operations": {"defaults": {}}})
    assert ir.api.cors is None


def test_122_port_string_int_conversion():
    ir = _transform_minimal(api={"port": "9000", "operations": {"defaults": {}}})
    assert ir.api.port == 9000


def test_123_mongo_defaults():
    ir = _transform_minimal(mongo={})
    assert ir.mongo.uri == "mongodb://localhost:27017"
    assert ir.mongo.database == "yaml_api"


def test_124_no_mongo_section_defaults():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {},
        "controllers": {},
    }
    ir = V02Transformer().transform(config)
    assert ir.mongo.uri == "mongodb://localhost:27017"
    assert ir.mongo.database == "yaml_api"
