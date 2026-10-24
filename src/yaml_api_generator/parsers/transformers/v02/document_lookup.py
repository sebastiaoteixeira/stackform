"""Desugar document bindings that name a record by route parameters into where-bindings.

``owner: users by ownerId`` loads the ``users`` record whose id field equals the
``ownerId`` route parameter, which is exactly ``users where <idField> = $ownerId``.

A bare ``document: posts`` binds the route's own record. A CRUD route fetches that
record itself; any other route loads it through its record parameter, within the
scope its other path parameters set.
"""

from dataclasses import replace

from yaml_api_generator.ir import (
    IRAccessRule,
    IRCollection,
    IRDocumentBinding,
    IRRoute,
    IRSymbolRef,
    IRWhereConjunct,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


def _invalid(message: str, path: str) -> ConfigErrors:
    return ConfigErrors([ConfigError(code="DOCUMENT_BINDING_INVALID", message=message, path=path)])


def _equal_to_params(fields_to_params: dict[str, str]) -> tuple[IRWhereConjunct, ...]:
    return tuple(
        IRWhereConjunct(field=field, rhs=IRSymbolRef(root=param))
        for field, param in fields_to_params.items()
    )


def _route_record(collection: IRCollection, route: IRRoute, path: str) -> dict[str, str]:
    if route.record_param is None:
        raise _invalid(f"'{collection.name}' binds the route's record, but the route path has no record parameter", path)
    scope = collection.scope(route.path_params, route.record_param)
    return {**{param: param for param in scope}, collection.idField: route.record_param}


def _where_binding(
    binding: IRDocumentBinding, collections: dict[str, IRCollection], route: IRRoute, path: str
) -> IRDocumentBinding:
    if binding.where or (binding.id_param is None and route.serves_crud):
        return binding
    collection = collections.get(binding.collection)
    if collection is None:
        raise _invalid(f"document binding references unknown collection '{binding.collection}'", path)
    lookup = (
        {collection.idField: binding.id_param} if binding.id_param is not None
        else _route_record(collection, route, path)
    )
    return IRDocumentBinding(collection=binding.collection, where=_equal_to_params(lookup))


def _rule_lookups(
    rule: IRAccessRule, collections: dict[str, IRCollection], route: IRRoute, path: str
) -> IRAccessRule:
    return replace(rule, document_symbols={
        name: _where_binding(binding, collections, route, f"{path}.given.{name}")
        for name, binding in rule.document_symbols.items()
    })


def desugar_document_lookups(
    routes: list[IRRoute], collections: dict[str, IRCollection]
) -> list[IRRoute]:
    return [
        replace(route, access_rules=[
            _rule_lookups(rule, collections, route, f"{route.method} {route.path} access[{index}]")
            for index, rule in enumerate(route.access_rules)
        ]) if route.access_rules else route
        for route in routes
    ]
