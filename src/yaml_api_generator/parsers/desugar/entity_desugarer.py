import copy
from typing import Any

from ..yaml_parser import ConfigError, ConfigErrors


class EntityDesugarer:
    """
    Handles entity desugaring: inheritance resolution and abstract entity cleanup.

    Responsibilities:
    - Validate entity extends references
    - Detect circular inheritance
    - Resolve inheritance (merge fields, type, auth from parents)
    - Remove abstract entities
    - Validate repositories don't reference abstract entities
    """

    def desugar(
        self, entities: dict[str, Any], repositories: dict[str, Any]
    ) -> None:
        """
        Desugar entities in-place: resolve inheritance and remove abstract entities.

        Args:
            entities: Entity definitions to desugar
            repositories: Repository definitions (checked for abstract entity refs)

        Raises:
            ConfigErrors: If validation fails
        """
        self._validate_extends(entities)
        self._validate_no_circular_inheritance(entities)
        self._resolve_inheritance(entities)
        self._validate_no_abstract_in_repositories(entities, repositories)
        self._remove_abstract_entities(entities)

    def _validate_extends(self, entities: dict[str, Any]) -> None:
        """Validate all extends references point to existing entities."""
        errors: list[ConfigError] = []

        for name, entity in entities.items():
            if not isinstance(entity, dict):
                continue
            parent = entity.get("extends")
            if parent is not None and parent not in entities:
                errors.append(
                    ConfigError(
                        code="ENTITY_EXTENDS_NOT_FOUND",
                        message=f"Entity '{name}' extends unknown entity '{parent}'",
                        path=f"entities.{name}.extends",
                    )
                )

        if errors:
            raise ConfigErrors(errors)

    def _validate_no_circular_inheritance(self, entities: dict[str, Any]) -> None:
        """Detect circular inheritance chains."""
        errors: list[ConfigError] = []
        dep_graph = self._build_dependency_graph(entities)

        for name in dep_graph:
            visited: set[str] = set()
            current = name
            while current is not None:
                if current in visited:
                    errors.append(
                        ConfigError(
                            code="ENTITY_CIRCULAR_EXTENDS",
                            message=f"Circular inheritance detected involving entity '{name}'",
                            path=f"entities.{name}.extends",
                        )
                    )
                    break
                visited.add(current)
                current = dep_graph.get(current)

        if errors:
            raise ConfigErrors(errors)

    def _resolve_inheritance(self, entities: dict[str, Any]) -> None:
        """Resolve inheritance: merge fields, type, and auth from parents."""
        dep_graph = self._build_dependency_graph(entities)
        order = self._topological_sort(dep_graph)

        for name in order:
            entity = entities[name]
            if not isinstance(entity, dict):
                continue
            parent_name = entity.get("extends")
            if parent_name is None:
                continue

            parent = entities[parent_name]
            if not isinstance(parent, dict):
                continue

            parent_fields = parent.get("fields", {})
            child_fields = entity.get("fields", {})
            entity["fields"] = {**parent_fields, **child_fields}

            if "type" not in entity and "type" in parent:
                entity["type"] = parent["type"]

            if "auth" not in entity and "auth" in parent:
                entity["auth"] = copy.deepcopy(parent["auth"])

            entity.pop("extends", None)

    def _validate_no_abstract_in_repositories(
        self, entities: dict[str, Any], repositories: dict[str, Any]
    ) -> None:
        """Ensure repositories don't reference abstract entities."""
        errors: list[ConfigError] = []
        abstract_entities = {
            name
            for name, entity in entities.items()
            if isinstance(entity, dict) and entity.get("abstract")
        }

        for repo_name, repo in repositories.items():
            if not isinstance(repo, dict):
                continue
            entity_name = repo.get("entity")
            if entity_name in abstract_entities:
                errors.append(
                    ConfigError(
                        code="DESUGAR_ABSTRACT_REFERENCED",
                        message=f"Repository '{repo_name}' references abstract entity '{entity_name}'",
                        path=f"repositories.{repo_name}.entity",
                    )
                )

        if errors:
            raise ConfigErrors(errors)

    def _remove_abstract_entities(self, entities: dict[str, Any]) -> None:
        """Remove abstract entities and abstract flags from entities."""
        for name in list(entities.keys()):
            entity = entities[name]
            if isinstance(entity, dict) and entity.get("abstract"):
                del entities[name]
            elif isinstance(entity, dict):
                entity.pop("abstract", None)

    def _build_dependency_graph(
        self, entities: dict[str, Any]
    ) -> dict[str, str | None]:
        """Build dependency graph: entity name -> parent name (or None)."""
        dep_graph: dict[str, str | None] = {}
        for name, entity in entities.items():
            if not isinstance(entity, dict):
                dep_graph[name] = None
            else:
                dep_graph[name] = entity.get("extends")
        return dep_graph

    def _topological_sort(self, dep_graph: dict[str, str | None]) -> list[str]:
        """
        Sort entities in dependency order (parents before children).

        Ensures parent entities are processed before their children.
        """
        visited: set[str] = set()
        order: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            parent = dep_graph.get(node)
            if parent is not None:
                visit(parent)
            order.append(node)

        for node in dep_graph:
            visit(node)

        return order
