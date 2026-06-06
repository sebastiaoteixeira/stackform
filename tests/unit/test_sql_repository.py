"""Tests for the relational table builder and SQLRepository CRUD.

CRUD runs against in-memory SQLite via aiosqlite; SQLAlchemy Core keeps the
statements dialect-neutral, so this exercises the same code paths as Postgres.
"""

import sqlalchemy as sa
import pytest

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.server.common.repositories.sql import SQLRepository
from yaml_api_generator.server.common.repositories.sql_schema import table_from_collection


def _collection() -> IRCollection:
    return IRCollection(
        name="events",
        entity_name="event",
        type="base",
        idField="id",
        idFormat="uuidv4",
        fields={
            "id": {"type": "id"},
            "kind": {"type": "string", "required": True, "maxLength": 40},
            "score": {"type": "number", "min": 0, "max": 100},
            "active": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "level": {"type": "enum", "values": ["low", "high"]},
        },
        datastore="warehouse",
    )


def test_table_from_collection_maps_types_and_constraints():
    table = table_from_collection(_collection(), sa.MetaData())
    assert table.name == "events"
    assert table.c.id.primary_key
    assert isinstance(table.c.kind.type, sa.String)
    assert table.c.kind.nullable is False
    assert isinstance(table.c.score.type, sa.Numeric)
    assert isinstance(table.c.active.type, sa.Boolean)
    assert isinstance(table.c.tags.type, sa.JSON)
    checks = {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint)}
    assert {"ck_kind_maxlen", "ck_score_min", "ck_score_max", "ck_level_enum"} <= checks


@pytest.fixture
async def repo():
    repository = SQLRepository("sqlite+aiosqlite://", [_collection()])
    repository.connect()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_crud_round_trip(repo):
    created = await repo.create("events", {"id": "e1", "kind": "click", "score": 5})
    assert created["id"] == "e1"

    assert await repo.get("events", "e1") == {
        "id": "e1", "kind": "click", "score": 5, "active": None, "tags": None, "level": None,
    }

    listed = await repo.list("events")
    assert len(listed) == 1 and listed[0]["id"] == "e1"

    updated = await repo.update("events", "e1", {"kind": "scroll"})
    assert updated["kind"] == "scroll" and updated["score"] == 5

    replaced = await repo.replace("events", "e1", {"kind": "view"})
    assert replaced["kind"] == "view" and replaced["score"] is None

    deleted = await repo.delete("events", "e1")
    assert deleted["id"] == "e1"
    assert await repo.get("events", "e1") is None


@pytest.mark.asyncio
async def test_unknown_columns_are_dropped(repo):
    created = await repo.create("events", {"id": "e2", "kind": "x", "_auth": {"x": 1}})
    assert "_auth" not in created
    assert await repo.get("events", "e2") is not None
