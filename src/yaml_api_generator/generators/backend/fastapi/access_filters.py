"""Jinja filters that serialize access rules into generated Python source.

The emitted source reconstructs the same dataclasses defined in the generated
``dependencies/when_eval.py`` and ``dependencies/authorization.py`` modules, so
the generated backend evaluates ``when`` expressions with no second
implementation and no runtime dependency on this package.
"""

from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor, RouteDescriptor
from yaml_api_generator.ir.api import EnvRef
from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    In,
    Not,
    NotEquals,
    NotIn,
    Or,
    StringLiteral,
    WhenExpr,
    needs_document,
)


_POST_FETCH_OPERATIONS = frozenset({"get", "update", "replace", "delete"})


def py_bool(value: object) -> str:
    return "True" if value else "False"


def py_literal(value: object) -> str:
    return repr(value)


def env_ref(value: str | EnvRef) -> str:
    """Render a str | EnvRef field as a Python expression in generated source.

    Plain strings become quoted literals; EnvRefs become settings attribute
    accesses, with .get_secret_value() for secret fields.
    """
    if isinstance(value, EnvRef):
        access = f"settings.{value.name}"
        return f"{access}.get_secret_value()" if value.secret else access
    return repr(value)


def when_py(expr: WhenExpr) -> str:
    if isinstance(expr, FieldRef):
        return f"FieldRef({expr.root!r}, {tuple(expr.path)!r})"
    if isinstance(expr, StringLiteral):
        return f"StringLiteral({expr.value!r})"
    if isinstance(expr, Equals):
        return f"Equals({when_py(expr.left)}, {when_py(expr.right)})"
    if isinstance(expr, NotEquals):
        return f"NotEquals({when_py(expr.left)}, {when_py(expr.right)})"
    if isinstance(expr, And):
        return f"And({when_py(expr.left)}, {when_py(expr.right)})"
    if isinstance(expr, Or):
        return f"Or({when_py(expr.left)}, {when_py(expr.right)})"
    if isinstance(expr, Not):
        return f"Not({when_py(expr.operand)})"
    if isinstance(expr, In):
        return f"In({when_py(expr.left)}, {tuple(expr.values)!r})"
    if isinstance(expr, NotIn):
        return f"NotIn({when_py(expr.left)}, {tuple(expr.values)!r})"
    raise TypeError(f"Unsupported when expression: {type(expr).__name__}")


def access_rule_py(rule: AccessRuleDescriptor) -> str:
    when = when_py(rule.when) if rule.when is not None else "None"
    return (
        f"AccessRule(principal={rule.principal!r}, required_role={rule.required_role!r}, "
        f"identity_symbols={list(rule.identity_symbols)!r}, "
        f"document_symbols={list(rule.document_symbols)!r}, "
        f"when={when}, effect={rule.effect!r})"
    )


def role_hierarchies_py(hierarchies: dict[str, dict[str, set[str]]]) -> str:
    if not hierarchies:
        return "{}"
    collections = ", ".join(
        f"{collection!r}: {{"
        + ", ".join(f"{role!r}: {set(included)!r}" for role, included in roles.items())
        + "}"
        for collection, roles in hierarchies.items()
    )
    return "{" + collections + "}"


def needs_post_fetch(route: RouteDescriptor) -> bool:
    return route.operation in _POST_FETCH_OPERATIONS and any(
        rule.document_symbols or (rule.when is not None and needs_document(rule.when))
        for rule in route.access_rules or ()
    )
