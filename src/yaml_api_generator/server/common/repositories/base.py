import operator
from abc import ABC, abstractmethod
from typing import Any

from ..pagination import Page, Primitives, expand_bound


_BOUND_COMPARATORS = {
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


def _matches_bound(document: dict[str, Any], bound) -> bool:
    def compare(key) -> bool:
        value = document.get(key.field)
        return (
            value is not None
            and key.value is not None
            and _BOUND_COMPARATORS[key.op](value, key.value)
        )

    return any(
        all(document.get(field) == value for field, value in equalities)
        and compare(key)
        for equalities, key in expand_bound(bound)
    )


class ConflictError(Exception):
    def __init__(self, field: str | None = None) -> None:
        self.field = field
        message = (
            f"Duplicate value violates unique constraint on field '{field}'"
            if field
            else "Duplicate value violates a unique constraint"
        )
        super().__init__(message)


class BaseRepository(ABC):
    def register_id_field(self, collection_name: str, id_field: str) -> None:
        pass

    async def run_operation(
        self,
        collection_name: str,
        query: dict[str, Any],
        bindings: dict[str, Any],
    ) -> Any:
        """Execute a declarative custom operation. Overridden per backend."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support custom operations"
        )

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def paginate(
        self,
        collection_name: str,
        primitives: Primitives,
    ) -> Page:
        documents = await self.list(collection_name)
        total = len(documents) if primitives.count == "exact" else None
        rows = [
            document
            for document in documents
            if all(_matches_bound(document, bound) for bound in primitives.bounds)
        ]
        for key in reversed(primitives.sort):
            rows.sort(
                key=lambda document: (
                    document.get(key.field) is None,
                    document.get(key.field),
                ),
                reverse=key.descending,
            )
        if primitives.skip:
            rows = rows[primitives.skip:]
        if primitives.limit is not None:
            rows = rows[:primitives.limit]
        return Page(rows, total)

    @abstractmethod
    async def get(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def find_one(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def update_by(
        self,
        collection_name: str,
        criteria: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def replace_by(
        self,
        collection_name: str,
        criteria: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def delete_by(
        self, collection_name: str, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def create(
        self, collection_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def upsert_by(
        self, collection_name: str, key_field: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Create-or-update a record keyed by a unique field.

        Backends with a native atomic upsert override this; the fallback resolves
        the existing record through the standard list/update/create operations.
        """
        if payload.get(key_field) is None:
            raise ValueError(f"upsert_by requires a non-null value for key field '{key_field}'")
        existing = next(
            (
                d
                for d in await self.list(collection_name)
                if str(d.get(key_field)) == str(payload.get(key_field))
            ),
            None,
        )
        if existing is None:
            return await self.create(collection_name, payload)
        document_id = existing.get(self._id_field(collection_name))
        updated = await self.update(collection_name, str(document_id), payload)
        return updated if updated is not None else {**existing, **payload}

    def _id_field(self, collection_name: str) -> str:
        return "id"

    @abstractmethod
    async def update(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def replace(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def delete(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError
