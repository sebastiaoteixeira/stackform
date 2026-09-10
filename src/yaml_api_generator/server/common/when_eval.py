"""Evaluates 'when' condition ASTs against runtime symbol bindings."""

from __future__ import annotations

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
from .utils.field_access import get_nested_field
from .utils.value_compare import values_equal

__all__ = ["evaluate_when_with_symbols", "needs_document"]


def _resolve_field(
    ref: FieldRef,
    symbols: dict[str, dict | None],
) -> object:
    binding = symbols.get(ref.root)
    if binding is None:
        return None
    if not ref.path:
        return binding.get("sub")
    return get_nested_field(binding, ".".join(ref.path))


def _evaluate(expr: WhenExpr, symbols: dict[str, dict | None]) -> bool:
    if isinstance(expr, Equals):
        return values_equal(_resolve(expr.left, symbols), _resolve(expr.right, symbols))
    if isinstance(expr, NotEquals):
        return not values_equal(_resolve(expr.left, symbols), _resolve(expr.right, symbols))
    if isinstance(expr, And):
        return _evaluate(expr.left, symbols) and _evaluate(expr.right, symbols)
    if isinstance(expr, Or):
        return _evaluate(expr.left, symbols) or _evaluate(expr.right, symbols)
    if isinstance(expr, Not):
        return not _evaluate(expr.operand, symbols)
    if isinstance(expr, In):
        return any(values_equal(_resolve(expr.left, symbols), v) for v in expr.values)
    if isinstance(expr, NotIn):
        return not any(values_equal(_resolve(expr.left, symbols), v) for v in expr.values)
    if isinstance(expr, IsNull):
        return _resolve(expr.operand, symbols) is None
    if isinstance(expr, IsNotNull):
        return _resolve(expr.operand, symbols) is not None
    return False


def _resolve(expr: WhenExpr, symbols: dict[str, dict | None]) -> object:
    if isinstance(expr, FieldRef):
        return _resolve_field(expr, symbols)
    if isinstance(expr, StringLiteral):
        return expr.value
    return None


def evaluate_when_with_symbols(
    expr: WhenExpr,
    symbols: dict[str, dict | None],
) -> bool:
    return _evaluate(expr, symbols)
