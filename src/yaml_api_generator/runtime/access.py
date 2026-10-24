"""Access-rule runtime shared by the built-in server and generated applications.

``values_equal`` is the equality every ``when`` comparison uses. On list routes
a rule that reads the listed record becomes a row predicate: operands that do not
name a record field fold to constants, and the ordered allow/deny rules fold into
one predicate that a repository applies in memory, as a Mongo query or as a SQL
clause.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial, reduce
from operator import eq
from typing import Any
from uuid import UUID

try:
    from bson import ObjectId

    _IDISH: tuple[type, ...] = (UUID, ObjectId)
except ImportError:
    _IDISH = (UUID,)


def values_equal(left: Any, right: Any) -> bool:
    """Compare by value, matching identifiers across their string and native forms.

    Booleans, numbers and plain scalars never coerce, so ``"1" == 1`` and
    ``"True" == True`` stay false.
    """
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left == right:
        return True
    if isinstance(left, _IDISH) or isinstance(right, _IDISH):
        return str(left) == str(right)
    return False


@dataclass(frozen=True)
class Field:
    """A field of the listed record, addressed by its dotted path."""

    path: tuple[str, ...]

    def value(self, row: dict[str, Any]) -> Any:
        return reduce(
            lambda current, key: current.get(key) if isinstance(current, dict) else None,
            self.path,
            row,
        )

    @property
    def name(self) -> str:
        return ".".join(self.path)

    def column(self, table: Any) -> Any:
        if len(self.path) != 1:
            raise ValueError(f"Row filters on SQL tables need a top-level field, got '{self.name}'")
        return table.c[self.path[0]]


class Predicate:
    def matches(self, row: dict[str, Any]) -> bool:
        raise NotImplementedError

    def mongo(self) -> dict[str, Any]:
        raise NotImplementedError

    def sql(self, table: Any) -> Any:
        raise NotImplementedError


@dataclass(frozen=True)
class Constant(Predicate):
    value: bool

    def matches(self, row: dict[str, Any]) -> bool:
        return self.value

    def mongo(self) -> dict[str, Any]:
        return {} if self.value else {"$expr": False}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        return sa.true() if self.value else sa.false()


EVERY_ROW = Constant(True)
NO_ROW = Constant(False)


@dataclass(frozen=True)
class FieldEquals(Predicate):
    field: Field
    value: Any

    def matches(self, row: dict[str, Any]) -> bool:
        return values_equal(self.field.value(row), self.value)

    def mongo(self) -> dict[str, Any]:
        return {self.field.name: self.value}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        column = self.field.column(table)
        if self.value is None:
            return column.is_(None)
        return sa.and_(column.is_not(None), column == self.value)


@dataclass(frozen=True)
class FieldsEqual(Predicate):
    left: Field
    right: Field

    def matches(self, row: dict[str, Any]) -> bool:
        return values_equal(self.left.value(row), self.right.value(row))

    def mongo(self) -> dict[str, Any]:
        operands = [{"$ifNull": [f"${field.name}", None]} for field in (self.left, self.right)]
        return {"$expr": {"$eq": operands}}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        left, right = self.left.column(table), self.right.column(table)
        return sa.or_(
            sa.and_(left.is_(None), right.is_(None)),
            sa.and_(left.is_not(None), right.is_not(None), left == right),
        )


@dataclass(frozen=True)
class FieldIn(Predicate):
    field: Field
    values: tuple[Any, ...]

    def matches(self, row: dict[str, Any]) -> bool:
        value = self.field.value(row)
        return any(values_equal(value, candidate) for candidate in self.values)

    def mongo(self) -> dict[str, Any]:
        return {self.field.name: {"$in": list(self.values)}}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        column = self.field.column(table)
        return sa.and_(column.is_not(None), column.in_(self.values))


@dataclass(frozen=True)
class Negation(Predicate):
    operand: Predicate

    def matches(self, row: dict[str, Any]) -> bool:
        return not self.operand.matches(row)

    def mongo(self) -> dict[str, Any]:
        return {"$nor": [self.operand.mongo()]}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        return sa.not_(self.operand.sql(table))


@dataclass(frozen=True)
class Conjunction(Predicate):
    left: Predicate
    right: Predicate

    def matches(self, row: dict[str, Any]) -> bool:
        return self.left.matches(row) and self.right.matches(row)

    def mongo(self) -> dict[str, Any]:
        return {"$and": [self.left.mongo(), self.right.mongo()]}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        return sa.and_(self.left.sql(table), self.right.sql(table))


@dataclass(frozen=True)
class Disjunction(Predicate):
    left: Predicate
    right: Predicate

    def matches(self, row: dict[str, Any]) -> bool:
        return self.left.matches(row) or self.right.matches(row)

    def mongo(self) -> dict[str, Any]:
        return {"$or": [self.left.mongo(), self.right.mongo()]}

    def sql(self, table: Any) -> Any:
        import sqlalchemy as sa

        return sa.or_(self.left.sql(table), self.right.sql(table))


def value_at(root: Any, path: tuple[str, ...]) -> Any:
    """The value at ``path`` under ``root``, or the record field it names when ``root`` is a ``Field``."""
    if isinstance(root, Field):
        return Field(root.path + path)
    return Field(path).value(root)


def has_path(root: Any, path: tuple[str, ...]) -> bool:
    """Whether ``root`` carries the key at ``path``, even with a null value."""
    parent = value_at(root, path[:-1])
    return isinstance(parent, dict) and path[-1] in parent


def constant(value: bool) -> Constant:
    return EVERY_ROW if value else NO_ROW


def equals(left: Any, right: Any) -> Predicate:
    if isinstance(left, Field) and isinstance(right, Field):
        return FieldsEqual(left, right)
    if isinstance(left, Field):
        return FieldEquals(left, right)
    if isinstance(right, Field):
        return FieldEquals(right, left)
    return constant(values_equal(left, right))


def one_of(operand: Any, values: tuple[Any, ...]) -> Predicate:
    if isinstance(operand, Field):
        return FieldIn(operand, tuple(values))
    return constant(any(values_equal(operand, value) for value in values))


def is_null(operand: Any) -> Predicate:
    return FieldEquals(operand, None) if isinstance(operand, Field) else constant(operand is None)


def all_of(*predicates: Predicate) -> Predicate:
    return reduce(conjoin, predicates, EVERY_ROW)


def matching(criteria: Mapping[str, Any]) -> Predicate:
    """The rows whose top-level fields hold the values ``criteria`` maps them to."""
    return all_of(*(FieldEquals(Field((name,)), value) for name, value in criteria.items()))


def negate(predicate: Predicate) -> Predicate:
    if isinstance(predicate, Constant):
        return constant(not predicate.value)
    if isinstance(predicate, Negation):
        return predicate.operand
    return Negation(predicate)


def conjoin(left: Predicate, right: Predicate) -> Predicate:
    if isinstance(left, Constant):
        return right if left.value else NO_ROW
    if isinstance(right, Constant):
        return left if right.value else NO_ROW
    return Conjunction(left, right)


def disjoin(left: Predicate, right: Predicate) -> Predicate:
    if isinstance(left, Constant):
        return EVERY_ROW if left.value else right
    if isinstance(right, Constant):
        return EVERY_ROW if right.value else left
    return Disjunction(left, right)


class AccessDenied(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def refusal(self, principal: Any) -> tuple[int, str]:
        """The status and detail refusing the caller ``principal`` names."""
        return 403, self.reason


class Unadmitted(AccessDenied):
    """No rule admits the caller, whom authenticating may yet admit."""

    def refusal(self, principal: Any) -> tuple[int, str]:
        return (401, "Unauthorized") if principal is None else super().refusal(principal)


@dataclass(frozen=True)
class Decision:
    """One access rule: its effect when ``predicate`` holds, and its refusal reason."""

    effect: str
    predicate: Predicate
    reason: str | None = None

    def admit(self, rest: Predicate) -> Predicate:
        """Fold this rule in front of the rules after it: the first match decides."""
        if self.effect == "deny":
            return conjoin(negate(self.predicate), rest)
        return disjoin(self.predicate, rest)


def refusal_reason(decisions: list[Decision]) -> str:
    """The detail of a refusal that no deny rule decided."""
    return next(
        (decision.reason for decision in decisions if decision.effect == "allow" and decision.reason),
        "Forbidden",
    )


def decide(decisions: list[Decision], holds: Callable[[Predicate], bool] = partial(eq, EVERY_ROW)) -> int:
    """Index of the first rule whose predicate ``holds``: the rule that decides.

    Raises ``AccessDenied`` when that rule denies or no rule holds.
    """
    index, decision = next(
        ((index, decision) for index, decision in enumerate(decisions) if holds(decision.predicate)),
        (None, None),
    )
    if decision is None:
        raise Unadmitted(refusal_reason(decisions))
    if decision.effect == "deny":
        raise AccessDenied(decision.reason or "Forbidden")
    return index


def row_filter(decisions: list[Decision]) -> Predicate:
    """Combine ordered rules into the predicate of the rows they admit.

    Raises ``AccessDenied`` when the rules admit no row whatever its content.
    """
    predicate = reduce(lambda rest, decision: decision.admit(rest), reversed(decisions), NO_ROW)
    if predicate == NO_ROW:
        decide(decisions)
    return predicate


def role_names(held: Any) -> list[str]:
    """Roles held as one name or a list of names, as a list of names."""
    return [held] if isinstance(held, str) else [str(role) for role in held or ()]


@dataclass(frozen=True)
class Roles:
    """Where an identity record keeps its roles: its ``field``, or the managed store under
    ``_auth`` when it declares none, and the role a new record gets when its creator may
    not choose one."""

    field: str | None = None
    default: str | None = None

    def of(self, document: Mapping[str, Any]) -> list[str]:
        return role_names(
            document.get(self.field) if self.field else (document.get("_auth") or {}).get("roles")
        )

    def granted(self, payload: dict[str, Any], assignable: bool) -> dict[str, Any]:
        """``payload`` of a new record, keeping the roles it names only when ``assignable``."""
        if assignable and self.field in payload:
            return payload
        record = {key: value for key, value in payload.items() if key != self.field}
        if self.default is None:
            return record
        if self.field:
            return {**record, self.field: self.default}
        return {**record, "_auth": {**record.get("_auth", {}), "roles": self.default}}
