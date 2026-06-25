"""Unit tests for the FastAPI access-rule compilation filters.

Verifies that ``rule_to_python`` compiles IR access rules to correct inline
Python boolean expressions, and that ``needs_post_fetch`` correctly identifies
routes requiring a post-fetch authorization check.
"""

import pytest

from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor, RouteDescriptor
from yaml_api_generator.generators.backend.fastapi.access_filters import (
    is_unconditional,
    needs_document_rule,
    needs_post_fetch,
    py_bool,
    role_hierarchies_py,
    rule_to_python,
)
from yaml_api_generator.ir.when import And, Equals, FieldRef, In, Not, NotIn, Or, StringLiteral


def test_py_bool():
    assert py_bool(True) == "True"
    assert py_bool(False) == "False"
    assert py_bool([]) == "False"
    assert py_bool(["x"]) == "True"


def test_rule_to_python_unconditional():
    rule = AccessRuleDescriptor(principal="identity:admins")
    assert rule_to_python(rule) == "True"


def test_rule_to_python_role_only():
    rule = AccessRuleDescriptor(principal="identity:admins", required_role="admin")
    assert rule_to_python(rule) == '_principal_has_role(principal, "admin")'


def test_rule_to_python_when_equals():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("created_by",))),
    )
    result = rule_to_python(rule)
    assert 'principal.get("sub") == document.get("created_by")' in result


def test_rule_to_python_role_and_when():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        required_role="admin",
        when=Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("id",))),
    )
    result = rule_to_python(rule)
    assert result.startswith('_principal_has_role(principal, "admin") and ')
    assert 'principal.get("sub") == document.get("id")' in result


def test_rule_to_python_in():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=In(FieldRef("principal", ("role",)), ("admin", "moderator")),
    )
    assert "in ('admin', 'moderator')" in rule_to_python(rule)


def test_rule_to_python_not_in():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=NotIn(FieldRef("principal", ("role",)), ("guest",)),
    )
    assert "not in ('guest',)" in rule_to_python(rule)


def test_rule_to_python_nested_record_path():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("principal", ("record", "role")), StringLiteral("admin")),
    )
    assert 'principal.get("record", {}).get("role")' in rule_to_python(rule)


def test_rule_to_python_and_or():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=And(
            Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("owner",))),
            Or(
                Equals(FieldRef("principal", ("role",)), StringLiteral("admin")),
                Not(Equals(FieldRef("principal", ("role",)), StringLiteral("banned"))),
            ),
        ),
    )
    result = rule_to_python(rule)
    assert "and" in result
    assert "or" in result
    assert "not" in result


def test_is_unconditional_true():
    rule = AccessRuleDescriptor(principal="identity:admins")
    assert is_unconditional(rule) is True


def test_is_unconditional_false_when_role():
    rule = AccessRuleDescriptor(principal="identity:admins", required_role="admin")
    assert is_unconditional(rule) is False


def test_is_unconditional_false_when_expr():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("principal", ("sub",)), StringLiteral("x")),
    )
    assert is_unconditional(rule) is False


def test_needs_document_rule_with_document_symbols():
    rule = AccessRuleDescriptor(principal="identity:users", document_symbols=["document"])
    assert needs_document_rule(rule) is True


def test_needs_document_rule_with_document_ref():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("document", ("owner",)), FieldRef("principal", ("sub",))),
    )
    assert needs_document_rule(rule) is True


def test_needs_document_rule_false():
    rule = AccessRuleDescriptor(principal="identity:users", required_role="admin")
    assert needs_document_rule(rule) is False


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
        path="/api/v1/x/{id}",
        relative_path="/x/{id}",
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
