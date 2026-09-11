import pytest

from yaml_api_generator.parsers.when_parser import (
    parse_document_binding,
    parse_when_expr,
    parse_when_list,
)
from yaml_api_generator.server.common.when_eval import evaluate_when_with_symbols


_PATH = "test"


def _eval(expr_str: str, *, principal=None, document=None) -> bool:
    expr, errors = parse_when_expr(expr_str, _PATH)
    assert not errors
    symbols: dict[str, dict | None] = {}
    if principal is not None:
        symbols["principal"] = principal
    if document is not None:
        symbols["document"] = document
    return evaluate_when_with_symbols(expr, symbols)


class TestParseWhenExpr:
    def test_134_equals_matches_when_equal(self):
        assert _eval("principal.sub equals 'hello'", principal={"sub": "hello"}) is True
        assert _eval("principal.sub equals 'hello'", principal={"sub": "world"}) is False

    def test_135_not_equals_matches_when_not_equal(self):
        assert _eval("principal.sub not equals 'hello'", principal={"sub": "hello"}) is False
        assert _eval("principal.sub not equals 'hello'", principal={"sub": "world"}) is True

    def test_136_field_ref_to_field_ref_compares_values(self):
        assert _eval(
            "principal.sub equals document.id",
            principal={"sub": "abc"},
            document={"id": "abc"},
        ) is True
        assert _eval(
            "principal.sub equals document.id",
            principal={"sub": "abc"},
            document={"id": "xyz"},
        ) is False

    def test_137_empty_string_literal(self):
        assert _eval("principal.sub equals ''", principal={"sub": ""}) is True
        assert _eval("principal.sub equals ''", principal={"sub": "x"}) is False

    def test_138_string_literal_with_spaces(self):
        assert _eval("principal.sub equals 'hello world'", principal={"sub": "hello world"}) is True
        assert _eval("principal.sub equals 'hello world'", principal={"sub": "hello"}) is False

    def test_139_deep_field_ref_traverses_nested_dicts(self):
        assert _eval(
            "principal.a.b.c equals 'x'",
            principal={"a": {"b": {"c": "x"}}},
        ) is True
        assert _eval(
            "principal.a.b.c equals 'x'",
            principal={"a": {"b": {"c": "y"}}},
        ) is False

    def test_140_bare_operand_without_dot(self):
        _, errors = parse_when_expr("principal equals 'hello'", _PATH)
        assert len(errors) == 1
        assert errors[0].code == "WHEN_OPERAND_INVALID"

    def test_141_number_operand(self):
        _, errors = parse_when_expr("123 equals 'hello'", _PATH)
        assert any(e.code == "WHEN_OPERAND_INVALID" for e in errors)

    def test_142_no_equals_or_not_equals(self):
        _, errors = parse_when_expr("principal.sub is 'hello'", _PATH)
        assert len(errors) == 1
        assert errors[0].code == "WHEN_EXPR_INVALID"

    def test_143_empty_string_expr(self):
        _, errors = parse_when_expr("", _PATH)
        assert len(errors) == 1
        assert errors[0].code == "WHEN_OPERAND_MISSING"

    def test_144_whitespace_trimming_evaluates_correctly(self):
        assert _eval("  principal.sub   equals   'hello'  ", principal={"sub": "hello"}) is True


class TestParseWhenList:
    def test_145_single_item_evaluates_like_single_expression(self):
        result, errors = parse_when_list("principal.sub equals 'hello'", _PATH)
        assert not errors
        assert evaluate_when_with_symbols(result, {"principal": {"sub": "hello"}}) is True
        assert evaluate_when_with_symbols(result, {"principal": {"sub": "world"}}) is False

    def test_146_multi_item_requires_all_conditions_true(self):
        result, errors = parse_when_list(
            ["principal.sub equals 'user-1'", "document.id equals 'doc-1'"], _PATH
        )
        assert not errors
        # Both true
        assert evaluate_when_with_symbols(result, {"principal": {"sub": "user-1"}, "document": {"id": "doc-1"}}) is True
        # First false
        assert evaluate_when_with_symbols(result, {"principal": {"sub": "other"}, "document": {"id": "doc-1"}}) is False
        # Second false
        assert evaluate_when_with_symbols(result, {"principal": {"sub": "user-1"}, "document": {"id": "other"}}) is False

    def test_147_empty_list_returns_none(self):
        result, errors = parse_when_list([], _PATH)
        assert not errors
        assert result is None

    def test_148_mixed_valid_invalid_collects_all_errors(self):
        result, errors = parse_when_list(
            ["principal.sub equals 'ok'", "bad operand equals 'x'"], _PATH
        )
        assert errors
        assert result is None


