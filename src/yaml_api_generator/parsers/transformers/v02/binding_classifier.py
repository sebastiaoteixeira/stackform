"""Shared classification of a ``given`` binding value into an IR binding.

The same prefix dispatch is used by access rules, reusable policies, the policy
expansion pass and the v0.3 symbol validator. ``binding_kind`` names the binding
form a raw value takes; ``classify_binding`` parses it into the matching IR kind.
"""

from collections.abc import Callable
from enum import Enum, auto
from typing import Any

from yaml_api_generator.ir import (
    IRBinding,
    IRDocumentBinding,
    IRIdentityBinding,
    IRRequestBinding,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.when_parser import (
    parse_document_binding,
    parse_request_binding,
)
from yaml_api_generator.parsers.where_parser import is_where_binding, parse_where_binding

_IDENTITY_PREFIX = "identity:"
_REQUEST_PREFIXES = ("request.", "request:")


class BindingKind(Enum):
    IDENTITY = auto()
    REQUEST = auto()
    WHERE = auto()
    DOCUMENT = auto()


def binding_kind(value: str, allow_where: bool = False) -> BindingKind:
    if value.startswith(_IDENTITY_PREFIX):
        return BindingKind.IDENTITY
    if value == "request" or value.startswith(_REQUEST_PREFIXES):
        return BindingKind.REQUEST
    if allow_where and is_where_binding(value):
        return BindingKind.WHERE
    return BindingKind.DOCUMENT


BindingParser = Callable[
    [str, str, dict[str, str]], tuple[IRBinding | None, list[ConfigError]]
]


def _identity(
    value: str, path: str, entity_to_collection: dict[str, str]
) -> tuple[IRBinding | None, list[ConfigError]]:
    entity_name = value[len(_IDENTITY_PREFIX):]
    collection = entity_to_collection.get(entity_name)
    if collection is None:
        return None, [ConfigError(
            code="ACCESS_UNKNOWN_ENTITY",
            message=f"Unknown auth entity '{entity_name}' in binding",
            path=path,
        )]
    return IRIdentityBinding(entity_name=entity_name, collection_name=collection), []


def _request(
    value: str, path: str, _: dict[str, str]
) -> tuple[IRBinding | None, list[ConfigError]]:
    parsed, errors = parse_request_binding(value, path)
    if parsed is None:
        return None, errors
    part, type_name, raw = parsed
    return IRRequestBinding(part=part, type_name=type_name, raw=raw), errors


def _where(
    value: str, path: str, _: dict[str, str]
) -> tuple[IRBinding | None, list[ConfigError]]:
    parsed, errors = parse_where_binding(value, path)
    if parsed is None:
        return None, errors
    return IRDocumentBinding(collection=parsed.collection, where=parsed.conjuncts), errors


def _document(
    value: str, path: str, _: dict[str, str]
) -> tuple[IRBinding | None, list[ConfigError]]:
    parsed, errors = parse_document_binding(value, path)
    if parsed is None:
        return None, errors
    collection, id_param = parsed
    return IRDocumentBinding(collection=collection, id_param=id_param), errors


_PARSERS: dict[BindingKind, BindingParser] = {
    BindingKind.IDENTITY: _identity,
    BindingKind.REQUEST: _request,
    BindingKind.WHERE: _where,
    BindingKind.DOCUMENT: _document,
}


def classify_binding(
    value: Any,
    path: str,
    entity_to_collection: dict[str, str],
    allow_where: bool = False,
) -> tuple[IRBinding | None, list[ConfigError]]:
    if not isinstance(value, str):
        return None, [ConfigError(
            code="ACCESS_RULE_INVALID",
            message=f"binding value must be a string, got {type(value).__name__}",
            path=path,
        )]
    if value in {"authenticated", "public"}:
        return None, [ConfigError(
            code="ACCESS_RULE_INVALID",
            message=f"'{value}' is an access value, not a given binding",
            path=path,
            hint='Use access: public or access: "*" outside the given map',
        )]
    return _PARSERS[binding_kind(value, allow_where)](value, path, entity_to_collection)
