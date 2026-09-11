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
    IsNotNull,
    IsNull,
    Not,
    NotEquals,
    NotIn,
    Or,
    StringLiteral,
    WhenExpr,
    collect_roots,
    needs_document,
)


_POST_FETCH_OPERATIONS = frozenset({"get", "update", "replace", "delete"})


def py_bool(value: object) -> str:
    return "True" if value else "False"


def py_literal(value: object) -> str:
    return repr(value)


def _safe_nested(root: str, path: tuple[str, ...]) -> str:
    chain = "".join(f'.get("{p}", {{}})' for p in path[:-1])
    return f'{root}{chain}.get("{path[-1]}")'


def _operand_to_python(
    expr: WhenExpr,
    record_roots: frozenset[str],
    wrapper_roots: frozenset[str],
) -> str:
    if isinstance(expr, StringLiteral):
        return f'"{expr.value}"'
    if isinstance(expr, FieldRef):
        if expr.root in record_roots:
            if not expr.path:
                return expr.root
            if len(expr.path) == 1:
                return f'{expr.root}.get("{expr.path[0]}")'
            return _safe_nested(expr.root, expr.path)
        if expr.root in wrapper_roots:
            return _safe_nested(expr.root, expr.path) if expr.path else expr.root
        if not expr.path:
            return f'{expr.root}.get("sub")'
        if len(expr.path) == 1:
            return f'{expr.root}.get("{expr.path[0]}")'
        if len(expr.path) >= 2 and expr.path[0] == "record":
            return f'{expr.root}.get("record", {{}}).get("{expr.path[1]}")'
        nested = ".".join(f'get("{p}")' for p in expr.path)
        return f"{expr.root}.{nested}"
    return "None"


def _when_to_python(
    expr: WhenExpr,
    record_roots: frozenset[str],
    wrapper_roots: frozenset[str],
) -> str:
    operand = lambda e: _operand_to_python(e, record_roots, wrapper_roots)
    recurse = lambda e: _when_to_python(e, record_roots, wrapper_roots)
    if isinstance(expr, Equals):
        return f"_values_equal({operand(expr.left)}, {operand(expr.right)})"
    if isinstance(expr, NotEquals):
        return f"(not _values_equal({operand(expr.left)}, {operand(expr.right)}))"
    if isinstance(expr, And):
        return f"({recurse(expr.left)} and {recurse(expr.right)})"
    if isinstance(expr, Or):
        return f"({recurse(expr.left)} or {recurse(expr.right)})"
    if isinstance(expr, Not):
        return f"(not {recurse(expr.operand)})"
    if isinstance(expr, In):
        return f"any(_values_equal({operand(expr.left)}, _v) for _v in {tuple(expr.values)!r})"
    if isinstance(expr, NotIn):
        return f"(not any(_values_equal({operand(expr.left)}, _v) for _v in {tuple(expr.values)!r}))"
    if isinstance(expr, IsNull):
        return f"({operand(expr.operand)} is None)"
    if isinstance(expr, IsNotNull):
        return f"({operand(expr.operand)} is not None)"
    return "False"


def rule_to_python(rule: AccessRuleDescriptor) -> str:
    """Compile a single access rule to an inline Python boolean expression."""
    record_roots = frozenset(sym.name for sym in rule.request_symbols if sym.is_record_shaped)
    wrapper_roots = frozenset(sym.name for sym in rule.request_symbols if sym.is_whole)
    conditions: list[str] = []
    if rule.principal.startswith("identity:"):
        collection = rule.principal.removeprefix("identity:")
        conditions.append(f'principal.get("identity_collection") == "{collection}"')
    if rule.required_role is not None:
        conditions.append(f'_principal_has_role(principal, "{rule.required_role}")')
    if rule.when is not None:
        conditions.append(_when_to_python(rule.when, record_roots, wrapper_roots))
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


_PART_SOURCE = {
    "body": "_request_body",
    "path": "_request_path",
    "query": "_request_query",
    "header": "_request_header",
    "cookie": "_request_cookie",
}


def request_symbol_binding(symbol) -> str:
    """Compile a request symbol descriptor to its local-variable assignment."""
    if symbol.is_whole:
        parts = ", ".join(f'"{part}": {source}' for part, source in _PART_SOURCE.items())
        return f"{symbol.name} = {{{parts}}}"
    return f"{symbol.name} = {_PART_SOURCE[symbol.effective_part]}"


def needs_request_rule(rule: AccessRuleDescriptor) -> bool:
    return bool(rule.request_symbols)


def needs_post_fetch(route: RouteDescriptor) -> bool:
    return route.operation in _POST_FETCH_OPERATIONS and any(
        rule.document_symbols or (rule.when is not None and needs_document(rule.when))
        for rule in route.access_rules or ()
    )


def is_unconditional(rule: AccessRuleDescriptor) -> bool:
    return not rule.principal and rule.when is None and rule.required_role is None


def needs_document_rule(rule: AccessRuleDescriptor) -> bool:
    return bool(rule.document_symbols) or (
        rule.when is not None and needs_document(rule.when)
    )
