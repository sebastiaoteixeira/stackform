"""Semantic coherence checks for auth configuration in a spec.

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
- AUTH_VIA_UNKNOWN_PROVIDER: a ``via`` entry that is neither a built-in provider
  nor a key of ``providers``, so no login can ever reach the identity through it.

Inheritance is resolved on the fly: ``fields`` and ``auth`` may be supplied by a
parent through ``extends``, exactly as the entity desugarer later merges them.
"""

from typing import Any

from yaml_api_generator.ir.api import CREDENTIAL_PROVIDERS
from yaml_api_generator.parsers.yaml_parser import ConfigError
from .entity_inheritance import inherited, inherited_fields


def _via_entries(value: Any) -> list[Any]:
    return [value] if isinstance(value, str | dict) else value if isinstance(value, list) else []


def _provider_name(entry: Any) -> str:
    return str(entry.get("provider")) if isinstance(entry, dict) else str(entry)


def _check_entity(
    name: str,
    entities: dict[str, Any],
    section: str,
    providers: frozenset[str],
    errors: list[ConfigError],
) -> None:
    auth = inherited(name, entities, "auth")
    if not isinstance(auth, dict):
        return

    base = f"{section}.{name}.auth"
    entries = _via_entries(auth.get("via"))
    errors.extend(
        ConfigError(
            code="AUTH_VIA_UNKNOWN_PROVIDER",
            message=f"Auth entity '{name}' uses via '{provider}', which is not a declared provider",
            path=f"{base}.via",
            hint=f"Declare providers.{provider} or use one of: {', '.join(sorted(CREDENTIAL_PROVIDERS))}",
        )
        for provider in map(_provider_name, entries)
        if provider not in CREDENTIAL_PROVIDERS | providers
    )
    # A mapping entry carries its own identifier, so only bare names need auth.identifier.
    via = [entry for entry in entries if isinstance(entry, str)]
    identifier = auth.get("identifier")
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
            path=f"{section}.{name}.fields.apiKey",
            hint="Declare an 'apiKey' field so a key can be stored and matched",
        ))


def validate_spec_auth(spec: dict[str, Any], section: str = "entities") -> list[ConfigError]:
    """Validate auth-configuration coherence across every model of ``section``."""
    errors: list[ConfigError] = []
    entities = spec.get(section) or {}
    providers = frozenset(spec.get("providers") or {})
    for name, entity in entities.items():
        if isinstance(entity, dict) and str(inherited(name, entities, "type") or "base") == "auth":
            _check_entity(name, entities, section, providers, errors)
    return errors
