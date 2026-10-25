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

from yaml_api_generator.ir.api import CREDENTIAL_PROVIDERS
from yaml_api_generator.parsers.yaml_parser import ConfigError
from .entity_inheritance import inherited, inherited_fields


def _normalize_via(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _check_entity(
    name: str, entities: dict[str, Any], errors: list[ConfigError]
) -> None:
    auth = inherited(name, entities, "auth")
    if not isinstance(auth, dict):
        return

    via = _normalize_via(auth.get("via"))
    identifier = auth.get("identifier")
    base = f"entities.{name}.auth"
    if CREDENTIAL_PROVIDERS.intersection(via) and not identifier:
        errors.append(ConfigError(
            code="AUTH_IDENTIFIER_REQUIRED",
            message=f"Auth entity '{name}' uses via {via} but declares no identifier",
            path=f"{base}.identifier",
            hint="Set auth.identifier to the field used to look up the principal",
        ))
        return

    fields = inherited_fields(name, entities)
    if identifier is not None and identifier not in fields:
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
        if isinstance(entity, dict) and str(inherited(name, entities, "type") or "base") == "auth":
            _check_entity(name, entities, errors)
    return errors
