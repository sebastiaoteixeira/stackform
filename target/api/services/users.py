from api.repositories.users import UsersRepository
from api.services.exceptions import NotFoundError, ValidationError


class UsersService:
    def __init__(self, repo: UsersRepository):
        self._repo = repo

    def list(self) -> list[dict]:
        return self._repo.list()

    def get(self, resource_id: str) -> dict:
        document = self._repo.get(resource_id)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document

    def create(self, data: dict) -> dict:
        return self._repo.create(data)

    def update(self, resource_id: str, data: dict) -> dict:
        document = self._repo.update(resource_id, data)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document

    def replace(self, resource_id: str, data: dict) -> dict:
        document = self._repo.replace(resource_id, data)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document

    def delete(self, resource_id: str) -> dict:
        document = self._repo.delete(resource_id)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document
