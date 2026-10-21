"""Tests for role requirements and where-bound records in access rules.

Roles are granted through the ``<entity>:<role>`` shorthand; a long-form rule
carries no ``role:`` key and is rejected by the schema.
"""

import pytest
import yaml

from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
from yaml_api_generator.generators.backend.fastapi.access_filters import rule_to_predicate
from yaml_api_generator.runtime import access
from yaml_api_generator.runtime.access import EVERY_ROW, NO_ROW
from yaml_api_generator.parsers.transformers.access_validation import validate_spec_access
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def test_role_compiles_to_a_principal_role_guard():
    condition = rule_to_predicate(
        AccessRuleDescriptor(principal="identity:users", required_role="org-admin")
    )
    scope = {**vars(access), "_principal_has_role": lambda principal, role: role in principal["roles"]}
    assert eval(condition, {**scope, "principal": {"identity_collection": "users", "roles": ["org-admin"]}}) == EVERY_ROW
    assert eval(condition, {**scope, "principal": {"identity_collection": "users", "roles": []}}) == NO_ROW
    assert eval(condition, {**scope, "principal": {"identity_collection": "admins", "roles": ["org-admin"]}}) == NO_ROW


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
                bind:
                  organizationId: $principal.record.organizationId
"""


@pytest.mark.parametrize("version", ["0.2", "0.3"])
def test_long_form_role_rejected_by_schema(tmp_path, version):
    spec = yaml.safe_load(_SPEC)
    spec["version"] = version
    rule = spec["controllers"]["posts"]["routes"]["listScoped"]["access"][0]
    rule["role"] = "org-admin"
    if version == "0.2":
        spec["services"]["listPosts"].pop("input")
        spec["services"]["listPosts"].pop("with")
        rule.pop("bind")
    path = tmp_path / "api.yaml"
    path.write_text(yaml.safe_dump(spec))

    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(path)

    assert [(error.code, "'role' was unexpected" in error.message) for error in exc_info.value.errors] == [
        ("SCHEMA_VALIDATION_ERROR", True)
    ]


def test_where_bound_document_is_available_to_create_rule():
    spec = yaml.safe_load(_SPEC)
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
    spec = yaml.safe_load(_SPEC)
    route = spec["controllers"]["posts"]["routes"].pop("listScoped")
    route["access"][0]["given"]["scope"] = "posts"
    route["access"][0]["when"] = (
        "scope.organizationId equals principal.record.organizationId"
    )
    spec["controllers"]["posts"]["operations"] = {"create": route}

    assert "ACCESS_RULE_INVALID" in {
        error.code for error in validate_spec_access(spec)
    }
