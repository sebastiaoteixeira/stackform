"""Build SQLAlchemy tables from collection field schemas.

Maps the spec's typed fields onto typed columns plus CHECK/NOT NULL/UNIQUE
constraints. Array and object fields become JSON; the id field becomes the
primary key. All tables built for one datastore share a single MetaData.
"""

from typing import Any

import sqlalchemy as sa

from yaml_api_generator.ir import IRCollection


def table_from_collection(collection: IRCollection, metadata: sa.MetaData) -> sa.Table:
    columns: list[sa.Column] = []
    constraints: list[sa.SchemaItem] = []

    for name, cfg in collection.fields.items():
        if not isinstance(cfg, dict):
            continue
        is_pk = name == collection.idField or cfg.get("type") == "id"
        columns.append(_column(name, cfg, is_pk))
        constraints.extend(_checks(name, cfg))

    return sa.Table(collection.name, metadata, *columns, *constraints)


def _column(name: str, cfg: dict[str, Any], is_pk: bool) -> sa.Column:
    nullable = not (is_pk or bool(cfg.get("required")))
    return sa.Column(
        name,
        _column_type(cfg),
        primary_key=is_pk,
        nullable=nullable,
        unique=True if cfg.get("unique") else None,
    )


def _column_type(cfg: dict[str, Any]) -> sa.types.TypeEngine:
    field_type = cfg.get("type", "string")
    if field_type in ("array", "object"):
        return sa.JSON()
    if field_type == "number":
        return sa.Numeric()
    if field_type == "boolean":
        return sa.Boolean()
    if field_type == "datetime":
        return sa.DateTime(timezone=True)
    max_length = cfg.get("maxLength")
    if field_type == "string" and isinstance(max_length, int):
        return sa.String(max_length)
    return sa.Text()


def _checks(name: str, cfg: dict[str, Any]) -> list[sa.CheckConstraint]:
    field_type = cfg.get("type", "string")
    checks: list[sa.CheckConstraint] = []

    if field_type == "enum" and cfg.get("values"):
        allowed = ", ".join(f"'{value}'" for value in cfg["values"])
        checks.append(sa.CheckConstraint(f"{name} IN ({allowed})", name=f"ck_{name}_enum"))

    if field_type == "number":
        if cfg.get("min") is not None:
            checks.append(sa.CheckConstraint(f"{name} >= {cfg['min']}", name=f"ck_{name}_min"))
        if cfg.get("max") is not None:
            checks.append(sa.CheckConstraint(f"{name} <= {cfg['max']}", name=f"ck_{name}_max"))

    if field_type == "string":
        if cfg.get("minLength") is not None:
            checks.append(sa.CheckConstraint(
                f"length({name}) >= {cfg['minLength']}", name=f"ck_{name}_minlen"
            ))
        if cfg.get("maxLength") is not None:
            checks.append(sa.CheckConstraint(
                f"length({name}) <= {cfg['maxLength']}", name=f"ck_{name}_maxlen"
            ))

    return checks
