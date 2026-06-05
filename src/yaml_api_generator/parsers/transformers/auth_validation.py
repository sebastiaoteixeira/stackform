"""Semantic coherence checks for auth configuration in a v0.2 spec.

The JSON schema validates each auth key's shape but not its meaning, so an auth
entity can build cleanly while its authentication is silently dead. These checks
run on the pre-desugar spec, mirroring ``validate_spec_access``, and reject the
spec with coded errors:

- AUTH_IDENTIFIER_REQUIRED: a ``via: password``/``apiKey`` identity with no
  ``auth.identifier``. Without it the transformer builds no provider bindings,
  ``resolve_principal`` is empty and no login route is emitted -- auth is dead.
- AUTH_IDENTIFIER_FIELD_NOT_FOUND: ``auth.identifier`` names a field that does
  not exist on the entity, so login can never match a stored document. Mirrors
  the existing ``AUTH_ROLES_FIELD_NOT_FOUND`` check.
- AUTH_API_KEY_FIELD_MISSING: a ``via: apiKey`` identity whose entity declares
  no ``apiKey`` field, so no document can ever store a key and auth always fails.

Inheritance is resolved on the fly: ``fields`` and ``auth`` may be supplied by a
parent through ``extends``, exactly as the entity desugarer later merges them.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

_IDENTIFIER_PROVIDERS = frozenset({"password", "apiKey"})


def _normalize_via(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _resolved(entity: str, entities: dict[str, Any], key: str) -> Any:
    """Walk the ``extends`` chain returning the nearest ``key`` value."""
    seen: set[str] = set()
    current: str | None = entity
    while isinstance(current, str) and current not in seen:
        seen.add(current)
        node = entities.get(current)
        if not isinstance(node, dict):
            return None
        if key in node:
            return node[key]
        current = node.get("extends")
    return None


def _resolved_fields(entity: str, entities: dict[str, Any]) -> dict[str, Any]:
    """Merge ``fields`` along the ``extends`` chain (parents first)."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = entity
    while isinstance(current, str) and current not in seen:
        seen.add(current)
        node = entities.get(current)
        if not isinstance(node, dict):
            break
        fields = node.get("fields")
        if isinstance(fields, dict):
            chain.append(fields)
        current = node.get("extends")
    merged: dict[str, Any] = {}
    for fields in reversed(chain):
        merged.update(fields)
    return merged


def _check_entity(
    name: str, entities: dict[str, Any], errors: list[ConfigError]
) -> None:
    auth = _resolved(name, entities, "auth")
    if not isinstance(auth, dict):
        return

    via = _normalize_via(auth.get("via"))
    if not _IDENTIFIER_PROVIDERS.intersection(via):
        return

    identifier = auth.get("identifier")
    base = f"entities.{name}.auth"
    if not identifier:
        errors.append(ConfigError(
            code="AUTH_IDENTIFIER_REQUIRED",
            message=f"Auth entity '{name}' uses via {via} but declares no identifier",
            path=f"{base}.identifier",
            hint="Set auth.identifier to the field used to look up the principal",
        ))
        return

    fields = _resolved_fields(name, entities)
    if identifier not in fields:
        errors.append(ConfigError(
            code="AUTH_IDENTIFIER_FIELD_NOT_FOUND",
            message=f"Auth identifier '{identifier}' not found in entity '{name}'",
            path=f"{base}.identifier",
            hint=f"Declare field '{identifier}' on entity '{name}' or fix the typo",
        ))

    if "apiKey" in via and "apiKey" not in fields:
        errors.append(ConfigError(
            code="AUTH_API_KEY_FIELD_MISSING",
            message=f"Auth entity '{name}' uses via apiKey but declares no apiKey field",
            path=f"entities.{name}.fields.apiKey",
            hint="Declare an 'apiKey' field so a key can be stored and matched",
        ))


def validate_spec_auth(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate auth-configuration coherence across every entity in the spec."""
    errors: list[ConfigError] = []
    entities = spec.get("entities") or {}
    for name, entity in entities.items():
        if isinstance(entity, dict) and str(_resolved(name, entities, "type") or "base") == "auth":
            _check_entity(name, entities, errors)
    return errors
