"""Backend-agnostic pagination primitives and request mapping.

The repository speaks a small, fixed vocabulary of all-optional primitives
(limit, skip, sort, bounds, count). A list-shaped operation applies whichever
are populated; omitting all of them is the unbounded v0.2 list. Bounds are the
one non-trivial primitive: each bound is an ordered tuple of comparison keys
that compiles to a *lexicographic* comparison, so a keyset page over a compound
sort is expressed as a single bound and expanded here into the canonical
OR-of-AND disjunction. Both the SQL and Mongo backends render that same
expansion into their native query shapes.
"""

import base64
import json
from dataclasses import dataclass
from typing import Any

from yaml_api_generator.ir.api import IRPagination, IRSortKey


@dataclass(frozen=True)
class SortKey:
    field: str
    dir: str = "asc"

    @property
    def descending(self) -> bool:
        return self.dir == "desc"


@dataclass(frozen=True)
class BoundKey:
    field: str
    op: str
    value: Any


Bound = tuple[BoundKey, ...]

_MAX_CURSOR_LENGTH = 1024
_MAX_SKIP = 2**63 - 1
_CURSOR_SCALARS = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class Primitives:
    limit: int | None = None
    skip: int | None = None
    sort: tuple[SortKey, ...] = ()
    bounds: tuple[Bound, ...] = ()
    count: str = "none"


@dataclass(frozen=True)
class Page:
    rows: list[dict[str, Any]]
    total: int | None = None


class PageOverflowError(ValueError):
    """Requested page size exceeds size.max under onOverflow: reject."""

    def __init__(self, requested: int, maximum: int) -> None:
        super().__init__(
            f"Requested page size {requested} exceeds the maximum of {maximum}"
        )
        self.requested = requested
        self.maximum = maximum


class InvalidPageRequestError(ValueError):
    """A pagination query parameter does not denote a usable page position."""

    def __init__(self, parameter: str) -> None:
        super().__init__(f"Invalid pagination parameter '{parameter}'")
        self.parameter = parameter


def expand_bound(bound: Bound):
    """Yield the disjuncts of a lexicographic comparison.

    For bound [(a,op_a,va), (b,op_b,vb)] yields, in order:
      ([], (a, op_a, va))
      ([(a, va)], (b, op_b, vb))
    i.e. each position contributes one disjunct: the earlier fields pinned to
    equality, the current field compared with its operator.
    """
    for index, key in enumerate(bound):
        equalities = [(bound[j].field, bound[j].value) for j in range(index)]
        yield equalities, key


def _to_sort(keys: tuple[IRSortKey, ...]) -> tuple[SortKey, ...]:
    return tuple(SortKey(k.field, k.dir) for k in keys)


def _strict_op(sort_key: SortKey) -> str:
    return "lt" if sort_key.descending else "gt"


def _int(value: Any) -> int | None:
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def encode_position(item: dict[str, Any], sort: tuple[SortKey, ...]) -> str:
    values = [item.get(key.field) for key in sort]
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_position(token: str, sort: tuple[SortKey, ...]) -> list[Any]:
    """Decode an `after` token into one scalar per declared sort key.

    Anything else is client input that cannot denote a page position: a
    non-scalar would reach the driver as a query operator rather than a value.
    """
    if len(token) > _MAX_CURSOR_LENGTH:
        raise InvalidPageRequestError("after")
    try:
        values = json.loads(base64.urlsafe_b64decode(token.encode()))
    except (ValueError, RecursionError):
        raise InvalidPageRequestError("after") from None
    if (
        not isinstance(values, list)
        or len(values) != len(sort)
        or not all(isinstance(value, _CURSOR_SCALARS) for value in values)
    ):
        raise InvalidPageRequestError("after")
    return values


def _skip(query: dict[str, Any]) -> int:
    requested = max(0, _int(query.get("offset")) or 0)
    if requested > _MAX_SKIP:
        raise InvalidPageRequestError("offset")
    return requested


def _clamp_limit(pagination: IRPagination, query: dict[str, Any]) -> int:
    requested = _int(query.get("limit"))
    if requested is None:
        return pagination.size.default
    if requested > pagination.size.max:
        if pagination.on_overflow == "reject":
            raise PageOverflowError(requested, pagination.size.max)
        return pagination.size.max
    return max(0, requested)


def _offset_primitives(pagination: IRPagination, query: dict[str, Any]) -> Primitives:
    return Primitives(
        limit=_clamp_limit(pagination, query),
        skip=_skip(query),
        sort=_to_sort(pagination.sort),
        count=pagination.count,
    )


def _keyset_primitives(pagination: IRPagination, query: dict[str, Any]) -> Primitives:
    sort = _to_sort(pagination.sort)
    limit = _clamp_limit(pagination, query)
    bounds: tuple[Bound, ...] = ()
    after = _scalar(query.get("after"))
    if after:
        values = decode_position(after, sort)
        bound = tuple(
            BoundKey(key.field, _strict_op(key), value)
            for key, value in zip(sort, values)
        )
        bounds = (bound,)
    return Primitives(
        limit=limit + 1,
        sort=sort,
        bounds=bounds,
        count=pagination.count,
    )


_MAPPERS = {"offset": _offset_primitives, "keyset": _keyset_primitives}


def map_request(pagination: IRPagination, query: dict[str, Any]) -> Primitives:
    return _MAPPERS[pagination.strategy](pagination, query or {})


def build_response(
    pagination: IRPagination,
    page: Page,
    query: dict[str, Any],
) -> Any:
    if pagination.strategy == "keyset":
        return _keyset_response(pagination, page, query)
    return _offset_response(pagination, page, query)


def _offset_response(
    pagination: IRPagination, page: Page, query: dict[str, Any]
) -> Any:
    if not pagination.envelope:
        return page.rows
    envelope: dict[str, Any] = {
        "items": page.rows,
        "limit": _clamp_limit(pagination, query),
        "offset": _skip(query),
    }
    if pagination.count != "none":
        envelope["total"] = page.total
    return envelope


def _keyset_response(
    pagination: IRPagination, page: Page, query: dict[str, Any]
) -> Any:
    sort = _to_sort(pagination.sort)
    limit = _clamp_limit(pagination, query)
    has_more = len(page.rows) > limit
    items = page.rows[:limit]
    if not pagination.envelope:
        return items
    envelope: dict[str, Any] = {"items": items, "hasMore": has_more}
    envelope["next"] = encode_position(items[-1], sort) if has_more and items else None
    if pagination.count != "none":
        envelope["total"] = page.total
    return envelope
