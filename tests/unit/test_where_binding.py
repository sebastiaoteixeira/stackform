"""Tests for the v0.3 ``where`` binding form used as a ``given:`` value.

Covers the parser, the v0.3-only gating through the access transformer, the
UNDEFINED_SYMBOL enforcement of RHS symbols, the runtime predicate fetch with a
404-on-miss, and the v0.2 regression that document bindings keep their implicit
fetch unchanged.
"""

import asyncio
from typing import Any

import pytest

from yaml_api_generator.ir import (
    IRDocumentBinding,
    IRIdentityBinding,
    IRLiteralRef,
    IRSymbolRef,
    IRWhereConjunct,
)
from yaml_api_generator.ir.when import Equals, FieldRef
from yaml_api_generator.parsers.where_parser import parse_where_binding
from yaml_api_generator.parsers.transformers.v02.access_transformer import AccessTransformer
from yaml_api_generator.parsers.transformers.symbol_validation import validate_spec_symbols
from yaml_api_generator.server.common.repositories.base import BaseRepository
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import RuntimeAccessRule
from yaml_api_generator.server.common.steps import NotFoundError
from yaml_api_generator.server.common.steps.authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
    ResolveWhereBindingsStep,
)


class InMemoryRepository(BaseRepository):
    def __init__(self, data: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._data = data or {}

    def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        return list(self._data.get(collection_name, []))

    async def get(self, collection_name: str, document_id: str) -> dict[str, Any] | None:
        return None

    async def create(self, collection_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    async def update(self, collection_name, document_id, payload):
        return None

    async def replace(self, collection_name, document_id, payload):
        return None

    async def delete(self, collection_name, document_id):
        return None

    async def find_one(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        for record in self._data.get(collection_name, []):
            if all(record.get(field) == value for field, value in criteria.items()):
                return record
        return None


def _codes(errors):
    return {error.code for error in errors}


# --- parser ---------------------------------------------------------------


def test_where_parser_single_conjunct_binds_symbol():
    parsed, errors = parse_where_binding(
        "assetCategories where slug = $categorySlug", "p"
    )
    assert errors == []
    collection, conjuncts = parsed
    assert collection == "assetCategories"
    assert conjuncts == (IRWhereConjunct("slug", IRSymbolRef("categorySlug")),)


def test_where_parser_multi_conjunct():
    parsed, errors = parse_where_binding(
        "docs where a = $x and b = $y", "p"
    )
    assert errors == []
    _, conjuncts = parsed
    assert conjuncts == (
        IRWhereConjunct("a", IRSymbolRef("x")),
        IRWhereConjunct("b", IRSymbolRef("y")),
    )


def test_where_parser_dotted_symbol_and_literals():
    parsed, _ = parse_where_binding(
        "docs where owner = $principal.record.id", "p"
    )
    _, conjuncts = parsed
    assert conjuncts == (IRWhereConjunct("owner", IRSymbolRef("principal", ("record", "id"))),)

    parsed, _ = parse_where_binding("docs where status = 'open'", "p")
    _, conjuncts = parsed
    assert conjuncts == (IRWhereConjunct("status", IRLiteralRef("open")),)

    parsed, _ = parse_where_binding("docs where count = 3", "p")
    _, conjuncts = parsed
    assert conjuncts == (IRWhereConjunct("count", IRLiteralRef(3)),)


def test_where_parser_reserved_operator_aborts():
    parsed, errors = parse_where_binding("docs where x != $y", "p")
    assert parsed is None
    assert _codes(errors) == {"WHERE_OPERATOR_UNSUPPORTED"}


@pytest.mark.parametrize("operator", ["<", "<=", ">", ">=", "in"])
def test_where_parser_all_reserved_operators_abort(operator):
    _, errors = parse_where_binding(f"docs where x {operator} 3", "p")
    assert _codes(errors) == {"WHERE_OPERATOR_UNSUPPORTED"}


def test_where_parser_malformed_aborts():
    _, errors = parse_where_binding("docs where slug", "p")
    assert _codes(errors) == {"WHERE_BINDING_INVALID"}


# --- transformer gating ---------------------------------------------------


def _parse_given(value, allow_where):
    transformer = AccessTransformer(allow_where=allow_where)
    is_public, rules, errors = transformer.parse_access(
        [{"given": {"category": value}}],
        "controllers.c.routes.r.access",
        set(),
        {},
    )
    return rules, errors


def test_v03_given_where_binds_predicate():
    rules, errors = _parse_given("assetCategories where slug = $categorySlug", True)
    assert errors == []
    binding = rules[0].document_symbols["category"]
    assert binding.collection == "assetCategories"
    assert binding.where == (IRWhereConjunct("slug", IRSymbolRef("categorySlug")),)


def test_v02_given_where_is_plain_document_binding():
    rules, errors = _parse_given("assetCategories where slug = $categorySlug", False)
    assert errors == []
    binding = rules[0].document_symbols["category"]
    assert binding.where == ()
    assert binding.collection == "assetCategories where slug = $categorySlug"


def _parse_rule(rule, allow_where):
    transformer = AccessTransformer(allow_where=allow_where)
    _, rules, errors = transformer.parse_access(
        [rule], "controllers.c.routes.r.access", set(), {}
    )
    return rules, errors


def test_v03_filter_key_aborts_with_coded_error():
    rules, errors = _parse_rule({"given": {"category": "posts by postId"}, "filter": "x = 1"}, True)
    assert rules is None
    assert _codes(errors) == {"ACCESS_FILTER_REMOVED"}
    assert errors[0].path == "controllers.c.routes.r.access[0].filter"


def test_v02_filter_key_is_preserved():
    rules, errors = _parse_rule({"given": {"category": "posts by postId"}, "filter": "x = 1"}, False)
    assert errors == []
    assert rules[0].filter == "x = 1"


def test_v02_document_binding_keeps_implicit_fetch():
    rules, errors = _parse_given("posts by postId", False)
    assert errors == []
    binding = rules[0].document_symbols["category"]
    assert binding == IRDocumentBinding(collection="posts", id_param="postId")
    assert binding.where == ()


# --- RHS symbol resolution (build-time, reuses #61 SymbolScope) ------------


def _where_spec(given):
    return {
        "version": "0.3",
        "controllers": {
            "assets": {
                "base_path": "/categories",
                "routes": {
                    "listAssets": {
                        "service": "listAssets",
                        "method": "GET",
                        "path": "/{categorySlug}/assets",
                        "access": [{"given": given}],
                    }
                },
            }
        },
    }


def test_v03_where_rhs_slug_resolves():
    spec = _where_spec({"category": "assetCategories where slug = $categorySlug"})
    assert validate_spec_symbols(spec) == []


def test_v03_where_rhs_given_symbol_resolves():
    spec = _where_spec({
        "principal": "identity:user",
        "category": "assetCategories where owner = $principal.record.id",
    })
    assert validate_spec_symbols(spec) == []


def test_v03_where_rhs_unbound_aborts_with_undefined_symbol():
    spec = _where_spec({"category": "assetCategories where slug = $ghost"})
    errors = validate_spec_symbols(spec)
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$ghost" in errors[0].message
    assert "given 'category' where" in errors[0].message


# --- runtime predicate fetch + 404-on-miss --------------------------------


def _where_rule():
    return RuntimeAccessRule(
        principal="identity:users",
        identity_symbols={"principal": IRIdentityBinding("user", "users")},
        document_symbols={
            "category": IRDocumentBinding(
                collection="assetCategories",
                where=(IRWhereConjunct("slug", IRSymbolRef("categorySlug")),),
            )
        },
        when=Equals(FieldRef("category", ("owner",)), FieldRef("principal", ("sub",))),
    )


def _ctx(repo, url_params):
    return RequestContext(
        method="GET",
        path="/categories/{categorySlug}/assets",
        api_version=None,
        collection="assets",
        operation="list",
        headers={},
        url_params=url_params,
        repository=repo,
        principal={"sub": "u1", "identity_collection": "users"},
        body=None,
        response=None,
    )


def test_runtime_where_binding_matching_record_allows():
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "u1"}]})
    rule = _where_rule()
    resolve = ResolveWhereBindingsStep([rule])
    ctx = asyncio.run(resolve(_ctx(repo, {"categorySlug": "books"})))
    assert ctx.where_documents["category"] == {"slug": "books", "owner": "u1"}
    assert AuthorizeRouteStep([rule])(ctx) is ctx


