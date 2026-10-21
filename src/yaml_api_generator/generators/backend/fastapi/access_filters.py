"""Jinja filters that compile access rules into inline Python predicate expressions.

At generation time, ``when`` predicates are fully known, so they are compiled
directly into calls on the ``access`` runtime module shipped with the app. No AST
interpreter is needed in the generated app.
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


class _RuleCompiler:
    """Compiles a ``when`` expression to a call tree over the shipped ``access`` module.

    The tree evaluates to a constant predicate for a loaded record and to a row
    predicate when the record symbol is bound to ``access.Field``.
    """

    def __init__(self, request_roots: frozenset[str], whole_roots: frozenset[str]) -> None:
        self._request_roots = request_roots
        self._whole_roots = whole_roots
        self._rules = {
            Equals: lambda expr: f"equals({self._operand(expr.left)}, {self._operand(expr.right)})",
            NotEquals: lambda expr: f"negate(equals({self._operand(expr.left)}, {self._operand(expr.right)}))",
            And: lambda expr: f"conjoin({self.compile(expr.left)}, {self.compile(expr.right)})",
            Or: lambda expr: f"disjoin({self.compile(expr.left)}, {self.compile(expr.right)})",
            Not: lambda expr: f"negate({self.compile(expr.operand)})",
            In: lambda expr: f"one_of({self._operand(expr.left)}, {tuple(expr.values)!r})",
            NotIn: lambda expr: f"negate(one_of({self._operand(expr.left)}, {tuple(expr.values)!r}))",
            IsNull: lambda expr: self._is_null(expr.operand),
            IsNotNull: lambda expr: f"negate({self._is_null(expr.operand)})",
        }

    def compile(self, expr: WhenExpr) -> str:
        rule = self._rules.get(type(expr))
        return rule(expr) if rule else "NO_ROW"

    def _is_null(self, operand: WhenExpr) -> str:
        if isinstance(operand, FieldRef) and operand.path and operand.root in self._request_roots:
            return f"constant(not has_path({operand.root}, {operand.path!r}))"
        return f"is_null({self._operand(operand)})"

    def _operand(self, expr: WhenExpr) -> str:
        if isinstance(expr, StringLiteral):
            return repr(expr.value)
        if not isinstance(expr, FieldRef):
            return "None"
        if not expr.path and expr.root in self._whole_roots:
            return expr.root
        return f"value_at({expr.root}, {expr.path or ('sub',)!r})"


def rule_to_predicate(rule: AccessRuleDescriptor) -> str:
    """Compile an access rule to a Python expression of the predicate it admits."""
    compiler = _RuleCompiler(
        request_roots=frozenset(sym.name for sym in rule.request_symbols),
        whole_roots=frozenset(
            sym.name for sym in rule.request_symbols if sym.is_record_shaped or sym.is_whole
        ),
    )
    conditions = [
        *(
            [f'constant(principal.get("identity_collection") == {rule.principal.removeprefix("identity:")!r})']
            if rule.principal.startswith("identity:")
            else []
        ),
        *(
            [f"constant(_principal_has_role(principal, {rule.required_role!r}))"]
            if rule.required_role is not None
            else []
        ),
        *(f"constant({symbol} is not None)" for symbol in rule.document_symbols),
        *([compiler.compile(rule.when)] if rule.when is not None else []),
    ]
    return f"all_of({', '.join(conditions)})"


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
        needs_current_document_rule(rule)
        for rule in route.access_rules or ()
    )


def is_unconditional(rule: AccessRuleDescriptor) -> bool:
    return not rule.principal and rule.when is None and rule.required_role is None


def needs_document_rule(rule: AccessRuleDescriptor) -> bool:
    return bool(rule.document_symbols) or (
        rule.when is not None and needs_document(rule.when)
    )


def needs_current_document_rule(rule: AccessRuleDescriptor) -> bool:
    where_symbols = {
        binding.name for binding in rule.document_bindings if binding.uses_where
    }
    return any(symbol not in where_symbols for symbol in rule.document_symbols) or (
        rule.when is not None and needs_document(rule.when)
    )
