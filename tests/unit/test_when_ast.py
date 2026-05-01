import pytest

from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    Not,
    NotEquals,
    Or,
    StringLiteral,
    needs_document,
)
from yaml_api_generator.parsers.when_parser import parse_when_expr, parse_when_list


def _parse(expr_str: str):
    expr, errors = parse_when_expr(expr_str, "test")
    assert not errors
    return expr


def _doc_ref():
    return FieldRef(root="document", path=("id",))


def _princ_ref():
    return FieldRef(root="principal", path=("sub",))


class TestNeedsDocument:
    def test_155_document_fieldref_true(self):
        assert needs_document(_doc_ref()) is True

    def test_156_principal_fieldref_false(self):
        assert needs_document(_princ_ref()) is False

    def test_157_string_literal_false(self):
        assert needs_document(StringLiteral(value="x")) is False

    def test_158_equals_with_doc_ref_true(self):
        expr = Equals(left=_doc_ref(), right=StringLiteral(value="x"))
        assert needs_document(expr) is True

    def test_principal_fieldref_does_not_reference_document(self):
        expr = _parse("principal.sub equals 'x'")
        assert needs_document(expr) is False

    def test_document_on_right_side_references_document(self):
        expr = _parse("principal.sub equals document.id")
        assert needs_document(expr) is True

    def test_and_principal_only_does_not_reference_document(self):
        expr, errors = parse_when_list(
            ["principal.sub equals 'a'", "principal.email equals 'b'"], "test"
        )
        assert not errors
        assert needs_document(expr) is False

    def test_and_mixed_references_document(self):
        expr, errors = parse_when_list(
            ["principal.sub equals 'a'", "document.authorId equals 'b'"], "test"
        )
        assert not errors
        assert needs_document(expr) is True