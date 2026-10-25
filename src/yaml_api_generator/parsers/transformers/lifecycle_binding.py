"""Binds a repository lifecycle to the fields of the entity it stores.

The soft-delete timestamp is added to the entity as a read-only datetime when
the entity does not declare it; every lifecycle timestamp must be a datetime.
"""

from collections.abc import Mapping
from typing import Any

from yaml_api_generator.parsers.errors import ConfigError
from yaml_api_generator.runtime.lifecycle import Expiry, Lifecycle

_TIMESTAMP = {"type": "datetime", "readonly": True}


def lifecycle_from_config(config: Mapping[str, Any]) -> Lifecycle:
    """The lifecycle of a 0.2/0.3 repository: `softDelete: <field>` and `ttl: {field, seconds}`."""
    ttl = config.get("ttl")
    return Lifecycle(
        removal=config.get("softDelete"),
        expiry=Expiry(field=ttl["field"], seconds=ttl["seconds"]) if ttl else None,
    )


def bind_lifecycle(
    lifecycle: Lifecycle, fields: Mapping[str, Any], path: str
) -> tuple[dict[str, Any], list[ConfigError]]:
    """The entity fields with the removal timestamp in place, and the errors of misdeclared timestamps."""
    removal = lifecycle.removal
    bound = {**fields, **({removal: _TIMESTAMP} if removal and removal not in fields else {})}
    timestamps = {
        f"{path}.softDelete": removal,
        f"{path}.ttl.field": lifecycle.expiry.field if lifecycle.expiry else None,
    }
    return bound, [
        error
        for key_path, name in timestamps.items()
        if name and (error := _timestamp_error(bound, name, key_path)) is not None
    ]


def _timestamp_error(fields: Mapping[str, Any], name: str, path: str) -> ConfigError | None:
    if name not in fields:
        return ConfigError(
            code="LIFECYCLE_FIELD_NOT_FOUND",
            message=f"Lifecycle timestamp '{name}' is not a field of the entity",
            path=path,
        )
    declared = fields[name]
    if not isinstance(declared, dict) or declared.get("type") != "datetime":
        return ConfigError(
            code="LIFECYCLE_FIELD_NOT_DATETIME",
            message=f"Lifecycle timestamp '{name}' must be a datetime field",
            path=path,
        )
    return None
