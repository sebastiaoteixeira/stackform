"""Build-time coherence checks for the provider bindings of ``auth.via`` in a v0.2 spec.

- BINDING_PROVIDER_NOT_FOUND: a binding names a provider the spec does not declare.
- BINDING_IDENTIFIER_FIELD_NOT_FOUND: a binding identifier is not a field of its entity.
- BINDING_RELATION_FIELD_NOT_FOUND: a relation fills a foreign key its entity does not declare.
- BINDING_RELATION_COLLECTION_NOT_FOUND: a relation targets a collection the spec does not declare.
- BINDING_RELATION_MATCH_FIELD_NOT_FOUND: a relation matches on a field the target collection lacks.
"""

from collections.abc import Iterator
from typing import Any

from yaml_api_generator.ir.api import CREDENTIAL_PROVIDERS
from yaml_api_generator.parsers.yaml_parser import ConfigError
from .entity_inheritance import inherited_fields


def _via_bindings(name: str, entity: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    via = (entity.get("auth") or {}).get("via")
    if isinstance(via, str):
        yield f"entities.{name}.auth.via", {"provider": via}
        return
    for index, entry in enumerate(via if isinstance(via, list) else []):
        yield f"entities.{name}.auth.via[{index}]", entry if isinstance(entry, dict) else {"provider": entry}


def _relation_errors(
    spec: dict[str, Any], fields: dict[str, Any], path: str, fk: str, relation: dict[str, Any]
) -> Iterator[ConfigError]:
    if fk not in fields:
        yield ConfigError(
            code="BINDING_RELATION_FIELD_NOT_FOUND",
            message=f"Relation '{fk}' fills a field its entity does not declare",
            path=path,
            hint=f"Declare field '{fk}' on the auth entity or fix the relation name",
        )
    collection = relation["collection"]
    repository = (spec.get("repositories") or {}).get(collection)
    if repository is None:
        yield ConfigError(
            code="BINDING_RELATION_COLLECTION_NOT_FOUND",
            message=f"Relation '{fk}' references unknown collection '{collection}'",
            path=f"{path}.collection",
            hint=f"Declare a collection named '{collection}' (a repository) or fix the relation collection name",
        )
        return
    target_fields = inherited_fields(repository.get("entity"), spec.get("entities") or {})
    for target in relation["match"]:
        if target not in target_fields:
            yield ConfigError(
                code="BINDING_RELATION_MATCH_FIELD_NOT_FOUND",
                message=f"Relation '{fk}' matches on '{target}', which collection '{collection}' does not declare",
                path=f"{path}.match.{target}",
                hint=f"Match on a field of collection '{collection}'",
            )


def _binding_errors(
    spec: dict[str, Any], name: str, path: str, binding: dict[str, Any]
) -> Iterator[ConfigError]:
    provider = binding["provider"]
    if provider not in CREDENTIAL_PROVIDERS and provider not in (spec.get("providers") or {}):
        yield ConfigError(
            code="BINDING_PROVIDER_NOT_FOUND",
            message=f"Auth entity '{name}' binds undeclared provider '{provider}'",
            path=path,
            hint=f"Declare provider '{provider}' under providers or bind one of {sorted(CREDENTIAL_PROVIDERS)}",
        )
    fields = inherited_fields(name, spec.get("entities") or {})
    identifier = binding.get("identifier")
    if identifier is not None and identifier not in fields:
        yield ConfigError(
            code="BINDING_IDENTIFIER_FIELD_NOT_FOUND",
            message=f"Binding identifier '{identifier}' not found in entity '{name}'",
            path=f"{path}.identifier",
            hint=f"Declare field '{identifier}' on entity '{name}' or fix the typo",
        )
    for fk, relation in (binding.get("relations") or {}).items():
        yield from _relation_errors(spec, fields, f"{path}.relations.{fk}", fk, relation)


def validate_spec_bindings(spec: dict[str, Any]) -> list[ConfigError]:
    """Reject ``auth.via`` bindings that reference providers, fields or collections the spec lacks."""
    return [
        error
        for name, entity in (spec.get("entities") or {}).items()
        if isinstance(entity, dict)
        for path, binding in _via_bindings(name, entity)
        for error in _binding_errors(spec, name, path, binding)
    ]
