from typing import Any

from ..yaml_parser import ConfigError, ConfigErrors
from ...constants import CRUD_OPERATIONS, AUTH_OPERATIONS


AUTH_SERVICE_TEMPLATES: dict[str, dict[str, str]] = {
    "register": {"operation": "create"},
    "login": {"operation": "login"},
}


class ServiceDesugarer:
    """
    Handles service desugaring: expand minified services into explicit operations.

    Responsibilities:
    - Detect minified service definitions
    - Resolve CRUD operations from defaults and repository config
    - Expand auth operations for identity entities
    - Generate flat service keys (e.g., "list-users", "create-posts")
    """

    def desugar(
        self,
        services: dict[str, Any],
        repositories: dict[str, Any],
        entities: dict[str, Any],
        defaults: dict[str, Any],
        auth_defaults: dict[str, Any],
        controllers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Desugar services in-place: expand minified definitions.

        Args:
            services: Service definitions to desugar
            repositories: Repository definitions
            entities: Entity definitions
            defaults: Global operation defaults
            auth_defaults: Auth operation defaults

        Returns:
            Updated services dict (same object, modified in-place)

        Raises:
            ConfigErrors: If validation fails
        """
        errors: list[ConfigError] = []
        expanded: dict[str, Any] = {}
        to_remove: list[str] = []

        for svc_name, entry in services.items():
            if not isinstance(entry, dict):
                expanded[svc_name] = entry
                continue

            if not self._is_minified_service(svc_name, entry, repositories):
                expanded[svc_name] = entry
                continue

            try:
                self._expand_minified_service(
                svc_name,
                    entry,
                    repositories,
                    entities,
                    defaults,
                    auth_defaults,
                    expanded,
                )
                to_remove.append(svc_name)
            except ConfigError as e:
                errors.append(e)

        if errors:
            raise ConfigErrors(errors)

        for key in to_remove:
            del services[key]

        services.update(expanded)
        return services

    def _is_minified_service(
        self, key: str, entry: dict[str, Any], repositories: dict[str, Any]
    ) -> bool:
        """Check if service entry is minified (needs expansion)."""
        if "operation" in entry or "handler" in entry:
            return False
        return "repository" in entry or key in repositories

    def _expand_minified_service(
        self,
        svc_name: str,
        entry: dict[str, Any],
        repositories: dict[str, Any],
        entities: dict[str, Any],
        defaults: dict[str, Any],
        auth_defaults: dict[str, Any],
        expanded: dict[str, Any],
    ) -> None:
        """Expand a minified service into explicit operation entries."""
        repo_name = entry.get("repository", svc_name)

        if repo_name not in repositories:
            raise ConfigError(
                code="DESUGAR_REPO_NOT_FOUND",
                message=f"Repository '{repo_name}' not found",
                path=f"services.{svc_name}.repository",
            )

        repo = repositories[repo_name]
        if not isinstance(repo, dict) or "entity" not in repo:
            raise ConfigError(
                code="DESUGAR_ENTITY_NOT_FOUND",
                message=f"Repository '{repo_name}' does not specify an entity",
                path=f"repositories.{repo_name}.entity",
            )

        entity_name = repo["entity"]
        if entity_name not in entities:
            raise ConfigError(
                code="DESUGAR_ENTITY_NOT_FOUND",
                message=f"Entity '{entity_name}' not found",
                path=f"repositories.{repo_name}.entity",
            )

        entity = entities[entity_name]
        service_ops = entry.get("operations", {})

        self._expand_crud_operations(
            svc_name, repo_name, repo, service_ops, defaults, expanded
        )

        is_auth = isinstance(entity, dict) and entity.get("type") == "auth"
        if is_auth:
            self._expand_auth_operations(
                svc_name, repo_name, service_ops, auth_defaults, expanded
            )

    def _expand_crud_operations(
        self,
        svc_name: str,
        repo_name: str,
        repo: dict[str, Any],
        service_ops: dict[str, Any],
        defaults: dict[str, Any],
        expanded: dict[str, Any],
    ) -> None:
        """Expand CRUD operations for a service."""
        repo_crud = repo.get("crud") if isinstance(repo, dict) else None
        repo_ops: dict[str, Any] = {}
        if repo_crud is not None:
            for op in CRUD_OPERATIONS:
                repo_ops[op] = op in repo_crud

        resolved = self._resolve_crud_ops(defaults, repo_ops, service_ops)

        for op_name, op_value in resolved.items():
            if op_value is False:
                continue
            flat_key = f"{op_name}-{svc_name}"
            if op_value is True:
                expanded[flat_key] = {"repository": repo_name, "operation": op_name}
            elif isinstance(op_value, dict) and "handler" in op_value:
                expanded[flat_key] = {"handler": op_value["handler"]}

    def _expand_auth_operations(
        self,
        svc_name: str,
        repo_name: str,
        service_ops: dict[str, Any],
        auth_defaults: dict[str, Any],
        expanded: dict[str, Any],
    ) -> None:
        """Expand auth operations (register, login) for identity entities."""
        auth_ops = self._resolve_auth_ops(auth_defaults, service_ops)
        for op_name, op_value in auth_ops.items():
            if op_value is False:
                continue
            flat_key = f"{op_name}-{svc_name}"
            if isinstance(op_value, dict) and "handler" in op_value:
                expanded[flat_key] = {"handler": op_value["handler"]}
            else:
                template = AUTH_SERVICE_TEMPLATES.get(op_name, {})
                expanded[flat_key] = {"repository": repo_name, **template}

    def _resolve_crud_ops(
        self,
        global_defaults: dict[str, Any],
        repo_ops: dict[str, Any],
        service_ops: dict[str, Any],
    ) -> dict[str, bool | dict[str, Any]]:
        """
        Resolve CRUD operations from defaults, repository config, and service overrides.

        Priority: service_ops > repo_ops > global_defaults > True (all enabled)
        """
        resolved: dict[str, bool | dict[str, Any]] = {op: True for op in CRUD_OPERATIONS}

        for op in CRUD_OPERATIONS:
            if op in global_defaults:
                resolved[op] = global_defaults[op]
            if op in repo_ops:
                resolved[op] = repo_ops[op]
            if op in service_ops:
                svc_override = service_ops[op]
                if isinstance(svc_override, bool):
                    resolved[op] = svc_override
                elif isinstance(svc_override, dict):
                    resolved[op] = svc_override

        for op_name, op_value in service_ops.items():
            if op_name not in CRUD_OPERATIONS:
                resolved[op_name] = op_value

        return resolved

    def _resolve_auth_ops(
        self,
        auth_defaults: dict[str, Any],
        service_ops: dict[str, Any],
    ) -> dict[str, bool | dict[str, Any]]:
        """
        Resolve auth operations from defaults and service overrides.

        Priority: service_ops > auth_defaults
        """
        resolved: dict[str, bool | dict[str, Any]] = {}
        for op in AUTH_OPERATIONS:
            if op in auth_defaults:
                resolved[op] = auth_defaults[op]
            if op in service_ops:
                svc_override = service_ops[op]
                if isinstance(svc_override, bool):
                    resolved[op] = svc_override
                elif isinstance(svc_override, dict):
                    resolved[op] = svc_override
        return resolved
