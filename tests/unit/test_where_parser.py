"""Tests for the v0.3 ``where`` binding grammar and its build-time validation.

Covers the tokenizer, the recursive-descent parser and its coded errors, the
binding-kind dispatch shared with the classifier, the runtime-aligned RHS symbol
scope (slugs plus identity/request symbols), and the entity field check.
"""

import textwrap

import pytest

from yaml_api_generator.ir import (
    IRDocumentBinding,
    IRLiteralRef,
    IRSymbolRef,
    IRWhereConjunct,
)
from yaml_api_generator.parsers.transformers.symbol_validation import (
    WHERE_FIELD_UNKNOWN,
    validate_spec_symbols,
)
from yaml_api_generator.parsers.transformers.v02.access_transformer import AccessTransformer
from yaml_api_generator.parsers.transformers.v02.binding_classifier import (
    BindingKind,
    binding_kind,
)
from yaml_api_generator.parsers.where_parser import (
    WHERE_BINDING_INVALID,
    WHERE_OPERATOR_UNSUPPORTED,
    WHERE_RHS_INVALID,
    TokenKind,
    is_where_binding,
    parse_where_binding,
    tokenize,
)
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _codes(errors):
    return {error.code for error in errors}


def _parse(raw):
    binding, errors = parse_where_binding(raw, "p")
    assert errors == []
    return binding


def _fail(raw):
    binding, errors = parse_where_binding(raw, "p")
    assert binding is None
    return errors


def _rhs(raw):
    (conjunct,) = _parse(f"docs where f = {raw}").conjuncts
    return conjunct.rhs


# --- tokenizer ---------------------------------------------------------------


def _kinds(raw):
    return [token.kind for token in tokenize(raw)][:-1]


def test_tokenizer_classifies_every_token_kind():
    assert _kinds("docs where a = $x and b = 'v' and c = 1 and d = true") == [
        TokenKind.IDENTIFIER, TokenKind.WHERE,
        TokenKind.IDENTIFIER, TokenKind.OPERATOR, TokenKind.SYMBOL, TokenKind.AND,
        TokenKind.IDENTIFIER, TokenKind.OPERATOR, TokenKind.STRING, TokenKind.AND,
        TokenKind.IDENTIFIER, TokenKind.OPERATOR, TokenKind.NUMBER, TokenKind.AND,
        TokenKind.IDENTIFIER, TokenKind.OPERATOR, TokenKind.BOOLEAN,
    ]


def test_tokenizer_records_positions_and_terminates_with_end():
    tokens = list(tokenize("docs where a = 1"))
    assert [token.position for token in tokens] == [0, 5, 11, 13, 15, 16]
    assert tokens[-1].kind is TokenKind.END


def test_tokenizer_keeps_quoted_keywords_inside_one_string_token():
    tokens = list(tokenize("docs where title = 'salt and pepper where $x'"))
    assert [token.kind for token in tokens].count(TokenKind.AND) == 0
    assert tokens[4].lexeme == "'salt and pepper where $x'"


def test_tokenizer_marks_unterminated_string_as_unknown():
    tokens = list(tokenize("docs where a = 'open"))
    assert tokens[4].kind is TokenKind.UNKNOWN
    assert tokens[4].lexeme == "'open"


def test_tokenizer_marks_stray_characters_as_unknown():
    assert TokenKind.UNKNOWN in _kinds("docs where a = #")


# --- grammar -------------------------------------------------------------------


def test_single_conjunct_binds_symbol():
    binding = _parse("assetCategories where slug = $categorySlug")
    assert binding.collection == "assetCategories"
    assert binding.conjuncts == (IRWhereConjunct("slug", IRSymbolRef("categorySlug")),)


def test_multi_conjunct():
    binding = _parse("docs where a = $x and b = $y and c = 3")
    assert binding.conjuncts == (
        IRWhereConjunct("a", IRSymbolRef("x")),
        IRWhereConjunct("b", IRSymbolRef("y")),
        IRWhereConjunct("c", IRLiteralRef(3)),
    )


def test_whitespace_is_insignificant():
    assert _parse("docs   where  a=$x   and b = 1").conjuncts == (
        IRWhereConjunct("a", IRSymbolRef("x")),
        IRWhereConjunct("b", IRLiteralRef(1)),
    )


def test_result_unpacks_as_collection_and_conjuncts():
    collection, conjuncts = _parse("docs where a = 1")
    assert collection == "docs"
    assert conjuncts == (IRWhereConjunct("a", IRLiteralRef(1)),)


