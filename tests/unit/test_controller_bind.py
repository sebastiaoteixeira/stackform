"""Tests for v0.3 controller access-rule ``bind:`` (issue #60).

``bind:`` inside an access rule reuses that rule's ``given:`` scope and supplies
the operation's service inputs post-auth. Its right-hand-side ``$symbols``
resolve against the route's ambient slugs plus the symbols the same rule binds in
``given:`` -- so ``$principal`` resolves only when the rule itself declares
``principal: identity:...`` (there is no ambient principal), and request parts
resolve only through a ``given:`` symbol. An unbound reference aborts generation
with UNDEFINED_SYMBOL. v0.2 specs never carry ``bind:`` and stay byte-identical.
"""

import compileall
import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.ir import (
    IRDocumentBinding,
    IRIdentityBinding,
    IRLiteralRef,
    IRSymbolRef,
    IRWhereConjunct,
)
from yaml_api_generator.parsers.transformers.symbol_validation import validate_spec_symbols
from yaml_api_generator.parsers.transformers.v02.access_transformer import AccessTransformer
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import RuntimeAccessRule
from yaml_api_generator.server.common.steps.authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
    ResolveAccessBindStep,
)
from yaml_api_generator.server.common.steps.services import ServiceInputStep


def _codes(errors):
    return {error.code for error in errors}


# --- transformer ----------------------------------------------------------


def _parse(rule):
    return AccessTransformer(allow_where=True)._parse_access_rule_object(
        rule, "p", {"user"}, {"user": "users"}
    )


def test_bind_symbol_and_literal_reach_ir():
    rule, errors = _parse(
        {
            "given": {"principal": "identity:user"},
            "bind": {"userId": "$principal.sub", "kind": "post", "audit": True},
        }
    )
    assert errors == []
    assert rule.bind == {
        "userId": IRSymbolRef(root="principal", path=("sub",)),
        "kind": IRLiteralRef("post"),
        "audit": IRLiteralRef(True),
    }


# --- build-time symbol resolution -----------------------------------------


