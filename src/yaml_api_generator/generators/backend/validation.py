"""Backend capability checks that run before a generator emits code.

Parse-time validation accepts every spec the language allows; a backend that
cannot implement one of those features must say so instead of emitting code
that silently skips it.
"""

from yaml_api_generator.generators.backend.compile_context import CompileContext
from yaml_api_generator.parsers.transformers import file_validation
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


_SQL_DATASTORES = frozenset({"postgres", "postgresql"})
_MONGO_DATASTORES = frozenset({"mongo", "mongodb"})


def validate_datastore_layout(context: CompileContext, backend: str) -> None:
    mongo = [
        name
        for name, datastore in context.datastores.items()
        if datastore["type"] in _MONGO_DATASTORES
    ]
    sql = [
        name
        for name, datastore in context.datastores.items()
        if datastore["type"] in _SQL_DATASTORES
    ]
    errors: list[ConfigError] = []
    for family, names in (("MongoDB", mongo), ("SQL", sql)):
        if len(names) > 1:
            errors.append(ConfigError(
                code="BACKEND_DATASTORE_LAYOUT_UNSUPPORTED",
                message=(
                    f"The '{backend}' backend cannot route {family} repositories "
                    f"across multiple datastores: {', '.join(sorted(names))}"
                ),
                path="datastores",
                hint=f"Use one {family} datastore per generated backend",
            ))
    if backend in {"drf", "raw"} and sql:
        errors.append(ConfigError(
            code="BACKEND_DATASTORE_UNSUPPORTED",
            message=f"The '{backend}' backend does not implement SQL repositories",
            path=f"datastores.{sql[0]}",
            hint="Generate the FastAPI backend or use a MongoDB datastore",
        ))
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


def reject_file_fields(context: CompileContext, backend: str) -> None:
    """Reject file fields on backends that implement no file datastore."""
    file_validation.reject_file_fields(
        {name: collection["fields"] for name, collection in context.collections.items()},
        backend,
    )


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


def reject_session_refresh_without_mongo(context: CompileContext) -> None:
    """Reject rotation when every collection is SQL, leaving no MongoDB store for refresh records."""
    collection_types = {context.collection_datastore_type(name) for name in context.collections}
    if not (context.session.refresh and collection_types and collection_types <= _SQL_DATASTORES):
        return
    raise ConfigErrors(
        [
            ConfigError(
                code="BACKEND_FEATURE_UNSUPPORTED",
                message="session.refresh keeps refresh records in MongoDB, but no collection uses it",
                path="session.refresh",
                hint="Declare a MongoDB datastore, or drop session.refresh",
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
