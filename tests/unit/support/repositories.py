from collections.abc import Callable
from typing import Any

from yaml_api_generator.runtime.access import EVERY_ROW, Predicate
from yaml_api_generator.server.common.repositories.base import BaseRepository

Document = dict[str, Any]


class InMemoryRepository(BaseRepository):
    def __init__(self, data: dict[str, list[Document]] | None = None) -> None:
        self._data = {name: [dict(doc) for doc in docs] for name, docs in (data or {}).items()}
        self._id_fields: dict[str, str] = {}

    def register_id_field(self, collection_name: str, id_field: str) -> None:
        self._id_fields[collection_name] = id_field

    def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def documents(self, collection_name: str) -> list[Document]:
        return self._data.setdefault(collection_name, [])

    async def list(
        self, collection_name: str, predicate: Predicate = EVERY_ROW
    ) -> list[Document]:
        return [dict(doc) for doc in self.documents(collection_name) if predicate.matches(doc)]

    async def get(self, collection_name: str, document_id: str) -> Document | None:
        index = self._index_of(collection_name, document_id)
        return None if index is None else dict(self.documents(collection_name)[index])

    async def find_one(self, collection_name: str, criteria: Document) -> Document | None:
        matches = (
            dict(doc)
            for doc in self.documents(collection_name)
            if all(doc.get(field) == value for field, value in criteria.items())
        )
        return next(matches, None)

    async def update_by(
        self, collection_name: str, criteria: Document, payload: Document
    ) -> Document | None:
        changes = {field: value for field, value in payload.items() if field not in criteria}
        return self._transform_by(
            collection_name, criteria, lambda document: {**document, **changes}
        )

    async def replace_by(
        self, collection_name: str, criteria: Document, payload: Document
    ) -> Document | None:
        return self._transform_by(
            collection_name,
            criteria,
            lambda _: {**payload, **criteria},
        )

    async def delete_by(
        self, collection_name: str, criteria: Document
    ) -> Document | None:
        index = self._index_matching(collection_name, criteria)
        if index is None:
            return None
        return dict(self.documents(collection_name).pop(index))

    async def create(self, collection_name: str, payload: Document) -> Document:
        self.documents(collection_name).append(dict(payload))
        return dict(payload)

    async def update(
        self, collection_name: str, document_id: str, payload: Document
    ) -> Document | None:
        return self._transform(collection_name, document_id, lambda doc: {**doc, **payload})

    async def replace(
        self, collection_name: str, document_id: str, payload: Document
    ) -> Document | None:
        return self._transform(collection_name, document_id, lambda _: dict(payload))

    async def delete(self, collection_name: str, document_id: str) -> Document | None:
        docs = self.documents(collection_name)
        index = self._index_of(collection_name, document_id)
        return None if index is None else docs.pop(index)

    def _index_of(self, collection_name: str, document_id: str) -> int | None:
        id_field = self._id_fields.get(collection_name, "id")
        positions = (
            index
            for index, doc in enumerate(self.documents(collection_name))
            if str(doc.get(id_field)) == document_id
        )
        return next(positions, None)

    def _index_matching(
        self, collection_name: str, criteria: Document
    ) -> int | None:
        positions = (
            index
            for index, document in enumerate(self.documents(collection_name))
            if all(document.get(field) == value for field, value in criteria.items())
        )
        return next(positions, None)

    def _transform_by(
        self,
        collection_name: str,
        criteria: Document,
        transform: Callable[[Document], Document],
    ) -> Document | None:
        documents = self.documents(collection_name)
        index = self._index_matching(collection_name, criteria)
        if index is None:
            return None
        documents[index] = transform(documents[index])
        return dict(documents[index])

    def _transform(
        self,
        collection_name: str,
        document_id: str,
        transform: Callable[[Document], Document],
    ) -> Document | None:
        docs = self.documents(collection_name)
        index = self._index_of(collection_name, document_id)
        if index is None:
            return None
        docs[index] = transform(docs[index])
        return dict(docs[index])
