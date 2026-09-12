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


def reject_cookie_delivery(context: CompileContext, backend: str) -> None:
    if not context.session.uses_cookie:
        return
    raise ConfigErrors(
        [
            ConfigError(
                code="BACKEND_FEATURE_UNSUPPORTED",
                message=(
                    f"session.delivery: cookie is not supported by the '{backend}' "
                    "backend"
                ),
                path="session.delivery",
                hint="Generate for the 'fastapi' backend, or use delivery: token-url",
            )
        ]
    )


def reject_pkce(context: CompileContext, backend: str) -> None:
    providers = [
        name
        for name, provider in context.auth.providers.items()
        if getattr(provider, "pkce", False)
    ]
    if not providers:
        return
    names = ", ".join(sorted(providers))
    raise ConfigErrors(
        [
            ConfigError(
                code="BACKEND_FEATURE_UNSUPPORTED",
                message=(
                    f"OIDC PKCE for provider(s) {names} is not supported by the "
                    f"'{backend}' backend"
                ),
                path="providers",
                hint="Generate for the 'fastapi' backend, or disable PKCE",
            )
        ]
    )


def reject_unsigned_session_algorithm(context: CompileContext) -> None:
    """Reject a session algorithm choice on a spec that mints no session tokens."""
    if not context.session.uses_asymmetric or context.auth.uses_jwt:
        return
    raise ConfigErrors([
        ConfigError(
            code="SESSION_ALGORITHM_UNUSED",
            message=(
                f"session.algorithm: {context.session.algorithm} has no effect because "
                "this spec never mints a session token"
            ),
            path="session.algorithm",
            hint=(
                "Give an identity a password, app-trust OIDC or SAML login, "
                "or drop the session block"
            ),
        )
    ])