class TestParentheses:
    _P = {"a": "1", "b": "1", "c": "0"}

    def test_grouping_overrides_precedence(self):
        # (a or b) and c with c false must be False; grouping must bind or first.
        assert _eval(
            "(principal.a equals '1' or principal.b equals '1') and principal.c equals '1'",
            principal=self._P,
        ) is False

    def test_flat_precedence_differs_from_grouped(self):
        # Without parentheses, and binds tighter, so the or short-circuits to True.
        assert _eval(
            "principal.a equals '1' or principal.b equals '1' and principal.c equals '1'",
            principal=self._P,
        ) is True

    def test_nested_parentheses(self):
        assert _eval(
            "((principal.a equals '1'))",
            principal=self._P,
        ) is True

    def test_not_applies_to_group(self):
        assert _eval(
            "not (principal.a equals '1' or principal.b equals '1')",
            principal=self._P,
        ) is False

    def test_unbalanced_open_paren_rejected(self):
        _, errors = parse_when_expr("(principal.a equals '1'", _PATH)
        assert errors and errors[0].code == "WHEN_EXPR_INVALID"

    def test_stray_close_paren_rejected(self):
        _, errors = parse_when_expr("principal.a equals '1')", _PATH)
        assert errors and errors[0].code == "WHEN_EXPR_INVALID"


class TestIsNullOperators:
    def test_is_null_parses_to_is_null_node(self):
        from yaml_api_generator.ir.when import FieldRef, IsNull
        expr, errors = parse_when_expr("document.organizationId is null", _PATH)
        assert not errors
        assert isinstance(expr, IsNull)
        assert expr.operand == FieldRef(root="document", path=("organizationId",))

    def test_is_not_null_parses_to_is_not_null_node(self):
        from yaml_api_generator.ir.when import FieldRef, IsNotNull
        expr, errors = parse_when_expr("principal.record.role is not null", _PATH)
        assert not errors
        assert isinstance(expr, IsNotNull)
        assert expr.operand == FieldRef(root="principal", path=("record", "role"))

    def test_is_null_evaluates_true_for_none_field(self):
        assert _eval("document.organizationId is null", document={"organizationId": None}) is True

    def test_is_null_evaluates_false_for_present_field(self):
        assert _eval("document.organizationId is null", document={"organizationId": "org-1"}) is False

    def test_is_not_null_evaluates_true_for_present_field(self):
        assert _eval("document.organizationId is not null", document={"organizationId": "org-1"}) is True

    def test_is_not_null_evaluates_false_for_none_field(self):
        assert _eval("document.organizationId is not null", document={"organizationId": None}) is False

    def test_is_null_evaluates_true_for_missing_field(self):
        assert _eval("document.organizationId is null", document={}) is True

    def test_is_null_combined_with_and(self):
        assert _eval(
            "document.organizationId is null and principal.sub equals 'u1'",
            principal={"sub": "u1"},
            document={},
        ) is True

    def test_is_not_null_combined_with_and(self):
        assert _eval(
            "principal.record.role is not null and document.id equals 'doc-1'",
            principal={"record": {"role": "admin"}},
            document={"id": "doc-1"},
        ) is True


class TestParseDocumentBinding:
    def test_149_collection_only(self):
        result, errors = parse_document_binding("collection", _PATH)
        assert not errors
        assert result == ("collection", None)

    def test_150_collection_by_param(self):
        result, errors = parse_document_binding("collection by param", _PATH)
        assert not errors
        assert result == ("collection", "param")

    def test_151_whitespace_trimming(self):
        result, errors = parse_document_binding(" posts  by  userId ", _PATH)
        assert not errors
        assert result == ("posts", "userId")

    def test_152_empty_string(self):
        result, errors = parse_document_binding("", _PATH)
        assert errors
        assert errors[0].code == "DOCUMENT_BINDING_INVALID"
        assert result is None

    def test_153_by_with_empty_collection(self):
        result, errors = parse_document_binding(" by id", _PATH)
        assert not errors
        assert result == ("by id", None)

    def test_154_collection_by_empty_param(self):
        result, errors = parse_document_binding("collection by ", _PATH)
        assert not errors
        assert result == ("collection by", None)