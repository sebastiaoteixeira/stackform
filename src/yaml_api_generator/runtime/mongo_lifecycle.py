"""A repository lifecycle expressed as MongoDB filters, pipelines, writes and a TTL index.

A lifecycle is the mapping ``{"removal": field | None, "expiry": {"field", "seconds"} | None}``.
Writes store the expiry field as a BSON date, the only type a TTL index erases rows by.
"""

from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument

EXPIRY_INDEX = "lifecycle_expiry"

_DELETES = frozenset({"deleteOne", "findOneAndDelete", "deleteMany"})
_FILTERED = frozenset({
    "find", "findOne", "countDocuments", "distinct", "updateOne", "findOneAndUpdate", "updateMany",
    "replaceOne", "findOneAndReplace", *_DELETES,
})
_WRITE_OPERATORS = ("$set", "$setOnInsert")


def _instant(value: Any) -> Any:
    """`value` as an aware datetime when it denotes an instant, otherwise unchanged."""
    if isinstance(value, str):
        with suppress(ValueError):
            return _instant(datetime.fromisoformat(value))
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _clock(field: str) -> dict[str, Any]:
    """The instant `field` holds, server side: BSON dates and ISO 8601 strings alike, null otherwise."""
    return {"$convert": {"input": f"${field}", "to": "date", "onError": None, "onNull": None}}


def _expired(expiry: Mapping[str, Any]) -> dict[str, Any]:
    instant = _clock(expiry["field"])
    cutoff = {"$subtract": ["$$NOW", expiry["seconds"] * 1000]}
    return {"$and": [{"$ne": [instant, None]}, {"$lt": [instant, cutoff]}]}


class MongoLifecycle:
    def __init__(self, lifecycle: Mapping[str, Any] | None = None, include_deleted: bool = False) -> None:
        """`include_deleted` keeps removed and expired rows in view; writes still keep to the lifecycle."""
        self._removal = (lifecycle or {}).get("removal")
        self._expiry = (lifecycle or {}).get("expiry")
        removal = [{self._removal: None}] if self._removal else []
        expiry = [{"$expr": {"$not": [_expired(self._expiry)]}}] if self._expiry else []
        self._conditions = () if include_deleted else (*removal, *expiry)

    def visible(self, criteria: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clauses = [dict(clause) for clause in (criteria, *self._conditions) if clause]
        return {"$and": clauses} if len(clauses) > 1 else next(iter(clauses), {})

    def pipeline(self, stages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [{"$match": self.visible()}, *stages] if self._conditions else list(stages)

    def stored(self, document: Mapping[str, Any]) -> dict[str, Any]:
        """`document` as written: its expiry timestamp as a BSON date."""
        return {**document, **self._dated(document)}

    def stored_update(self, update: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Any:
        """`update` as applied: setting the expiry timestamp as a BSON date."""
        if self._expiry is None:
            return update
        if not isinstance(update, Mapping):
            field = self._expiry["field"]
            return [*update, {"$set": {field: _clock(field)}}]
        return {**update, **{
            operator: {**changes, **self._dated(changes)}
            for operator, changes in update.items()
            if operator in _WRITE_OPERATORS
        }}

    def _dated(self, values: Mapping[str, Any]) -> dict[str, Any]:
        field = (self._expiry or {}).get("field")
        return {field: _instant(values[field])} if field in values else {}

    def removal(self) -> dict[str, Any] | None:
        """The update a delete applies in place of erasing rows, when soft deletion is on."""
        return {"$set": {self._removal: datetime.now(UTC).isoformat()}} if self._removal else None

    async def remove(self, collection: Any, criteria: Mapping[str, Any]) -> dict[str, Any] | None:
        removal = self.removal()
        if removal is None:
            return await collection.find_one_and_delete(self.visible(criteria))
        return await collection.find_one_and_update(self.visible(criteria), removal, return_document=ReturnDocument.AFTER)

    async def expire(self, collection: Any) -> None:
        """Keeps the TTL index that erases expired rows in step with the configured expiry."""
        if self._expiry is None:
            return
        field, seconds = self._expiry["field"], self._expiry["seconds"]
        index = (await collection.index_information()).get(EXPIRY_INDEX)
        if index is not None and index["key"] != [(field, 1)]:
            await collection.drop_index(EXPIRY_INDEX)
            index = None
        if index is None:
            await collection.create_index(field, name=EXPIRY_INDEX, expireAfterSeconds=seconds)
        elif index.get("expireAfterSeconds") != seconds:
            await collection.database.command(
                "collMod", collection.name, index={"name": EXPIRY_INDEX, "expireAfterSeconds": seconds}
            )

    def scoped(self, query: Mapping[str, Any]) -> dict[str, Any]:
        """A declared operation's `query` confined to visible rows, writing as `stored` does."""
        return self._confined(query["command"], query)

    def _confined(self, command: str, spec: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **spec,
            **({"filter": self.visible(spec.get("filter"))} if command in _FILTERED else {}),
            **({"pipeline": self.pipeline(spec.get("pipeline") or [])} if command == "aggregate" else {}),
            **({"document": self.stored(spec["document"])} if "document" in spec else {}),
            **({"documents": [*map(self.stored, spec["documents"])]} if "documents" in spec else {}),
            **({"replacement": self.stored(spec["replacement"])} if "replacement" in spec else {}),
            **({"update": self.stored_update(spec["update"])} if "update" in spec else {}),
            **({"removal": self.removal()} if command in _DELETES and self._removal else {}),
            **({"requests": [
                {kind: self._confined(kind, request_spec) for kind, request_spec in request.items()}
                for request in spec["requests"]
            ]} if "requests" in spec else {}),
        }


def scoped(query: Mapping[str, Any], lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    """`query` scoped to the lifecycle it carries, a target collection's, or else to `lifecycle`."""
    scope = MongoLifecycle(query.get("lifecycle", lifecycle), query.get("includeDeleted", False))
    return scope.scoped(query)
