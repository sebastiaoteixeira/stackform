"""Unsupported-target guard for providers that sign users in through the app."""

from collections.abc import Mapping

from yaml_api_generator.ir.api import IRProvider
from yaml_api_generator.parsers.errors import ConfigError, ConfigErrors


def reject_external_login(providers: Mapping[str, IRProvider], target: str) -> None:
    """Raise when a provider needs the login, callback and code-exchange routes the target lacks."""
    errors = [
        ConfigError(
            code="BACKEND_FEATURE_UNSUPPORTED",
            message=f"{provider.type.upper()} login through provider '{name}' is not supported by target '{target}'",
            path=f"providers.{name}",
            hint="Generate for the 'fastapi' backend, or run the FastAPI dev server",
        )
        for name, provider in providers.items()
        if not provider.is_idp
    ]
    if errors:
        raise ConfigErrors(errors)
