from abc import ABC, abstractmethod
from typing import Any


class BaseRepository(ABC):
    def register_id_field(self, collection_name: str, id_field: str) -> None:
        pass

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def create(
        self, collection_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

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
