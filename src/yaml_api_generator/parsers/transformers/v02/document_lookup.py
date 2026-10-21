"""Desugar ``<collection> by <param>`` document bindings into where-bindings.

``owner: users by ownerId`` loads the ``users`` record whose id field equals the
``ownerId`` route parameter, which is exactly ``users where <idField> = $ownerId``.
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


def _where_binding(
    binding: IRDocumentBinding, collections: dict[str, IRCollection], path: str
) -> IRDocumentBinding:
    if binding.id_param is None:
        return binding
    collection = collections.get(binding.collection)
    if collection is None:
        raise ConfigErrors([ConfigError(
            code="DOCUMENT_BINDING_INVALID",
            message=f"document binding references unknown collection '{binding.collection}'",
            path=path,
        )])
    return IRDocumentBinding(
        collection=binding.collection,
        where=(IRWhereConjunct(field=collection.idField, rhs=IRSymbolRef(root=binding.id_param)),),
    )


def _rule_lookups(
    rule: IRAccessRule, collections: dict[str, IRCollection], path: str
) -> IRAccessRule:
    return replace(rule, document_symbols={
        name: _where_binding(binding, collections, f"{path}.given.{name}")
        for name, binding in rule.document_symbols.items()
    })


def desugar_document_lookups(
    routes: list[IRRoute], collections: dict[str, IRCollection]
) -> list[IRRoute]:
    return [
        replace(route, access_rules=[
            _rule_lookups(rule, collections, f"{route.method} {route.path} access[{index}]")
            for index, rule in enumerate(route.access_rules)
        ]) if route.access_rules else route
        for route in routes
    ]
