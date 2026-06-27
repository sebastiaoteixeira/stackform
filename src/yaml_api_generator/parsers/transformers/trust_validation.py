"""Semantic coherence checks for per-provider ``trust`` in a v0.2 spec.

A provider's ``trust`` decides who verifies its tokens on each request:

- ``app`` (the default) -- after login the app mints and verifies its own
  token. This is the only meaningful value for password/apiKey-style logins,
  since no external IdP sits behind them.
- ``idp`` -- the client keeps carrying the IdP's token and the app verifies it
  against the IdP each call, issuing no session of its own. It requires an
  ``issuer`` and ``audience`` to verify against, and only makes sense for
  providers that front an external IdP (OIDC, SAML).

These checks run on the pre-desugar spec, mirroring ``validate_spec_auth``, and
reject the spec with coded errors before the schema's structural validation.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

_TRUST_VALUES = frozenset({"app", "idp"})
_IDP_PROVIDER_TYPES = frozenset({"oidc", "saml"})
_APP_ONLY_KEYS = ("algorithm", "secret", "ttl", "refresh", "delivery")


def _check_provider(
    name: str, config: dict[str, Any], errors: list[ConfigError]
) -> None:
    trust = config.get("trust", "app")
    base = f"providers.{name}"

    if trust not in _TRUST_VALUES:
        errors.append(ConfigError(
            code="TRUST_INVALID_VALUE",
            message=f"Provider '{name}' has invalid trust '{trust}'",
            path=f"{base}.trust",
            hint="Set trust to 'app' (the app mints its own token) or 'idp'",
        ))
        return

    if trust == "app":
        for key in ("issuer", "audience"):
            if key in config:
                errors.append(ConfigError(
                    code="TRUST_APP_FIELD_FORBIDDEN",
                    message=f"Provider '{name}' is app-trust but declares '{key}'",
                    path=f"{base}.{key}",
                    hint=f"'{key}' only applies to trust: idp; remove it",
                ))
        return

    if config.get("type") not in _IDP_PROVIDER_TYPES:
        errors.append(ConfigError(
            code="TRUST_IDP_PROVIDER_UNSUPPORTED",
            message=f"Provider '{name}' uses trust: idp but is not an OIDC or SAML provider",
            path=f"{base}.trust",
            hint="trust: idp is only valid for providers fronting an external IdP",
        ))

    for key, code in (("issuer", "TRUST_IDP_ISSUER_REQUIRED"),
                      ("audience", "TRUST_IDP_AUDIENCE_REQUIRED")):
        if not config.get(key):
            errors.append(ConfigError(
                code=code,
                message=f"Provider '{name}' uses trust: idp but declares no {key}",
                path=f"{base}.{key}",
                hint=f"Set {key} so the app can verify the IdP's tokens",
            ))

    for key in _APP_ONLY_KEYS:
        if key in config:
            errors.append(ConfigError(
                code="TRUST_IDP_APP_FIELD_FORBIDDEN",
                message=f"Provider '{name}' is idp-trust but declares app-signing field '{key}'",
                path=f"{base}.{key}",
                hint="The app issues no token under trust: idp; remove this field",
            ))


def validate_spec_trust(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate per-provider trust coherence across every provider in the spec."""
    errors: list[ConfigError] = []
    providers = spec.get("providers") or {}
    for name, config in providers.items():
        if isinstance(config, dict):
            _check_provider(name, config, errors)
    return errors
