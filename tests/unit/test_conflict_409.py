"""Unique-violation handling: repositories raise ConflictError, maps answer 409.

The relational path runs against in-memory SQLite via aiosqlite; the Mongo path
drives a fake collection that raises DuplicateKeyError like the real driver. Both
HTTP maps (raw ASGI and FastAPI) translate ConflictError into a 409 whose body
names the offending field.
"""

import json
import textwrap
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.server import build_app, build_raw_app
from yaml_api_generator.server.common.repositories import ConflictError
from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
)
from yaml_api_generator.server.common.repositories.sql import SQLRepository


def _collection() -> IRCollection:
    return IRCollection(
        name="members",
        entity_name="member",
        type="base",
        idField="id",
        idFormat="uuidv4",
        fields={
            "id": {"type": "id"},
            "email": {"type": "string", "required": True, "unique": True},
        },
        datastore="warehouse",
    )


@pytest.fixture
async def repo():
    repository = SQLRepository("sqlite+aiosqlite://", [_collection()])
    repository.connect()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_sql_duplicate_create_raises_conflict_naming_field(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.create("members", {"id": "m2", "email": "a@x.io"})
    assert excinfo.value.field == "email"
    assert "email" in str(excinfo.value)


@pytest.mark.asyncio
async def test_sql_duplicate_update_raises_conflict(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    await repo.create("members", {"id": "m2", "email": "b@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.update("members", "m2", {"email": "a@x.io"})
    assert excinfo.value.field == "email"


class _DuplicateCollection:
    async def insert_one(self, payload: dict[str, Any]) -> Any:
        raise DuplicateKeyError(
            "E11000 duplicate key error",
            details={"keyPattern": {"email": 1}, "keyValue": {"email": "a@x.io"}},
        )


@pytest.mark.asyncio
async def test_mongo_duplicate_key_raises_conflict_naming_field():
    repository = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repository._db = {"members": _DuplicateCollection()}
    with pytest.raises(ConflictError) as excinfo:
        await repository.create("members", {"id": "m1", "email": "a@x.io"})
    assert excinfo.value.field == "email"


_SPEC = """
    version: "0.2"
    api: { basePath: "" }
    datastores:
      store:
        type: postgres
        dsn: "postgresql+asyncpg://localhost/unused"
        default: true
    entities:
      member:
        fields:
          id: { type: id, format: uuidv4 }
          email: { type: string, required: true, unique: true }
    repositories:
      members: { entity: member }
    services:
      members: { repository: members }
    controllers:
      members:
        base_path: /members
        routes:
          create: { service: members, method: POST, path: "", access: public }
"""


def _write_spec(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC))
    return str(spec)


async def _invoke(app, method, path, body=None):
    scope = {"type": "http", "method": method, "path": path, "headers": []}

    async def receive():
        payload = json.dumps(body).encode() if body is not None else b""
        return {"type": "http.request", "body": payload, "more_body": False}

    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    data = next(m for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(data["body"])


@pytest.mark.asyncio
async def test_raw_asgi_duplicate_returns_409(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    app = build_raw_app(_write_spec(tmp_path))
    status, _ = await _invoke(app, "POST", "/members", {"email": "a@x.io"})
    assert status == 200
    status, body = await _invoke(app, "POST", "/members", {"email": "a@x.io"})
    assert status == 409
    assert "email" in body["detail"]


def test_fastapi_duplicate_returns_409(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    app = build_app(_write_spec(tmp_path))
    with TestClient(app) as client:
        assert client.post("/members", json={"email": "a@x.io"}).status_code == 200
        response = client.post("/members", json={"email": "a@x.io"})
    assert response.status_code == 409
    assert "email" in response.json()["detail"]
