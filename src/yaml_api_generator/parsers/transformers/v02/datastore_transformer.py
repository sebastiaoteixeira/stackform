"""Datastore registry parsing for v0.2 specs.

Parses the optional top-level `datastores:` block into IR datastore objects and
resolves the default. When the block is absent, a single default datastore is
synthesized from the legacy `mongo:` block so existing specs are unaffected.
"""

from typing import Any

from yaml_api_generator.ir import IRDatastore, IRMongo, IRPostgres
from yaml_api_generator.parsers.yaml_parser import ConfigError

DEFAULT_DATASTORE = "default"


def parse_datastores(
    resolved: dict[str, Any],
) -> tuple[dict[str, IRDatastore], str, list[ConfigError]]:
    """Return (datastores, default_name, errors) for a resolved spec."""
    raw = resolved.get("datastores")
    if not raw:
        mongo = resolved.get("mongo", {}) or {}
        datastore = IRMongo(
            uri=mongo.get("uri", IRMongo.uri),
            database=mongo.get("database", IRMongo.database),
        )
        return {DEFAULT_DATASTORE: datastore}, DEFAULT_DATASTORE, []

    errors: list[ConfigError] = []
    datastores: dict[str, IRDatastore] = {}
    default_name: str | None = None

    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            errors.append(ConfigError(
                code="DATASTORE_INVALID",
                message=f"Datastore '{name}' must be a mapping",
                path=f"datastores.{name}",
            ))
            continue

        datastore, type_errors = _build_datastore(name, cfg.get("type"), cfg)
        errors.extend(type_errors)
        if datastore is not None:
            datastores[name] = datastore

        if cfg.get("default") is True:
            if default_name is not None:
                errors.append(ConfigError(
                    code="DATASTORE_MULTIPLE_DEFAULTS",
                    message=f"Datastores '{default_name}' and '{name}' both marked default",
                    path=f"datastores.{name}.default",
                ))
            default_name = name

    if default_name is None:
        if len(datastores) == 1:
            default_name = next(iter(datastores))
        elif datastores:
            errors.append(ConfigError(
                code="DATASTORE_NO_DEFAULT",
                message="Multiple datastores declared but none marked 'default: true'",
                path="datastores",
            ))

    return datastores, default_name or DEFAULT_DATASTORE, errors


def resolve_binding(
    repo_name: str,
    repo_cfg: dict[str, Any],
    valid_names: set[str],
    default_name: str,
) -> tuple[str | None, ConfigError | None]:
    """Resolve and validate a repository's datastore binding."""
    declared = repo_cfg.get("datastore")
    if declared is None:
        return default_name, None
    if declared not in valid_names:
        return None, ConfigError(
            code="DATASTORE_UNKNOWN_REFERENCE",
            message=f"Repository '{repo_name}' references unknown datastore '{declared}'",
            path=f"repositories.{repo_name}.datastore",
        )
    return declared, None


def _build_datastore(
    name: str, ds_type: Any, cfg: dict[str, Any]
) -> tuple[IRDatastore | None, list[ConfigError]]:
    if ds_type in (None, "mongodb", "mongo"):
        return IRMongo(
            uri=cfg.get("uri", IRMongo.uri),
            database=cfg.get("database", IRMongo.database),
        ), []
    if ds_type in ("postgres", "postgresql"):
        dsn = cfg.get("dsn")
        if dsn is None:
            return None, [ConfigError(
                code="DATASTORE_MISSING_DSN",
                message=f"Postgres datastore '{name}' requires a 'dsn'",
                path=f"datastores.{name}.dsn",
            )]
        return IRPostgres(dsn=dsn), []
    return None, [ConfigError(
        code="DATASTORE_TYPE_UNKNOWN",
        message=f"Unknown datastore type '{ds_type}' for datastore '{name}'",
        path=f"datastores.{name}.type",
    )]
