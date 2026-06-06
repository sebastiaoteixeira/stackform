"""Unit tests for the FastAPI access-rule serialization filters.

Verifies that ``access_rule_py`` / ``when_py`` emit source that, evaluated
against the generated ``when_eval`` classes, reconstructs the original IR
expression, and that the emitted evaluator matches the run-server evaluator.
"""

import pytest

from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor, RouteDescriptor
from yaml_api_generator.generators.backend.fastapi.access_filters import (
    access_rule_py,
    needs_post_fetch,
    py_bool,
    role_hierarchies_py,
    when_py,
)
from yaml_api_generator.ir.when import And, Equals, FieldRef, In, Not, NotEquals, NotIn, Or, StringLiteral


_WHEN_NAMESPACE = {
    "FieldRef": FieldRef,
    "StringLiteral": StringLiteral,
    "Equals": Equals,
    "NotEquals": NotEquals,
    "And": And,
    "Or": Or,
    "Not": Not,
    "In": In,
    "NotIn": NotIn,
}


_EXPRESSIONS = [
    FieldRef("principal", ()),
    FieldRef("document", ("id",)),
    StringLiteral("admin"),
    Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("id",))),
    NotEquals(FieldRef("principal", ("record", "role")), StringLiteral("guest")),
    And(
        Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("owner",))),
        NotEquals(FieldRef("principal", ("role",)), StringLiteral("banned")),
    ),
    Or(Equals(FieldRef("principal", ("role",)), StringLiteral("admin")), Not(FieldRef("principal", ()))),
    In(FieldRef("principal", ("role",)), ("admin", "moderator")),
    NotIn(FieldRef("principal", ("role",)), ("guest",)),
]


@pytest.mark.parametrize("expr", _EXPRESSIONS)
def test_when_py_round_trips_to_equal_ast(expr):
    reconstructed = eval(when_py(expr), dict(_WHEN_NAMESPACE))
    assert reconstructed == expr


def test_py_bool():
    assert py_bool(True) == "True"
    assert py_bool(False) == "False"
    assert py_bool([]) == "False"
    assert py_bool(["x"]) == "True"


def test_access_rule_py_emits_constructor_with_all_fields():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        required_role="moderator",
        identity_symbols=["principal"],
        document_symbols=["document"],
        when=Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("id",))),
        effect="deny",
    )
    source = access_rule_py(rule)
    assert "principal='identity:users'" in source
    assert "required_role='moderator'" in source
    assert "identity_symbols=['principal']" in source
    assert "document_symbols=['document']" in source
    assert "effect='deny'" in source
    assert "when=Equals(FieldRef('principal', ('sub',)), FieldRef('document', ('id',)))" in source


def test_access_rule_py_without_when_emits_none():
    rule = AccessRuleDescriptor(principal="authenticated")
    assert "when=None" in access_rule_py(rule)


def test_role_hierarchies_py_round_trips():
    hierarchies = {"admin_user": {"super_admin": {"admin", "moderator"}, "admin": {"moderator"}}}
    reconstructed = eval(role_hierarchies_py(hierarchies))
    assert reconstructed == hierarchies


def test_role_hierarchies_py_empty():
    assert role_hierarchies_py({}) == "{}"


def _route(operation, document_symbols=None):
    rules = None
    if document_symbols is not None:
        rules = [AccessRuleDescriptor(principal="identity:users", document_symbols=document_symbols)]
    return RouteDescriptor(
        method="DELETE",
        path="/x/{id}",
        operation=operation,
        collection="x",
        is_public=False,
        needs_auth=True,
        is_identity_create=False,
        body_model=None,
        has_id_param=True,
        password_via=False,
        access_rules=rules,
    )


@pytest.mark.parametrize("operation", ["get", "update", "replace", "delete"])
def test_needs_post_fetch_true_for_document_rule_on_fetching_op(operation):
    assert needs_post_fetch(_route(operation, document_symbols=["document"]))


def test_needs_post_fetch_false_without_document_symbols():
    assert not needs_post_fetch(_route("delete", document_symbols=[]))
    assert not needs_post_fetch(_route("delete", document_symbols=None))


def test_needs_post_fetch_false_for_non_fetching_op():
    assert not needs_post_fetch(_route("create", document_symbols=["document"]))
    assert not needs_post_fetch(_route("list", document_symbols=["document"]))
