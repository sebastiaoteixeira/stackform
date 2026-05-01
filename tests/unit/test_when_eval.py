import pytest

from yaml_api_generator.server.when_eval import evaluate_when
from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    Not,
    NotEquals,
    Or,
    StringLiteral,
    WhenExpr,
)

_PRINCIPAL = {"sub": "user-1", "record": {"role": "admin", "teamId": "t1"}}
_DOCUMENT = {"id": "doc-1", "authorId": "user-1", "status": "published"}


def _princ_sub():
    return FieldRef(root="principal", path=("sub",))


def _doc_id():
    return FieldRef(root="document", path=("id",))


def _doc_field(name: str):
    return FieldRef(root="document", path=(name,))


def _princ_record_field(name: str):
    return FieldRef(root="principal", path=("record", name))


class TestEvaluateWhen:
    def test_162_equals_matching_principal_sub(self):
        expr = Equals(left=_princ_sub(), right=StringLiteral(value="user-1"))
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_163_equals_non_matching(self):
        expr = Equals(left=_princ_sub(), right=StringLiteral(value="other"))
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_164_not_equals_opposite(self):
        expr = NotEquals(left=_princ_sub(), right=StringLiteral(value="other"))
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_165_and_both_true(self):
        expr = And(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="user-1")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="doc-1")),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_166_and_one_false(self):
        expr = And(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="user-1")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="wrong")),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_167_or_one_true(self):
        expr = Or(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="wrong")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="doc-1")),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_168_or_both_false(self):
        expr = Or(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="wrong")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="wrong")),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_169_not_true(self):
        expr = Not(
            operand=Equals(left=_princ_sub(), right=StringLiteral(value="user-1"))
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_170_principal_record_field(self):
        expr = Equals(
            left=_princ_record_field("role"),
            right=StringLiteral(value="admin"),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_171_document_field(self):
        expr = Equals(
            left=_doc_field("authorId"),
            right=StringLiteral(value="user-1"),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_172_unknown_principal_path_returns_none(self):
        expr = Equals(
            left=FieldRef(root="principal", path=("unknown", "path")),
            right=StringLiteral(value="anything"),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_173_multi_level_document_path_returns_none(self):
        expr = Equals(
            left=FieldRef(root="document", path=("nested", "deep")),
            right=StringLiteral(value="anything"),
        )
        assert evaluate_when(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_174_principal_and_document_none(self):
        expr = Equals(left=_princ_sub(), right=StringLiteral(value="user-1"))
        assert evaluate_when(expr, None, None) is False

    def test_175_unknown_expression_type_returns_false(self):
        class UnknownExpr(WhenExpr):
            pass

        assert evaluate_when(UnknownExpr(), _PRINCIPAL, _DOCUMENT) is False
