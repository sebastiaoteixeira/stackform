"""Aggregates framework settings fields into a deduplicated SettingField list.

Framework fields are conditionally included based on enabled features.
"""

from ..compile_context import CompileContext, SettingField


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
            add(SettingField("JWT_SECRET", "str", None, secret=True, generated=True))
            add(SettingField("JWT_EXPIRATION_HOURS", "int", "24"))

        if ctx.auth.has_app_oidc_auth:
            add(SettingField("FRONTEND_URL", "str", ""))

    add(SettingField("HOST", "str", "127.0.0.1"))
    add(SettingField("PORT", "int", str(ctx.app.port)))

    return fields
