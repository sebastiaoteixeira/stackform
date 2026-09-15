"""Tests for v0.3 access-rule ``role:``.

The ``<entity>:<role>`` shorthand carries a role but no ``bind:``, so a route
that both gates on a role and supplies its service inputs from the principal was
previously inexpressible. ``role:`` moves the role requirement onto the long
rule form, where it compiles to the same ``_principal_has_role`` guard and
composes with ``given:``, ``when:`` and ``bind:``.
"""

import compileall
import subprocess
import sys
import textwrap

import pytest
import yaml

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.access_filters import rule_to_python
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.transformers.access_validation import (
    validate_spec_access,
    warn_public_routes,
)
from yaml_api_generator.parsers.transformers.v02.access_transformer import AccessTransformer
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _parse(rule, allow_where=True):
    return AccessTransformer(allow_where=allow_where)._parse_access_rule_object(
        rule, "p", {"user"}, {"user": "users"}
    )


def test_role_reaches_ir_alongside_bind():
    rule, errors = _parse(
        {
            "given": {"principal": "identity:user"},
            "role": "org-admin",
            "bind": {"organizationId": "$principal.record.organizationId"},
        }
    )
    assert errors == []
    assert rule.required_role == "org-admin"
    assert rule.principal == "identity:users"


def test_role_rejected_without_v03_feature_gate():
    _, errors = _parse({"given": {"principal": "identity:user"}, "role": "admin"}, allow_where=False)
    assert [error.code for error in errors] == ["ACCESS_ROLE_UNSUPPORTED"]


def test_role_requires_an_identity_binding():
    rule, errors = _parse({"then": "allow", "role": "admin"})
    assert rule is None
    assert [error.code for error in errors] == ["ACCESS_ROLE_WITHOUT_IDENTITY"]


def test_role_compiles_to_a_principal_role_guard():
    condition = rule_to_python(
        AccessRuleDescriptor(principal="identity:users", required_role="org-admin")
    )
    assert condition == (
        'principal.get("identity_collection") == "users" '
        'and _principal_has_role(principal, "org-admin")'
    )


_SPEC = """
    version: "0.3"
    entities:
      user:
        type: auth
        auth:
          identifier: id
          via: password
          roles: roles
        fields:
          id: { type: id }
          organizationId: { type: string }
          roles: { type: enum, values: [org-admin], readonly: true }
      post:
        fields:
          id: { type: id }
          organizationId: { type: string }
    repositories:
      users:
        entity: user
      posts:
        entity: post
        operations:
          listScoped:
            query:
              command: find
              filter:
                organizationId: $organizationId
    services:
      listPosts:
        repository: posts
        operation: listScoped
        input:
          organizationId: string
        with:
          organizationId: $organizationId
    controllers:
      posts:
        base_path: /posts
        routes:
          listScoped:
            method: GET
            path: ""
            service: listPosts
            access:
              - given:
                  principal: identity:user
                role: ROLE
                bind:
                  organizationId: $principal.record.organizationId
"""


def test_declared_role_passes_validation():
    assert validate_spec_access(yaml.safe_load(_SPEC.replace("ROLE", "org-admin"))) == []


def test_undeclared_role_is_rejected():
    errors = validate_spec_access(yaml.safe_load(_SPEC.replace("ROLE", "ghost-admin")))
    assert [error.code for error in errors] == ["ACCESS_RULE_INVALID"]
    assert "ghost-admin" in errors[0].message


def test_v03_full_spec_load_preserves_role_and_bind(tmp_path):
    path = tmp_path / "api.yaml"
    path.write_text(_SPEC.replace("ROLE", "org-admin"))

    rule = load_and_generate_ir(path).ir.routes[0].access_rules[0]

    assert rule.required_role == "org-admin"
    assert set(rule.bind) == {"organizationId"}


