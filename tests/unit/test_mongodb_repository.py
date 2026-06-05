from typing import Any

import pytest

from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
)


class FakeCollection:
    """Emulates the document-replacement semantics of Mongo's find_one_and_replace."""

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []

    def _matches(self, doc: dict[str, Any], match_filter: dict[str, Any]) -> bool:
        conditions = match_filter["$or"]
        return any(
            all(doc.get(key) == value for key, value in condition.items())
            for condition in conditions
        )

    class _Insert:
        inserted_id = "fake-object-id"

    async def insert_one(self, payload: dict[str, Any]) -> "FakeCollection._Insert":
        self._docs.append(dict(payload))
        return self._Insert()

    async def find_one(self, match_filter: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._docs:
            if self._matches(doc, match_filter):
                return dict(doc)
        return None

    async def find_one_and_replace(
        self, match_filter: dict[str, Any], payload: dict[str, Any], **_: Any
    ) -> dict[str, Any] | None:
        for index, doc in enumerate(self._docs):
            if self._matches(doc, match_filter):
                self._docs[index] = dict(payload)
                return dict(payload)
        return None


@pytest.fixture
def repository() -> MongoRepository:
    repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repo.register_id_field("items", "id")
    repo._db = {"items": FakeCollection()}
    return repo


@pytest.mark.asyncio
async def test_replace_preserves_id(repository: MongoRepository) -> None:
    await repository.create("items", {"id": "abc", "title": "old", "extra": "gone"})

    replaced = await repository.replace("items", "abc", {"title": "new"})

    assert replaced is not None
    assert replaced["id"] == "abc"
    assert replaced["title"] == "new"
    assert "extra" not in replaced

    fetched = await repository.get("items", "abc")
    assert fetched is not None
    assert fetched["id"] == "abc"
    assert fetched["title"] == "new"
