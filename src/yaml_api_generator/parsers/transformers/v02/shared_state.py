"""Shared state for v0.2 transformation.

Encapsulates context data that flows through multiple transformers
to avoid passing many individual parameters.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TransformContext:
    """Shared state for v0.2 YAML to IR transformation.

    Attributes:
        defaults: Default operation configuration
        import_map: Handler import path resolution
        repo_entity_map: Repository name → entity name mapping
        entity_to_collection: Entity name → repository name (inverse map)
        auth_entities: Set of entity names marked as auth type
    """
    defaults: dict
    import_map: dict[str, str]
    repo_entity_map: dict[str, str]
    entity_to_collection: dict[str, str]
    auth_entities: set[str]
