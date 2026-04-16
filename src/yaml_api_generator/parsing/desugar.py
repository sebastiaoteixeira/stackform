import copy
from typing import Any

from .parser import ConfigError, ConfigErrors


CRUD_OPERATIONS = ("list", "get", "create", "update", "replace", "delete")
AUTH_OPERATIONS = ("register", "login")

CRUD_ROUTE_CONVENTIONS = {
    "list": ("GET", ""),
    "get": ("GET", "/{id}"),
    "create": ("POST", ""),
    "update": ("PATCH", "/{id}"),
    "replace": ("PUT", "/{id}"),
    "delete": ("DELETE", "/{id}"),
}

AUTH_ROUTE_CONVENTIONS = {
    "register": ("POST", "/register"),
    "login": ("POST", "/login"),
}

ALL_ROUTE_CONVENTIONS = {**CRUD_ROUTE_CONVENTIONS, **AUTH_ROUTE_CONVENTIONS}


def desugar_v02(config: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(config)

    api_ops = config.get("api", {}).get("operations", {})
    defaults = api_ops.get("defaults", {})
    auth_defaults = api_ops.pop("auth", {})
    repositories = config.get("repositories", {})
    entities = config.get("entities", {})
    services = config.get("services", {})
    controllers = config.get("controllers", {})

    _desugar_entities(entities, repositories)

    expanded_services = _desugar_services(
        services, repositories, entities, defaults, auth_defaults
    )

    _desugar_repositories(repositories)

    _desugar_controllers(controllers, expanded_services)

    return config


def _desugar_entities(
    entities: dict[str, Any], repositories: dict[str, Any]
) -> None:
    errors: list[ConfigError] = []

    # Build dependency graph and detect cycles
    dep_graph: dict[str, str | None] = {}
    for name, entity in entities.items():
        if not isinstance(entity, dict):
            dep_graph[name] = None
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
            dep_graph[name] = None
        else:
            dep_graph[name] = parent

    if errors:
        raise ConfigErrors(errors)

    # Detect circular extends
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

    # Topological sort
    order = _topological_sort(dep_graph)

    # Merge fields from parent (parent first, child overrides)
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

        # Merge fields: parent fields first, child overrides
        parent_fields = parent.get("fields", {})
        child_fields = entity.get("fields", {})
        merged = {**parent_fields, **child_fields}
        entity["fields"] = merged

        # Inherit type if not set
        if "type" not in entity and "type" in parent:
            entity["type"] = parent["type"]

        # Inherit auth if not set
        if "auth" not in entity and "auth" in parent:
            entity["auth"] = copy.deepcopy(parent["auth"])

        # Strip extends key
        entity.pop("extends", None)

    # Validate no repository references an abstract entity
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

    # Remove abstract entities
    for name in list(entities.keys()):
        entity = entities[name]
        if isinstance(entity, dict) and entity.get("abstract"):
            del entities[name]
        elif isinstance(entity, dict):
            entity.pop("abstract", None)


def _topological_sort(dep_graph: dict[str, str | None]) -> list[str]:
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


def _desugar_repositories(repositories: dict[str, Any]) -> None:
    for repo_entry in repositories.values():
        if isinstance(repo_entry, dict):
            repo_entry.pop("operations", None)


def _is_minified_service(
    key: str, entry: dict[str, Any], repositories: dict[str, Any]
) -> bool:
    if "operation" in entry or "handler" in entry:
        return False
    return key in repositories or "operations" in entry


def _resolve_crud_ops(
    global_defaults: dict[str, Any],
    repo_ops: dict[str, Any],
    service_ops: dict[str, Any],
) -> dict[str, bool | dict[str, Any]]:
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
    auth_defaults: dict[str, Any],
    service_ops: dict[str, Any],
) -> dict[str, bool | dict[str, Any]]:
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


AUTH_SERVICE_TEMPLATES: dict[str, dict[str, str]] = {
    "register": {"operation": "create"},
    "login": {"operation": "login"},
}


