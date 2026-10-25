"""Relational repository on SQLAlchemy Core (async).

Implements the BaseRepository contract over typed tables built from the spec.
The engine and schema are created lazily on first use so that the connection
pool binds to the serving event loop, not the build-time loop.
"""

import asyncio
import operator
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.runtime.sql_lifecycle import SQLLifecycle
from .base import BaseRepository, ConflictError
from .bindings import resolve
from .sql_schema import table_from_collection
from ..pagination import Page, Primitives, expand_bound


_SQL_COMPARATORS = {
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


@contextmanager
def _as_conflict() -> Iterator[None]:
    try:
        yield
    except IntegrityError as error:
        if not _is_unique_violation(error):
            raise
        raise ConflictError(_conflict_field(error)) from error


def _is_unique_violation(error: IntegrityError) -> bool:
    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    sqlite_unique_codes = {
        sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,
        sqlite3.SQLITE_CONSTRAINT_UNIQUE,
    }
    message = str(original).lower()
    return (
        sqlstate == "23505"
        or sqlite_code in sqlite_unique_codes
        or "unique constraint failed" in message
        or "duplicate key value violates unique constraint" in message
    )


def _conflict_field(error: IntegrityError) -> str | None:
    orig = getattr(error, "orig", error)
    diagnostics = getattr(orig, "diag", None)
    column = getattr(diagnostics, "column_name", None)
    if column:
        return column
    detail = getattr(diagnostics, "message_detail", None) or getattr(orig, "detail", None)
    if detail and "Key (" in detail:
        return detail.split("Key (", 1)[1].split(")", 1)[0]
    message = str(orig)
    if "UNIQUE constraint failed:" in message:
        first = message.split("UNIQUE constraint failed:", 1)[1].split(",")[0]
        return first.strip().split(".")[-1]
    return None


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
        self._lifecycles = {c.name: SQLLifecycle(self._tables[c.name], c.lifecycle) for c in cols}
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

    async def purge_expired(self) -> None:
        engine = await self._engine_ready()
        for lifecycle in self._lifecycles.values():
            await lifecycle.purge(engine)

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        table = self._table(collection_name)
        async with await self._connection() as conn:
            result = await conn.execute(sa.select(table).where(*self._visible(collection_name, {})))
            return [dict(row._mapping) for row in result]

    async def paginate(self, collection_name: str, primitives: Primitives) -> Page:
        table = self._table(collection_name)
        visible = self._visible(collection_name, {})
        stmt = sa.select(table).where(*self._bounds_clauses(table, primitives.bounds), *visible)
        for key in primitives.sort:
            column = table.c[key.field]
            stmt = stmt.order_by(column.desc() if key.descending else column.asc())
        if primitives.skip:
            stmt = stmt.offset(primitives.skip)
        if primitives.limit is not None:
            stmt = stmt.limit(primitives.limit)
        async with await self._connection() as conn:
            rows = [dict(row._mapping) for row in await conn.execute(stmt)]
            total = None
            if primitives.count == "exact":
                count_stmt = sa.select(sa.func.count()).select_from(table).where(*visible)
                total = (await conn.execute(count_stmt)).scalar()
        return Page(rows=rows, total=total)

    def _bounds_clauses(self, table: sa.Table, bounds) -> "list[Any]":
        clauses = []
        for bound in bounds:
            disjuncts = []
            for equalities, key in expand_bound(bound):
                terms = [table.c[field] == value for field, value in equalities]
                terms.append(_SQL_COMPARATORS[key.op](table.c[key.field], key.value))
                disjuncts.append(sa.and_(*terms))
            clauses.append(sa.or_(*disjuncts))
        return clauses

    async def get(self, collection_name: str, document_id: str) -> dict[str, Any] | None:
        return await self.find_one(collection_name, self._id_criteria(collection_name, document_id))

    async def find_one(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        statement = (
            sa.select(self._table(collection_name))
            .where(*self._visible(collection_name, criteria))
            .limit(1)
        )
        async with await self._connection() as conn:
            return self._one(await conn.execute(statement))

    async def update_by(
        self,
        collection_name: str,
        criteria: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        table = self._table(collection_name)
        values = self._known_columns(
            collection_name,
            {field: value for field, value in payload.items() if field not in criteria},
            drop_id=True,
        )
        if not values:
            return await self.find_one(collection_name, criteria)
        statement = (
            sa.update(table)
            .where(*self._visible(collection_name, criteria))
            .values(**values)
            .returning(table)
        )
        with _as_conflict():
            async with await self._begin() as conn:
                return self._one(await conn.execute(statement))

    async def replace_by(
        self,
        collection_name: str,
        criteria: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        table = self._table(collection_name)
        replacement = {**payload, **criteria}
        id_field = self._id_fields[collection_name]
        values = {
            column.name: replacement.get(column.name)
            for column in table.columns
            if column.name != id_field
        }
        statement = (
            sa.update(table)
            .where(*self._visible(collection_name, criteria))
            .values(**values)
            .returning(table)
        )
        with _as_conflict():
            async with await self._begin() as conn:
                return self._one(await conn.execute(statement))

    async def delete_by(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        statement = self._lifecycles[collection_name].remove(
            *self._criteria(collection_name, criteria)
        )
        async with await self._begin() as conn:
            return self._one(await conn.execute(statement))

    async def create(self, collection_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        table = self._table(collection_name)
        values = self._known_columns(collection_name, payload)
        with _as_conflict():
            async with await self._begin() as conn:
                await conn.execute(sa.insert(table).values(**values))
        return values

    async def upsert_by(
        self, collection_name: str, key_field: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        if payload.get(key_field) is None:
            raise ValueError(f"upsert_by requires a non-null value for key field '{key_field}'")
        table = self._table(collection_name)
        values = self._known_columns(collection_name, payload)
        statement = pg_insert(table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[key_field],
            set_={k: statement.excluded[k] for k in values if k != key_field},
        ).returning(table)
        with _as_conflict():
            async with await self._begin() as conn:
                result = await conn.execute(statement)
                row = self._one(result)
        return row if row is not None else values

    async def update(
        self, collection_name: str, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        table = self._table(collection_name)
        values = self._known_columns(collection_name, payload, drop_id=True)
        with _as_conflict():
            async with await self._begin() as conn:
                result = await conn.execute(
                    sa.update(table)
                    .where(*self._visible(collection_name, self._id_criteria(collection_name, document_id)))
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
        with _as_conflict():
            async with await self._begin() as conn:
                result = await conn.execute(
                    sa.update(table)
                    .where(*self._visible(collection_name, self._id_criteria(collection_name, document_id)))
                    .values(**values)
                    .returning(table)
                )
                return self._one(result)

    async def delete(self, collection_name: str, document_id: str) -> dict[str, Any] | None:
        return await self.delete_by(collection_name, self._id_criteria(collection_name, document_id))

    async def run_operation(
        self,
        collection_name: str,
        query: dict[str, Any],
        bindings: dict[str, Any],
        include_deleted: bool = False,
    ) -> Any:
        sql = query.get("sql")
        if not sql:
            raise ValueError("SQL custom operations require a 'sql' string")
        params = {key: resolve(value, bindings) for key, value in (query.get("params") or {}).items()}
        with _as_conflict():
            async with await self._begin() as conn:
                result = await conn.execute(sa.text(sql), params)
                if result.returns_rows:
                    return [dict(row._mapping) for row in result]
                return {"rowcount": result.rowcount}

    def _table(self, collection_name: str) -> sa.Table:
        return self._tables[collection_name]

    def _column(self, collection_name: str, field: str) -> sa.Column:
        return self._table(collection_name).c[field]

    def _id_criteria(self, collection_name: str, document_id: str) -> dict[str, Any]:
        return {self._id_fields[collection_name]: document_id}

    def _criteria(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> tuple[sa.ColumnElement[bool], ...]:
        return tuple(
            self._column(collection_name, field) == value
            for field, value in criteria.items()
        )

    def _visible(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> tuple[sa.ColumnElement[bool], ...]:
        return (
            *self._criteria(collection_name, criteria),
            *self._lifecycles[collection_name].visible(),
        )

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
