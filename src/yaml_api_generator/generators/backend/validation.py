"""Backend capability checks that run before a generator emits code.

Parse-time validation accepts every spec the language allows; a backend that
cannot implement one of those features must say so instead of emitting code
that silently skips it.
"""

from yaml_api_generator.generators.backend.compile_context import CompileContext
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


def reject_pagination(context: CompileContext, backend: str) -> None:
    """Reject paginated operations for backends that only emit an unbounded list."""
    errors = [
        ConfigError(
            code="BACKEND_FEATURE_UNSUPPORTED",
            message=(
                f"Operation '{route.operation}' on '{route.collection}' declares "
                f"pagination, which the '{backend}' backend does not implement"
            ),
            path=(
                f"controllers.{route.collection}.operations."
                f"{route.operation}.pagination"
            ),
            hint="Serve the spec with 'yaml-api run', or drop the pagination block",
        )
        for route in context.routes
        if route.pagination is not None
    ]
    if errors:
        raise ConfigErrors(errors)


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
