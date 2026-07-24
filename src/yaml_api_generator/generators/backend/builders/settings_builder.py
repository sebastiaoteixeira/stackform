from secrets import token_urlsafe

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ..compile_context import CompileContext, SettingField
from ....ir.api import IROIDCProvider


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
        add(SettingField("MONGO_URI", "str", "mongodb://localhost:27017"))
        add(SettingField("MONGO_DB", "str", "yaml_api"))
    if uses_postgres:
        postgres_dsn = next(
            (ds["dsn"] for ds in ctx.datastores.values()
             if ds["type"] in ("postgres", "postgresql")),
            None,
        )
        add(SettingField("DATABASE_URL", "str", postgres_dsn))

    if ctx.auth.enabled:
        add(SettingField("PASSWORD_HASH_ROUNDS", "int", "390000"))

        if ctx.auth.uses_jwt:
            if ctx.session.uses_asymmetric:
                add(SettingField(
                    "JWT_PRIVATE_KEY", "str", None,
                    secret=True, generated=True, secret_kind="rsa_private_key",
                ))
            else:
                add(SettingField("JWT_SECRET", "str", None, secret=True, generated=True))
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
                    add(SettingField(env_name, "str", None, secret=True, generated=False))

    add(SettingField("HOST", "str", "127.0.0.1"))
    add(SettingField("PORT", "int", str(ctx.app.port)))

    return fields


def _rsa_private_key_env_value() -> str:
    """A fresh RSA private key as a double-quoted single-line dotenv value.

    PEM newlines are escaped as ``\\n`` inside double quotes so python-dotenv
    restores the real newlines when the generated app loads its ``.env``.
    """
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return '"' + pem.replace("\n", "\\n") + '"'


def _generated_value(field: SettingField) -> str:
    if field.secret_kind == "rsa_private_key":
        return _rsa_private_key_env_value()
    return token_urlsafe(32)


def generated_secret_values(fields: list[SettingField]) -> dict[str, str]:
    """Return a mapping of env_name -> generated value for generated secrets."""
    return {f.env_name: _generated_value(f) for f in fields if f.generated}
