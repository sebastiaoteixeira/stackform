"""Build-time coherence checks for provider binding relations in a v0.2 spec."""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError


def _via_bindings(entity: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    via = (entity.get("auth") or {}).get("via")
    return [(index, entry) for index, entry in enumerate(via) if isinstance(entry, dict)] if isinstance(via, list) else []


def validate_spec_bindings(spec: dict[str, Any]) -> list[ConfigError]:
    """Reject ``auth.via`` relations whose collection the spec does not declare."""
    declared_collections = set(spec.get("repositories") or {})
    return [
        ConfigError(
            code="BINDING_RELATION_COLLECTION_NOT_FOUND",
            message=f"Relation '{fk}' references unknown collection '{relation['collection']}'",
            path=f"entities.{entity_name}.auth.via[{index}].relations.{fk}.collection",
            hint=(
                f"Declare a collection named '{relation['collection']}' (a repository)"
                " or fix the relation collection name"
            ),
        )
        for entity_name, entity in (spec.get("entities") or {}).items()
        for index, binding in _via_bindings(entity)
        for fk, relation in (binding.get("relations") or {}).items()
        if relation["collection"] not in declared_collections
    ]
