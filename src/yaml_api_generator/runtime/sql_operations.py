"""Run a resolved SQL operation query on an open SQLAlchemy async connection."""

from decimal import Decimal
from typing import Any

import sqlalchemy as sa


def _json_value(value: Any) -> Any:
    """A NUMERIC value as the JSON number it denotes: integral ones as int, others as float."""
    if isinstance(value, Decimal):
        return int(value) if value.as_tuple().exponent >= 0 else float(value)
    return value


async def run_sql(connection: Any, query: dict[str, Any]) -> Any:
    result = await connection.execute(sa.text(query["sql"]), query.get("params") or {})
    if result.returns_rows:
        return [{key: _json_value(value) for key, value in row._mapping.items()} for row in result]
    return {"rowcount": result.rowcount}