def test_dotted_symbol_path():
    assert _rhs("$principal.record.id") == IRSymbolRef("principal", ("record", "id"))


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("'open'", "open"),
        ('"open"', "open"),
        ("'salt and pepper'", "salt and pepper"),
        ("'x where y'", "x where y"),
        ("'$notASymbol'", "$notASymbol"),
        ("'a = b'", "a = b"),
        (r"'it\'s'", "it's"),
        (r'"say \"hi\""', 'say "hi"'),
        (r"'back\\slash'", "back\\slash"),
        ("'it\"s'", 'it"s'),
        ("''", ""),
    ],
)
def test_string_literals(raw, value):
    assert _rhs(raw) == IRLiteralRef(value)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("3", 3),
        ("-3", -3),
        ("+3", 3),
        ("0", 0),
        ("1.5", 1.5),
        ("-0.5", -0.5),
        (".5", 0.5),
        ("3.", 3.0),
        ("1e3", 1000.0),
        ("2.5E-2", 0.025),
        ("-1e+2", -100.0),
    ],
)
def test_numeric_literals(raw, value):
    literal = _rhs(raw)
    assert literal == IRLiteralRef(value)
    assert type(literal.value) is type(value)


@pytest.mark.parametrize(("raw", "value"), [("true", True), ("false", False)])
def test_boolean_literals(raw, value):
    assert _rhs(raw) == IRLiteralRef(value)


# --- grammar errors --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "a collection name"),
        ("where a = 1", "a collection name"),
        ("docs", "'where'"),
        ("docs a = 1", "'where'"),
        ("docs where", "a field name"),
        ("docs where slug", "'='"),
        ("docs where a.b = 1", "'='"),
        ("docs where a = 1 and", "a field name"),
        ("docs where a = 1 and and b = 2", "a field name"),
        ("docs where a = 1 b = 2", "'and' or end of binding"),
        ("docs where a = 1 'x'", "'and' or end of binding"),
        ("docs where a = 1 where b = 2", "'and' or end of binding"),
    ],
)
def test_grammar_errors_name_what_was_expected(raw, expected):
    [error] = _fail(raw)
    assert error.code == WHERE_BINDING_INVALID
    assert f"Expected {expected}" in error.message
    assert "column" in error.message


def test_grammar_error_reports_column_of_offending_token():
    [error] = _fail("docs where a = 1 b = 2")
    assert "at column 18, found 'b'" in error.message


@pytest.mark.parametrize(
    "raw",
    ["docs where a =", "docs where a = #", "docs where a = 'open", "docs where a = b", "docs where a = $"],
)
def test_missing_or_invalid_rhs(raw):
    [error] = _fail(raw)
    assert error.code == WHERE_RHS_INVALID
    assert "$symbol" in error.hint


def test_unterminated_string_error_names_the_fragment():
    [error] = _fail("docs where a = 'open")
    assert "\"'open\"" in error.message


@pytest.mark.parametrize("operator", ["!=", "<", "<=", ">", ">=", "in"])
def test_reserved_operators_abort(operator):
    [error] = _fail(f"docs where x {operator} 3")
    assert error.code == WHERE_OPERATOR_UNSUPPORTED
    assert f"'{operator}'" in error.message


def test_reserved_operator_in_second_conjunct_aborts():
    assert _codes(_fail("docs where a = 1 and b < 2")) == {WHERE_OPERATOR_UNSUPPORTED}


def test_errors_carry_the_path():
    _, errors = parse_where_binding("docs where", "controllers.c.routes.r.access[0].given.d")
    assert errors[0].path == "controllers.c.routes.r.access[0].given.d"


# --- symbol extraction --------------------------------------------------------------


def test_symbols_collects_rhs_symbol_roots():
    binding = _parse("docs where a = $x and b = $principal.record.id and c = 'lit' and d = $x")
    assert binding.symbols == frozenset({"x", "principal"})


def test_symbols_ignores_dollar_inside_string_literals():
    assert _parse("docs where a = '$ghost'").symbols == frozenset()


# --- detection and classifier gating ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("docs where a = 1", True),
        ("docs where", True),
        ("docs where a = 'x", True),
        ("posts", False),
        ("posts by postId", False),
        ("warehouse by id", False),
        ("posts by 'where'", False),
        ("identity:user", False),
    ],
)
def test_is_where_binding(raw, expected):
    assert is_where_binding(raw) is expected


