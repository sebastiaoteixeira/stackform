"""Role set and hierarchy parsing shared by every spec version."""

from typing import Any

from yaml_api_generator.ir import IRRolesConfig, RoleHierarchyCycleError, flatten_role_hierarchy
from yaml_api_generator.parsers.yaml_parser import ConfigError


def parse_roles_config(
    section: str, owner: str, roles_data: Any
) -> tuple[IRRolesConfig | None, list[ConfigError]]:
    """Build the roles of ``<section>.<owner>.roles``, validating its hierarchy."""
    if not isinstance(roles_data, dict):
        return None, []

    values = tuple(str(v) for v in roles_data.get("values", []))
    if not values:
        return None, []

    raw_hierarchy = roles_data.get("hierarchy", {})
    hierarchy = {
        str(role): tuple(str(i) for i in (includes or []))
        for role, includes in raw_hierarchy.items()
    } if isinstance(raw_hierarchy, dict) else {}

    errors = _hierarchy_errors(section, owner, values, hierarchy)
    if errors:
        return None, errors

    default = str(roles_data.get("default", values[0]))
    return IRRolesConfig(values=values, default=default, hierarchy=hierarchy), []


def _hierarchy_errors(
    section: str,
    owner: str,
    values: tuple[str, ...],
    hierarchy: dict[str, tuple[str, ...]],
) -> list[ConfigError]:
    path = f"{section}.{owner}.roles.hierarchy"
    referenced = {*hierarchy, *(i for includes in hierarchy.values() for i in includes)}
    errors = [
        ConfigError(
            code="ROLES_HIERARCHY_UNKNOWN_ROLE",
            message=f"Role hierarchy references undeclared role '{role}'",
            path=path,
            hint=f"Add '{role}' to {section}.{owner}.roles.values",
        )
        for role in sorted(referenced - set(values))
    ]
    if errors:
        return errors
    try:
        flatten_role_hierarchy(hierarchy)
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
