"""Shared resolution of access-rule principal strings.

Resolves principal expressions (public, authenticated, identity:<entity>, role)
into a normalized principal and optional required role, with symbol resolution
against the known auth entities. Used by both the v0.1 and v0.2 transformers.
"""

from typing import Any, NamedTuple

from yaml_api_generator.parsers.yaml_parser import ConfigError


class ResolvedPrincipal(NamedTuple):
    """Outcome of resolving a principal string.

    is_public is True for the 'public' keyword. principal/required_role describe
    an identity principal; both are None for 'authenticated' (any logged-in user).
    """

    is_public: bool
    principal: str | None
    required_role: str | None


def resolve_principal(
    value: str,
    path: str,
    auth_entities: set[str],
    entity_to_collection: dict[str, str],
) -> tuple[ResolvedPrincipal | None, list[ConfigError]]:
    if value == "public":
        return ResolvedPrincipal(is_public=True, principal=None, required_role=None), []
    if value in ("*", "authenticated"):
        return ResolvedPrincipal(is_public=False, principal=None, required_role=None), []

    if value.startswith("identity:"):
        entity_name = value[len("identity:"):]
        collection = entity_to_collection.get(entity_name)
        if collection is None:
            return None, [_unknown_entity(entity_name, path)]
        return ResolvedPrincipal(False, f"identity:{collection}", None), []

    if ":" in value:
        entity_part, role_part = value.split(":", 1)
        if entity_part not in auth_entities:
            return None, [_unknown_entity(entity_part, path)]
        collection = entity_to_collection[entity_part]
        required_role = None if role_part == "*" else role_part
        return ResolvedPrincipal(False, f"identity:{collection}", required_role), []

    if not auth_entities:
        return None, [
            ConfigError(
                code="ACCESS_NO_AUTH_ENTITY",
                message=f"Cannot use role '{value}' without auth entities",
                path=path,
            )
        ]
    if len(auth_entities) > 1:
        return None, [
            ConfigError(
                code="ACCESS_AMBIGUOUS_ROLE",
                message=f"Unscoped role '{value}' is ambiguous with multiple auth entities; use 'entity:{value}'",
                path=path,
            )
        ]
    entity_name = next(iter(auth_entities))
    collection = entity_to_collection[entity_name]
    return ResolvedPrincipal(False, f"identity:{collection}", value), []


def _unknown_entity(entity_name: str, path: str) -> ConfigError:
    return ConfigError(
        code="ACCESS_UNKNOWN_ENTITY",
        message=f"Unknown auth entity '{entity_name}' in access rule",
        path=path,
    )
