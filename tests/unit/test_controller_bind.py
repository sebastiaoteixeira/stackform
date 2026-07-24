"""Tests for v0.3 controller access-rule ``bind:`` (issue #60).

``bind:`` inside an access rule reuses that rule's ``given:`` scope and supplies
the operation's service inputs post-auth. Its right-hand-side ``$symbols``
resolve against the route's ambient slugs plus the symbols the same rule binds in
``given:`` -- so ``$principal`` resolves only when the rule itself declares
``principal: identity:...`` (there is no ambient principal), and request parts
resolve only through a ``given:`` symbol. An unbound reference aborts generation
with UNDEFINED_SYMBOL. v0.2 specs never carry ``bind:`` and stay byte-identical.
"""

import textwrap

import pytest

from yaml_api_generator.ir import (
    IRIdentityBinding,
    IRLiteralRef,
    IRSymbolRef,
)
from yaml_api_generator.parsers.transformers.symbol_validation import validate_spec_symbols
from yaml_api_generator.parsers.transformers.v02.access_transformer import AccessTransformer
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import RuntimeAccessRule
from yaml_api_generator.server.common.steps.authorization import ResolveAccessBindStep


def _codes(errors):
    return {error.code for error in errors}


# --- transformer ----------------------------------------------------------


def _parse(rule, allow_where=True):
    return AccessTransformer(allow_where=allow_where)._parse_access_rule_object(
        rule, "p", {"user"}, {"user": "users"}
    )


def test_bind_symbol_and_literal_reach_ir():
    rule, errors = _parse(
        {"given": {"principal": "identity:user"}, "bind": {"userId": "$principal.id", "kind": "'post'"}}
    )
    assert errors == []
    assert rule.bind == {
        "userId": IRSymbolRef(root="principal", path=("id",)),
        "kind": IRLiteralRef("post"),
    }


def test_bind_ignored_without_where_flag():
    rule, errors = _parse({"then": "allow", "bind": {"userId": "$principal.id"}}, allow_where=False)
    assert errors == []
    assert rule.bind == {}


# --- build-time symbol resolution -----------------------------------------


def _spec(rule):
    return {
        "version": "0.3",
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "archive": {
                        "service": "archive",
                        "method": "POST",
                        "path": "/{postId}/archive",
                        "access": [rule],
                    }
                },
            }
        },
    }


def test_bind_from_ambient_slug_resolves():
    assert validate_spec_symbols(_spec({"then": "allow", "bind": {"id": "$postId"}})) == []


def test_bind_from_given_principal_resolves():
    spec = _spec({"given": {"principal": "identity:user"}, "bind": {"owner": "$principal.id"}})
    assert validate_spec_symbols(spec) == []


