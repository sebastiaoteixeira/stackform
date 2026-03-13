import uuid
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.database import Database

_SENSITIVE_FIELDS = {"password", "passwordHash"}


def _generate_id(id_format: str) -> str:
    if id_format == "uuidv7":
        return str(uuid.uuid7())
    return str(uuid.uuid4())


def _match_filter(document_id: str) -> dict[str, Any]:
    candidates: list[Any] = [document_id]
    try:
        candidates.append(ObjectId(document_id))
    except InvalidId:
        pass
    return {"$or": [{"_id": v} for v in candidates] + [{"id": document_id}]}


class PostsRepository:
    COLLECTION = "posts"
    ID_FIELD = "id"

    def __init__(self, db: Database) -> None:
        self._col = db[self.COLLECTION]

    def _normalize(self, doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if doc is None:
            return None
        result = dict(doc)
        if self.ID_FIELD not in result and result.get("_id") is not None:
            result[self.ID_FIELD] = str(result["_id"])
        if self.ID_FIELD != "_id":
            result.pop("_id", None)
        for key in _SENSITIVE_FIELDS:
            result.pop(key, None)
        return result

    def list(self) -> list[dict[str, Any]]:
        docs = list(self._col.find({}))
        return [self._normalize(d) for d in docs]

    def get(self, document_id: str) -> dict[str, Any] | None:
        doc = self._col.find_one(_match_filter(document_id))
        return self._normalize(doc)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        data[self.ID_FIELD] = _generate_id("uuidv7")
        self._col.insert_one(data)
        return self._normalize(data)

    def update(
        self, document_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        doc = self._col.find_one_and_update(
            _match_filter(document_id),
            {"$set": data},
            return_document=ReturnDocument.AFTER,
        )
        return self._normalize(doc)

    def replace(
        self, document_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        doc = self._col.find_one_and_replace(
            _match_filter(document_id),
            data,
            return_document=ReturnDocument.AFTER,
        )
        return self._normalize(doc)

    def delete(self, document_id: str) -> dict[str, Any] | None:
        doc = self._col.find_one_and_delete(_match_filter(document_id))
        return self._normalize(doc)
