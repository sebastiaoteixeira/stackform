from __future__ import annotations

from ..when_ast import (
    And,
    Equals,
    FieldRef,
    In,
    Not,
    NotEquals,
    NotIn,
    Not,
    NotEquals,
    Or,
    StringLiteral,
    WhenExpr,
    needs_document,
)

__all__ = ["evaluate_when", "needs_document"]


def _resolve_field(ref: FieldRef, principal: dict | None, document: dict | None) -> object:
    if ref.root == "principal" and principal is not None:
        if len(ref.path) == 1 and ref.path[0] == "sub":
            return principal.get("sub")
        if len(ref.path) >= 2 and ref.path[0] == "record":
            record = principal.get("record", {})
            return record.get(ref.path[1]) if isinstance(record, dict) else None
    elif ref.root == "document" and document is not None:
        if len(ref.path) == 1:
            return document.get(ref.path[0])
    return None


def _evaluate(expr: WhenExpr, principal: dict | None, document: dict | None) -> bool:
    if isinstance(expr, Equals):
        return _resolve(expr.left, principal, document) == _resolve(expr.right, principal, document)
    if isinstance(expr, NotEquals):
        return _resolve(expr.left, principal, document) != _resolve(expr.right, principal, document)
    if isinstance(expr, In):
        return _resolve(expr.left, principal, document) in expr.values
    if isinstance(expr, NotIn):
        return _resolve(expr.left, principal, document) not in expr.values
    if isinstance(expr, And):
        return _evaluate(expr.left, principal, document) and _evaluate(expr.right, principal, document)
    if isinstance(expr, Or):
        return _evaluate(expr.left, principal, document) or _evaluate(expr.right, principal, document)
    if isinstance(expr, Not):
        return not _evaluate(expr.operand, principal, document)
    return False


def _resolve(expr: WhenExpr, principal: dict | None, document: dict | None) -> object:
    if isinstance(expr, FieldRef):
        return _resolve_field(expr, principal, document)
    if isinstance(expr, StringLiteral):
        return expr.value
    return None


def evaluate_when(
    expr: WhenExpr, principal: dict | None, document: dict | None
) -> bool:
    return _evaluate(expr, principal, document)
