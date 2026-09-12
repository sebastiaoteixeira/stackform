"""Semantic coherence checks for per-provider ``trust`` in a v0.2 spec.

A provider's ``trust`` decides who verifies its tokens on each request:

- ``app`` (the default) -- after login the app mints and verifies its own
  token. This is the only meaningful value for password/apiKey-style logins,
  since no external IdP sits behind them.
- ``idp`` -- the client keeps carrying the IdP's token and the app verifies it
  against the IdP each call, issuing no session of its own. For OIDC providers
  this requires ``discovery_url``; the issuer is derived from it automatically.
  ``audiences`` is optional and defaults to ``[client_id]`` at runtime.

These checks run on the pre-desugar spec, mirroring ``validate_spec_auth``, and
reject the spec with coded errors before the schema's structural validation.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

_TRUST_VALUES = frozenset({"app", "idp"})
_IDP_PROVIDER_TYPES = frozenset({"oidc", "saml"})
_APP_ONLY_KEYS = (
    "algorithm",
    "secret",
    "ttl",
    "refresh",
    "delivery",
    "pkce",
    "dpop",
)


def _check_provider(
    name: str, config: dict[str, Any], results: list[ConfigError]
) -> None:
    trust = config.get("trust", "app")
    base = f"providers.{name}"

    if trust not in _TRUST_VALUES:
        results.append(ConfigError(
            code="TRUST_INVALID_VALUE",
            message=f"Provider '{name}' has invalid trust '{trust}'",
            path=f"{base}.trust",
            hint="Set trust to 'app' (the app mints its own token) or 'idp'",
        ))
        return

    if trust == "app":
        if "issuer" in config:
            results.append(ConfigError(
                code="TRUST_APP_FIELD_FORBIDDEN",
                message=f"Provider '{name}' is app-trust but declares 'issuer'",
                path=f"{base}.issuer",
                hint="'issuer' only applies to trust: idp; remove it",
            ))
        return

    if config.get("type") not in _IDP_PROVIDER_TYPES:
        results.append(ConfigError(
            code="TRUST_IDP_PROVIDER_UNSUPPORTED",
            message=f"Provider '{name}' uses trust: idp but is not an OIDC or SAML provider",
            path=f"{base}.trust",
            hint="trust: idp is only valid for providers fronting an external IdP",
        ))

    if config.get("type") == "oidc" and not config.get("discovery_url"):
        results.append(ConfigError(
            code="TRUST_IDP_DISCOVERY_URL_REQUIRED",
            message=f"Provider '{name}' uses trust: idp but declares no discovery_url",
            path=f"{base}.discovery_url",
            hint="Set discovery_url; the issuer is derived from it automatically",
        ))

    if config.get("type") == "oidc" and not config.get("audiences"):
        results.append(ConfigError(
            code="TRUST_IDP_AUDIENCE_DEFAULTED",
            message=(
                f"Provider '{name}': verifying aud against client_id by default; "
                "set audiences explicitly to also accept access tokens from sibling services "
                "(resource-server mode)."
            ),
            path=f"{base}.audiences",
            severity="warning",
        ))

    for key in _APP_ONLY_KEYS:
        if key in config:
            results.append(ConfigError(
                code="TRUST_IDP_APP_FIELD_FORBIDDEN",
                message=f"Provider '{name}' is idp-trust but declares app-signing field '{key}'",
                path=f"{base}.{key}",
                hint="The app issues no token under trust: idp; remove this field",
            ))


def validate_spec_trust(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate per-provider trust coherence across every provider in the spec."""
    results: list[ConfigError] = []
    providers = spec.get("providers") or {}
    for name, config in providers.items():
        if isinstance(config, dict):
            _check_provider(name, config, results)
    return results
