"""v0.3 uniform undefined-symbol enforcement.

Every ``$<symbol>`` resolves against the names bound in its scope; an unbound
reference aborts with the single ``UNDEFINED_SYMBOL`` error naming the symbol and
the scope. Enforced now at the two sites that exist on this branch -- ``when``
operands and repository query filters. v0.2 keeps its ambient behavior
(``WHEN_UNBOUND_SYMBOL`` and an ambient ``$principal`` in filters) unchanged.
"""
import textwrap

import pytest

from yaml_api_generator.parsers.transformers.access_validation import validate_spec_access
from yaml_api_generator.parsers.transformers.symbol_validation import validate_spec_symbols
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

_ENTITIES = {
    "user": {
        "type": "auth",
        "auth": {"identifier": "email", "via": "password"},
        "roles": {"values": ["admin", "editor"], "default": "editor"},
        "fields": {"id": {"type": "id"}},
    },
}


def _access_errors(controllers, version):
    spec = {"version": version, "entities": _ENTITIES, "controllers": controllers}
    return validate_spec_access(spec)


def _codes(errors):
    return {error.code for error in errors}


def _unbound_when(version):
    controllers = {"c": {"operations": {"get": {"access": [{
        "given": {"principal": "identity:user"},
        "when": "ghost.sub equals 'x'",
    }]}}}}
    return _access_errors(controllers, version)


def test_v03_unbound_when_operand_aborts():
    assert _codes(_unbound_when("0.3")) == {"UNDEFINED_SYMBOL"}


def test_v03_when_bound_via_given_resolves():
    controllers = {"c": {"operations": {"get": {"access": [{
        "given": {"principal": "identity:user"},
        "when": "principal.sub equals 'x'",
    }]}}}}
    assert _access_errors(controllers, "0.3") == []


def test_v03_when_error_message_names_symbol_and_scope():
    [error] = [e for e in _unbound_when("0.3") if e.code == "UNDEFINED_SYMBOL"]
    assert "$ghost" in error.message
    assert "controllers.c.operations.get.access[0] when" in error.message


def test_v02_unbound_when_keeps_legacy_code():
    assert _codes(_unbound_when("0.2")) == {"WHEN_UNBOUND_SYMBOL"}


def test_v03_given_without_when_resolves():
    controllers = {"c": {"operations": {"get": {"access": [{
        "given": {"principal": "identity:user"},
    }]}}}}
    assert _access_errors(controllers, "0.3") == []


def test_v03_empty_when_list_resolves():
    controllers = {"c": {"operations": {"get": {"access": [{
        "given": {"principal": "identity:user"},
        "when": [],
    }]}}}}
    assert _access_errors(controllers, "0.3") == []


def _filter_spec(query_filter, route_path):
    return {
        "repositories": {"orders": {"entity": "order", "operations": {
            "byOwner": {"query": {"command": "find", "filter": query_filter}},
        }}},
        "services": {"byOwner": {"repository": "orders", "operation": "byOwner"}},
        "controllers": {"orders": {"base_path": "/orders", "routes": {
            "byOwner": {
                "service": "byOwner", "method": "GET",
                "path": route_path, "access": "public",
            },
        }}},
    }


def test_v03_principal_in_repository_filter_aborts():
    errors = validate_spec_symbols(_filter_spec({"ownerId": "$principal.record"}, "/by-owner"))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$principal" in errors[0].message
    assert "repository 'orders' operation 'byOwner' filter" in errors[0].message


def test_v03_route_slug_in_repository_filter_resolves():
    assert validate_spec_symbols(_filter_spec({"_id": "$orderId"}, "/{orderId}")) == []


_REPO_FILTER_SPEC = """
    version: "{version}"
    api:
      basePath: /api
      version: v1
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      order:
        fields:
          id: {{ type: id }}
          ownerId: {{ type: string }}
    repositories:
      orders:
        entity: order
        operations:
          byOwner:
            query:
              command: find
              filter: {{ ownerId: "$principal.record" }}
    services:
      byOwner: {{ repository: orders, operation: byOwner }}
    controllers:
      orders:
        base_path: /orders
        routes:
          byOwner: {{ service: byOwner, method: GET, path: /by-owner, access: public }}
"""


def _load(version, tmp_path):
    path = tmp_path / f"spec-{version}.yaml"
    path.write_text(textwrap.dedent(_REPO_FILTER_SPEC.format(version=version)))
    return load_and_generate_ir(str(path))


def test_v03_repository_filter_principal_aborts_end_to_end(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _load("0.3", tmp_path)
    assert any(e.code == "UNDEFINED_SYMBOL" for e in exc_info.value.errors)


def test_v02_repository_filter_principal_still_builds(tmp_path):
    assert _load("0.2", tmp_path).ir.version == "0.2"
