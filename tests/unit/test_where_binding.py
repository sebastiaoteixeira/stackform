"""Runtime tests for the v0.3 ``where`` binding form.

A where-bound document is fetched per access rule before authorization; a
predicate that matches no record makes only that rule fail, so the request is
forbidden unless another rule allows it. Grammar and build-time scope tests
live in ``test_where_parser.py``.
"""

import asyncio
import textwrap

import pytest

from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.ir import (
    IRDocumentBinding,
    IRIdentityBinding,
    IRSymbolRef,
    IRWhereConjunct,
)
from yaml_api_generator.ir.when import Equals, FieldRef
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import RuntimeAccessRule
from yaml_api_generator.server.common.steps.authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
    PostFetchAuthorizeStep,
    ResolveWhereBindingsStep,
)

_PRINCIPAL = {"sub": "u1", "identity_collection": "users"}


def _owner_rule(collection="assetCategories", **bindings):
    return RuntimeAccessRule(
        principal="identity:users",
        identity_symbols={"principal": IRIdentityBinding("user", "users")},
        document_symbols={
            "category": IRDocumentBinding(
                collection=collection,
                where=(IRWhereConjunct("slug", IRSymbolRef("categorySlug")),),
            ),
            **bindings,
        },
        when=Equals(FieldRef("category", ("owner",)), FieldRef("principal", ("sub",))),
    )


def _ctx(repo, url_params, principal=_PRINCIPAL):
    return RequestContext(
        method="GET",
        path="/categories/{categorySlug}/assets",
        api_version=None,
        collection="assets",
        operation="list",
        headers={},
        url_params=url_params,
        repository=repo,
        principal=principal,
        body=None,
        response=None,
    )


def _authorize(rules, repo, url_params):
    ctx = asyncio.run(ResolveWhereBindingsStep(rules)(_ctx(repo, url_params)))
    return AuthorizeRouteStep(rules)(ctx)


def test_matching_record_is_bound_to_the_rule_and_allows():
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "u1"}]})
    ctx = _authorize([_owner_rule()], repo, {"categorySlug": "books"})
    assert ctx.where_documents == [{"category": {"slug": "books", "owner": "u1"}}]


def test_matching_record_failing_the_predicate_is_forbidden():
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "other"}]})
    with pytest.raises(ForbiddenError):
        _authorize([_owner_rule()], repo, {"categorySlug": "books"})


def test_missing_record_is_forbidden_not_not_found():
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "u1"}]})
    with pytest.raises(ForbiddenError):
        _authorize([_owner_rule()], repo, {"categorySlug": "missing"})


def test_missing_record_fails_only_its_own_rule():
    repo = InMemoryRepository({"assetCategories": []})
    rules = [_owner_rule(), RuntimeAccessRule(principal="identity:users")]
    ctx = _authorize(rules, repo, {"categorySlug": "missing"})
    assert ctx.where_documents == [{"category": None}, {}]


def test_same_binding_name_in_different_rules_does_not_collide():
    repo = InMemoryRepository({
        "assetCategories": [{"slug": "books", "owner": "u1"}],
        "tags": [{"slug": "books", "owner": "other"}],
    })
    rules = [_owner_rule("assetCategories"), _owner_rule("tags")]
    ctx = _authorize(rules, repo, {"categorySlug": "books"})
    assert ctx.where_documents == [
        {"category": {"slug": "books", "owner": "u1"}},
        {"category": {"slug": "books", "owner": "other"}},
    ]


def test_multi_conjunct_fetches_by_every_criterion():
    rule = RuntimeAccessRule(
        principal="identity:users",
        document_symbols={
            "category": IRDocumentBinding(
                collection="assetCategories",
                where=(
                    IRWhereConjunct("slug", IRSymbolRef("categorySlug")),
                    IRWhereConjunct("tenant", IRSymbolRef("tenantId")),
                ),
            )
        },
    )
    repo = InMemoryRepository({
        "assetCategories": [
            {"slug": "books", "tenant": "t1"},
            {"slug": "books", "tenant": "t2"},
        ]
    })
    ctx = _authorize([rule], repo, {"categorySlug": "books", "tenantId": "t2"})
    assert ctx.where_documents == [{"category": {"slug": "books", "tenant": "t2"}}]


def test_post_fetch_rule_sees_its_where_document():
    rule = _owner_rule(post=IRDocumentBinding(collection="posts", id_param="id"))
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "u1"}]})
    ctx = _authorize([rule], repo, {"categorySlug": "books", "id": "p1"})
    ctx.response = {"id": "p1"}
    assert PostFetchAuthorizeStep([rule])(ctx) is ctx


def test_step_is_a_no_op_without_principal():
    repo = InMemoryRepository({"assetCategories": []})
    ctx = _ctx(repo, {"categorySlug": "books"}, principal=None)
    assert asyncio.run(ResolveWhereBindingsStep([_owner_rule()])(ctx)) is ctx
    assert ctx.where_documents is None


_SPEC = """
    version: "0.3"
    api:
      basePath: /api
      version: v1
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      user:
        type: auth
        auth: { identifier: email, via: password }
        fields:
          id: { type: id }
          email: { type: string }
      assetCategory:
        fields:
          id: { type: id }
          slug: { type: string }
          title: { type: string }
    repositories:
      users: { entity: user }
      assetCategories: { entity: assetCategory }
    services:
      listAssets: { repository: assetCategories, operation: list }
    controllers:
      assets:
        base_path: /categories
        routes:
          listAssets:
            service: listAssets
            method: GET
            path: /{categorySlug}/assets
            access:
              - given:
                  principal: identity:user
                  category: "assetCategories where title = 'salt and pepper' and slug = $categorySlug"
"""


def test_quoted_literal_reaches_the_repository_intact(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(textwrap.dedent(_SPEC))
    runtime = build_runtime_context(load_and_generate_ir(spec_path).ir)
    [route] = [route for route in runtime.routes if route.access_rules]
    repo = InMemoryRepository({
        "assetCategories": [
            {"slug": "books", "title": "salt"},
            {"slug": "books", "title": "salt and pepper"},
        ]
    })
    ctx = asyncio.run(
        ResolveWhereBindingsStep(route.access_rules)(_ctx(repo, {"categorySlug": "books"}))
    )
    assert ctx.where_documents == [{"category": {"slug": "books", "title": "salt and pepper"}}]
