from secrets import token_urlsafe

from ..compile_context import CompileContext, SettingField
from ....ir.api import IROIDCProvider
from ....runtime.dpop import generate_private_key_pem as generate_dpop_private_key_pem
from ....utils.rsa_keys import generate_private_key_pem
from ....utils.strings import to_py_identifier


def _dotenv_pem() -> str:
    """A fresh RSA private key as a double-quoted single-line dotenv value.

    PEM newlines are escaped as ``\\n`` inside double quotes so python-dotenv
    restores the real newlines when the generated app loads its ``.env``.
    """
    return '"' + generate_private_key_pem().replace("\n", "\\n") + '"'


def _dotenv_dpop_pem() -> str:
    return '"' + generate_dpop_private_key_pem().replace("\n", "\\n") + '"'


def dpop_private_key_env(provider_name: str) -> str:
    return f"{to_py_identifier(provider_name).upper()}_DPOP_PRIVATE_KEY"


def _token() -> str:
    return token_urlsafe(32)


def build_settings_fields(ctx: CompileContext) -> list[SettingField]:
    """Return an ordered, deduplicated list of SettingField for the spec."""
    fields: list[SettingField] = []
    seen: set[str] = set()

    def add(f: SettingField) -> None:
        if f.env_name not in seen:
            seen.add(f.env_name)
            fields.append(f)

    datastore_types = ctx.datastore_types
    uses_mongo = "mongodb" in datastore_types or "mongo" in datastore_types
    uses_postgres = bool(datastore_types & {"postgres", "postgresql"})
    if not datastore_types:
        uses_mongo = True

    if uses_mongo:
        mongo = next(
            (
                datastore
                for datastore in ctx.datastores.values()
                if datastore["type"] in {"mongodb", "mongo"}
            ),
            {},
        )
        add(SettingField(
            "MONGO_URI", "str", mongo.get("uri", "mongodb://localhost:27017")
        ))
        add(SettingField("MONGO_DB", "str", mongo.get("database", "yaml_api")))
    if uses_postgres:
        postgres_dsn = next(
            (ds["dsn"] for ds in ctx.datastores.values()
             if ds["type"] in ("postgres", "postgresql")),
            None,
        )
        add(SettingField("DATABASE_URL", "str", postgres_dsn))

    for setting in (f for store in ctx.file_stores.values() for f in store.settings):
        add(setting)

    if ctx.auth.enabled:
        add(SettingField("PASSWORD_HASH_ROUNDS", "int", "390000"))

        if ctx.auth.uses_jwt:
            if ctx.session.uses_asymmetric:
                add(SettingField("JWT_PRIVATE_KEY", "str", None, secret=True, generator=_dotenv_pem))
                add(SettingField("JWT_RETIRED_PUBLIC_KEY", "str", ""))
            else:
                add(SettingField("JWT_SECRET", "str", None, secret=True, generator=_token))
            if ctx.session.refresh:
                add(SettingField(
                    "JWT_ACCESS_TTL_SECONDS", "int", str(ctx.session.ttl or 900)
                ))
                add(SettingField("JWT_REFRESH_TTL_SECONDS", "int", "2592000"))
            else:
                add(SettingField("JWT_EXPIRATION_HOURS", "int", "24"))

        if ctx.auth.has_app_oidc_auth:
            add(SettingField("FRONTEND_URL", "str", ""))
            for provider_name, provider in ctx.auth.providers.items():
                if isinstance(provider, IROIDCProvider) and provider.client_secret is not None:
                    env_name = f"{provider_name.upper()}_CLIENT_SECRET"
                    add(SettingField(env_name, "str", None, secret=True))
                if isinstance(provider, IROIDCProvider) and provider.dpop:
                    add(
                        SettingField(
                            dpop_private_key_env(provider_name),
                            "str",
                            None,
                            secret=True,
                            generator=_dotenv_dpop_pem,
                        )
                    )

    add(SettingField("HOST", "str", "127.0.0.1"))
    add(SettingField("PORT", "int", str(ctx.app.port)))

    return fields


def generated_secret_values(fields: list[SettingField]) -> dict[str, str]:
    """Return a mapping of env_name -> freshly generated value."""
    return {f.env_name: f.generator() for f in fields if f.generator is not None}
