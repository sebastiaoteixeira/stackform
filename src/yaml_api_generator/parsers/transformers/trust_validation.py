"""Advisory checks for per-provider ``trust`` in a v0.2/v0.3 spec.

Under ``trust: idp`` the app verifies the IdP's token on every request. The
schema rejects incoherent trust settings; this module only warns when an OIDC
provider leaves ``audiences`` to its ``[client_id]`` default.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError


def validate_spec_trust(spec: dict[str, Any]) -> list[ConfigError]:
    return [
        ConfigError(
            code="TRUST_IDP_AUDIENCE_DEFAULTED",
            message=(
                f"Provider '{name}': verifying aud against client_id by default; "
                "set audiences explicitly to also accept access tokens from sibling services "
                "(resource-server mode)."
            ),
            path=f"providers.{name}.audiences",
            severity="warning",
        )
        for name, config in spec.get("providers", {}).items()
        if config.get("trust") == "idp" and not config.get("audiences")
    ]