def _desugar_services(
    services: dict[str, Any],
    repositories: dict[str, Any],
    entities: dict[str, Any],
    defaults: dict[str, Any],
    auth_defaults: dict[str, Any],
) -> dict[str, Any]:
    errors: list[ConfigError] = []
    expanded: dict[str, Any] = {}
    to_remove: list[str] = []

    for svc_name, entry in services.items():
        if not isinstance(entry, dict):
            expanded[svc_name] = entry
            continue

        if not _is_minified_service(svc_name, entry, repositories):
            expanded[svc_name] = entry
            continue

        repo_name = entry.get("repository", svc_name)
        if repo_name not in repositories:
            errors.append(
                ConfigError(
                    code="DESUGAR_REPO_NOT_FOUND",
                    message=f"Repository '{repo_name}' not found",
                    path=f"services.{svc_name}.repository",
                )
            )
            continue

        repo = repositories[repo_name]
        if not isinstance(repo, dict) or "entity" not in repo:
            errors.append(
                ConfigError(
                    code="DESUGAR_ENTITY_NOT_FOUND",
                    message=f"Repository '{repo_name}' does not specify an entity",
                    path=f"repositories.{repo_name}.entity",
                )
            )
            continue

        entity_name = repo["entity"]
        if entity_name not in entities:
            errors.append(
                ConfigError(
                    code="DESUGAR_ENTITY_NOT_FOUND",
                    message=f"Entity '{entity_name}' not found",
                    path=f"repositories.{repo_name}.entity",
                )
            )
            continue

        entity = entities[entity_name]
        repo_ops = repo.get("operations", {}) if isinstance(repo, dict) else {}
        service_ops = entry.get("operations", {})

        resolved = _resolve_crud_ops(defaults, repo_ops, service_ops)

        for op_name, op_value in resolved.items():
            if op_value is False:
                continue
            flat_key = f"{op_name}-{svc_name}"
            if op_value is True:
                expanded[flat_key] = {"repository": repo_name, "operation": op_name}
            elif isinstance(op_value, dict) and "handler" in op_value:
                expanded[flat_key] = {"handler": op_value["handler"]}

        is_auth = isinstance(entity, dict) and entity.get("type") == "auth"
        if is_auth:
            auth_ops = _resolve_auth_ops(auth_defaults, service_ops)
            for op_name, op_value in auth_ops.items():
                if op_value is False:
                    continue
                flat_key = f"{op_name}-{svc_name}"
                if isinstance(op_value, dict) and "handler" in op_value:
                    expanded[flat_key] = {"handler": op_value["handler"]}
                else:
                    template = AUTH_SERVICE_TEMPLATES.get(op_name, {})
                    expanded[flat_key] = {"repository": repo_name, **template}

        to_remove.append(svc_name)

    if errors:
        raise ConfigErrors(errors)

    for key in to_remove:
        del services[key]

    services.update(expanded)
    return services


def _is_minified_controller(entry: dict[str, Any]) -> bool:
    return "service" in entry


def _desugar_controllers(
    controllers: dict[str, Any], expanded_services: dict[str, Any]
) -> None:
    errors: list[ConfigError] = []

    for ctrl_name, entry in list(controllers.items()):
        if not isinstance(entry, dict):
            continue

        if not _is_minified_controller(entry):
            continue

        service_name = entry["service"]
        base_access = entry.get("access", "public")
        ops_overrides = entry.get("operations", {})

        matching_services: dict[str, str] = {}
        for svc_key in expanded_services.keys():
            if "-" not in svc_key:
                continue
            op_part, svc_part = svc_key.split("-", 1)
            if svc_part == service_name:
                matching_services[op_part] = svc_key

        if not matching_services:
            errors.append(
                ConfigError(
                    code="DESUGAR_SERVICE_NOT_FOUND",
                    message=f"No services found for service group '{service_name}'",
                    path=f"controllers.{ctrl_name}.service",
                )
            )
            continue

        routes: dict[str, Any] = {}

        for op_name, svc_key in matching_services.items():
            op_override = ops_overrides.get(op_name)
            if op_override is False:
                continue

            if op_name in ALL_ROUTE_CONVENTIONS:
                method, path = ALL_ROUTE_CONVENTIONS[op_name]
            else:
                if not isinstance(op_override, dict) or "method" not in op_override or "path" not in op_override:
                    errors.append(
                        ConfigError(
                            code="DESUGAR_CUSTOM_OP_MISSING_ROUTE",
                            message=f"Custom operation '{op_name}' requires 'method' and 'path'",
                            path=f"controllers.{ctrl_name}.operations.{op_name}",
                        )
                    )
                    continue
                method = op_override["method"]
                path = op_override["path"]

            access = base_access
            if isinstance(op_override, dict) and "access" in op_override:
                access = op_override["access"]

            routes[op_name] = {
                "service": svc_key,
                "method": method,
                "path": path,
                "access": access,
            }

        entry.pop("service", None)
        entry.pop("access", None)
        entry.pop("operations", None)
        entry["routes"] = routes

    if errors:
        raise ConfigErrors(errors)
