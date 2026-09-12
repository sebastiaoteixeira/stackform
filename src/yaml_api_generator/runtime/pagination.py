"""Standalone pagination contract shared by runtime and generated backends."""

import base64
import json
from dataclasses import dataclass
from typing import Any


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
    def __init__(self, requested: int, maximum: int) -> None:
        super().__init__(
            f"Requested page size {requested} exceeds the maximum of {maximum}"
        )


class InvalidPageRequestError(ValueError):
    def __init__(self, parameter: str) -> None:
        super().__init__(f"Invalid pagination parameter '{parameter}'")
        self.parameter = parameter


_MAX_CURSOR_LENGTH = 1024
_MAX_SKIP = 2**63 - 1
_CURSOR_SCALARS = (str, int, float, bool, type(None))


def expand_bound(bound: Bound):
    for index, key in enumerate(bound):
        equalities = [
            (bound[position].field, bound[position].value)
            for position in range(index)
        ]
        yield equalities, key


def _sort(config: dict[str, Any]) -> tuple[SortKey, ...]:
    return tuple(
        SortKey(item["field"], item.get("dir", "asc"))
        for item in config["sort"]
    )


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _integer(query: dict[str, Any], parameter: str) -> int | None:
    value = _scalar(query.get(parameter))
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise InvalidPageRequestError(parameter) from None
    if (
        isinstance(value, bool)
        or isinstance(value, float) and not value.is_integer()
        or parsed < 0
    ):
        raise InvalidPageRequestError(parameter)
    return parsed


def _limit(config: dict[str, Any], query: dict[str, Any]) -> int:
    requested = _integer(query, "limit")
    if requested is None:
        return config["size"]["default"]
    maximum = config["size"]["max"]
    if requested > maximum:
        if config["on_overflow"] == "reject":
            raise PageOverflowError(requested, maximum)
        return maximum
    return requested


def _skip(query: dict[str, Any]) -> int:
    requested = _integer(query, "offset") or 0
    if requested > _MAX_SKIP:
        raise InvalidPageRequestError("offset")
    return requested


def encode_position(item: dict[str, Any], sort: tuple[SortKey, ...]) -> str:
    raw = json.dumps(
        [item.get(key.field) for key in sort],
        separators=(",", ":"),
        default=str,
    ).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_position(token: str, sort: tuple[SortKey, ...]) -> list[Any]:
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


def map_request(config: dict[str, Any], query: dict[str, Any]) -> Primitives:
    sort = _sort(config)
    limit = _limit(config, query)
    if config["strategy"] == "offset":
        return Primitives(
            limit=limit,
            skip=_skip(query),
            sort=sort,
            count=config["count"],
        )
    if limit == 0:
        raise InvalidPageRequestError("limit")
    bounds: tuple[Bound, ...] = ()
    after = _scalar(query.get("after"))
    if after:
        values = decode_position(after, sort)
        bounds = (
            tuple(
                BoundKey(key.field, "lt" if key.descending else "gt", value)
                for key, value in zip(sort, values)
            ),
        )
    return Primitives(
        limit=limit + 1,
        sort=sort,
        bounds=bounds,
        count=config["count"],
    )


def build_response(
    config: dict[str, Any],
    page: Page,
    query: dict[str, Any],
) -> Any:
    limit = _limit(config, query)
    if config["strategy"] == "offset":
        if not config["envelope"]:
            return page.rows
        result: dict[str, Any] = {
            "items": page.rows,
            "limit": limit,
            "offset": _skip(query),
        }
    else:
        has_more = len(page.rows) > limit
        items = page.rows[:limit]
        if not config["envelope"]:
            return items
        result = {
            "items": items,
            "hasMore": has_more,
            "next": (
                encode_position(items[-1], _sort(config))
                if has_more and items
                else None
            ),
        }
    if config["count"] != "none":
        result["total"] = page.total
    return result
