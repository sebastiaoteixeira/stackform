from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import BulkWriteError, DuplicateKeyError

from yaml_api_generator.runtime.mongo_operations import run_mongo
from .base import BaseRepository, ConflictError
from ..pagination import Page, Primitives, expand_bound


_MONGO_COMPARATORS = {"gt": "$gt", "gte": "$gte", "lt": "$lt", "lte": "$lte"}


def _mongo_bounds(bounds) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    for bound in bounds:
        disjuncts: list[dict[str, Any]] = []
        for equalities, key in expand_bound(bound):
            term: dict[str, Any] = {field: value for field, value in equalities}
            term[key.field] = {_MONGO_COMPARATORS[key.op]: key.value}
            disjuncts.append(term)
        clauses.append(disjuncts[0] if len(disjuncts) == 1 else {"$or": disjuncts})
    return clauses


@contextmanager
def _as_conflict() -> Iterator[None]:
    try:
        yield
    except (BulkWriteError, DuplicateKeyError) as error:
        details = _duplicate_details(error)
        if details is None:
            raise
        raise ConflictError(_conflict_field(details)) from error


def _duplicate_details(
    error: BulkWriteError | DuplicateKeyError,
) -> dict[str, Any] | None:
    details = error.details or {}
    if isinstance(error, DuplicateKeyError):
        return details
    return next(
        (
            write_error
            for write_error in details.get("writeErrors", [])
            if write_error.get("code") == 11000
        ),
        None,
    )


def _conflict_field(details: dict[str, Any]) -> str | None:
    for key in ("keyPattern", "keyValue"):
        fields = details.get(key)
        if fields:
            return next(iter(fields))
    return None


_NON_NULL_BSON_TYPES = [
    "double",
    "string",
    "object",
    "array",
    "binData",
    "objectId",
    "bool",
    "date",
    "regex",
    "javascript",
    "int",
    "timestamp",
    "long",
    "decimal",
    "minKey",
    "maxKey",
]


def unique_index_partial_filter(field_name: str) -> dict[str, Any]:
    return {field_name: {"$type": _NON_NULL_BSON_TYPES}}


@dataclass(frozen=True)
class MongoRepositoryConfig:
    uri: str
    database: str


