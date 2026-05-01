from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WhenExpr:
    pass


@dataclass(frozen=True)
class FieldRef(WhenExpr):
    root: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class StringLiteral(WhenExpr):
    value: str


@dataclass(frozen=True)
class Equals(WhenExpr):
    left: WhenExpr
    right: WhenExpr


@dataclass(frozen=True)
class NotEquals(WhenExpr):
    left: WhenExpr
    right: WhenExpr


@dataclass(frozen=True)
class And(WhenExpr):
    left: WhenExpr
    right: WhenExpr


@dataclass(frozen=True)
class Or(WhenExpr):
    left: WhenExpr
    right: WhenExpr


@dataclass(frozen=True)
class Not(WhenExpr):
    operand: WhenExpr


def needs_document(expr: WhenExpr) -> bool:
    if isinstance(expr, FieldRef):
        return expr.root == "document"
    if isinstance(expr, StringLiteral):
        return False
    if isinstance(expr, (Equals, NotEquals, And, Or)):
        return needs_document(expr.left) or needs_document(expr.right)

    if isinstance(expr, Not):
        return needs_document(expr.operand)
    return False


def collect_roots(expr: WhenExpr) -> set[str]:
    if isinstance(expr, FieldRef):
        return {expr.root}
    if isinstance(expr, StringLiteral):
        return set()
    if isinstance(expr, (Equals, NotEquals, And, Or)):
        return collect_roots(expr.left) | collect_roots(expr.right)
    if isinstance(expr, Not):
        return collect_roots(expr.operand)
    return set()
