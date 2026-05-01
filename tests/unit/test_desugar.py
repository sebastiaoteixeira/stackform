"""Tests for desugaring behavior.

Structural tests verify the final IR produced by load_and_generate_ir, not the
intermediate desugared dict. Error tests call desugar_v02 directly since they
exercise specific error paths that are easiest to trigger at that layer.
"""
import pytest
import textwrap

from yaml_api_generator.parsers.desugar import desugar_v02
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse(yaml_str: str, tmp_path) -> object:
    """Write yaml_str to a temp file and parse it, returning ir."""
    path = tmp_path / "test.yaml"
    path.write_text(textwrap.dedent(yaml_str))
    return load_and_generate_ir(str(path)).ir


def _base_config() -> dict:
    return {
        "api": {
            "basePath": "/api",
            "version": "v1",
            "operations": {
                "defaults": {"list": True, "get": True, "create": True, "update": True, "replace": False, "delete": True},
                "auth": {"register": True, "login": True},
            },
        },
        "mongo": {"uri": "mongodb://localhost:27017", "database": "testdb"},
        "entities": {},
        "repositories": {},
        "services": {},
        "controllers": {},
    }


# ---------------------------------------------------------------------------
# Entity inheritance — test through IR
# ---------------------------------------------------------------------------


def test_single_level_extends_merges_parent_fields(tmp_path):
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          base:
            abstract: true
            fields:
              id: { type: id }
              createdAt: { type: datetime }
          post:
            extends: base
            fields:
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
    col = ir.collections["posts"]
    assert "id" in col.fields
    assert "createdAt" in col.fields
    assert "title" in col.fields


def test_child_field_overrides_parent_field(tmp_path):
    """Child entity fields take precedence over parent fields with the same name."""
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          base:
            abstract: true
            fields:
              id: { type: id }
              title: { type: string, required: false }
          post:
            extends: base
            fields:
              title: { type: string, required: true }
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
    col = ir.collections["posts"]
    assert col.fields["title"].get("required") is True


def test_multi_level_extends_all_fields_present(tmp_path):
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          a:
            abstract: true
            fields:
              id: { type: id }
          b:
            abstract: true
            extends: a
            fields:
              name: { type: string }
          c:
            extends: b
            fields:
              age: { type: number }
        repositories:
          cs:
            entity: c
        services:
          cs:
            repository: cs
        controllers:
          cs:
            service: cs
            base_path: /cs
            access: public
    """, tmp_path)
    col = ir.collections["cs"]
    assert "id" in col.fields
    assert "name" in col.fields
    assert "age" in col.fields


def test_type_inherited_from_parent(tmp_path):
    """Entities that extend an auth entity should be auth type."""
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          base_auth:
            abstract: true
            type: auth
            auth:
              identifier: email
              via: password
            fields:
              id: { type: id }
              email: { type: string, required: true }
          user:
            extends: base_auth
            fields:
              name: { type: string }
        repositories:
          users:
            entity: user
        services:
          users:
            repository: users
        controllers:
          users:
            service: users
            base_path: /users
            access: "*"
            operations:
              register: { access: public }
              login: { access: public }
    """, tmp_path)
    assert "users" in ir.identityCollections


# ---------------------------------------------------------------------------
# Abstract entities — test through IR
# ---------------------------------------------------------------------------


def test_abstract_entity_not_in_ir_collections(tmp_path):
    ir = _parse("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          base:
            abstract: true
            fields:
              id: { type: id }
          post:
            extends: base
            fields:
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
    assert "base" not in ir.collections
    assert "posts" in ir.collections


# ---------------------------------------------------------------------------
# Error cases — kept at desugar_v02 level (easiest to trigger there)
# ---------------------------------------------------------------------------


def test_extends_self_circular_error():
    config = _base_config()
    config["entities"]["self_ref"] = {"extends": "self_ref", "fields": {"id": {"type": "id"}}}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "ENTITY_CIRCULAR_EXTENDS" for e in exc_info.value.errors)


def test_circular_chain_error():
    config = _base_config()
    config["entities"]["a"] = {"extends": "b", "fields": {"id": {"type": "id"}}}
    config["entities"]["b"] = {"extends": "a", "fields": {"id": {"type": "id"}}}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "ENTITY_CIRCULAR_EXTENDS" for e in exc_info.value.errors)


def test_extends_nonexistent_error():
    config = _base_config()
    config["entities"]["child"] = {"extends": "ghost", "fields": {"id": {"type": "id"}}}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "ENTITY_EXTENDS_NOT_FOUND" for e in exc_info.value.errors)


