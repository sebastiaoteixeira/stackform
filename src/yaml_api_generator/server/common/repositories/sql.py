"""Relational repository on SQLAlchemy Core (async).

Implements the BaseRepository contract over typed tables built from the spec.
The engine and schema are created lazily on first use so that the connection
pool binds to the serving event loop, not the build-time loop.
"""

import asyncio
from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from yaml_api_generator.ir import IRCollection
from .base import BaseRepository
from .bindings import resolve
from .sql_schema import table_from_collection


class SQLRepository(BaseRepository):
    def __init__(
        self,
        dsn: str,
        collections: Iterable[IRCollection],
        *,
        create_schema: bool = True,
    ) -> None:
        self._dsn = dsn
        self._create_schema = create_schema
        self._metadata = sa.MetaData()
        cols = list(collections)
        self._tables = {c.name: table_from_collection(c, self._metadata) for c in cols}
        self._id_fields = {c.name: c.idField for c in cols}
        self._engine: AsyncEngine | None = None
        self._schema_ready = False
        self._lock = asyncio.Lock()

    def register_id_field(self, collection_name: str, id_field: str) -> None:
        self._id_fields[collection_name] = id_field

    def connect(self) -> None:
        self._engine = create_async_engine(self._dsn)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._schema_ready = False

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        table = self._table(collection_name)
        async with await self._connection() as conn:
            result = await conn.execute(sa.select(table))
            return [dict(row._mapping) for row in result]

    async def get(self, collection_name: str, document_id: str) -> dict[str, Any] | None:
        table = self._table(collection_name)
        async with await self._connection() as conn:
            result = await conn.execute(
                sa.select(table).where(self._id_column(collection_name) == document_id)
            )
            return self._one(result)

    async def find_one(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        table = self._table(collection_name)
        statement = sa.select(table)
        for field, value in criteria.items():
            statement = statement.where(table.c[field] == value)
        async with await self._connection() as conn:
            result = await conn.execute(statement)
            return self._one(result)

    async def create(self, collection_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        table = self._table(collection_name)
        values = self._known_columns(collection_name, payload)
        async with await self._begin() as conn:
            await conn.execute(sa.insert(table).values(**values))
        return values

    async def update(
        self, collection_name: str, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        table = self._table(collection_name)
        values = self._known_columns(collection_name, payload, drop_id=True)
        async with await self._begin() as conn:
            result = await conn.execute(
                sa.update(table)
                .where(self._id_column(collection_name) == document_id)
                .values(**values)
                .returning(table)
            )
            return self._one(result)

    async def replace(
        self, collection_name: str, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        table = self._table(collection_name)
        id_field = self._id_fields[collection_name]
        values = {
            column.name: payload.get(column.name)
            for column in table.columns
            if column.name != id_field
        }
        async with await self._begin() as conn:
            result = await conn.execute(
                sa.update(table)
                .where(self._id_column(collection_name) == document_id)
                .values(**values)
                .returning(table)
            )
            return self._one(result)

    async def delete(self, collection_name: str, document_id: str) -> dict[str, Any] | None:
        table = self._table(collection_name)
        async with await self._begin() as conn:
            result = await conn.execute(
                sa.delete(table)
                .where(self._id_column(collection_name) == document_id)
                .returning(table)
            )
            return self._one(result)

    async def run_operation(
        self,
        collection_name: str,
        query: dict[str, Any],
        bindings: dict[str, Any],
    ) -> Any:
        sql = query.get("sql")
        if not sql:
            raise ValueError("SQL custom operations require a 'sql' string")
        params = {key: resolve(value, bindings) for key, value in (query.get("params") or {}).items()}
        async with await self._begin() as conn:
            result = await conn.execute(sa.text(sql), params)
            if result.returns_rows:
                return [dict(row._mapping) for row in result]
            return {"rowcount": result.rowcount}

    def _table(self, collection_name: str) -> sa.Table:
        return self._tables[collection_name]

    def _id_column(self, collection_name: str) -> sa.Column:
        return self._tables[collection_name].c[self._id_fields[collection_name]]

    def _known_columns(
        self, collection_name: str, payload: dict[str, Any], drop_id: bool = False
    ) -> dict[str, Any]:
        table = self._table(collection_name)
        id_field = self._id_fields[collection_name]
        return {
            key: value
            for key, value in payload.items()
            if key in table.columns and not (drop_id and key == id_field)
        }

    @staticmethod
    def _one(result: sa.Result) -> dict[str, Any] | None:
        row = result.first()
        return dict(row._mapping) if row is not None else None

    async def _engine_ready(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(self._dsn)
        if self._create_schema and not self._schema_ready:
            async with self._lock:
                if not self._schema_ready:
                    async with self._engine.begin() as conn:
                        await conn.run_sync(self._metadata.create_all)
                    self._schema_ready = True
        return self._engine

    async def _connection(self):
        engine = await self._engine_ready()
        return engine.connect()

    async def _begin(self):
        engine = await self._engine_ready()
        return engine.begin()