def _spec(rule):
    return {
        "version": "0.3",
        "services": {
            "archive": {
                "input": {
                    "id": {"type": "string", "required": False},
                    "owner": {"type": "string", "required": False},
                    "kind": {"type": "string", "required": False},
                }
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


def test_bind_from_ambient_slug_resolves():
    assert validate_spec_symbols(_spec({"then": "allow", "bind": {"id": "$postId"}})) == []


def test_bind_from_given_principal_resolves():
    spec = _spec({"given": {"principal": "identity:user"}, "bind": {"owner": "$principal.sub"}})
    assert validate_spec_symbols(spec) == []


def test_bind_unbound_symbol_aborts():
    errors = validate_spec_symbols(_spec({"then": "allow", "bind": {"id": "$ghost"}}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$ghost" in errors[0].message
    assert "posts' route 'archive' access[0] bind" in errors[0].message


def test_bind_principal_without_given_is_unbound():
    errors = validate_spec_symbols(_spec({"then": "allow", "bind": {"owner": "$principal.sub"}}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$principal" in errors[0].message


def test_bind_literal_needs_no_scope():
    assert validate_spec_symbols(_spec({"then": "allow", "bind": {"kind": "post"}})) == []


def test_bind_target_must_be_declared_service_input():
    errors = validate_spec_symbols(
        _spec({"then": "allow", "bind": {"unknown": "post"}})
    )
    assert _codes(errors) == {"BIND_TARGET_UNKNOWN"}


def test_bind_must_supply_each_required_service_input():
    spec = _spec({"then": "allow", "bind": {"kind": "post"}})
    spec["services"]["archive"]["input"]["owner"]["required"] = True
    errors = validate_spec_symbols(spec)
    assert _codes(errors) == {"BIND_MISSING_REQUIRED_INPUT"}
    assert "owner" in errors[0].message


def test_route_slug_satisfies_required_service_input():
    spec = _spec({"then": "allow", "bind": {"kind": "post"}})
    spec["services"]["archive"]["input"]["postId"] = "string"
    assert validate_spec_symbols(spec) == []


def test_bind_rejects_document_rule():
    errors = validate_spec_symbols(
        _spec(
            {
                "given": {"post": "posts"},
                "bind": {"kind": "post"},
            }
        )
    )
    assert _codes(errors) == {"BIND_DOCUMENT_RULE_UNSUPPORTED"}


def test_bind_rejects_where_document_rule_on_same_route():
    errors = validate_spec_symbols(
        _spec(
            {
                "given": {"post": "posts where id = $postId"},
                "bind": {"kind": "post"},
            }
        )
    )
    assert _codes(errors) == {"BIND_DOCUMENT_RULE_UNSUPPORTED"}


# --- end to end -----------------------------------------------------------


_SPEC = """
version: "0.3"
api:
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
            owner: "$actor"
services:
  archive:
    repository: posts
    operation: archive
    input:
      owner: string
    with:
      actor: $owner
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
              owner: $principal.sub
"""


def _load(tmp_path, spec=_SPEC):
    path = tmp_path / "spec.yaml"
    path.write_text(textwrap.dedent(spec))
    return load_and_generate_ir(str(path))


def test_bind_reaches_ir_end_to_end(tmp_path):
    document = _load(tmp_path).ir
    route = next(r for r in document.routes if r.operation == "archive")
    rule = route.access_rules[0]
    assert rule.bind == {"owner": IRSymbolRef(root="principal", path=("sub",))}


def test_unbound_bind_aborts_end_to_end(tmp_path):
    broken = _SPEC.replace("owner: $principal.sub", "owner: $ghost")
    with pytest.raises(ConfigErrors) as exc_info:
        _load(tmp_path, broken)
    assert any(e.code == "UNDEFINED_SYMBOL" for e in exc_info.value.errors)


def test_v02_bind_aborts_end_to_end(tmp_path):
    spec = tmp_path / "v02-bind.yaml"
    spec.write_text(
        textwrap.dedent(
            """
            version: "0.2"
            api: { basePath: /api }
            entities:
              post:
                fields:
                  id: { type: id }
            repositories:
              posts: { entity: post }
            services:
              posts: { repository: posts }
            controllers:
              posts:
                base_path: /posts
                routes:
                  create:
                    service: posts
                    method: POST
                    path: ""
                    access:
                      - then: allow
                        bind: { actor: "$principal.sub" }
            """
        )
    )

    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(spec))

    assert {error.code for error in exc_info.value.errors} == {"SCHEMA_VALIDATION_ERROR"}


@pytest.mark.parametrize(
    "generator",
    [FastAPIGenerator(), DRFGenerator(), RawASGIGenerator()],
)
def test_generated_targets_compile_with_access_bind(generator, tmp_path):
    context = build_context(_load(tmp_path).ir)
    output = tmp_path / "generated"
    generator.generate(context, output)

    route = next(route for route in context.routes if route.operation == "archive")
    assert route.access_rules[0].bind == {
        "owner": {"symbol": ["principal", "sub"]}
    }
    assert compileall.compile_dir(str(output), quiet=1)


def test_generated_fastapi_applies_authorized_bind_end_to_end(tmp_path):
    context = build_context(_load(tmp_path).ir)
    output = tmp_path / "generated"
    FastAPIGenerator().generate(context, output)
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

        class RecordingRepository:
            async def archive(self, **kwargs):
                return kwargs

        async def principal():
            return {{
                "sub": "u9",
                "identity_collection": "users",
                "roles": [],
                "record": {{"id": "u9"}},
            }}

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_principal] = principal
        app.dependency_overrides[get_posts_repository] = RecordingRepository
        response = TestClient(app).post(
            "/posts/p1/archive", json={{"owner": "spoofed"}}
        )
        assert response.status_code == 200, response.text
        assert response.json() == {{"filter": {{"id": "p1", "owner": "u9"}}}}
        """
    )
    subprocess.run([sys.executable, "-c", script], check=True)


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


def _authorize_and_bind(rules, ctx):
    ctx = AuthorizeRouteStep(rules)(ctx)
    return ResolveAccessBindStep(rules)(ctx)


def test_runtime_binds_slug_into_service_inputs():
    rules = [RuntimeAccessRule(principal="", bind={"id": IRSymbolRef(root="postId")})]
    ctx = _authorize_and_bind(
        rules, _ctx({"postId": "p1"}, principal={"identity_collection": "user"})
    )
    assert ctx.bound_inputs == {"id": "p1"}
    assert ctx.url_params == {"postId": "p1"}


def test_runtime_binds_principal_field_only_from_given():
    rules = [_identity_rule({"owner": IRSymbolRef(root="principal", path=("sub",))})]
    ctx = _authorize_and_bind(
        rules,
        _ctx(
            {"postId": "p1"},
            principal={"identity_collection": "user", "sub": "u9"},
        ),
    )
    assert ctx.bound_inputs == {"owner": "u9"}


def test_runtime_first_matching_rule_wins():
    other = RuntimeAccessRule(principal="identity:admin", bind={"owner": IRLiteralRef("admin")})
    rules = [other, _identity_rule({"owner": IRLiteralRef("member")})]
    ctx = _authorize_and_bind(rules, _ctx({}, principal={"identity_collection": "user"}))
    assert ctx.bound_inputs == {"owner": "member"}


def test_runtime_where_miss_falls_through_to_later_rule_bind():
    predicate = (IRWhereConjunct("id", IRLiteralRef("missing")),)
    missed = RuntimeAccessRule(
        principal="",
        document_symbols={"post": IRDocumentBinding("posts", where=predicate)},
        bind={"owner": IRLiteralRef("wrong")},
    )
    rules = [missed, _identity_rule({"owner": IRLiteralRef("member")})]
    ctx = _ctx({}, principal={"identity_collection": "user"})
    ctx.where_documents = [{"post": None}, {}]

    assert _authorize_and_bind(rules, ctx).bound_inputs == {"owner": "member"}


def test_runtime_denied_rule_never_binds():
    rules = [RuntimeAccessRule(principal="", effect="deny", bind={"owner": IRLiteralRef("bad")})]
    ctx = _ctx({}, principal={"identity_collection": "user"})
    with pytest.raises(ForbiddenError):
        _authorize_and_bind(rules, ctx)
    assert ctx.bound_inputs is None


def test_bound_input_overrides_untrusted_body_before_forwarding():
    rules = [_identity_rule({"owner": IRSymbolRef(root="principal", path=("sub",))})]
    ctx = _ctx({}, principal={"identity_collection": "user", "sub": "u9"})
    ctx.body = {"owner": "spoofed"}
    ctx = _authorize_and_bind(rules, ctx)
    ctx = ServiceInputStep(
        {"owner": {"type": "string"}},
        {"actor": IRSymbolRef(root="owner")},
    )(ctx)
    assert ctx.service_inputs == {"actor": "u9"}


def test_runtime_no_rules_is_noop():
    ctx = ResolveAccessBindStep(None)(_ctx({"postId": "p1"}))
    assert ctx.bound_inputs is None
