"""v0.3 controller pagination parsing and validation.

Pagination is declared explicitly at the controller (``operations.<op>.pagination``)
and nowhere else: the repository primitives and the service mapping stay implicit.
This module turns that declaration into an ``IRPagination`` and validates it
against the entity it pages.

``offset`` and ``keyset`` are the implemented strategies. The grammar names
``cursor`` and ``range`` -- and ``count: estimated`` -- but no runtime backs
them, so a spec that asks for one is rejected here rather than built into an
app that would ignore it.
"""

from dataclasses import dataclass
from typing import Any

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.ir.api import IRPageSize, IRPagination, IRSortKey
from yaml_api_generator.parsers.yaml_parser import ConfigError

_DIRECTIONS = {"asc", "desc"}


@dataclass(frozen=True)
class Choice:
    """A closed set of accepted values, split into implemented and unsupported."""

    subject: str
    supported: frozenset[str]
    unknown_code: str
    unsupported: frozenset[str] = frozenset()

    def validate(self, value: Any, path: str) -> list[ConfigError]:
        if value in self.supported:
            return []
        hint = f"Use one of: {', '.join(sorted(self.supported))}"
        if value in self.unsupported:
            return [ConfigError(
                code="PAGINATION_UNSUPPORTED",
                message=(
                    f"{self.subject} '{value}' is named by the v0.3 grammar but is "
                    "not supported yet"
                ),
                path=path,
                hint=hint,
            )]
        return [ConfigError(
            code=self.unknown_code,
            message=f"Unknown {self.subject} '{value}'",
            path=path,
            hint=hint,
        )]


_STRATEGY = Choice(
    subject="pagination strategy",
    supported=frozenset({"offset", "keyset"}),
    unknown_code="PAGINATION_INVALID_STRATEGY",
    unsupported=frozenset({"cursor", "range"}),
)
_COUNT = Choice(
    subject="count mode",
    supported=frozenset({"none", "exact"}),
    unknown_code="PAGINATION_INVALID_COUNT",
    unsupported=frozenset({"estimated"}),
)
_OVERFLOW = Choice(
    subject="onOverflow mode",
    supported=frozenset({"clamp", "reject"}),
    unknown_code="PAGINATION_INVALID_OVERFLOW",
)


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
    errors.extend(_STRATEGY.validate(strategy, f"{path}.strategy"))

    size, size_errors = _parse_size(raw.get("size"), f"{path}.size")
    errors.extend(size_errors)

    count = raw.get("count", "none")
    errors.extend(_COUNT.validate(count, f"{path}.count"))

    on_overflow = raw.get("onOverflow", "clamp")
    errors.extend(_OVERFLOW.validate(on_overflow, f"{path}.onOverflow"))

    sort, sort_errors = _parse_sort(raw.get("sort"), collection, f"{path}.sort")
    errors.extend(sort_errors)

    if strategy == "keyset":
        errors.extend(_validate_keyset(sort, collection, path))

    if errors:
        return None, errors

    return IRPagination(
        strategy=strategy,
        size=size,
        count=count,
        on_overflow=on_overflow,
        envelope=bool(raw.get("envelope", False)),
        sort=sort,
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
            message="keyset pagination requires a 'sort'",
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


def _has_field(collection: IRCollection, field: str) -> bool:
    return field == collection.idField or field in collection.fields


def _is_unique(collection: IRCollection, field: str) -> bool:
    if field == collection.idField:
        return True
    cfg = collection.fields.get(field)
    return isinstance(cfg, dict) and (bool(cfg.get("unique")) or cfg.get("type") == "id")