def test_binding_kind_gates_where_on_allow_where():
    raw = "assetCategories where slug = $categorySlug"
    assert binding_kind(raw, allow_where=True) is BindingKind.WHERE
    assert binding_kind(raw) is BindingKind.DOCUMENT


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("identity:user", BindingKind.IDENTITY),
        ("request", BindingKind.REQUEST),
        ("request.body", BindingKind.REQUEST),
        ("request:Dto", BindingKind.REQUEST),
        ("posts by postId", BindingKind.DOCUMENT),
    ],
)
def test_binding_kind_prefix_dispatch(raw, kind):
    assert binding_kind(raw, allow_where=True) is kind


def _parse_given(given, allow_where):
    _, rules, errors = AccessTransformer(allow_where=allow_where).parse_access(
        [{"given": given}], "controllers.c.routes.r.access", set(), {}
    )
    return rules, errors


def test_v03_given_where_binds_predicate():
    rules, errors = _parse_given({"category": "assetCategories where slug = $categorySlug"}, True)
    assert errors == []
    assert rules[0].document_symbols["category"] == IRDocumentBinding(
        collection="assetCategories",
        where=(IRWhereConjunct("slug", IRSymbolRef("categorySlug")),),
    )


def test_v02_given_where_is_plain_document_binding():
    rules, errors = _parse_given({"category": "assetCategories where slug = $categorySlug"}, False)
    assert errors == []
    assert rules[0].document_symbols["category"] == IRDocumentBinding(
        collection="assetCategories where slug = $categorySlug"
    )


def test_v02_document_binding_keeps_implicit_fetch():
    rules, errors = _parse_given({"category": "posts by postId"}, False)
    assert errors == []
    assert rules[0].document_symbols["category"] == IRDocumentBinding(
        collection="posts", id_param="postId"
    )


def test_transformer_surfaces_grammar_errors_under_v03():
    _, errors = _parse_given({"d": "docs where slug"}, True)
    assert _codes(errors) == {WHERE_BINDING_INVALID}


def test_transformer_keeps_quoted_literal_intact():
    rules, errors = _parse_given({"d": "docs where title = 'salt and pepper'"}, True)
    assert errors == []
    assert rules[0].document_symbols["d"].where == (
        IRWhereConjunct("title", IRLiteralRef("salt and pepper")),
    )


# --- build-time scope and field checks --------------------------------------------------


_ENTITIES = {
    "user": {
        "type": "auth",
        "auth": {"identifier": "email", "via": "password"},
        "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
    },
    "taggable": {"abstract": True, "fields": {"tag": {"type": "string"}}},
    "assetCategory": {
        "extends": "taggable",
        "fields": {"id": {"type": "id"}, "slug": {"type": "string"}, "owner": {"type": "string"}},
    },
    "post": {"fields": {"id": {"type": "id"}, "categoryId": {"type": "string"}}},
}

_REPOSITORIES = {
    "users": {"entity": "user"},
    "assetCategories": {"entity": "assetCategory"},
    "posts": {"entity": "post"},
    "orphans": {"entity": "missing"},
}


def _spec(given, path="/{categorySlug}/assets"):
    return {
        "version": "0.3",
        "entities": _ENTITIES,
        "repositories": _REPOSITORIES,
        "controllers": {
            "assets": {
                "base_path": "/categories",
                "routes": {
                    "listAssets": {
                        "service": "listAssets",
                        "method": "GET",
                        "path": path,
                        "access": [{"given": given}],
                    }
                },
            }
        },
    }


def test_slug_resolves():
    assert validate_spec_symbols(_spec({"category": "assetCategories where slug = $categorySlug"})) == []


def test_base_path_slug_resolves():
    spec = _spec({"category": "assetCategories where slug = $tenant"}, path="/assets")
    spec["controllers"]["assets"]["base_path"] = "/{tenant}/categories"
    assert validate_spec_symbols(spec) == []


def test_identity_symbol_resolves():
    assert validate_spec_symbols(_spec({
        "principal": "identity:user",
        "category": "assetCategories where owner = $principal.record.id",
    })) == []


def test_request_symbol_resolves():
    assert validate_spec_symbols(_spec({
        "req": "request.query",
        "category": "assetCategories where slug = $req.slug",
    })) == []


