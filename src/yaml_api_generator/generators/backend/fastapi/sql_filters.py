"""Jinja filters for rendering SQLAlchemy table definitions in generated code."""

from typing import Any


def sql_column(name: str, cfg: dict[str, Any], id_field: str) -> str:
    field_type = cfg.get("type", "string")
    is_pk = name == id_field or field_type == "id"

    parts = [f'"{name}"', _column_type(cfg, field_type)]
    if is_pk:
        parts.append("primary_key=True")
    elif cfg.get("required"):
        parts.append("nullable=False")
    if cfg.get("unique"):
        parts.append("unique=True")
    return f"sa.Column({', '.join(parts)})"


def _column_type(cfg: dict[str, Any], field_type: str) -> str:
    if field_type in ("array", "object", "file"):
        return "sa.JSON()"
    if field_type == "number":
        return "sa.Numeric()"
    if field_type == "boolean":
        return "sa.Boolean()"
    if field_type == "datetime":
        return "sa.DateTime(timezone=True)"
    max_length = cfg.get("maxLength")
    if field_type == "string" and isinstance(max_length, int):
        return f"sa.String({max_length})"
    return "sa.Text()"