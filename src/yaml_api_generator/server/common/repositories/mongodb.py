from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import AsyncMongoClient, ReturnDocument

from .base import BaseRepository
from .bindings import resolve


@dataclass(frozen=True)
class MongoRepositoryConfig:
    uri: str
    database: str


class MongoRepository(BaseRepository):
    def __init__(self, config: MongoRepositoryConfig):
        self._config = config
        self._client: Any | None = None
        self._db: Any | None = None
        self._id_fields: dict[str, str] = {}

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

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        cursor = self.collection(collection_name).find({})
        documents = await cursor.to_list(length=None)
        return [self._normalize_document_required(document) for document in documents]

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

    async def create(
        self, collection_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        inserted = await self.collection(collection_name).insert_one(payload)
        created = dict(payload)
        created.setdefault("_id", str(inserted.inserted_id))
        return self._normalize_document_required(created)

    async def update(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
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

    async def run_operation(
        self,
        collection_name: str,
        query: dict[str, Any],
        bindings: dict[str, Any],
    ) -> Any:
        command = query.get("command")
        target = self.collection(query.get("collection") or collection_name)
        get = lambda field: resolve(query.get(field), bindings)

        if command == "find":
            cursor = target.find(get("filter") or {})
            docs = await cursor.to_list(length=None)
            return [self._normalize_document_required(d) for d in docs]
        if command == "findOne":
            return self._normalize_document(await target.find_one(get("filter") or {}))
        if command == "aggregate":
            cursor = await target.aggregate(get("pipeline") or [])
            docs = await cursor.to_list(length=None)
            return [self._normalize_document_required(d) for d in docs]
        if command == "countDocuments":
            return await target.count_documents(get("filter") or {})
        if command == "estimatedDocumentCount":
            return await target.estimated_document_count()
        if command == "distinct":
            return await target.distinct(query.get("key"), get("filter") or {})
        if command == "insertOne":
            document = get("document") or {}
            await target.insert_one(document)
            return self._normalize_document_required(document)
        if command == "insertMany":
            documents = get("documents") or []
            await target.insert_many(documents)
            return [self._normalize_document_required(d) for d in documents]
        if command in ("updateOne", "findOneAndUpdate"):
            doc = await target.find_one_and_update(
                get("filter") or {}, get("update") or {}, return_document=ReturnDocument.AFTER
            )
            return self._normalize_document(doc)
        if command in ("replaceOne", "findOneAndReplace"):
            doc = await target.find_one_and_replace(
                get("filter") or {}, get("replacement") or {}, return_document=ReturnDocument.AFTER
            )
            return self._normalize_document(doc)
        if command in ("deleteOne", "findOneAndDelete"):
            return self._normalize_document(await target.find_one_and_delete(get("filter") or {}))
        if command == "updateMany":
            result = await target.update_many(get("filter") or {}, get("update") or {})
            return {"matched": result.matched_count, "modified": result.modified_count}
        if command == "deleteMany":
            result = await target.delete_many(get("filter") or {})
            return {"deleted": result.deleted_count}

        raise ValueError(f"Unsupported query command: {command}")

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
