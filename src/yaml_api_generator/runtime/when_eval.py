from __future__ import annotations

from ..when_ast import (
    And,
    Equals,
    FieldRef,
    Not,
    NotEquals,
    Or,
    StringLiteral,
    WhenExpr,
    needs_document,
)

__all__ = ["evaluate_when", "needs_document"]


def _resolve_field(
    ref: FieldRef,
    symbols: dict[str, dict | None],
) -> object:
    binding = symbols.get(ref.root)
    if binding is None:
        return None
    if not ref.path:
        return binding.get("sub")
    current: object = binding
    for part in ref.path:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _evaluate(expr: WhenExpr, symbols: dict[str, dict | None]) -> bool:
    if isinstance(expr, Equals):
        return _resolve(expr.left, symbols) == _resolve(expr.right, symbols)
    if isinstance(expr, NotEquals):
        return _resolve(expr.left, symbols) != _resolve(expr.right, symbols)
    if isinstance(expr, And):
        return _evaluate(expr.left, symbols) and _evaluate(expr.right, symbols)
    if isinstance(expr, Or):
        return _evaluate(expr.left, symbols) or _evaluate(expr.right, symbols)
    if isinstance(expr, Not):
        return not _evaluate(expr.operand, symbols)
    return False


def _resolve(expr: WhenExpr, symbols: dict[str, dict | None]) -> object:
    if isinstance(expr, FieldRef):
        return _resolve_field(expr, symbols)
    if isinstance(expr, StringLiteral):
        return expr.value
    return None


def evaluate_when(
    expr: WhenExpr,
    principal: dict | None,
    document: dict | None,
) -> bool:
    symbols: dict[str, dict | None] = {}
    if principal is not None:
        symbols["principal"] = principal
    if document is not None:
        symbols["document"] = document
    return _evaluate(expr, symbols)


def evaluate_when_with_symbols(
    expr: WhenExpr,
    symbols: dict[str, dict | None],
) -> bool:
    return _evaluate(expr, symbols)
