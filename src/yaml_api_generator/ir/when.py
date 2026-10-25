"""Authorization expression AST for 'when' conditions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import Any


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


@dataclass(frozen=True)
class In(WhenExpr):
    left: WhenExpr
    values: tuple[Any, ...]


@dataclass(frozen=True)
class NotIn(WhenExpr):
    left: WhenExpr
    values: tuple[Any, ...]


@dataclass(frozen=True)
class IsNull(WhenExpr):
    operand: WhenExpr


@dataclass(frozen=True)
class IsNotNull(WhenExpr):
    operand: WhenExpr


@dataclass(frozen=True)
class PolicyRef(WhenExpr):
    name: str
    args: tuple[str, ...] = ()
    has_parens: bool = False


def needs_document(expr: WhenExpr) -> bool:
    if isinstance(expr, FieldRef):
        return expr.root == "document"
    if isinstance(expr, StringLiteral):
        return False
    if isinstance(expr, (Equals, NotEquals, And, Or)):
        return needs_document(expr.left) or needs_document(expr.right)
    if isinstance(expr, (In, NotIn)):
        return needs_document(expr.left)
    if isinstance(expr, (Not, IsNull, IsNotNull)):
        return needs_document(expr.operand)
    return False


def collect_roots(expr: WhenExpr) -> set[str]:
    if isinstance(expr, FieldRef):
        return {expr.root}
    if isinstance(expr, StringLiteral):
        return set()
    if isinstance(expr, (Equals, NotEquals, And, Or)):
        return collect_roots(expr.left) | collect_roots(expr.right)
    if isinstance(expr, (In, NotIn)):
        return collect_roots(expr.left)
    if isinstance(expr, (Not, IsNull, IsNotNull)):
        return collect_roots(expr.operand)
    return set()


def map_operands(expr: WhenExpr, transform: Callable[[WhenExpr], WhenExpr]) -> WhenExpr:
    """Rebuild ``expr`` with ``transform`` applied to each direct sub-expression."""
    children = {
        field.name: transform(getattr(expr, field.name))
        for field in fields(expr)
        if isinstance(getattr(expr, field.name), WhenExpr)
    }
    return replace(expr, **children) if children else expr
