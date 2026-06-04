"""Tests for the v0.2 transformer.

Private-function tests (_parse_access_string etc.) have been replaced with
full-parse tests that go through load_and_generate_ir and check the IR output.
Pure utility function tests (_normalize_auth_via, _normalize_operations) are
kept since they test stable function contracts.
"""
import textwrap

import pytest

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.parsers.transformers.v02 import V02Transformer
from tests.conftest import INVALID_DIR, VALID_DIR


def _parse(yaml_str: str, tmp_path):
    path = tmp_path / "test.yaml"
    path.write_text(textwrap.dedent(yaml_str))
    return load_and_generate_ir(str(path)).ir


_MINIMAL_YAML = """
    version: "0.2"
    api:
      basePath: /api
      version: v1
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      post:
        fields:
          id: {{ type: id }}
          title: {{ type: string }}
    repositories:
      posts:
        entity: post
    services:
      posts:
        repository: posts
    controllers:
      posts:
        service: posts
        base_path: /posts
        access: {access}
"""

_AUTH_PREAMBLE = """
    version: "0.2"
    api:
      basePath: /api
      version: v1
      operations:
        auth:
          register: true
          login: true
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      user:
        type: auth
        auth:
          identifier: email
          via: password
        fields:
          id: {type: id}
          email: {type: string, required: true}
          role:
            type: enum
            values: [admin, moderator, user]
            default: user
      post:
        fields:
          id: {type: id}
          title: {type: string}
          authorId: {type: ref, ref: user}
    repositories:
      users:
        entity: user
      posts:
        entity: post
    services:
      users:
        repository: users
      posts:
        repository: posts
"""


# ---- Collection Building ----


def test_71_no_id_field_no_pk_id_field_missing():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "no-id-field.yaml"))
    assert any(e.code == "ID_FIELD_MISSING" for e in exc_info.value.errors)


def test_72_multiple_id_fields_id_field_multiple():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "multiple-id-fields.yaml"))
    assert any(e.code == "ID_FIELD_MULTIPLE" for e in exc_info.value.errors)


def test_73_id_field_config_not_dict_schema_error(tmp_path):
    """A non-dict field config must be caught by schema validation."""
    with pytest.raises(ConfigErrors) as exc_info:
        _parse("""
            version: "0.2"
            api:
              basePath: /api
              version: v1
            mongo:
              uri: mongodb://localhost:27017
              database: testdb
            entities:
              post:
                fields:
                  id: not-a-dict
                  title: {type: string}
            repositories:
              posts:
                entity: post
            services:
              posts:
                repository: posts
            controllers:
              posts:
                service: posts
                base_path: /posts
                access: public
        """, tmp_path)
    assert any(e.code == "SCHEMA_VALIDATION_ERROR" for e in exc_info.value.errors)


def test_74_id_format_uuidv4_parsed_from_yaml():
    ir = load_and_generate_ir(str(VALID_DIR / "uuidv4-id.yaml")).ir
    col = ir.collections["posts"]
    assert col.idFormat == "uuidv4"


def test_77_id_format_invalid_string():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "invalid-id-format.yaml"))
    assert any(e.code == "ID_FORMAT_INVALID" for e in exc_info.value.errors)


def test_78_operations_normalization_repo_overrides_defaults(tmp_path):
    """Repo-level crud list overrides which operations are generated."""
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
          operations:
            defaults:
              list: true
              get: true
              create: true
              update: true
              replace: false
              delete: true
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          post:
            fields:
              id: { type: id }
              title: { type: string }
        repositories:
          posts:
            entity: post
            crud: [list, get, create, update, replace]
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    assert ir.repositories["posts"].crud == ("list", "get", "create", "update", "replace")
    ops = {r.operation for r in ir.routes if "posts" in r.path}
    assert "replace" in ops
    assert "delete" not in ops
    assert "list" in ops


# ---- PK Handling ----


def test_80_pk_field_not_found_in_entity():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "pk-field-not-found.yaml"))
    assert any(e.code == "PK_FIELD_NOT_FOUND" for e in exc_info.value.errors)


# ---- Identity Collection Building ----


def test_82_non_auth_entity_produces_no_identity_collections():
    ir = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml")).ir
    assert len(ir.identityCollections) == 0


