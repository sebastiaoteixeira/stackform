"""Build-time coherence checks for provider binding relations in a v0.2 spec."""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError


def _binding_relations_errors(
    entity_name: str,
    binding_index: int,
    binding: dict[str, Any],
    declared_collections: set[str],
) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for fk, spec in (binding.get("relations") or {}).items():
        if not isinstance(spec, dict):
            continue
        collection = spec.get("collection", "")
        if collection not in declared_collections:
            errors.append(ConfigError(
                code="BINDING_RELATION_COLLECTION_NOT_FOUND",
                message=(
                    f"Relation '{fk}' references unknown collection '{collection}'"
                ),
                path=(
                    f"entities.{entity_name}.auth.bindings"
                    f"[{binding_index}].relations.{fk}.collection"
                ),
                hint=(
                    f"Declare a collection named '{collection}' (a repository)"
                    f" or fix the relation collection name"
                ),
            ))
    return errors


def validate_spec_bindings(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate referential integrity of binding relations across the spec."""
    declared_collections = set((spec.get("repositories") or {}).keys())

    entities: dict[str, Any] = spec.get("entities") or {}
    errors: list[ConfigError] = []
    for entity_name, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        auth = entity.get("auth")
        if not isinstance(auth, dict):
            continue
        for index, binding in enumerate(auth.get("bindings") or []):
            if not isinstance(binding, dict):
                continue
            errors.extend(
                _binding_relations_errors(
                    entity_name, index, binding, declared_collections
                )
            )
    return errors