def test_abstract_entity_referenced_by_repo_error():
    config = _base_config()
    config["entities"]["base"] = {"abstract": True, "fields": {"id": {"type": "id"}}}
    config["repositories"]["bases"] = {"entity": "base"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ABSTRACT_REFERENCED" for e in exc_info.value.errors)


def test_repo_not_found_error():
    config = _base_config()
    config["services"]["posts"] = {"repository": "nonexistent"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_REPO_NOT_FOUND" for e in exc_info.value.errors)


def test_repo_with_no_entity_error():
    config = _base_config()
    config["repositories"]["posts"] = {}
    config["services"]["posts"] = {}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ENTITY_NOT_FOUND" for e in exc_info.value.errors)


def test_entity_not_found_for_repo_error():
    config = _base_config()
    config["repositories"]["posts"] = {"entity": "ghost"}
    config["services"]["posts"] = {}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ENTITY_NOT_FOUND" for e in exc_info.value.errors)


def test_no_matching_services_error():
    config = _base_config()
    config["controllers"]["posts"] = {"service": "nonexistent", "base_path": "/posts", "access": "public"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_SERVICE_NOT_FOUND" for e in exc_info.value.errors)


def test_custom_op_without_method_path_error():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "posts", "operations": {"custom_op": {"handler": "posts.custom"}}}
    config["controllers"]["posts"] = {"service": "posts", "base_path": "/posts", "access": "public", "operations": {"custom_op": {}}}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_CUSTOM_OP_MISSING_ROUTE" for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# Service expansion — test through IR routes
# ---------------------------------------------------------------------------


def test_service_expands_to_crud_routes_in_ir(tmp_path):
    """A service with repository should produce list/get/create/update/delete routes."""
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
    ops = {r.operation for r in ir.routes}
    assert "list" in ops
    assert "create" in ops
    assert "get" in ops
    assert "update" in ops
    assert "delete" in ops


def test_disabled_replace_op_produces_no_replace_route(tmp_path):
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
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    ops = {r.operation for r in ir.routes}
    assert "replace" not in ops


def test_auth_entity_produces_login_and_register_routes(tmp_path):
    ir = _parse("""
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
              id: { type: id }
              email: { type: string, required: true }
        repositories:
          users:
            entity: user
        services:
          users:
            repository: users
        controllers:
          users:
            service: users
            base_path: /users
            access: "*"
            operations:
              register: { access: public }
              login: { access: public }
    """, tmp_path)
    ops = {r.operation for r in ir.routes}
    assert "login" in ops
    assert "create" in ops  # register maps to create


def test_non_auth_entity_produces_no_login_route(tmp_path):
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
    ops = {r.operation for r in ir.routes}
    assert "login" not in ops


# ---------------------------------------------------------------------------
# Controller routing — test through IR routes
# ---------------------------------------------------------------------------


def test_controller_generates_correct_http_methods(tmp_path):
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
    route_map = {r.operation: r for r in ir.routes}
    assert route_map["list"].method == "GET"
    assert route_map["get"].method == "GET"
    assert route_map["create"].method == "POST"
    assert route_map["update"].method == "PATCH"
    assert route_map["delete"].method == "DELETE"


def test_access_override_per_operation_applied(tmp_path):
    """Operations with explicit access should override the controller-level access."""
    ir = _parse("""
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
          post:
            fields:
              id: { type: id }
              title: { type: string }
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
              create: { access: "*" }
    """, tmp_path)
    list_route = next(r for r in ir.routes if r.operation == "list" and "posts" in r.path)
    create_route = next(r for r in ir.routes if r.operation == "create" and "posts" in r.path)
    assert list_route.is_public is True
    assert create_route.is_public is False


def test_disabled_operation_generates_no_route(tmp_path):
    """Setting an operation to false in the controller should omit that route."""
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
            operations:
              delete: false
    """, tmp_path)
    ops = {r.operation for r in ir.routes}
    assert "delete" not in ops


def test_custom_operation_generates_route(tmp_path):
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
            operations:
              publish: { handler: posts.publish }
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
            operations:
              publish: { method: POST, path: "/{id}/publish" }
    """, tmp_path)
    ops = {r.operation for r in ir.routes}
    assert "publish" in ops
    publish_route = next(r for r in ir.routes if r.operation == "publish")
    assert publish_route.method == "POST"
    assert "publish" in publish_route.path