def test_83_via_string_normalized_to_list():
    """A string `via` in YAML must produce a list in the IR identity collection."""
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "user": {
                "type": "auth",
                "auth": {"identifier": "email", "via": "password"},
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
    assert len(ic.bindings) == 1
    assert ic.bindings[0].provider == "password"
    assert ic.bindings[0].identifier == "email"


def test_84_via_list_preserved():
    """A list `via` in YAML must produce one binding per provider in the IR identity collection."""
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "user": {
                "type": "auth",
                "auth": {"identifier": "email", "via": ["password", "apiKey"]},
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
    assert {b.provider for b in ic.bindings} == {"password", "apiKey"}


def test_85_via_other_type_empty_list():
    """An invalid `via` type must not crash — identity collection bindings defaults to empty."""
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "user": {
                "type": "auth",
                "auth": {"identifier": "email", "via": 42},
                "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
            }
        },
        "repositories": {"users": {"entity": "user"}},
        "services": {},
        "controllers": {},
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    assert ir.identityCollections["users"].bindings == ()


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
    assert ic.bindings == ()


def test_87_roles_field_stored_in_identity_collection():
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


# ---- Implicit Auth Field Validation ----


def test_90_password_field_forbidden_with_password_auth():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "auth-password-field-forbidden.yaml"))
    assert any(e.code == "AUTH_PASSWORD_FIELD_FORBIDDEN" for e in exc_info.value.errors)


def test_91_password_hash_field_forbidden_with_password_auth():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "auth-password-hash-field-forbidden.yaml"))
    assert any(e.code == "AUTH_PASSWORD_HASH_FIELD_FORBIDDEN" for e in exc_info.value.errors)


def test_92_no_password_in_via_allows_password_field():
    """API-key-only auth must not forbid a field named 'password'."""
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


# ---- Access Rule Parsing — tested through full IR ----


def test_93_none_access_produces_public_route(tmp_path):
    ir = _parse(_MINIMAL_YAML.format(access="public"), tmp_path)
    route = next(r for r in ir.routes if r.operation == "list")
    assert route.is_public is True
    assert route.access_rules is None


def test_94_public_string_produces_public_route(tmp_path):
    ir = _parse(_MINIMAL_YAML.format(access="public"), tmp_path)
    route = next(r for r in ir.routes if r.operation == "list")
    assert route.is_public is True


