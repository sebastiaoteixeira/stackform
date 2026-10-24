"""Jinja filters for rendering SQLAlchemy table definitions in generated code."""

from typing import Any

from yaml_api_generator.server.common.repositories.sql_schema import column_type


def sql_column(name: str, cfg: dict[str, Any], id_field: str) -> str:
    field_type = cfg.get("type", "string")
    is_pk = name == id_field or field_type == "id"

    parts = [f'"{name}"', f"sa.{column_type(cfg)!r}"]
    if is_pk:
        parts.append("primary_key=True")
    elif cfg.get("required"):
        parts.append("nullable=False")
    if cfg.get("unique"):
        parts.append("unique=True")
    return f"sa.Column({', '.join(parts)})"
