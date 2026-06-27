"""Jinja filters that compile access rules into inline Python boolean expressions.

At generation time, ``when`` predicates are fully known, so they are compiled
directly into source strings that reference the runtime ``principal`` dict and
the fetched ``document`` dict. No AST interpreter is needed in the generated app.
"""

from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor, RouteDescriptor
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


def _operand_to_python(expr: WhenExpr) -> str:
    if isinstance(expr, StringLiteral):
        return f'"{expr.value}"'
    if isinstance(expr, FieldRef):
        if not expr.path:
            return f'{expr.root}.get("sub")'
        if len(expr.path) == 1:
            return f'{expr.root}.get("{expr.path[0]}")'
        if len(expr.path) >= 2 and expr.path[0] == "record":
            return f'{expr.root}.get("record", {{}}).get("{expr.path[1]}")'
        nested = ".".join(f'get("{p}")' for p in expr.path)
        return f"{expr.root}.{nested}"
    return "None"


def _when_to_python(expr: WhenExpr) -> str:
    if isinstance(expr, Equals):
        return f"{_operand_to_python(expr.left)} == {_operand_to_python(expr.right)}"
    if isinstance(expr, NotEquals):
        return f"{_operand_to_python(expr.left)} != {_operand_to_python(expr.right)}"
    if isinstance(expr, And):
        return f"({_when_to_python(expr.left)} and {_when_to_python(expr.right)})"
    if isinstance(expr, Or):
        return f"({_when_to_python(expr.left)} or {_when_to_python(expr.right)})"
    if isinstance(expr, Not):
        return f"(not {_when_to_python(expr.operand)})"
    if isinstance(expr, In):
        return f"{_operand_to_python(expr.left)} in {tuple(expr.values)!r}"
    if isinstance(expr, NotIn):
        return f"{_operand_to_python(expr.left)} not in {tuple(expr.values)!r}"
    return "False"


def rule_to_python(rule: AccessRuleDescriptor) -> str:
    """Compile a single access rule to an inline Python boolean expression."""
    conditions: list[str] = []
    if rule.required_role is not None:
        conditions.append(f'_principal_has_role(principal, "{rule.required_role}")')
    if rule.when is not None:
        conditions.append(_when_to_python(rule.when))
    return " and ".join(conditions) if conditions else "True"


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


def is_unconditional(rule: AccessRuleDescriptor) -> bool:
    return rule.when is None and rule.required_role is None


def needs_document_rule(rule: AccessRuleDescriptor) -> bool:
    return bool(rule.document_symbols) or (
        rule.when is not None and needs_document(rule.when)
    )
