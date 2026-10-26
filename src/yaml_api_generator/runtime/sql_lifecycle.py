"""A repository lifecycle expressed as SQLAlchemy Core clauses and statements."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from .lifecycle import Lifecycle


def _instant(value: datetime) -> sa.BindParameter[datetime]:
    """A timestamp bound as such, whatever type decorates the column it meets."""
    return sa.literal(value, sa.DateTime(timezone=True))


class SQLLifecycle:
    def __init__(self, table: sa.Table, lifecycle: Lifecycle = Lifecycle()) -> None:
        self._table = table
        self._lifecycle = lifecycle

    def visible(self) -> tuple[sa.ColumnElement[bool], ...]:
        removal, expiry = self._lifecycle.removal, self._lifecycle.expiry
        removed = (self._table.c[removal].is_(None),) if removal else ()
        if expiry is None:
            return removed
        stamp = self._table.c[expiry.field]
        return (*removed, sa.or_(stamp.is_(None), stamp >= _instant(expiry.cutoff())))

    def remove(self, *criteria: sa.ColumnElement[bool]) -> sa.Executable:
        """Stamps the removal timestamp when soft deletion is on, otherwise erases the row."""
        removal = self._lifecycle.removal
        statement = (
            sa.update(self._table).values({removal: _instant(datetime.now(UTC))})
            if removal
            else sa.delete(self._table)
        )
        return statement.where(*criteria, *self.visible()).returning(self._table)

    async def purge(self, engine: AsyncEngine) -> None:
        expiry = self._lifecycle.expiry
        if expiry is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.delete(self._table).where(self._table.c[expiry.field] < _instant(expiry.cutoff()))
                )
