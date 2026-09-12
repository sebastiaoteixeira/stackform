"""Backend capability checks that run before a generator emits code.

Parse-time validation accepts every spec the language allows; a backend that
cannot implement one of those features must say so instead of emitting code
that silently skips it.
"""

from yaml_api_generator.generators.backend.compile_context import CompileContext
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


def reject_idp_trust(context: CompileContext, backend: str) -> None:
    """Reject providers whose tokens the backend cannot verify on each request."""
    errors = [
        ConfigError(
            code="BACKEND_FEATURE_UNSUPPORTED",
            message=(
                f"Provider '{name}' uses trust: idp, which the '{backend}' backend "
                "cannot verify"
            ),
            path=f"providers.{name}.trust",
            hint=f"Generate for the 'fastapi' backend, or set trust: app on '{name}'",
        )
        for name, provider in context.auth.providers.items()
        if provider.is_idp
    ]
    if errors:
        raise ConfigErrors(errors)


def reject_session_refresh(context: CompileContext, backend: str) -> None:
    """Reject rotation on backends that emit neither refresh tokens nor an endpoint."""
    if not context.session.refresh:
        return
    raise ConfigErrors(
        [
            ConfigError(
                code="BACKEND_FEATURE_UNSUPPORTED",
                message=(
                    f"session.refresh is not supported by the '{backend}' backend, "
                    "which issues no refresh token and exposes no rotation endpoint"
                ),
                path="session.refresh",
                hint=(
                    "Generate for the 'fastapi' backend, or drop session.refresh to "
                    "keep long-lived access tokens"
                ),
            )
        ]
    )
