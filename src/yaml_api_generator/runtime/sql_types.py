"""SQLAlchemy column types for field types whose stored form differs from their JSON form."""

from datetime import datetime

import sqlalchemy as sa

from .fields import iso_utc


class IsoDateTime(sa.TypeDecorator):
    """A timestamp column read and written as the canonical ISO 8601 UTC string."""

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: sa.Dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)

    def process_result_value(self, value: datetime | None, dialect: sa.Dialect) -> str | None:
        return None if value is None else iso_utc(value)
