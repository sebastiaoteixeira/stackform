"""Shared classification of a ``given`` binding value into an IR binding.

The same prefix dispatch is used by access rules, reusable policies, and the
policy expansion pass. It maps a raw binding string to one of the three IR
binding kinds, reusing the request/document binding grammar parsers.
"""

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


def _is_request(value: str) -> bool:
    return value == "request" or value.startswith(("request.", "request:"))


def classify_binding(
    value: Any,
    path: str,
    entity_to_collection: dict[str, str],
) -> tuple[IRBinding | None, list[ConfigError]]:
    if not isinstance(value, str):
        return None, [ConfigError(
            code="ACCESS_RULE_INVALID",
            message=f"binding value must be a string, got {type(value).__name__}",
            path=path,
        )]

    if value.startswith("identity:"):
        entity_name = value[len("identity:"):]
        collection = entity_to_collection.get(entity_name)
        if collection is None:
            return None, [ConfigError(
                code="ACCESS_UNKNOWN_ENTITY",
                message=f"Unknown auth entity '{entity_name}' in binding",
                path=path,
            )]
        return IRIdentityBinding(
            entity_name=entity_name, collection_name=collection
        ), []

    if _is_request(value):
        parsed, errors = parse_request_binding(value, path)
        if parsed is None:
            return None, errors
        return IRRequestBinding(
            part=parsed[0], type_name=parsed[1], raw=parsed[2]
        ), errors

    parsed_doc, errors = parse_document_binding(value, path)
    if parsed_doc is None:
        return None, errors
    return IRDocumentBinding(
        collection=parsed_doc[0], id_param=parsed_doc[1]
    ), errors
