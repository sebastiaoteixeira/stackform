import pytest

from yaml_api_generator.parsing.when_parser import (
    parse_document_binding,
    parse_when_expr,
    parse_when_list,
)
from yaml_api_generator.when_ast import And, Equals, FieldRef, NotEquals, StringLiteral


_PATH = "test"


class TestParseWhenExpr:
    def test_134_equals_fieldref_string(self):
        expr, errors = parse_when_expr("principal.sub equals 'hello'", _PATH)
        assert not errors
        assert isinstance(expr, Equals)
        assert isinstance(expr.left, FieldRef)
        assert expr.left.root == "principal"
        assert expr.left.path == ("sub",)
        assert isinstance(expr.right, StringLiteral)
        assert expr.right.value == "hello"

    def test_135_not_equals_fieldref_string(self):
        expr, errors = parse_when_expr("principal.sub not equals 'hello'", _PATH)
        assert not errors
        assert isinstance(expr, NotEquals)
        assert isinstance(expr.left, FieldRef)
        assert isinstance(expr.right, StringLiteral)

    def test_136_equals_fieldref_fieldref(self):
        expr, errors = parse_when_expr("principal.sub equals document.id", _PATH)
        assert not errors
        assert isinstance(expr, Equals)
        assert isinstance(expr.left, FieldRef)
        assert expr.left.root == "principal"
        assert isinstance(expr.right, FieldRef)
        assert expr.right.root == "document"

    def test_137_empty_string_literal(self):
        expr, errors = parse_when_expr("principal.sub equals ''", _PATH)
        assert not errors
        assert isinstance(expr, Equals)
        assert isinstance(expr.right, StringLiteral)
        assert expr.right.value == ""

    def test_138_string_with_spaces(self):
        expr, errors = parse_when_expr("principal.sub equals 'hello world'", _PATH)
        assert not errors
        assert isinstance(expr.right, StringLiteral)
        assert expr.right.value == "hello world"

    def test_139_deep_field_ref(self):
        expr, errors = parse_when_expr("principal.a.b.c equals 'x'", _PATH)
        assert not errors
        lhs = expr.left
        assert isinstance(lhs, FieldRef)
        assert lhs.root == "principal"
        assert lhs.path == ("a", "b", "c")

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
        assert errors[0].code == "WHEN_EXPR_INVALID"

    def test_144_whitespace_trimming(self):
        expr, errors = parse_when_expr("  principal.sub   equals   'hello'  ", _PATH)
        assert not errors
        assert isinstance(expr, Equals)
        assert isinstance(expr.left, FieldRef)
        assert expr.left.path == ("sub",)
        assert isinstance(expr.right, StringLiteral)
        assert expr.right.value == "hello"


class TestParseWhenList:
    def test_145_single_item_returns_expression_directly(self):
        result, errors = parse_when_list("principal.sub equals 'hello'", _PATH)
        assert not errors
        assert isinstance(result, Equals)
        assert not isinstance(result, And)

    def test_146_multi_item_nested_and(self):
        result, errors = parse_when_list(
            ["principal.sub equals 'hello'", "document.id equals 'x'"], _PATH
        )
        assert not errors
        assert isinstance(result, And)
        assert isinstance(result.left, Equals)
        assert isinstance(result.right, Equals)

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
