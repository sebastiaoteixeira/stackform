"""Run a resolved SQL operation query on an open SQLAlchemy async connection."""

from typing import Any

import sqlalchemy as sa


async def run_sql(connection: Any, query: dict[str, Any]) -> Any:
    result = await connection.execute(sa.text(query["sql"]), query.get("params") or {})
    if result.returns_rows:
        return [dict(row._mapping) for row in result]
    return {"rowcount": result.rowcount}