def test_unbound_symbol_aborts():
    errors = validate_spec_symbols(_spec({"category": "assetCategories where slug = $ghost"}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$ghost" in errors[0].message
    assert "controller 'assets' route 'listAssets' access[0] given 'category' where" in errors[0].message
    assert errors[0].path == "controllers.assets.routes.listAssets.access[0].given.category"


def test_self_reference_aborts():
    errors = validate_spec_symbols(_spec({"category": "assetCategories where slug = $category.slug"}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$category" in errors[0].message


def test_other_document_symbol_is_out_of_scope():
    errors = validate_spec_symbols(_spec({
        "post": "posts",
        "category": "assetCategories where slug = $post.categoryId",
    }))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$post" in errors[0].message


def test_other_where_symbol_is_out_of_scope():
    errors = validate_spec_symbols(_spec({
        "post": "posts where id = $categorySlug",
        "category": "assetCategories where slug = $post.categoryId",
    }))
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}


def test_dollar_inside_quoted_literal_is_not_a_symbol():
    assert validate_spec_symbols(_spec({"category": "assetCategories where slug = '$ghost'"})) == []


def test_unparseable_binding_is_left_to_the_transformer():
    assert validate_spec_symbols(_spec({"category": "assetCategories where slug = $"})) == []


def test_known_field_passes():
    assert validate_spec_symbols(_spec({"category": "assetCategories where owner = 'u1'"})) == []


def test_inherited_field_passes():
    assert validate_spec_symbols(_spec({"category": "assetCategories where tag = 'x'"})) == []


def test_unknown_field_aborts():
    errors = validate_spec_symbols(_spec({"category": "assetCategories where slgu = $categorySlug"}))
    assert _codes(errors) == {WHERE_FIELD_UNKNOWN}
    assert "'slgu'" in errors[0].message
    assert "'assetCategories'" in errors[0].message
    assert errors[0].path == "controllers.assets.routes.listAssets.access[0].given.category"


def test_each_unknown_field_is_reported():
    errors = validate_spec_symbols(_spec({
        "category": "assetCategories where slug = $categorySlug and nope = 1 and nada = 2",
    }))
    assert [error.code for error in errors] == [WHERE_FIELD_UNKNOWN, WHERE_FIELD_UNKNOWN]


def test_unknown_field_and_unbound_symbol_are_both_reported():
    errors = validate_spec_symbols(_spec({"category": "assetCategories where slgu = $ghost"}))
    assert _codes(errors) == {"UNDEFINED_SYMBOL", WHERE_FIELD_UNKNOWN}


def test_unknown_collection_skips_field_check():
    assert validate_spec_symbols(_spec({"category": "ghosts where slug = $categorySlug"})) == []


def test_collection_with_missing_entity_skips_field_check():
    assert validate_spec_symbols(_spec({"category": "orphans where slug = $categorySlug"})) == []


# --- end to end -------------------------------------------------------------------------


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
        auth: {{ identifier: email, via: password }}
        fields:
          id: {{ type: id }}
          email: {{ type: string }}
      assetCategory:
        fields:
          id: {{ type: id }}
          slug: {{ type: string }}
          title: {{ type: string }}
    repositories:
      users: {{ entity: user }}
      assetCategories: {{ entity: assetCategory }}
    services:
      listAssets: {{ repository: assetCategories, operation: list }}
    controllers:
      assets:
        base_path: /categories
        routes:
          listAssets:
            service: listAssets
            method: GET
            path: /{{categorySlug}}/assets
            access:
              - given:
                  principal: identity:user
                  category: "{binding}"
"""


def _load(binding, tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(textwrap.dedent(_SPEC.format(binding=binding)))
    return load_and_generate_ir(str(path))


def test_end_to_end_escaped_literal_passes_schema_and_builds(tmp_path):
    result = _load(r"assetCategories where title = 'it\\'s' and slug = $categorySlug", tmp_path)
    [route] = [route for route in result.ir.routes if route.access_rules]
    binding = route.access_rules[0].document_symbols["category"]
    assert binding.where == (
        IRWhereConjunct("title", IRLiteralRef("it's")),
        IRWhereConjunct("slug", IRSymbolRef("categorySlug")),
    )


def test_end_to_end_unknown_field_aborts(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _load("assetCategories where slgu = $categorySlug", tmp_path)
    assert _codes(exc_info.value.errors) == {WHERE_FIELD_UNKNOWN}


def test_end_to_end_self_reference_aborts(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _load("assetCategories where slug = $category.slug", tmp_path)
    assert _codes(exc_info.value.errors) == {"UNDEFINED_SYMBOL"}
