"""Role set and hierarchy parsing shared by every spec version."""

from typing import Any

from yaml_api_generator.ir import IRRolesConfig, RoleHierarchyCycleError, flatten_role_hierarchy
from yaml_api_generator.parsers.yaml_parser import ConfigError


def parse_roles_config(
    section: str, owner: str, roles_data: dict[str, Any] | None
) -> tuple[IRRolesConfig | None, list[ConfigError]]:
    """Build the roles of ``<section>.<owner>.roles``, validating the roles it references."""
    if roles_data is None:
        return None, []
    roles = IRRolesConfig(
        values=tuple(roles_data["values"]),
        default=roles_data["default"],
        hierarchy={role: tuple(includes) for role, includes in roles_data.get("hierarchy", {}).items()},
    )
    errors = _default_errors(section, owner, roles) or _hierarchy_errors(section, owner, roles)
    return (None, errors) if errors else (roles, [])


def _default_errors(section: str, owner: str, roles: IRRolesConfig) -> list[ConfigError]:
    if roles.default in roles.values:
        return []
    return [
        ConfigError(
            code="ROLES_DEFAULT_UNKNOWN_ROLE",
            message=f"Default role '{roles.default}' is not one of the declared roles",
            path=f"{section}.{owner}.roles.default",
            hint=f"Add '{roles.default}' to {section}.{owner}.roles.values",
        )
    ]


def _hierarchy_errors(section: str, owner: str, roles: IRRolesConfig) -> list[ConfigError]:
    path = f"{section}.{owner}.roles.hierarchy"
    referenced = {*roles.hierarchy, *(i for includes in roles.hierarchy.values() for i in includes)}
    errors = [
        ConfigError(
            code="ROLES_HIERARCHY_UNKNOWN_ROLE",
            message=f"Role hierarchy references undeclared role '{role}'",
            path=path,
            hint=f"Add '{role}' to {section}.{owner}.roles.values",
        )
        for role in sorted(referenced - set(roles.values))
    ]
    if errors:
        return errors
    try:
        flatten_role_hierarchy(roles.hierarchy)
    except RoleHierarchyCycleError as exc:
        return [
            ConfigError(
                code="ROLES_HIERARCHY_CYCLE",
                message=f"Role hierarchy for '{owner}' is cyclic through '{exc.role}'",
                path=path,
                hint="Remove the circular or self-referential role inclusion",
            )
        ]
    return []
