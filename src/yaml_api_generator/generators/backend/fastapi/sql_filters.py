"""Jinja filters for rendering SQLAlchemy table definitions in generated code."""

from typing import Any

import sqlalchemy as sa

from yaml_api_generator.server.common.repositories.sql_schema import column_type


def sql_column(name: str, cfg: dict[str, Any], id_field: str) -> str:
    field_type = cfg.get("type", "string")
    is_pk = name == id_field or field_type == "id"

    parts = [f'"{name}"', _constructor(column_type(cfg))]
    if is_pk:
        parts.append("primary_key=True")
    elif cfg.get("required"):
        parts.append("nullable=False")
    if cfg.get("unique"):
        parts.append("unique=True")
    return f"sa.Column({', '.join(parts)})"


def _constructor(column: sa.types.TypeEngine) -> str:
    """The source building ``column``; SQLAlchemy's own types are reached through ``sa``."""
    namespace = "sa." if type(column).__module__.startswith("sqlalchemy.") else ""
    return f"{namespace}{column!r}"
