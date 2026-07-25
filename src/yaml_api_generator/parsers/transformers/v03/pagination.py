"""v0.3 controller pagination parsing and validation.

Pagination is declared explicitly at the controller (``operations.<op>.pagination``)
and nowhere else: the repository primitives and the service mapping stay implicit.
This module turns that declaration into an ``IRPagination`` and validates it
against the entity it pages. ``offset`` and ``keyset`` are implemented; ``cursor``,
``range`` and ``count: estimated`` are reserved -- accepted and validated
syntactically here, without a runtime.
"""

from typing import Any

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.ir.api import IRPageSize, IRPagination, IRSortKey
from yaml_api_generator.parsers.yaml_parser import ConfigError

_STRATEGIES = {"offset", "keyset", "cursor", "range"}
_KEYSET_LIKE = {"keyset", "cursor"}
_COUNTS = {"none", "exact", "estimated"}
_OVERFLOWS = {"clamp", "reject"}
_DIRECTIONS = {"asc", "desc"}


def parse_pagination(
    raw: Any,
    collection: IRCollection | None,
    path: str,
) -> tuple[IRPagination | None, list[ConfigError]]:
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, [ConfigError(
            code="PAGINATION_INVALID",
            message="pagination must be an object",
            path=path,
        )]

    errors: list[ConfigError] = []
    strategy = raw.get("strategy")
    if strategy not in _STRATEGIES:
        errors.append(ConfigError(
            code="PAGINATION_INVALID_STRATEGY",
            message=f"Unknown pagination strategy '{strategy}'",
            path=f"{path}.strategy",
            hint="Use one of: offset, keyset, cursor, range",
        ))

    size, size_errors = _parse_size(raw.get("size"), f"{path}.size")
    errors.extend(size_errors)

    count = raw.get("count", "none")
    if count not in _COUNTS:
        errors.append(ConfigError(
            code="PAGINATION_INVALID_COUNT",
            message=f"Unknown count mode '{count}'",
            path=f"{path}.count",
            hint="Use one of: none, exact, estimated",
        ))

    on_overflow = raw.get("onOverflow", "clamp")
    if on_overflow not in _OVERFLOWS:
        errors.append(ConfigError(
            code="PAGINATION_INVALID_OVERFLOW",
            message=f"Unknown onOverflow mode '{on_overflow}'",
            path=f"{path}.onOverflow",
            hint="Use one of: clamp, reject",
        ))

    sort, sort_errors = _parse_sort(raw.get("sort"), collection, f"{path}.sort")
    errors.extend(sort_errors)

    if strategy in _KEYSET_LIKE:
        errors.extend(_validate_keyset(sort, collection, path))

    on = raw.get("on")
    if strategy == "range":
        errors.extend(_validate_range(on, collection, path))

    if errors:
        return None, errors

    return IRPagination(
        strategy=strategy,
        size=size,
        count=count,
        on_overflow=on_overflow,
        envelope=bool(raw.get("envelope", False)),
        sort=sort,
        on=on,
    ), []


def _parse_size(raw: Any, path: str) -> tuple[IRPageSize, list[ConfigError]]:
    if not isinstance(raw, dict):
        return IRPageSize(default=0, max=0), [ConfigError(
            code="PAGINATION_INVALID_SIZE",
            message="pagination.size must declare 'default' and 'max'",
            path=path,
        )]
    default = raw.get("default")
    maximum = raw.get("max")
    errors: list[ConfigError] = []
    if not isinstance(default, int) or isinstance(default, bool) or default < 0:
        errors.append(ConfigError(
            code="PAGINATION_INVALID_SIZE",
            message="pagination.size.default must be a non-negative integer",
            path=f"{path}.default",
        ))
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        errors.append(ConfigError(
            code="PAGINATION_INVALID_SIZE",
            message="pagination.size.max must be a positive integer",
            path=f"{path}.max",
        ))
    if not errors and default > maximum:
        errors.append(ConfigError(
            code="PAGINATION_INVALID_SIZE",
            message="pagination.size.default must not exceed size.max",
            path=path,
        ))
    return IRPageSize(default=default or 0, max=maximum or 0), errors


def _parse_sort(
    raw: Any, collection: IRCollection | None, path: str
) -> tuple[tuple[IRSortKey, ...], list[ConfigError]]:
    if raw is None:
        return (), []
    if not isinstance(raw, list):
        return (), [ConfigError(
            code="PAGINATION_INVALID_SORT",
            message="pagination.sort must be a list of { field, dir }",
            path=path,
        )]
    keys: list[IRSortKey] = []
    errors: list[ConfigError] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict) or "field" not in entry:
            errors.append(ConfigError(
                code="PAGINATION_INVALID_SORT",
                message="each sort entry must declare a 'field'",
                path=f"{path}[{index}]",
            ))
            continue
        direction = entry.get("dir", "asc")
        if direction not in _DIRECTIONS:
            errors.append(ConfigError(
                code="PAGINATION_INVALID_SORT",
                message=f"sort dir must be 'asc' or 'desc', got '{direction}'",
                path=f"{path}[{index}].dir",
            ))
            continue
        field = entry["field"]
        if collection is not None and not _has_field(collection, field):
            errors.append(ConfigError(
                code="PAGINATION_SORT_FIELD_UNKNOWN",
                message=f"sort field '{field}' is not a field of '{collection.name}'",
                path=f"{path}[{index}].field",
            ))
            continue
        keys.append(IRSortKey(field=field, dir=direction))
    return tuple(keys), errors


def _validate_keyset(
    sort: tuple[IRSortKey, ...],
    collection: IRCollection | None,
    path: str,
) -> list[ConfigError]:
    if not sort:
        return [ConfigError(
            code="PAGINATION_KEYSET_SORT_REQUIRED",
            message="keyset and cursor pagination require a 'sort'",
            path=f"{path}.sort",
            hint="Declare at least one sort key; the last must be a unique, indexed field",
        )]
    if collection is None:
        return []
    tiebreaker = sort[-1].field
    if not _is_unique(collection, tiebreaker):
        return [ConfigError(
            code="PAGINATION_KEYSET_TIEBREAKER_NOT_UNIQUE",
            message=(
                f"keyset tiebreaker '{tiebreaker}' must be a unique, indexed field"
            ),
            path=f"{path}.sort",
            hint="Mark the last sort field 'unique: true' (or use the id field)",
        )]
    return []


def _validate_range(
    on: Any, collection: IRCollection | None, path: str
) -> list[ConfigError]:
    if not isinstance(on, str) or not on:
        return [ConfigError(
            code="PAGINATION_RANGE_FIELD_REQUIRED",
            message="range pagination requires 'on: <field>'",
            path=f"{path}.on",
        )]
    if collection is not None and not _has_field(collection, on):
        return [ConfigError(
            code="PAGINATION_SORT_FIELD_UNKNOWN",
            message=f"range field '{on}' is not a field of '{collection.name}'",
            path=f"{path}.on",
        )]
    return []


def _has_field(collection: IRCollection, field: str) -> bool:
    return field == collection.idField or field in collection.fields


def _is_unique(collection: IRCollection, field: str) -> bool:
    if field == collection.idField:
        return True
    cfg = collection.fields.get(field)
    return isinstance(cfg, dict) and (bool(cfg.get("unique")) or cfg.get("type") == "id")
