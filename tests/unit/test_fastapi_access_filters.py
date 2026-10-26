"""Unit tests for the FastAPI access-rule compilation filters.

Verifies that ``rule_to_predicate`` compiles IR access rules to expressions over
the shipped ``access`` runtime that admit exactly the intended principals and
rows, and that ``needs_post_fetch`` identifies routes requiring a post-fetch
authorization check.
"""

import pytest

from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor, RouteDescriptor
from yaml_api_generator.generators.backend.fastapi.access_filters import (
    is_unconditional,
    needs_document_rule,
    needs_post_fetch,
    py_bool,
    role_hierarchies_py,
    rule_to_predicate,
)
from yaml_api_generator.ir.when import And, Equals, FieldRef, In, IsNotNull, IsNull, Not, NotIn, Or, StringLiteral
from yaml_api_generator.runtime import access
from yaml_api_generator.runtime.access import EVERY_ROW, NO_ROW, Field

USER = {"identity_collection": "users", "sub": "u1", "roles": ["admin"], "record": {"role": "admin"}}


def _predicate(rule, **symbols):
    namespace = {
        **vars(access),
        "_principal_has_role": lambda principal, role: role in principal.get("roles", ()),
        "principal": USER,
        **symbols,
    }
    return eval(rule_to_predicate(rule), namespace)


def test_py_bool():
    assert py_bool(True) == "True"
    assert py_bool(False) == "False"
    assert py_bool([]) == "False"
    assert py_bool(["x"]) == "True"


def test_identity_scope_admits_only_its_collection():
    rule = AccessRuleDescriptor(principal="identity:admins")
    assert _predicate(rule) == NO_ROW
    assert _predicate(rule, principal={**USER, "identity_collection": "admins"}) == EVERY_ROW


def test_required_role_is_checked():
    assert _predicate(AccessRuleDescriptor(principal="identity:users", required_role="admin")) == EVERY_ROW
    assert _predicate(AccessRuleDescriptor(principal="identity:users", required_role="owner")) == NO_ROW


def test_when_equals_against_loaded_document():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("created_by",))),
    )
    assert _predicate(rule, document={"created_by": "u1"}) == EVERY_ROW
    assert _predicate(rule, document={"created_by": "u2"}) == NO_ROW


def test_when_equals_against_listed_rows_is_a_row_predicate():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("created_by",))),
    )
    predicate = _predicate(rule, document=Field(()))
    assert predicate.mongo() == {"created_by": "u1"}
    assert [row["created_by"] for row in ({"created_by": "u1"}, {"created_by": "u2"}) if predicate.matches(row)] == ["u1"]


def test_in_and_not_in():
    role_in = AccessRuleDescriptor(
        principal="identity:users", when=In(FieldRef("principal", ("record", "role")), ("admin", "moderator"))
    )
    role_not_in = AccessRuleDescriptor(
        principal="identity:users", when=NotIn(FieldRef("principal", ("record", "role")), ("admin",))
    )
    assert _predicate(role_in) == EVERY_ROW
    assert _predicate(role_not_in) == NO_ROW


def test_and_or_not():
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=And(
            Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("owner",))),
            Or(
                Equals(FieldRef("principal", ("record", "role")), StringLiteral("editor")),
                Not(Equals(FieldRef("principal", ("record", "role")), StringLiteral("banned"))),
            ),
        ),
    )
    assert _predicate(rule, document={"owner": "u1"}) == EVERY_ROW
    assert _predicate(rule, document={"owner": "u2"}) == NO_ROW


def test_missing_document_admits_nothing():
    rule = AccessRuleDescriptor(principal="identity:users", document_symbols=["document"])
    assert _predicate(rule, document=None) == NO_ROW
    assert _predicate(rule, document={}) == EVERY_ROW


def test_is_unconditional_true():
    rule = AccessRuleDescriptor(principal="")
    assert is_unconditional(rule) is True


def test_is_unconditional_false_when_identity_is_scoped():
    rule = AccessRuleDescriptor(principal="identity:admins")
    assert is_unconditional(rule) is False


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


def test_is_null_and_is_not_null():
    is_null = AccessRuleDescriptor(
        principal="identity:users", when=IsNull(operand=FieldRef("document", ("organizationId",)))
    )
    is_not_null = AccessRuleDescriptor(
        principal="identity:users", when=IsNotNull(operand=FieldRef("principal", ("record", "role")))
    )
    assert _predicate(is_null, document={}) == EVERY_ROW
    assert _predicate(is_null, document={"organizationId": "o1"}) == NO_ROW
    assert _predicate(is_not_null) == EVERY_ROW
