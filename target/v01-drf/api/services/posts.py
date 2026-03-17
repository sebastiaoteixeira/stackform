from api.repositories.posts import PostsRepository
from api.services.exceptions import NotFoundError, ValidationError


class PostsService:
    def __init__(self, repo: PostsRepository):
        self._repo = repo

    def list(self) -> list[dict]:
        return self._repo.list()

    def get(self, resource_id: str) -> dict:
        document = self._repo.get(resource_id)
        if document is None:
            raise NotFoundError("posts", resource_id)
        return document

    def create(self, data: dict) -> dict:
        return self._repo.create(data)

    def update(self, resource_id: str, data: dict) -> dict:
        document = self._repo.update(resource_id, data)
        if document is None:
            raise NotFoundError("posts", resource_id)
        return document

    def replace(self, resource_id: str, data: dict) -> dict:
        document = self._repo.replace(resource_id, data)
        if document is None:
            raise NotFoundError("posts", resource_id)
        return document

    def delete(self, resource_id: str) -> dict:
        document = self._repo.delete(resource_id)
        if document is None:
            raise NotFoundError("posts", resource_id)
        return document