def test_bind_unbound_symbol_aborts():
    errors = validate_spec_symbols(_spec({"then": "allow", "bind": {"id": "$ghost"}}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$ghost" in errors[0].message
    assert "posts' route 'archive' access[0] bind" in errors[0].message


def test_bind_principal_without_given_is_unbound():
    errors = validate_spec_symbols(_spec({"then": "allow", "bind": {"owner": "$principal.id"}}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$principal" in errors[0].message


def test_bind_literal_needs_no_scope():
    assert validate_spec_symbols(_spec({"then": "allow", "bind": {"kind": "'post'"}})) == []


# --- bind covers required service inputs ----------------------------------


def _spec_service(rule, service_input):
    return {
        "version": "0.3",
        "services": {
            "archive": {
                "repository": "posts",
                "operation": "archive",
                "input": service_input,
            }
        },
        "controllers": {
            "posts": {
                "base_path": "/posts",
                "routes": {
                    "archive": {
                        "service": "archive",
                        "method": "POST",
                        "path": "/{postId}/archive",
                        "access": [rule],
                    }
                },
            }
        },
    }


def test_bind_supplying_required_input_resolves():
    spec = _spec_service(
        {"given": {"principal": "identity:user"}, "bind": {"owner": "$principal.id"}},
        {"owner": "string"},
    )
    assert validate_spec_symbols(spec) == []


def test_bind_omitting_required_input_aborts():
    spec = _spec_service(
        {"then": "allow", "bind": {"kind": "'post'"}},
        {"owner": "string"},
    )
    errors = validate_spec_symbols(spec)
    assert _codes(errors) == {"BIND_MISSING_REQUIRED_INPUT"}
    assert "owner" in errors[0].message
    assert "posts' route 'archive' access[0]" in errors[0].message


def test_bind_required_input_satisfied_by_ambient_slug():
    spec = _spec_service(
        {"then": "allow", "bind": {"kind": "'post'"}},
        {"postId": "string"},
    )
    assert validate_spec_symbols(spec) == []


def test_bind_need_not_supply_optional_input():
    spec = _spec_service(
        {"then": "allow", "bind": {"kind": "'post'"}},
        {"cursor": {"type": "string", "required": False}},
    )
    assert validate_spec_symbols(spec) == []


def test_required_input_check_skipped_without_bind():
    spec = _spec_service({"then": "allow"}, {"owner": "string"})
    assert validate_spec_symbols(spec) == []


# --- end to end -----------------------------------------------------------


_SPEC = """
version: "0.3"
api:
  name: test
  basePath: /api
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      id:
        type: id
      email:
        type: string
        required: true
        unique: true
  post:
    fields:
      id:
        type: id
      title:
        type: string
repositories:
  users:
    entity: user
  posts:
    entity: post
    operations:
      archive:
        query:
          command: find
          filter:
            id: "$postId"
services:
  archive:
    repository: posts
    operation: archive
    input:
      owner: string
controllers:
  posts:
    base_path: /posts
    routes:
      archive:
        service: archive
        method: POST
        path: "/{postId}/archive"
        access:
          - given:
              principal: identity:user
            bind:
              owner: $principal.id
"""


def _load(tmp_path, spec=_SPEC):
    path = tmp_path / "spec.yaml"
    path.write_text(textwrap.dedent(spec))
    return load_and_generate_ir(str(path))


def test_bind_reaches_ir_end_to_end(tmp_path):
    document = _load(tmp_path).ir
    route = next(r for r in document.routes if r.operation == "archive")
    rule = route.access_rules[0]
    assert rule.bind == {"owner": IRSymbolRef(root="principal", path=("id",))}


def test_unbound_bind_aborts_end_to_end(tmp_path):
    broken = _SPEC.replace("owner: $principal.id", "owner: $ghost")
    with pytest.raises(ConfigErrors) as exc_info:
        _load(tmp_path, broken)
    assert any(e.code == "UNDEFINED_SYMBOL" for e in exc_info.value.errors)


def test_bind_missing_required_input_aborts_end_to_end(tmp_path):
    broken = _SPEC.replace("owner: $principal.id", "id: $postId")
    with pytest.raises(ConfigErrors) as exc_info:
        _load(tmp_path, broken)
    assert any(
        e.code == "BIND_MISSING_REQUIRED_INPUT" for e in exc_info.value.errors
    )


# --- runtime step ---------------------------------------------------------


def _ctx(url_params, principal=None):
    return RequestContext(
        method="POST",
        path="/api/posts/{postId}/archive",
        api_version=None,
        collection="posts",
        operation="archive",
        headers={},
        url_params=url_params,
        repository=None,
        principal=principal,
        body=None,
        response=None,
    )


def _identity_rule(bind, principal="identity:user"):
    return RuntimeAccessRule(
        principal=principal,
        identity_symbols={"principal": IRIdentityBinding("user", "user")},
        bind=bind,
    )


def test_runtime_binds_slug_into_service_inputs():
    step = ResolveAccessBindStep([RuntimeAccessRule(principal="", bind={"id": IRSymbolRef(root="postId")})])
    ctx = step(_ctx({"postId": "p1"}, principal={"identity_collection": "user"}))
    assert ctx.service_inputs == {"id": "p1"}
    assert ctx.url_params["id"] == "p1"


def test_runtime_binds_principal_field_only_from_given():
    step = ResolveAccessBindStep([_identity_rule({"owner": IRSymbolRef(root="principal", path=("id",))})])
    ctx = step(_ctx({"postId": "p1"}, principal={"identity_collection": "user", "id": "u9"}))
    assert ctx.service_inputs == {"owner": "u9"}


def test_runtime_first_matching_rule_wins():
    other = RuntimeAccessRule(principal="identity:admin", bind={"owner": IRLiteralRef("admin")})
    step = ResolveAccessBindStep([other, _identity_rule({"owner": IRLiteralRef("member")})])
    ctx = step(_ctx({}, principal={"identity_collection": "user"}))
    assert ctx.service_inputs == {"owner": "member"}


def test_runtime_no_rules_is_noop():
    ctx = ResolveAccessBindStep(None)(_ctx({"postId": "p1"}))
    assert ctx.service_inputs is None
