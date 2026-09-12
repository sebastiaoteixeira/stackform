"""Runtime adapter for the standalone pagination contract."""

from typing import Any

from yaml_api_generator.ir.api import IRPagination
from yaml_api_generator.runtime.pagination import (
    Bound,
    BoundKey,
    InvalidPageRequestError,
    Page,
    PageOverflowError,
    Primitives,
    SortKey,
    build_response as _build_response,
    decode_position,
    encode_position,
    expand_bound,
    map_request as _map_request,
)


def _config(pagination: IRPagination) -> dict[str, Any]:
    return {
        "strategy": pagination.strategy,
        "size": {
            "default": pagination.size.default,
            "max": pagination.size.max,
        },
        "count": pagination.count,
        "on_overflow": pagination.on_overflow,
        "envelope": pagination.envelope,
        "sort": [
            {"field": key.field, "dir": key.dir}
            for key in pagination.sort
        ],
    }


def map_request(
    pagination: IRPagination,
    query: dict[str, Any],
) -> Primitives:
    return _map_request(_config(pagination), query)


def build_response(
    pagination: IRPagination,
    page: Page,
    query: dict[str, Any],
) -> Any:
    return _build_response(_config(pagination), page, query)


__all__ = [
    "Bound",
    "BoundKey",
    "InvalidPageRequestError",
    "Page",
    "PageOverflowError",
    "Primitives",
    "SortKey",
    "build_response",
    "decode_position",
    "encode_position",
    "expand_bound",
    "map_request",
]
