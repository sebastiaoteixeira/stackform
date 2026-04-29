import uuid
from typing import Any

import pytest

from yaml_api_generator.runtime.context import RequestContext
from yaml_api_generator.runtime.repositories.base import BaseRepository
from yaml_api_generator.runtime.steps import NotFoundError
from yaml_api_generator.runtime.steps.repositories import (
    RepositoryCreateStep,
    RepositoryDeleteStep,
    RepositoryGetStep,
    RepositoryListStep,
    RepositoryReplaceStep,
    RepositoryUpdateStep,
    _generate_id,
    _inject_canonical_id,
    _prepare_payload,
)


class InMemoryRepository(BaseRepository):
    def __init__(self):
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._id_fields: dict[str, str] = {}

    def register_id_field(self, collection_name: str, id_field: str) -> None:
        self._id_fields[collection_name] = id_field

    def connect(self):
        pass

    def close(self):
        pass

    def _collection(self, name: str) -> dict[str, dict[str, Any]]:
        if name not in self._data:
            self._data[name] = {}
        return self._data[name]

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        return list(self._collection(collection_name).values())

    async def get(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        id_field = self._id_fields.get(collection_name, "id")
        for doc in self._collection(collection_name).values():
            if str(doc.get(id_field, "")) == document_id:
                return dict(doc)
        return None

    async def create(
        self, collection_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        id_field = self._id_fields.get(collection_name, "id")
        doc_id = payload.get(id_field)
        self._collection(collection_name)[str(doc_id)] = dict(payload)
        return dict(payload)

    async def update(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        id_field = self._id_fields.get(collection_name, "id")
        col = self._collection(collection_name)
        for key, doc in col.items():
            if str(doc.get(id_field, "")) == document_id:
                merged = {**doc, **payload}
                col[key] = merged
                return dict(merged)
        return None

    async def replace(
        self,
        collection_name: str,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        id_field = self._id_fields.get(collection_name, "id")
        col = self._collection(collection_name)
        for key, doc in col.items():
            if str(doc.get(id_field, "")) == document_id:
                col[key] = dict(payload)
                return dict(payload)
        return None

    async def delete(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        id_field = self._id_fields.get(collection_name, "id")
        col = self._collection(collection_name)
        for key, doc in list(col.items()):
            if str(doc.get(id_field, "")) == document_id:
                removed = col.pop(key)
                return dict(removed)
        return None


def _make_ctx(**overrides) -> RequestContext:
    defaults = dict(
        method="POST",
        path="/items",
        api_version=None,
        collection="items",
        operation="create",
        headers={},
        url_params={},
        repository=None,
        principal=None,
        body=None,
        response=None,
    )
    defaults.update(overrides)
    return RequestContext(**defaults)


# --- ID Generation (241-243) ---


def test_generate_id_uuidv7():
    result = _generate_id("uuidv7")
    parsed = uuid.UUID(result)
    assert parsed.version == 7


def test_generate_id_uuidv4():
    result = _generate_id("uuidv4")
    parsed = uuid.UUID(result)
    assert parsed.version == 4


def test_generate_id_unknown_format_raises():
    with pytest.raises(ValueError, match="Unsupported id format"):
        _generate_id("uuidv3")


# --- Payload Preparation (244-249) ---


def test_prepare_payload_password_via_false():
    payload = {"title": "hello", "password": "secret"}
    result = _prepare_payload(payload, password_via=False)
    assert result == {"title": "hello", "password": "secret"}


def test_prepare_payload_password_via_true_no_password_key():
    payload = {"title": "hello"}
    result = _prepare_payload(payload, password_via=True)
    assert result == {"title": "hello"}


def test_prepare_payload_password_via_true_valid_password():
    payload = {"title": "hello", "password": "secret123"}
    result = _prepare_payload(payload, password_via=True)
    assert "password" not in result
    assert "_auth" in result
    assert "passwordHash" in result["_auth"]
    assert result["_auth"]["passwordHash"].startswith("pbkdf2$sha256$")


def test_prepare_payload_password_via_true_empty_password():
    with pytest.raises(ValueError, match="non-empty string"):
        _prepare_payload({"password": ""}, password_via=True)


def test_prepare_payload_password_via_true_non_string_password():
    with pytest.raises(ValueError, match="non-empty string"):
        _prepare_payload({"password": 123}, password_via=True)


def test_prepare_payload_existing_auth_dict_merged():
    payload = {"_auth": {"apiKey": "abc123"}, "password": "secret"}
    result = _prepare_payload(payload, password_via=True)
    assert "apiKey" in result["_auth"]
    assert "passwordHash" in result["_auth"]


# --- Canonical ID Normalization (250-253) ---


def test_inject_canonical_id_from_mongo_id():
    doc = {"_id": "abc123", "name": "test"}
    result = _inject_canonical_id(doc, "id")
    assert result["id"] == "abc123"
    assert "_id" not in result


def test_inject_canonical_id_removes_mongo_id_when_different():
    doc = {"_id": "abc123", "id": "real-id", "name": "test"}
    result = _inject_canonical_id(doc, "id")
    assert result["id"] == "real-id"
    assert "_id" not in result


def test_inject_canonical_id_strips_auth_and_password():
    doc = {
        "id": "1",
        "_auth": {"passwordHash": "x"},
        "password": "secret",
        "name": "test",
    }
    result = _inject_canonical_id(doc, "id")
    assert "_auth" not in result
    assert "password" not in result
    assert result["name"] == "test"


def test_inject_canonical_id_none_returns_none():
    assert _inject_canonical_id(None, "id") is None


# --- CRUD Steps (254-265) ---


@pytest.mark.asyncio
async def test_repository_list_step():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {
        "1": {"id": "1", "title": "a"},
        "2": {"id": "2", "title": "b"},
    }
    ctx = _make_ctx(repository=repo, operation="list", method="GET")
    step = RepositoryListStep("items", "id")
    result = await step(ctx)
    assert len(result.response) == 2
    assert all("_id" not in d for d in result.response)


@pytest.mark.asyncio
async def test_repository_get_step():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {"abc": {"id": "abc", "title": "found"}}
    ctx = _make_ctx(
        repository=repo, operation="get", method="GET", url_params={"id": "abc"}
    )
    step = RepositoryGetStep("items", "id")
    result = await step(ctx)
    assert result.response["title"] == "found"


@pytest.mark.asyncio
async def test_repository_get_step_not_found():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    ctx = _make_ctx(
        repository=repo, operation="get", method="GET", url_params={"id": "missing"}
    )
    step = RepositoryGetStep("items", "id")
    with pytest.raises(NotFoundError):
        await step(ctx)


@pytest.mark.asyncio
async def test_repository_create_step_generates_id():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    ctx = _make_ctx(repository=repo, body={"title": "new"})
    step = RepositoryCreateStep("items", "id", "uuidv4", False)
    result = await step(ctx)
    assert result.response["id"] is not None
    assert uuid.UUID(result.response["id"]).version == 4


@pytest.mark.asyncio
async def test_repository_create_step_natural_pk_no_id_generated():
    repo = InMemoryRepository()
    repo.register_id_field("countries", "code")
    ctx = _make_ctx(
        repository=repo,
        collection="countries",
        body={"code": "US", "name": "United States"},
    )
    step = RepositoryCreateStep("countries", "code", "natural", False)
    result = await step(ctx)
    assert result.response["code"] == "US"
    assert "id" not in result.response or result.response.get("id") is None


@pytest.mark.asyncio
async def test_repository_update_step():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {"abc": {"id": "abc", "title": "old"}}
    ctx = _make_ctx(
        repository=repo,
        operation="update",
        method="PATCH",
        url_params={"id": "abc"},
        body={"title": "new"},
    )
    step = RepositoryUpdateStep("items", "id", False)
    result = await step(ctx)
    assert result.response["title"] == "new"


@pytest.mark.asyncio
async def test_repository_update_step_not_found():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    ctx = _make_ctx(
        repository=repo,
        operation="update",
        method="PATCH",
        url_params={"id": "missing"},
        body={"title": "x"},
    )
    step = RepositoryUpdateStep("items", "id", False)
    with pytest.raises(NotFoundError):
        await step(ctx)


@pytest.mark.asyncio
async def test_repository_replace_step():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {"abc": {"id": "abc", "title": "old", "extra": "gone"}}
    ctx = _make_ctx(
        repository=repo,
        operation="replace",
        method="PUT",
        url_params={"id": "abc"},
        body={"id": "abc", "title": "replaced"},
    )
    step = RepositoryReplaceStep("items", "id", False)
    result = await step(ctx)
    assert result.response["title"] == "replaced"


@pytest.mark.asyncio
async def test_repository_delete_step():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    repo._data["items"] = {"abc": {"id": "abc", "title": "gone"}}
    ctx = _make_ctx(
        repository=repo, operation="delete", method="DELETE", url_params={"id": "abc"}
    )
    step = RepositoryDeleteStep("items", "id")
    result = await step(ctx)
    assert result.response["id"] == "abc"


@pytest.mark.asyncio
async def test_repository_delete_step_not_found():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    ctx = _make_ctx(
        repository=repo,
        operation="delete",
        method="DELETE",
        url_params={"id": "missing"},
    )
    step = RepositoryDeleteStep("items", "id")
    with pytest.raises(NotFoundError):
        await step(ctx)


@pytest.mark.asyncio
async def test_repository_step_missing_id_url_param():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    ctx = _make_ctx(repository=repo, operation="get", method="GET", url_params={})
    step = RepositoryGetStep("items", "id")
    with pytest.raises(ValueError, match="Missing route parameter"):
        await step(ctx)


@pytest.mark.asyncio
async def test_repository_step_non_dict_body():
    repo = InMemoryRepository()
    repo.register_id_field("items", "id")
    ctx = _make_ctx(repository=repo, body="not a dict")
    step = RepositoryCreateStep("items", "id", "uuidv4", False)
    with pytest.raises(ValueError, match="Request body must be a JSON object"):
        await step(ctx)
