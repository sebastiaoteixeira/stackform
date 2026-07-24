import pytest

from yaml_api_generator.server.common.when_eval import evaluate_when_with_symbols
from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    In,
    IsNotNull,
    IsNull,
    Not,
    NotEquals,
    NotIn,
    Or,
    StringLiteral,
    WhenExpr,
)

_PRINCIPAL = {"sub": "user-1", "record": {"role": "admin", "teamId": "t1"}}
_DOCUMENT = {"id": "doc-1", "authorId": "user-1", "status": "published"}


def _eval(expr: WhenExpr, principal: dict | None = None, document: dict | None = None) -> bool:
    symbols: dict[str, dict | None] = {}
    if principal is not None:
        symbols["principal"] = principal
    if document is not None:
        symbols["document"] = document
    return evaluate_when_with_symbols(expr, symbols)


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
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_163_equals_non_matching(self):
        expr = Equals(left=_princ_sub(), right=StringLiteral(value="other"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_164_not_equals_opposite(self):
        expr = NotEquals(left=_princ_sub(), right=StringLiteral(value="other"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_165_and_both_true(self):
        expr = And(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="user-1")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="doc-1")),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_166_and_one_false(self):
        expr = And(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="user-1")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="wrong")),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_167_or_one_true(self):
        expr = Or(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="wrong")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="doc-1")),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_168_or_both_false(self):
        expr = Or(
            left=Equals(left=_princ_sub(), right=StringLiteral(value="wrong")),
            right=Equals(left=_doc_id(), right=StringLiteral(value="wrong")),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_169_not_true(self):
        expr = Not(
            operand=Equals(left=_princ_sub(), right=StringLiteral(value="user-1"))
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_170_principal_record_field(self):
        expr = Equals(
            left=_princ_record_field("role"),
            right=StringLiteral(value="admin"),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_171_document_field(self):
        expr = Equals(
            left=_doc_field("authorId"),
            right=StringLiteral(value="user-1"),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_172_unknown_principal_path_returns_none(self):
        expr = Equals(
            left=FieldRef(root="principal", path=("unknown", "path")),
            right=StringLiteral(value="anything"),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_173_multi_level_document_path_returns_none(self):
        expr = Equals(
            left=FieldRef(root="document", path=("nested", "deep")),
            right=StringLiteral(value="anything"),
        )
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_174_principal_and_document_none(self):
        expr = Equals(left=_princ_sub(), right=StringLiteral(value="user-1"))
        assert _eval(expr, None, None) is False

    def test_175_unknown_expression_type_returns_false(self):
        class UnknownExpr(WhenExpr):
            pass

        assert _eval(UnknownExpr(), _PRINCIPAL, _DOCUMENT) is False

    def test_176_in_field_matching(self):
        expr = In(left=_princ_record_field("role"), values=("admin", "editor"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_177_in_field_non_matching(self):
        expr = In(left=_doc_field("status"), values=("draft", "archived"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_178_in_string_literal(self):
        expr = In(left=StringLiteral(value="admin"), values=("admin", "editor"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_179_not_in_field_non_member(self):
        expr = NotIn(left=_doc_field("status"), values=("draft", "archived"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is True

    def test_180_not_in_field_member(self):
        expr = NotIn(left=_princ_record_field("role"), values=("admin", "editor"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_181_not_in_string_literal(self):
        expr = NotIn(left=StringLiteral(value="admin"), values=("admin", "editor"))
        assert _eval(expr, _PRINCIPAL, _DOCUMENT) is False

    def test_182_is_null_none_field_returns_true(self):
        expr = IsNull(operand=FieldRef(root="document", path=("organizationId",)))
        assert _eval(expr, document={"organizationId": None}) is True

    def test_183_is_null_present_field_returns_false(self):
        expr = IsNull(operand=FieldRef(root="document", path=("organizationId",)))
        assert _eval(expr, document={"organizationId": "org-1"}) is False

    def test_184_is_null_missing_field_returns_true(self):
        expr = IsNull(operand=FieldRef(root="document", path=("organizationId",)))
        assert _eval(expr, document={}) is True

    def test_185_is_not_null_present_field_returns_true(self):
        expr = IsNotNull(operand=FieldRef(root="principal", path=("record", "role")))
        assert _eval(expr, principal=_PRINCIPAL) is True

    def test_186_is_not_null_none_field_returns_false(self):
        expr = IsNotNull(operand=FieldRef(root="principal", path=("record", "role")))
        assert _eval(expr, principal={"record": {"role": None}}) is False

    def test_187_is_not_null_missing_symbol_returns_false(self):
        expr = IsNotNull(operand=FieldRef(root="document", path=("id",)))
        assert _eval(expr) is False