class MongoRepository(BaseRepository):
    def __init__(self, config: MongoRepositoryConfig, manage_indexes: bool = True):
        self._config = config
        self._client: Any | None = None
        self._db: Any | None = None
        self._id_fields: dict[str, str] = {}
        self.manage_indexes = manage_indexes

    def register_id_field(self, collection_name: str, id_field: str) -> None:
        self._id_fields[collection_name] = id_field

    def connect(self) -> None:
        self._client = AsyncMongoClient(self._config.uri)
        if self._client is None:
            raise RuntimeError("Failed to initialize Mongo client")
        self._db = self._client[self._config.database]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._db = None

    def collection(self, name: str) -> Any:
        if self._db is None:
            raise RuntimeError("MongoRepository is not connected")
        return self._db[name]

    async def create_unique_index(self, collection_name: str, field_name: str) -> None:
        await self.collection(collection_name).create_index(
            field_name,
            unique=True,
            partialFilterExpression=unique_index_partial_filter(field_name),
        )

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        cursor = self.collection(collection_name).find({})
        documents = await cursor.to_list(length=None)
        return [self._normalize_document_required(document) for document in documents]

    async def paginate(self, collection_name: str, primitives: Primitives) -> Page:
        target = self.collection(collection_name)
        bound_clauses = _mongo_bounds(primitives.bounds)
        query = {"$and": bound_clauses} if bound_clauses else {}
        cursor = target.find(query)
        if primitives.sort:
            cursor = cursor.sort(
                [(key.field, -1 if key.descending else 1) for key in primitives.sort]
            )
        if primitives.skip:
            cursor = cursor.skip(primitives.skip)
        if primitives.limit is not None:
            cursor = cursor.limit(primitives.limit)
        documents = await cursor.to_list(length=None)
        rows = [self._normalize_document_required(d) for d in documents]
        total = None
        if primitives.count == "exact":
            total = await target.count_documents({})
        return Page(rows=rows, total=total)

    async def get(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        document = await self.collection(collection_name).find_one(
            self._match_filter(document_id, collection_name)
        )
        return self._normalize_document(document)

    async def find_one(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        document = await self.collection(collection_name).find_one(dict(criteria))
        return self._normalize_document(document)

    async def update_by(
        self,
        collection_name: str,
        criteria: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        changes = {field: value for field, value in payload.items() if field not in criteria}
        if not changes:
            return await self.find_one(collection_name, criteria)
        with _as_conflict():
            document = await self.collection(collection_name).find_one_and_update(
                dict(criteria), {"$set": changes}, return_document=ReturnDocument.AFTER
            )
        return self._normalize_document(document)

    async def replace_by(
        self,
        collection_name: str,
        criteria: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        replacement = {**payload, **criteria}
        with _as_conflict():
            document = await self.collection(collection_name).find_one_and_replace(
                dict(criteria), replacement, return_document=ReturnDocument.AFTER
            )
        return self._normalize_document(document)

    async def delete_by(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        document = await self.collection(collection_name).find_one_and_delete(
            dict(criteria)
        )
        return self._normalize_document(document)

    async def create(
        self, collection_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with _as_conflict():
            inserted = await self.collection(collection_name).insert_one(payload)
        created = dict(payload)
        created.setdefault("_id", str(inserted.inserted_id))
        return self._normalize_document_required(created)

    async def upsert_by(
        self, collection_name: str, key_field: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload.get(key_field) is None:
            raise ValueError(f"upsert_by requires a non-null value for key field '{key_field}'")
        id_field = self._id_fields.get(collection_name, "id")
        on_insert = {id_field: payload[id_field]} if id_field in payload else {}
        update_fields = {k: v for k, v in payload.items() if k != id_field}
        with _as_conflict():
            document = await self.collection(collection_name).find_one_and_update(
                {key_field: payload.get(key_field)},
                {"$set": update_fields, "$setOnInsert": on_insert},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        return self._normalize_document_required(document)

    async def update(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        with _as_conflict():
            document = await self.collection(collection_name).find_one_and_update(
                self._match_filter(document_id, collection_name),
                {"$set": payload},
                return_document=ReturnDocument.AFTER,
            )
        return self._normalize_document(document)

    async def replace(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        payload[self._id_fields.get(collection_name, "id")] = document_id
        with _as_conflict():
            document = await self.collection(collection_name).find_one_and_replace(
                self._match_filter(document_id, collection_name),
                payload,
                return_document=ReturnDocument.AFTER,
            )
        return self._normalize_document(document)

    async def delete(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        document = await self.collection(collection_name).find_one_and_delete(
            self._match_filter(document_id, collection_name)
        )
        return self._normalize_document(document)

    async def run_operation(self, collection_name: str, query: dict[str, Any]) -> Any:
        with _as_conflict():
            return await run_mongo(self.collection(collection_name), query)

    @staticmethod
    def _normalize_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
        if document is None:
            return None
        normalized = dict(document)
        if "_id" in normalized:
            normalized["_id"] = str(normalized["_id"])
        return normalized

    @classmethod
    def _normalize_document_required(cls, document: dict[str, Any]) -> dict[str, Any]:
        normalized = cls._normalize_document(document)
        if normalized is None:
            raise RuntimeError("Expected document")
        return normalized

    def _match_filter(self, document_id: str, collection_name: str | None = None) -> dict[str, Any]:
        id_field = self._id_fields.get(collection_name, "id") if collection_name else "id"
        candidates: list[Any] = [document_id]
        try:
            candidates.append(ObjectId(document_id))
        except InvalidId:
            pass
        conditions = [{"_id": value} for value in candidates]
        conditions.append({id_field: document_id})
        return {"$or": conditions}
