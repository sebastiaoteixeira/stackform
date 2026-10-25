"""Evaluates 'when' condition ASTs against runtime symbol bindings.

A symbol bound to a ``Field`` names the record a list route is filtering, so the
expression evaluates to a row predicate instead of a constant.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

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
    needs_document,
)
from yaml_api_generator.runtime.access import (
    EVERY_ROW,
    NO_ROW,
    Predicate,
    conjoin,
    constant,
    disjoin,
    equals,
    has_path,
    is_null,
    negate,
    one_of,
    value_at,
)

__all__ = ["evaluate_when_with_symbols", "needs_document", "when_predicate"]

Symbols = dict[str, object]


class _Evaluation:
    def __init__(self, symbols: Symbols, request_roots: Collection[str]) -> None:
        self._symbols = symbols
        self._request_roots = request_roots
        self._rules: dict[type, Callable[[WhenExpr], Predicate]] = {
            Equals: lambda expr: equals(self._operand(expr.left), self._operand(expr.right)),
            NotEquals: lambda expr: negate(equals(self._operand(expr.left), self._operand(expr.right))),
            And: lambda expr: conjoin(self.predicate(expr.left), self.predicate(expr.right)),
            Or: lambda expr: disjoin(self.predicate(expr.left), self.predicate(expr.right)),
            Not: lambda expr: negate(self.predicate(expr.operand)),
            In: lambda expr: one_of(self._operand(expr.left), expr.values),
            NotIn: lambda expr: negate(one_of(self._operand(expr.left), expr.values)),
            IsNull: lambda expr: self._is_null(expr.operand),
            IsNotNull: lambda expr: negate(self._is_null(expr.operand)),
        }

    def predicate(self, expr: WhenExpr) -> Predicate:
        rule = self._rules.get(type(expr))
        return rule(expr) if rule else NO_ROW

    def _is_null(self, operand: WhenExpr) -> Predicate:
        if isinstance(operand, FieldRef) and operand.path and operand.root in self._request_roots:
            return constant(not has_path(self._symbols.get(operand.root), operand.path))
        return is_null(self._operand(operand))

    def _operand(self, expr: WhenExpr) -> object:
        if isinstance(expr, StringLiteral):
            return expr.value
        if not isinstance(expr, FieldRef):
            return None
        return value_at(self._symbols.get(expr.root), expr.path or ("sub",))


def when_predicate(
    expr: WhenExpr,
    symbols: Symbols,
    request_roots: Collection[str] = (),
) -> Predicate:
    """The rows ``expr`` admits; a constant unless a symbol is bound to a ``Field``.

    ``is null`` over a ``request_roots`` symbol holds only when the key is absent.
    """
    return _Evaluation(symbols, request_roots).predicate(expr)


def evaluate_when_with_symbols(
    expr: WhenExpr,
    symbols: Symbols,
    request_roots: Collection[str] = (),
) -> bool:
    return when_predicate(expr, symbols, request_roots) == EVERY_ROW
