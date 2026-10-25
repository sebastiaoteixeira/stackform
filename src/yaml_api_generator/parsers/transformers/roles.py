"""Role declarations of an identity, shared by every spec version."""

from typing import Any

from yaml_api_generator.ir import IRRolesConfig, RoleHierarchyCycleError, flatten_role_hierarchy
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


def roles_config(path: str, roles_data: Any) -> IRRolesConfig | None:
    """The roles declared at ``path``, whose hierarchy names only declared roles and never cycles.

    Raises:
        ConfigErrors: If the hierarchy names an undeclared role or is cyclic
    """
    if not isinstance(roles_data, dict) or not roles_data.get("values"):
        return None
    values = tuple(str(v) for v in roles_data["values"])
    hierarchy = {
        str(role): tuple(str(i) for i in (includes or []))
        for role, includes in (roles_data.get("hierarchy") or {}).items()
    }
    undeclared = sorted(({*hierarchy} | {i for includes in hierarchy.values() for i in includes}) - {*values})
    if undeclared:
        raise ConfigErrors([
            ConfigError(
                code="ROLES_HIERARCHY_UNKNOWN_ROLE",
                message=f"Role hierarchy references undeclared role '{role}'",
                path=f"{path}.hierarchy",
                hint=f"Add '{role}' to {path}.values",
            )
            for role in undeclared
        ])
    try:
        flatten_role_hierarchy(hierarchy)
    except RoleHierarchyCycleError as exc:
        raise ConfigErrors([
            ConfigError(
                code="ROLES_HIERARCHY_CYCLE",
                message=f"Role hierarchy at '{path}' is cyclic through '{exc.role}'",
                path=f"{path}.hierarchy",
                hint="Remove the circular or self-referential role inclusion",
            )
        ]) from exc
    return IRRolesConfig(values=values, default=str(roles_data.get("default", values[0])), hierarchy=hierarchy)
