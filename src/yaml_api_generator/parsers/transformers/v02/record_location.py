"""Locate the record each route acts on from its path parameters.

A route acts on one record unless it lists or creates rows. The record
parameter carries that record's id; every other path parameter naming a field
of the route's collection scopes the route to the rows holding its value.
"""

from collections.abc import Callable
from dataclasses import replace

from yaml_api_generator.ir import IRCollection, IRRoute

RecordParam = Callable[[list[str]], str | None]


def id_param(params: list[str]) -> str | None:
    return "id" if "id" in params else None


def last_param(params: list[str]) -> str | None:
    return params[-1] if params else None


def _acts_on_a_record(route: IRRoute) -> bool:
    return not (route.serves_crud and route.operation in ("list", "create"))


def _located(route: IRRoute, collection: IRCollection | None, record_param: RecordParam) -> IRRoute:
    own = record_param(route.path_params) if _acts_on_a_record(route) else None
    scope = collection.scope(route.path_params, own) if collection is not None else ()
    return replace(route, record_param=own, scope=scope)


def locate_records(
    routes: list[IRRoute], collections: dict[str, IRCollection], record_param: RecordParam
) -> list[IRRoute]:
    return [_located(route, collections.get(route.collection), record_param) for route in routes]
