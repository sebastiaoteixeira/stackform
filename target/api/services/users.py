from api.repositories.users import UsersRepository
from api.services.exceptions import NotFoundError, ValidationError
from api.authentication.auth import hash_password


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
        self._validate_identity_fields(data)
        self._process_password(data)
        return self._repo.create(data)

    def update(self, resource_id: str, data: dict) -> dict:
        self._process_password(data)
        document = self._repo.update(resource_id, data)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document

    def replace(self, resource_id: str, data: dict) -> dict:
        self._process_password(data)
        document = self._repo.replace(resource_id, data)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document

    def delete(self, resource_id: str) -> dict:
        document = self._repo.delete(resource_id)
        if document is None:
            raise NotFoundError("users", resource_id)
        return document

    @staticmethod
    def _process_password(data: dict) -> None:
        raw_password = data.pop("password", None)
        if raw_password is not None:
            if not isinstance(raw_password, str) or not raw_password.strip():
                raise ValidationError("password", "Password must be a non-empty string")
            data["passwordHash"] = hash_password(raw_password)

    @staticmethod
    def _validate_identity_fields(data: dict) -> None:
        if not isinstance(data.get("email"), str) or not data.get("email", "").strip():
            raise ValidationError("email", "Missing required field: email")
        if not isinstance(data.get("password"), str) or not data.get("password", "").strip():
            raise ValidationError("password", "Missing required field: password")