def test_95_star_produces_non_public_route_with_no_rules(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: "*"
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    assert list_route.is_public is False
    assert list_route.access_rules is None


def test_96_authenticated_legacy_produces_non_public_route(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: authenticated
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    assert list_route.is_public is False


def test_97_identity_entity_resolves_to_collection_in_access_rule(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: "identity:user"
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    assert list_route.is_public is False
    assert list_route.access_rules is not None
    # entity "user" must resolve to collection "users"
    assert any(r.principal == "identity:users" for r in list_route.access_rules)


def test_98_identity_unknown_entity_error(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _parse(
            _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: "identity:nonexistent"
    """, tmp_path
        )
    assert any(e.code == "ACCESS_UNKNOWN_ENTITY" for e in exc_info.value.errors)


def test_99_scoped_role_parsed_into_principal_and_role(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: "user:admin"
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    assert list_route.access_rules is not None
    rule = list_route.access_rules[0]
    assert rule.principal == "identity:users"
    assert rule.required_role == "admin"


def test_100_entity_star_resolves_without_role(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: "user:*"
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    rule = list_route.access_rules[0]
    assert rule.principal == "identity:users"
    assert rule.required_role is None


def test_101_unscoped_role_resolves_against_single_auth_entity(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: admin
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    rule = list_route.access_rules[0]
    assert rule.principal == "identity:users"
    assert rule.required_role == "admin"


def test_102_unscoped_role_with_no_auth_entities_raises_error():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}},
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {"list-posts": {"repository": "posts", "operation": "list"}},
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "list": {"service": "list-posts", "method": "GET", "path": "", "access": "admin"},
                },
            },
        },
        "mongo": {},
    }
    with pytest.raises(ConfigErrors) as exc_info:
        V02Transformer().transform(config)
    assert any(e.code == "ACCESS_NO_AUTH_ENTITY" for e in exc_info.value.errors)


def test_103_unscoped_role_with_multiple_auth_entities_raises_ambiguous_error(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _parse("""
    version: "0.2"
    api:
      basePath: /api
      version: v1
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      user:
        type: auth
        auth:
          identifier: email
          via: password
        fields:
          id: { type: id }
          email: { type: string, required: true }
      apiClient:
        type: auth
        auth:
          identifier: clientId
          via: apiKey
        fields:
          id: { type: id }
          clientId: { type: string, required: true }
      post:
        fields:
          id: { type: id }
          title: { type: string }
    repositories:
      users:
        entity: user
      apiClients:
        entity: apiClient
      posts:
        entity: post
    services:
      users:
        repository: users
      apiClients:
        repository: apiClients
      posts:
        repository: posts
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      apiClients:
        service: apiClients
        base_path: /clients
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: admin
    """, tmp_path)
    assert any(e.code == "ACCESS_AMBIGUOUS_ROLE" for e in exc_info.value.errors)


def test_104_list_of_roles_produces_multiple_access_rules(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: [user:admin, user:moderator]
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    roles = {r.required_role for r in list_route.access_rules}
    assert "admin" in roles
    assert "moderator" in roles


def test_105_rule_dict_with_given_principal_and_then_allow(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access:
          - given:
              principal: identity:user
            then: allow
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    assert list_route.access_rules is not None
    assert list_route.access_rules[0].effect == "allow"


def test_107_given_principal_entity_resolved_to_collection(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access:
          - given:
              principal: identity:user
            then: allow
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    rule = list_route.access_rules[0]
    assert rule.principal == "identity:users"


def test_108_rule_with_when_expression_parsed(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: public
        operations:
          delete:
            access:
              - given:
                  principal: identity:user
                  document: posts
                when: principal.sub equals document.authorId
    """, tmp_path
    )
    delete_route = next(r for r in ir.routes if r.operation == "delete" and "posts" in r.path)
    assert delete_route.access_rules is not None
    rule = delete_route.access_rules[0]
    assert rule.when is not None


def test_109_then_deny_produces_deny_effect(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: public
        operations:
          delete:
            access:
              - given:
                  principal: identity:user
                  document: posts
                when: principal.sub not equals document.authorId
                then: deny
    """, tmp_path
    )
    delete_route = next(r for r in ir.routes if r.operation == "delete" and "posts" in r.path)
    assert delete_route.access_rules[0].effect == "deny"


def test_110_default_effect_is_allow(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access:
          - given:
              principal: identity:user
    """, tmp_path
    )
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    assert list_route.access_rules[0].effect == "allow"


def test_111_document_binding_in_rule_resolved(tmp_path):
    ir = _parse(
        _AUTH_PREAMBLE + """
    controllers:
      users:
        service: users
        base_path: /users
        access: "*"
        operations:
          register: { access: public }
          login: { access: public }
      posts:
        service: posts
        base_path: /posts
        access: public
        operations:
          delete:
            access:
              - given:
                  principal: identity:user
                  document: posts
                when: principal.sub equals document.authorId
    """, tmp_path
    )
    delete_route = next(r for r in ir.routes if r.operation == "delete" and "posts" in r.path)
    rule = delete_route.access_rules[0]
    assert rule.document_symbols
    assert rule.document_symbols["document"].collection == "posts"


# ---- Role Hierarchy ----


def test_113_roles_hierarchy_unknown_entity():
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "roles-unknown-entity.yaml"))
    assert any(e.code == "ROLES_UNKNOWN_ENTITY" for e in exc_info.value.errors)


def test_114_empty_roles_section_produces_empty_hierarchies():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {"post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}}},
        "repositories": {"posts": {"entity": "post"}},
        "services": {},
        "controllers": {},
        "mongo": {},
        "roles": {},
    }
    ir = V02Transformer().transform(config)
    assert ir.role_hierarchies == {}


# ---- Route Building ----


def test_115_route_path_combines_base_path_version_and_controller_path(tmp_path):
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          post:
            fields:
              id: { type: id }
              title: { type: string }
        repositories:
          posts:
            entity: post
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    list_route = next(r for r in ir.routes if r.operation == "list")
    assert list_route.path == "/api/v1/posts"


def test_116_no_api_version_omits_version_segment(tmp_path):
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          post:
            fields:
              id: { type: id }
              title: { type: string }
        repositories:
          posts:
            entity: post
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    list_route = next(r for r in ir.routes if r.operation == "list")
    assert list_route.path == "/api/posts"


# ---- API & Mongo Config ----


def test_120_cors_config_parsed_with_defaults(tmp_path):
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
          cors:
            origins: ["https://example.com"]
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          post:
            fields:
              id: { type: id }
              title: { type: string }
        repositories:
          posts:
            entity: post
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    assert ir.api.cors is not None
    assert "https://example.com" in ir.api.cors.origins
    assert ir.api.cors.credentials is False


def test_123_mongo_defaults_applied_when_section_empty():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {"post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}}},
        "repositories": {"posts": {"entity": "post"}},
        "services": {},
        "controllers": {},
        "mongo": {},
    }
    ir = V02Transformer().transform(config)
    assert ir.mongo.uri == "mongodb://localhost:27017"
    assert ir.mongo.database == "yaml_api"


def test_124_mongo_defaults_applied_when_section_missing():
    config = {
        "version": "0.2",
        "api": {"operations": {"defaults": {}}},
        "entities": {"post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}}},
        "repositories": {"posts": {"entity": "post"}},
        "services": {},
        "controllers": {},
    }
    ir = V02Transformer().transform(config)
    assert ir.mongo.uri == "mongodb://localhost:27017"
    assert ir.mongo.database == "yaml_api"


# ---- Name Validation ----

from yaml_api_generator.parsers.transformers.name_validation import validate_spec_names


def _codes(spec):
    return {e.code for e in validate_spec_names(spec)}


def test_125_field_name_python_keyword_rejected():
    spec = {"entities": {"post": {"fields": {"class": {"type": "string"}}}}}
    assert "INVALID_FIELD_NAME" in _codes(spec)


def test_126_field_name_shadowing_pydantic_api_rejected():
    spec = {"entities": {"post": {"fields": {"model_config": {"type": "string"}}}}}
    assert "INVALID_FIELD_NAME" in _codes(spec)


def test_127_field_name_model_prefix_rejected():
    spec = {"entities": {"post": {"fields": {"model_dump": {"type": "string"}}}}}
    assert "INVALID_FIELD_NAME" in _codes(spec)


def test_128_field_name_schema_rejected():
    spec = {"entities": {"post": {"fields": {"schema": {"type": "string"}}}}}
    assert "INVALID_FIELD_NAME" in _codes(spec)


def test_129_entity_name_python_keyword_rejected():
    spec = {"entities": {"import": {"fields": {"id": {"type": "id"}}}}}
    assert "INVALID_NAME" in _codes(spec)


def test_130_repository_name_python_keyword_rejected():
    spec = {"repositories": {"import": {"entity": "post"}}}
    assert "INVALID_NAME" in _codes(spec)


def test_131_service_name_python_keyword_rejected():
    spec = {"services": {"return": {"repository": "posts"}}}
    assert "INVALID_NAME" in _codes(spec)


def test_132_controller_name_python_keyword_rejected():
    spec = {"controllers": {"lambda": {"service": "posts"}}}
    assert "INVALID_NAME" in _codes(spec)


def test_133_provider_name_not_identifier_validated():
    """Provider names appear only as route-path segments and as sanitized
    identifiers (py_identifier), so hyphenated or keyword names are accepted."""
    assert "INVALID_NAME" not in _codes({"providers": {"def": {"type": "oidc"}}})
    assert "INVALID_NAME" not in _codes({"providers": {"my-oidc": {"type": "oidc"}}})


def test_134_name_shadowing_pydantic_api_rejected():
    spec = {"repositories": {"schema": {"entity": "post"}}}
    assert "INVALID_NAME" in _codes(spec)


def test_135_soft_keyword_name_rejected():
    spec = {"entities": {"match": {"fields": {"id": {"type": "id"}}}}}
    assert "INVALID_NAME" in _codes(spec)


def test_136_valid_names_accepted():
    spec = {
        "entities": {"post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}}},
        "repositories": {"posts": {"entity": "post"}},
        "services": {"posts": {"repository": "posts"}},
        "controllers": {"posts": {"service": "posts"}},
    }
    assert validate_spec_names(spec) == []


def test_137_keyword_field_rejected_end_to_end(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _parse("""
            version: "0.2"
            api:
              basePath: /api
              version: v1
            mongo:
              uri: mongodb://localhost:27017
              database: testdb
            entities:
              post:
                fields:
                  id: { type: id }
                  class: { type: string }
            repositories:
              posts:
                entity: post
            services:
              posts:
                repository: posts
            controllers:
              posts:
                service: posts
                base_path: /posts
                access: public
        """, tmp_path)
    assert "INVALID_FIELD_NAME" in {e.code for e in exc_info.value.errors}


def test_138_keyword_repository_rejected_end_to_end(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _parse("""
            version: "0.2"
            api:
              basePath: /api
              version: v1
            mongo:
              uri: mongodb://localhost:27017
              database: testdb
            entities:
              post:
                fields:
                  id: { type: id }
                  title: { type: string }
            repositories:
              import:
                entity: post
            services:
              posts:
                repository: import
            controllers:
              posts:
                service: posts
                base_path: /posts
                access: public
        """, tmp_path)
    assert "INVALID_NAME" in {e.code for e in exc_info.value.errors}