def test_runtime_where_binding_present_but_unauthorized_is_forbidden():
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "other"}]})
    rule = _where_rule()
    ctx = asyncio.run(ResolveWhereBindingsStep([rule])(_ctx(repo, {"categorySlug": "books"})))
    with pytest.raises(ForbiddenError):
        AuthorizeRouteStep([rule])(ctx)


def test_runtime_where_binding_no_match_is_404():
    repo = InMemoryRepository({"assetCategories": [{"slug": "books", "owner": "u1"}]})
    resolve = ResolveWhereBindingsStep([_where_rule()])
    with pytest.raises(NotFoundError):
        asyncio.run(resolve(_ctx(repo, {"categorySlug": "missing"})))


def test_runtime_where_binding_multi_conjunct_fetches_by_both():
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
    ctx = asyncio.run(
        ResolveWhereBindingsStep([rule])(
            _ctx(repo, {"categorySlug": "books", "tenantId": "t2"})
        )
    )
    assert ctx.where_documents["category"] == {"slug": "books", "tenant": "t2"}


def test_runtime_where_binding_skipped_without_principal():
    repo = InMemoryRepository({"assetCategories": []})
    ctx = _ctx(repo, {"categorySlug": "books"})
    ctx.principal = None
    result = asyncio.run(ResolveWhereBindingsStep([_where_rule()])(ctx))
    assert result.where_documents is None
