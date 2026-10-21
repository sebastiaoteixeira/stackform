"""Run a resolved MongoDB operation query against an async pymongo collection.

``bulkWrite`` requests use the shell form, e.g.
``{"updateOne": {"filter": ..., "update": ..., "upsert": true}}``.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from pymongo import DeleteMany, DeleteOne, InsertOne, ReplaceOne, ReturnDocument, UpdateMany, UpdateOne

Command = Callable[[Any, dict[str, Any]], Awaitable[Any]]

_COMMANDS: dict[str, Command] = {}

_BULK_REQUESTS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "insertOne": lambda spec: InsertOne(spec["document"]),
    "updateOne": lambda spec: UpdateOne(spec["filter"], spec["update"], upsert=spec.get("upsert", False)),
    "updateMany": lambda spec: UpdateMany(spec["filter"], spec["update"], upsert=spec.get("upsert", False)),
    "replaceOne": lambda spec: ReplaceOne(spec["filter"], spec["replacement"], upsert=spec.get("upsert", False)),
    "deleteOne": lambda spec: DeleteOne(spec["filter"]),
    "deleteMany": lambda spec: DeleteMany(spec["filter"]),
}


async def run_mongo(collection: Any, query: dict[str, Any]) -> Any:
    target = collection.database[query["collection"]] if query.get("collection") else collection
    return await _COMMANDS[query["command"]](target, query)


def _command(*names: str) -> Callable[[Command], Command]:
    def register(run: Command) -> Command:
        _COMMANDS.update(dict.fromkeys(names, run))
        return run

    return register


def _stringified(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None or "_id" not in document:
        return document
    return {**document, "_id": str(document["_id"])}


def _filter(query: dict[str, Any]) -> dict[str, Any]:
    return query.get("filter") or {}


@_command("find")
async def _find(target: Any, query: dict[str, Any]) -> list[dict[str, Any]]:
    return [_stringified(document) async for document in target.find(_filter(query))]


@_command("findOne")
async def _find_one(target: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    return _stringified(await target.find_one(_filter(query)))


@_command("aggregate")
async def _aggregate(target: Any, query: dict[str, Any]) -> list[dict[str, Any]]:
    cursor = await target.aggregate(query.get("pipeline") or [])
    return [_stringified(document) async for document in cursor]


@_command("countDocuments")
async def _count_documents(target: Any, query: dict[str, Any]) -> int:
    return await target.count_documents(_filter(query))


@_command("estimatedDocumentCount")
async def _estimated_document_count(target: Any, query: dict[str, Any]) -> int:
    return await target.estimated_document_count()


@_command("distinct")
async def _distinct(target: Any, query: dict[str, Any]) -> list[Any]:
    return await target.distinct(query.get("key"), _filter(query))


@_command("insertOne")
async def _insert_one(target: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    document = dict(query.get("document") or {})
    await target.insert_one(document)
    return _stringified(document)


@_command("insertMany")
async def _insert_many(target: Any, query: dict[str, Any]) -> list[dict[str, Any] | None]:
    documents = [dict(document) for document in query.get("documents") or []]
    await target.insert_many(documents)
    return [_stringified(document) for document in documents]


@_command("updateOne", "findOneAndUpdate")
async def _update_one(target: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    return _stringified(await target.find_one_and_update(
        _filter(query), query.get("update") or {}, return_document=ReturnDocument.AFTER
    ))


@_command("replaceOne", "findOneAndReplace")
async def _replace_one(target: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    return _stringified(await target.find_one_and_replace(
        _filter(query), query.get("replacement") or {}, return_document=ReturnDocument.AFTER
    ))


@_command("deleteOne", "findOneAndDelete")
async def _delete_one(target: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    return _stringified(await target.find_one_and_delete(_filter(query)))


@_command("updateMany")
async def _update_many(target: Any, query: dict[str, Any]) -> dict[str, int]:
    result = await target.update_many(_filter(query), query.get("update") or {})
    return {"matched": result.matched_count, "modified": result.modified_count}


@_command("deleteMany")
async def _delete_many(target: Any, query: dict[str, Any]) -> dict[str, int]:
    result = await target.delete_many(_filter(query))
    return {"deleted": result.deleted_count}


@_command("bulkWrite")
async def _bulk_write(target: Any, query: dict[str, Any]) -> dict[str, int]:
    result = await target.bulk_write([
        _BULK_REQUESTS[kind](spec)
        for request in query["requests"]
        for kind, spec in request.items()
    ])
    return {
        "inserted": result.inserted_count,
        "matched": result.matched_count,
        "modified": result.modified_count,
        "deleted": result.deleted_count,
        "upserted": result.upserted_count,
    }
