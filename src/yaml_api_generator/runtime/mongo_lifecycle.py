"""A repository lifecycle expressed as MongoDB filters, pipelines and writes."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument

from .lifecycle import Expiry, Lifecycle


def _expired(expiry: Expiry) -> dict[str, Any]:
    """Expiry is evaluated against the server clock and accepts BSON dates and ISO 8601 strings alike."""
    instant = {"$convert": {"input": f"${expiry.field}", "to": "date", "onError": None, "onNull": None}}
    cutoff = {"$subtract": ["$$NOW", expiry.seconds * 1000]}
    return {"$and": [{"$ne": [instant, None]}, {"$lt": [instant, cutoff]}]}


class MongoLifecycle:
    def __init__(self, lifecycle: Lifecycle = Lifecycle()) -> None:
        self._lifecycle = lifecycle
        removal = [{lifecycle.removal: None}] if lifecycle.removal else []
        expiry = [{"$expr": {"$not": [_expired(lifecycle.expiry)]}}] if lifecycle.expiry else []
        self._conditions = (*removal, *expiry)

    def visible(self, criteria: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clauses = [dict(clause) for clause in (criteria, *self._conditions) if clause]
        return {"$and": clauses} if len(clauses) > 1 else next(iter(clauses), {})

    def pipeline(self, stages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [{"$match": self.visible()}, *stages] if self._conditions else list(stages)

    async def remove(self, collection: Any, criteria: Mapping[str, Any]) -> dict[str, Any] | None:
        """Stamps the removal timestamp when soft deletion is on, otherwise erases the row."""
        if self._lifecycle.removal is None:
            return await collection.find_one_and_delete(self.visible(criteria))
        stamp = {"$set": {self._lifecycle.removal: datetime.now(UTC).isoformat()}}
        return await collection.find_one_and_update(self.visible(criteria), stamp, return_document=ReturnDocument.AFTER)

    async def purge(self, collection: Any) -> None:
        if self._lifecycle.expiry is not None:
            await collection.delete_many({"$expr": _expired(self._lifecycle.expiry)})