@pytest.mark.parametrize(
    ("generator", "route_path"),
    [
        (FastAPIGenerator(), "routes/posts.py"),
        (DRFGenerator(), "api/views/posts.py"),
        (RawASGIGenerator(), "routes/posts.py"),
    ],
)
def test_all_generated_backends_enforce_long_form_role(
    generator, route_path, tmp_path
):
    path = tmp_path / "api.yaml"
    path.write_text(_SPEC.replace("ROLE", "org-admin"))
    output = tmp_path / generator.__class__.__name__

    generator.generate(build_context(load_and_generate_ir(path).ir), output)

    assert compileall.compile_dir(str(output), quiet=1)
    route_source = (output / route_path).read_text()
    assert "_principal_has_role" in route_source
    assert '"org-admin"' in route_source


def test_generated_fastapi_enforces_role_before_applying_bind(tmp_path):
    path = tmp_path / "api.yaml"
    path.write_text(_SPEC.replace("ROLE", "org-admin"))
    output = tmp_path / "generated"
    FastAPIGenerator().generate(
        build_context(load_and_generate_ir(path).ir), output
    )
    script = textwrap.dedent(
        f"""
        import os
        import sys

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies.auth import require_principal
        from dependencies.repositories import get_posts_repository
        from routes.posts import router

        class Repository:
            async def listScoped(self, **kwargs):
                return kwargs

        current = {{
            "sub": "u1",
            "identity_collection": "users",
            "roles": [],
            "record": {{"organizationId": "org-1"}},
        }}

        async def principal():
            return current

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_principal] = principal
        app.dependency_overrides[get_posts_repository] = Repository
        client = TestClient(app)

        denied = client.get("/posts")
        assert denied.status_code == 403, denied.text

        current["roles"] = ["org-admin"]
        allowed = client.get("/posts")
        assert allowed.status_code == 200, allowed.text
        assert allowed.json() == {{"filter": {{"organizationId": "org-1"}}}}
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_v02_full_spec_load_rejects_long_form_role(tmp_path):
    path = tmp_path / "api.yaml"
    spec = yaml.safe_load(_SPEC.replace("ROLE", "org-admin"))
    spec["version"] = "0.2"
    spec["services"]["listPosts"].pop("input")
    spec["services"]["listPosts"].pop("with")
    spec["controllers"]["posts"]["routes"]["listScoped"]["access"][0].pop("bind")
    path.write_text(yaml.safe_dump(spec))

    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(path)

    assert "ACCESS_ROLE_UNSUPPORTED" in {error.code for error in exc_info.value.errors}


def test_where_bound_document_is_available_to_create_rule():
    spec = yaml.safe_load(_SPEC.replace("ROLE", "org-admin"))
    route = spec["controllers"]["posts"]["routes"].pop("listScoped")
    route["method"] = "POST"
    route["access"][0]["given"]["scope"] = (
        "posts where organizationId = $principal.record.organizationId"
    )
    route["access"][0]["when"] = (
        "scope.organizationId equals principal.record.organizationId"
    )
    spec["controllers"]["posts"]["operations"] = {"create": route}

    assert validate_spec_access(spec) == []


def test_implicit_current_document_remains_unavailable_to_create_rule():
    spec = yaml.safe_load(_SPEC.replace("ROLE", "org-admin"))
    route = spec["controllers"]["posts"]["routes"].pop("listScoped")
    route["access"][0]["given"]["scope"] = "posts"
    route["access"][0]["when"] = (
        "scope.organizationId equals principal.record.organizationId"
    )
    spec["controllers"]["posts"]["operations"] = {"create": route}

    assert "ACCESS_RULE_INVALID" in {
        error.code for error in validate_spec_access(spec)
    }


def test_different_roles_are_not_contradictory_rules():
    spec = yaml.safe_load(_SPEC.replace("ROLE", "org-admin"))
    rules = spec["controllers"]["posts"]["routes"]["listScoped"]["access"]
    spec["entities"]["user"]["fields"]["roles"]["values"].append("auditor")
    rules.append({**rules[0], "role": "auditor", "then": "deny"})

    assert validate_spec_access(spec) == []


def test_role_only_rule_is_not_reported_as_public():
    spec = yaml.safe_load(_SPEC.replace("ROLE", "org-admin"))

    assert "PUBLIC_ROUTE" not in {
        warning.code for warning in warn_public_routes(spec)
    }
