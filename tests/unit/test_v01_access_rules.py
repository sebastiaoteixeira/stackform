"""0.1 access rules bind the record a ``when`` names as ``document``."""

import pytest

from yaml_api_generator.ir import IRDocumentBinding
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

SPEC = """
version: "0.1"
mongo: {{ uri: "mongodb://localhost", database: blog }}
collections:
  users:
    type: auth
    auth: {{ identifier: email, via: password }}
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
  posts:
    access:
      {operation}:
        - principal: "users:*"
          when: "principal.sub equals document.ownerId"
    fields:
      id: {{ type: id }}
      ownerId: {{ type: string }}
"""


def _parse(tmp_path, operation):
    path = tmp_path / "spec.yaml"
    path.write_text(SPEC.format(operation=operation))
    return load_and_generate_ir(path)


@pytest.mark.parametrize("operation", ["list", "get", "update", "replace", "delete"])
def test_when_document_binds_the_routes_record(tmp_path, operation):
    routes = _parse(tmp_path, operation).ir.routes
    [rule] = next(route for route in routes if route.collection == "posts" and route.operation == operation).access_rules
    assert rule.document_symbols == {"document": IRDocumentBinding(collection="posts")}


def test_create_rule_naming_document_is_refused(tmp_path):
    with pytest.raises(ConfigErrors) as raised:
        _parse(tmp_path, "create")
    assert [(error.code, error.path) for error in raised.value.errors] == [
        ("ACCESS_RULE_INVALID", "collections.posts.access.create[0].when")
    ]
