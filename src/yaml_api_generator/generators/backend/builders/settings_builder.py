"""Aggregates runtime env fields into a deduplicated SettingField list.

Framework fields are conditionally included based on enabled features;
spec-derived EnvRefs (from providers / datastores) are appended after.
"""

from yaml_api_generator.ir.api import EnvRef
from ..compile_context import CompileContext, SettingField


def build_settings_fields(ctx: CompileContext) -> list[SettingField]:
    """Return an ordered, deduplicated list of SettingField for the spec.

    Framework fields come first (in a stable, predictable order), followed
    by spec-derived EnvRefs sourced from providers and datastores.
    """
    fields: list[SettingField] = []
    seen: set[str] = set()

    def add(f: SettingField) -> None:
        if f.env_name not in seen:
            seen.add(f.env_name)
            fields.append(f)

    datastore_types = ctx.datastore_types
    uses_mongo = "mongodb" in datastore_types or "mongo" in datastore_types
    uses_postgres = bool(datastore_types & {"postgres", "postgresql"})
    # Fall back to mongo when no explicit datastores are declared
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
        # PASSWORD_HASH_ROUNDS is included whenever auth.py is rendered (always with auth)
        add(SettingField("PASSWORD_HASH_ROUNDS", "int", "390000"))

        if ctx.auth.uses_jwt:
            add(SettingField("JWT_SECRET", "str", None, secret=True, generated=True))
            add(SettingField("JWT_EXPIRATION_HOURS", "int", "24"))

        if ctx.auth.has_oidc_auth:
            add(SettingField("FRONTEND_URL", "str", ""))

    add(SettingField("HOST", "str", "127.0.0.1"))
    add(SettingField("PORT", "int", str(ctx.app.port)))

    # Spec-derived EnvRefs from providers
    for provider in ctx.auth.providers.values():
        for attr in vars(provider).values():
            if isinstance(attr, EnvRef):
                add(SettingField(attr.name, attr.value_type, attr.default, attr.secret))

    # Spec-derived EnvRefs from raw datastore configs
    for ds in ctx.datastores.values():
        for attr in ds.values():
            if isinstance(attr, EnvRef):
                add(SettingField(attr.name, attr.value_type, attr.default, attr.secret))

    return fields
