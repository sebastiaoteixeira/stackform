from typing import Any

import pytest
from bson import ObjectId

from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
)


class FakeCollection:
    """Emulates the document-replacement semantics of Mongo's find_one_and_replace."""

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []

    def _matches(self, doc: dict[str, Any], match_filter: dict[str, Any]) -> bool:
        return all(
            any(self._matches(doc, branch) for branch in value)
            if key == "$or"
            else doc.get(key) == value
            for key, value in match_filter.items()
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

    async def find_one_and_update(
        self, match_filter: dict[str, Any], update: dict[str, Any], **_: Any
    ) -> dict[str, Any] | None:
        for index, doc in enumerate(self._docs):
            if self._matches(doc, match_filter):
                self._docs[index] = {**doc, **update["$set"]}
                return dict(self._docs[index])
        return None

    async def find_one_and_delete(
        self, match_filter: dict[str, Any]
    ) -> dict[str, Any] | None:
        for index, doc in enumerate(self._docs):
            if self._matches(doc, match_filter):
                return dict(self._docs.pop(index))
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


@pytest.mark.asyncio
async def test_find_one_matches_equality_criteria(repository: MongoRepository) -> None:
    await repository.create("items", {"id": "a", "slug": "books", "tenant": "t1"})
    await repository.create("items", {"id": "b", "slug": "books", "tenant": "t2"})

    found = await repository.find_one("items", {"slug": "books", "tenant": "t2"})

    assert found is not None
    assert found["id"] == "b"


@pytest.mark.asyncio
async def test_find_one_no_match_is_none(repository: MongoRepository) -> None:
    await repository.create("items", {"id": "a", "slug": "books"})

    assert await repository.find_one("items", {"slug": "missing"}) is None


@pytest.mark.asyncio
async def test_find_one_normalizes_object_id(repository: MongoRepository) -> None:
    object_id = ObjectId()
    await repository.collection("items").insert_one({"_id": object_id, "slug": "books"})

    found = await repository.find_one("items", {"slug": "books"})

    assert found is not None
    assert found["_id"] == str(object_id)


@pytest.mark.asyncio
async def test_criteria_mutations_are_atomic_and_scoped(
    repository: MongoRepository,
) -> None:
    await repository.create("items", {"id": "a", "tenant": "t1", "title": "old"})
    await repository.create("items", {"id": "a", "tenant": "t2", "title": "other"})

    updated = await repository.update_by(
        "items",
        {"id": "a", "tenant": "t1"},
        {"tenant": "t3", "title": "updated"},
    )
    assert updated is not None
    assert updated["title"] == "updated" and updated["tenant"] == "t1"
    unchanged = await repository.update_by(
        "items", {"id": "a", "tenant": "t1"}, {"id": "different", "tenant": "t3"}
    )
    assert unchanged == updated

    replaced = await repository.replace_by(
        "items", {"id": "a", "tenant": "t1"}, {"tenant": "t3", "title": "fresh"}
    )
    assert replaced == {"id": "a", "tenant": "t1", "title": "fresh"}

    deleted = await repository.delete_by("items", {"id": "a", "tenant": "t1"})
    assert deleted == replaced
    remaining = await repository.find_one("items", {"id": "a", "tenant": "t2"})
    assert remaining is not None and remaining["title"] == "other"


@pytest.mark.asyncio
async def test_criteria_mutation_wrong_scope_does_not_mutate(
    repository: MongoRepository,
) -> None:
    await repository.create("items", {"id": "a", "tenant": "t1", "title": "old"})

    result = await repository.update_by(
        "items", {"id": "a", "tenant": "t2"}, {"title": "wrong"}
    )

    assert result is None
    found = await repository.get("items", "a")
    assert found is not None and found["title"] == "old"
