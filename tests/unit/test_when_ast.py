import pytest

from yaml_api_generator.when_ast import (
    And,
    Equals,
    FieldRef,
    Not,
    NotEquals,
    Or,
    StringLiteral,
    needs_document,
)


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

    def test_159_and_principal_only_false(self):
        expr = And(left=_princ_ref(), right=FieldRef(root="principal", path=("email",)))
        assert needs_document(expr) is False

    def test_160_not_doc_ref_true(self):
        expr = Not(operand=_doc_ref())
        assert needs_document(expr) is True

    def test_161_mixed_expression_with_doc_true(self):
        expr = And(
            left=Equals(left=_princ_ref(), right=StringLiteral(value="a")),
            right=Or(
                left=Equals(left=_doc_ref(), right=StringLiteral(value="b")),
                right=Equals(left=_princ_ref(), right=StringLiteral(value="c")),
            ),
        )
        assert needs_document(expr) is True
